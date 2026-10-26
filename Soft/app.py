import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv
from flask_mail import Mail, Message
from docxtpl import DocxTemplate

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'clavesegura_123'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///valhala.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Carpeta para plantillas Word
DOC_TEMPLATES_FOLDER = os.path.join(os.getcwd(), 'static', 'templates_doc')
os.makedirs(DOC_TEMPLATES_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

ADMIN_DOMAIN = "@admin.valhala.com"

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==========================================
# MODELOS DE BASE DE DATOS
# ==========================================
attendance = db.Table('attendance',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    section = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(250), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')
    is_active = db.Column(db.Boolean, default=False)
    profile_pic = db.Column(db.String(250), default='') 
    phrase = db.Column(db.String(100), default='OPERADOR BASE_')
    attended_events = db.relationship('Event', secondary=attendance, backref=db.backref('attendees', lazy='dynamic'))

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(500), nullable=False) # Sede o Link de Google Maps
    poster = db.Column(db.String(500), nullable=True) # Imagen (Materiales específicos si aplica)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organizer = db.relationship('User', backref=db.backref('events', lazy=True))
    
    # Flujo de aprobación
    status = db.Column(db.String(50), default='pending') # pending, approved, rejected
    doc_path = db.Column(db.String(500), nullable=True)

    # NUEVOS CAMPOS DEL FORMULARIO EXTENDIDO
    description = db.Column(db.Text, nullable=True)
    objective = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    attendee_count = db.Column(db.Integer, nullable=True)
    fee = db.Column(db.String(50), nullable=True)
    has_guests = db.Column(db.Boolean, default=False)
    guest_names = db.Column(db.Text, nullable=True)
    guest_affiliation = db.Column(db.String(250), nullable=True)
    scope = db.Column(db.String(100), nullable=True)
    event_type = db.Column(db.String(100), nullable=True)
    background = db.Column(db.Text, nullable=True)
    media = db.Column(db.String(250), nullable=True)
    requires_internet = db.Column(db.Boolean, default=False)

class EmailLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default="Enviado")

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

def send_and_log_email(recipient, subject, html_body):
    try:
        msg = Message(subject=subject, recipients=[recipient])
        msg.html = html_body
        mail.send(msg)
        status = "Enviado exitosamente"
    except Exception as e: status = f"Error: {str(e)}"
    db.session.add(EmailLog(recipient=recipient, subject=subject, body=html_body, status=status))
    db.session.commit()

# ==========================================
# RUTAS BÁSICAS (Auth)
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.session.execute(db.select(User).filter_by(email=request.form.get('email').strip().lower())).scalar()
        if user and check_password_hash(user.password, request.form.get('password')):
            if not user.is_active: flash('Cuenta inactiva. Revisa tu correo.', 'error')
            else:
                login_user(user)
                return redirect(url_for('dashboard'))
        else: flash('Credenciales inválidas', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        if db.session.execute(db.select(User).filter_by(email=email)).scalar():
            flash('Correo ya registrado.', 'error')
            return redirect(url_for('register'))
        
        role = 'admin' if email.endswith(ADMIN_DOMAIN) or email.endswith('@gmail.com') else request.form.get('role', 'user')
        new_user = User(
            name=request.form.get('name'), employee_id=request.form.get('employee_id'), 
            email=email, section=request.form.get('section'), role=role, 
            password=generate_password_hash(os.urandom(24).hex()), is_active=False
        )
        db.session.add(new_user)
        db.session.commit()
        token = s.dumps(email, salt='email-activate-salt')
        send_and_log_email(email, "Activación", f"<a href='{url_for('activate', token=token, _external=True)}'>Activar</a>")
        flash('Registro completado. Revisa tu correo.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/activate/<token>', methods=['GET', 'POST'])
def activate(token):
    try: email = s.loads(token, salt='email-activate-salt', max_age=86400)
    except Exception: return redirect(url_for('login'))
    user = db.session.execute(db.select(User).filter_by(email=email)).scalar()
    if request.method == 'POST':
        user.password = generate_password_hash(request.form.get('password'))
        user.is_active = True
        db.session.commit()
        flash('Cuenta activada.', 'success')
        return redirect(url_for('login'))
    return render_template('activate.html', email=email)

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    db.session.execute(db.delete(Event).filter_by(organizer_id=current_user.id))
    db.session.execute(db.delete(EmailLog).filter_by(recipient=current_user.email))
    db.session.delete(db.session.get(User, current_user.id))
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))

# ==========================================
# VISTAS PRINCIPALES
# ==========================================
@app.route('/')
@login_required
def dashboard():
    pending_requests = []
    if current_user.role == 'admin':
        # Los admins ven la bandeja de solicitudes que deben procesar
        pending_requests = db.session.execute(db.select(Event).filter_by(status='pending')).scalars().all()
    return render_template('dashboard.html', user=current_user, pending_requests=pending_requests)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        new_phrase = request.form.get('phrase', '').strip()
        if len(new_phrase) <= 100: current_user.phrase = new_phrase if new_phrase else 'OPERADOR BASE_'
            
        if 'profile_pic' in request.files and allowed_file(request.files['profile_pic'].filename):
            file = request.files['profile_pic']
            unique_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            current_user.profile_pic = unique_filename
        db.session.commit()
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

@app.route('/my_events')
@login_required
def my_events():
    organized_events = db.session.execute(db.select(Event).filter_by(organizer_id=current_user.id)).scalars().all()
    return render_template('my_events.html', user=current_user, organized_events=organized_events, attended_events=current_user.attended_events)

# ==========================================
# FLUJO DE SOLICITUD Y APROBACIÓN
# ==========================================
@app.route('/request_space', methods=['GET', 'POST'])
@login_required
def request_space():
    if current_user.role not in ['admin', 'organizer']:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        # Fechas y Horas (Duración 24 hrs)
        fecha = request.form.get('fecha')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        
        try:
            start_dt = datetime.fromisoformat(f"{fecha}T{start_time}")
            end_dt = datetime.fromisoformat(f"{fecha}T{end_time}")
        except ValueError:
            flash("Error en formato de fechas", "error")
            return redirect(url_for('request_space'))

        # Checkboxes
        has_guests = True if request.form.get('has_guests') == 'on' else False
        requires_internet = True if request.form.get('requires_internet') == 'on' else False
        requires_equipment = True if request.form.get('requires_equipment') == 'on' else False

        # Imagen de materiales específicos (guardado en 'poster')
        poster_name = "" 
        if requires_equipment and 'equipment_image' in request.files:
            file = request.files['equipment_image']
            if file.filename != '' and allowed_file(file.filename):
                poster_name = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], poster_name))

        # Crear Evento (Estado: Pending)
        new_event = Event(
            name=request.form.get('name'),
            description=request.form.get('description'),
            objective=request.form.get('objective')[:150],
            start_date=start_dt, end_date=end_dt,
            location=request.form.get('location'),
            contact_phone=request.form.get('contact_phone'),
            contact_email=request.form.get('contact_email'),
            attendee_count=int(request.form.get('attendee_count') or 0),
            fee=request.form.get('fee'),
            has_guests=has_guests,
            guest_names=request.form.get('guest_names') if has_guests else None,
            guest_affiliation=request.form.get('guest_affiliation') if has_guests else None,
            scope=request.form.get('scope'),
            event_type=request.form.get('event_type'),
            background=request.form.get('background'),
            media=request.form.get('media'),
            requires_internet=requires_internet,
            poster=poster_name,
            organizer_id=current_user.id,
            status='pending'
        )
        db.session.add(new_event)
        db.session.commit()
        
        return redirect(url_for('my_events'))

    return render_template('request_space.html', user=current_user)

@app.route('/api/events/<int:event_id>/review', methods=['POST'])
@login_required
def review_event(event_id):
    if current_user.role != 'admin': return jsonify({"error": "No autorizado"}), 403
    
    event = db.session.get(Event, event_id)
    if not event: return jsonify({"error": "Evento no encontrado"}), 404

    # Datos recibidos del modal Mad Libs
    resolucion = request.form.get('resolucion')
    folio = request.form.get('folio')
    condiciones = request.form.get('condiciones')
    firma = request.form.get('firma')

    # Generación de la plantilla Word
    template_path = os.path.join(DOC_TEMPLATES_FOLDER, 'plantilla_maestra.docx')
    if os.path.exists(template_path):
        try:
            doc = DocxTemplate(template_path)
            context = {
                'nombre_evento': event.name,
                'organizador': event.organizer.name,
                'sede': event.location,
                'fecha_inicio': event.start_date.strftime('%d/%m/%Y %H:%M'),
                'resolucion': resolucion,
                'folio': folio,
                'condiciones': condiciones,
                'firma': firma
            }
            doc.render(context)
            
            doc_filename = f"Aval_{event.id}_{uuid.uuid4().hex[:6]}.docx"
            doc.save(os.path.join(app.config['UPLOAD_FOLDER'], doc_filename))
            event.doc_path = doc_filename
        except Exception as e:
            return jsonify({"error": f"Error al procesar el documento: {str(e)}"}), 500

    # Cambio de estado oficial
    if resolucion == 'APROBADO':
        # Si se aprueba, ya es visible en el calendario para todos
        event.status = 'approved'
    else:
        event.status = 'rejected'
        
    db.session.commit()
    return jsonify({"message": "Resolutivo Generado Exitosamente."}), 200


# ==========================================
# API DE CALENDARIO
# ==========================================
@app.route('/api/calendar')
@login_required
def get_calendar():
    # El calendario de la pantalla principal SOLO mostrará eventos 'approved'
    events = db.session.execute(db.select(Event).filter_by(status='approved')).scalars().all()
    calendar_data = []
    for e in events:
        is_attending = e in current_user.attended_events
        calendar_data.append({
            'id': str(e.id), 'title': e.name, 'start': e.start_date.isoformat(),
            'end': e.end_date.isoformat(),
            'extendedProps': { 'location': e.location, 'poster': e.poster, 'is_attending': is_attending }
        })
    return jsonify(calendar_data)

@app.route('/api/events/<int:event_id>/attend', methods=['POST'])
@login_required
def toggle_attendance(event_id):
    event = db.session.get(Event, event_id)
    if not event: return jsonify({"error": "Evento no encontrado"}), 404

    if event in current_user.attended_events:
        current_user.attended_events.remove(event)
        msg = "Has cancelado tu asistencia."
    else:
        current_user.attended_events.append(event)
        msg = "Te has registrado para asistir exitosamente."
    
    db.session.commit()
    return jsonify({"message": msg})

# ==========================================
# INICIALIZADOR DE BASE DE DATOS Y USUARIOS
# ==========================================
with app.app_context():
    db.create_all()
    # Generar cuentas de prueba necesarias para la demostración de roles
    if not db.session.execute(db.select(User).filter_by(email='admin@admin.valhala.com')).scalar():
        db.session.add(User(
            name='Director de Sistemas', employee_id='ADM-000', section='Dirección', 
            email='admin@admin.valhala.com', password=generate_password_hash('admin123'), 
            role='admin', is_active=True, phrase='ACCESO NIVEL OMEGA'
        ))
    if not db.session.execute(db.select(User).filter_by(email='org@valhala.com')).scalar():
        db.session.add(User(
            name='Coordinador de Eventos', employee_id='ORG-001', section='Logística', 
            email='org@valhala.com', password=generate_password_hash('org123'), 
            role='organizer', is_active=True, phrase='LÍDER DE DESPLIEGUE'
        ))
    if not db.session.execute(db.select(User).filter_by(email='comun@valhala.com')).scalar():
        db.session.add(User(
            name='Operador Base', employee_id='USR-001', section='Operaciones', 
            email='comun@valhala.com', password=generate_password_hash('comun123'), 
            role='user', is_active=True, phrase='UNIDAD STANDBY'
        ))
    db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)