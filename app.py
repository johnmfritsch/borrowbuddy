import sys
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import sqlite3
import json
from datetime import datetime, timedelta
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import secrets
from utils import normalize_phone_number, format_phone_for_display, get_contact_initials, generate_image_variants
from config import Config

# Load configuration
config = Config.get_config()

app = Flask(__name__)
app.config['DATABASE'] = config.DATABASE
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Session configuration
# Persistent secret key - generated once, stored in file
_secret_key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secret_key.txt')
if not os.path.exists(_secret_key_path):
    with open(_secret_key_path, 'w') as _f:
        _f.write(secrets.token_hex(32))
with open(_secret_key_path, 'r') as _f:
    app.config['SECRET_KEY'] = _f.read().strip()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only

# Allowed file extensions for photo uploads
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
# Disposition status codes
DISPOSITION_ACTIVE = 1       # Currently loaned out
DISPOSITION_RETURNED = 2     # Returned normally
DISPOSITION_CANCELLED = 3    # Loan cancelled
DISPOSITION_LOST = 4         # Item lost/not returned
DISPOSITION_DAMAGED = 5      # Returned damaged

# Middleware to handle URL prefix
class PrefixMiddleware:
    def __init__(self, app, prefix=''):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if environ['PATH_INFO'].startswith(self.prefix):
            environ['PATH_INFO'] = environ['PATH_INFO'][len(self.prefix):]
            environ['SCRIPT_NAME'] = self.prefix
            return self.app(environ, start_response)
        else:
            start_response('404', [('Content-Type', 'text/plain')])
            return [b'Not Found']

# Wrap the app with the prefix middleware
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=config.URL_PREFIX)

# /health: no auth, no DB, no template. Polled by the shared NAS app watchdog
# (/volume1/util/system/app_watchdog), the same endpoint every other app exposes.
from health import health_bp
app.register_blueprint(health_bp)


# Middleware to set cache headers for improved performance
@app.after_request
def set_cache_headers(response):
    """Set cache control headers for different response types"""
    if request.path.startswith('/static/images/'):
        # Static images: cache for 1 year (immutable content)
        # Using a year instead of max-age to ensure long-term caching
        response.cache_control.public = True
        response.cache_control.max_age = 31536000  # 1 year in seconds
        # Add ETag for change detection if not already present
        if 'ETag' not in response.headers:
            response.add_etag()
    elif request.path.startswith('/api/'):
        # API responses: cache for 5 minutes (may change frequently)
        response.cache_control.public = True
        response.cache_control.max_age = 300  # 5 minutes
    return response
@app.context_processor
def inject_config():
    """Make config available to all templates automatically"""
    return dict(config=config)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.')[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin privileges for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))

        user = get_current_user()
        if not user or not user.get('is_admin'):
            return "Unauthorized", 403

        return f(*args, **kwargs)
    return decorated_function

def get_db():
    """Get database connection"""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def get_current_user():
    """Get current logged in user info"""
    if 'user_id' not in session:
        return None
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    db.close()
    return dict(user) if user else None


def log_audit(db, user_id, action, entity_type, entity_id=None, entity_name=None, details=None):
    """Log user activity to audit table - uses existing db connection"""
    try:
        # Get user email from session if available, otherwise query
        user_email = session.get('user_email', 'unknown')

        # Get IP address
        ip_address = request.remote_addr if request else None

        # Convert details to JSON if it's a dict
        if details and isinstance(details, dict):
            details = json.dumps(details)

        db.execute("""
            INSERT INTO audit_log (user_id, user_email, action, entity_type, entity_id,
                                   entity_name, details, ip_address, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, user_email, action, entity_type, entity_id,
              entity_name, details, ip_address, datetime.now().isoformat()))

        # Note: Caller is responsible for commit/close
    except Exception as e:
        # Log error but don't crash the app
        print("ERROR in log_audit: " + str(e), file=sys.stderr)
        import traceback
        traceback.print_exc()


def sync_default_photo(db, item_id):
    """Keep items.photo_uri, photo_uri_thumb, photo_uri_display in sync with item_photos default"""
    default_photo = db.execute(
        'SELECT photo_uri, photo_uri_thumb, photo_uri_display FROM item_photos WHERE item_id = ? AND is_default = 1',
        (item_id,)
    ).fetchone()
    photo_uri = default_photo['photo_uri'] if default_photo else None
    photo_uri_thumb = default_photo['photo_uri_thumb'] if default_photo else None
    photo_uri_display = default_photo['photo_uri_display'] if default_photo else None
    db.execute('UPDATE items SET photo_uri = ?, photo_uri_thumb = ?, photo_uri_display = ? WHERE id = ?',
               (photo_uri, photo_uri_thumb, photo_uri_display, item_id))


def migrate_existing_data_to_user(user_id):
    """Assign all existing data without user_id to the specified user"""
    db = get_db()

    # Update items
    db.execute('UPDATE items SET user_id = ? WHERE user_id IS NULL', (user_id,))

    # Update contacts
    db.execute('UPDATE contacts SET user_id = ? WHERE user_id IS NULL', (user_id,))

    # Update loans
    db.execute('UPDATE loans SET user_id = ? WHERE user_id IS NULL', (user_id,))

    # Update borrows
    db.execute('UPDATE borrows SET user_id = ? WHERE user_id IS NULL', (user_id,))

    db.commit()
    db.close()

def init_db():
    """Initialize the database with tables"""
    db = get_db()

    # Create users table
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            display_name TEXT
        )
    ''')

    # Create contacts table
    db.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            user_id INTEGER
        )
    ''')

    # Create items table
    db.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            photo_uri TEXT,
            user_id INTEGER
        )
    ''')

    # Create loans table
    db.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            return_date TEXT,
            disposition INTEGER DEFAULT 1,
            date_loaned TEXT NOT NULL,
            notes TEXT,
            user_id INTEGER,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (item_id) REFERENCES items (id),
            FOREIGN KEY (contact_id) REFERENCES contacts (id)
        )
    ''')

    # Create borrows table
    db.execute('''
        CREATE TABLE IF NOT EXISTS borrows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            return_date TEXT,
            disposition INTEGER DEFAULT 1,
            date_borrowed TEXT NOT NULL,
            notes TEXT,
            user_id INTEGER,
            FOREIGN KEY (item_id) REFERENCES items (id),
            FOREIGN KEY (contact_id) REFERENCES contacts (id)
        )
    ''')

    # Create indexes for better performance
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_items_name ON items(name)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user_id ON contacts(user_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_loans_user_id ON loans(user_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_borrows_user_id ON borrows(user_id)')
    except:
        pass  # Indexes might already exist

    db.commit()
    db.close()

# Authentication Routes

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        if not email or not password or not display_name:
            return render_template('register.html', error='Email, name, and password are required')

        if len(password) < 8:
            return render_template('register.html', error='Password must be at least 8 characters')

        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match')

        db = get_db()

        # Check if email already exists
        existing_user = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing_user:
            db.close()
            return render_template('register.html', error='Email already registered')

        # Create user
        password_hash = generate_password_hash(password)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor = db.execute(
            'INSERT INTO users (email, password_hash, created_at, display_name) VALUES (?, ?, ?, ?)',
            (email, password_hash, created_at, display_name if display_name else None)
        )
        user_id = cursor.lastrowid

        # Set session before audit log so email is available
        session['user_id'] = user_id
        session['user_email'] = email
        session.permanent = True

        # Audit log
        log_audit(db, user_id, 'create', 'user', user_id, email)

        db.commit()

        # If first user, migrate existing data
        if user_id == 1:
            migrate_existing_data_to_user(user_id)

        db.close()

        return redirect(url_for('index'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            return render_template('login.html', error='Email and password are required')

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

        if not user or not check_password_hash(user['password_hash'], password):
            db.close()
            return render_template('login.html', error='Invalid email or password')

        # Log user in
        session['user_id'] = user['id']
        session['user_email'] = user['email']
        session.permanent = True

        # Audit log
        log_audit(db, user['id'], 'login', 'user', user['id'], user['email'])

        db.commit()
        db.close()
        return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    # Audit log before clearing session
    if 'user_id' in session:
        db = get_db()
        log_audit(db, session['user_id'], 'logout', 'user')
        db.commit()
        db.close()

    session.clear()
    return redirect(url_for('login'))


@app.route('/my-profile')
@login_required
def my_profile():
    user = get_current_user()
    return render_template('coming_soon.html', feature_name='My Profile', current_user=user)

@app.route('/settings')
@login_required
def settings():
    user = get_current_user()
    return render_template('coming_soon.html', feature_name='Settings', current_user=user)

@app.route('/invite-friends')
@login_required
def invite_friends():
    user = get_current_user()
    return render_template('coming_soon.html', feature_name='Invite Friends', current_user=user)

@app.route('/borrowbuddy-features')
@login_required
def borrowbuddy_features():
    user = get_current_user()
    return render_template('coming_soon.html', feature_name='BorrowBuddy Features', current_user=user)

# Main Application Routes

@app.route('/')
@login_required
def index():
    """Main menu"""
    user = get_current_user()
    return render_template('index.html', current_user=user)

@app.route('/api/items')
@login_required
def api_items():
    """API endpoint to get all items with their loan statistics"""
    user_id = session['user_id']
    db = get_db()
    items = db.execute('''
        SELECT i.id, i.name, i.photo_uri, i.photo_uri_thumb, (SELECT COUNT(*) FROM item_photos WHERE item_id = i.id) as photo_count,
               COUNT(l.id) as loan_count,
               MAX(l.date_loaned) as last_loaned
        FROM items i
        LEFT JOIN loans l ON i.id = l.item_id AND l.user_id = ?
        WHERE i.user_id = ? 
          AND (i.is_active = 1 OR i.is_active IS NULL)
          AND i.id NOT IN (
              SELECT item_id FROM loans 
              WHERE user_id = ? AND disposition = 1
          )
        GROUP BY i.id
        ORDER BY loan_count DESC, last_loaned DESC
    ''', (user_id, user_id, user_id)).fetchall()
    db.close()

    return jsonify([dict(item) for item in items])


@app.route('/api/contacts')
@login_required
def api_contacts():
    """API endpoint for contacts data"""
    user_id = session['user_id']
    db = get_db()

    # Get contacts with loan count
    contacts = db.execute('''
        SELECT c.id, c.name, c.email, c.phone,
               COUNT(DISTINCT l.id) as loan_count,
               MAX(l.date_loaned) as last_loaned
        FROM contacts c
        LEFT JOIN loans l ON c.id = l.contact_id AND l.user_id = ?
        WHERE c.user_id = ? AND (c.is_active = 1 OR c.is_active IS NULL)
        GROUP BY c.id
        ORDER BY loan_count DESC, c.name ASC
    ''', (user_id, user_id)).fetchall()

    db.close()
    return jsonify([dict(contact) for contact in contacts])

@app.route('/api/contacts/check_duplicate', methods=['POST'])
@login_required
def check_duplicate_contact():
    """Check if contact name already exists (case-insensitive, fuzzy match)"""
    user_id = session['user_id']
    data = request.json
    name = data.get('name', '').strip()
    email = data.get('email', '').strip() if 'email' in data else None
    phone = data.get('phone', '').strip() if 'phone' in data else None

    if not name:
        return jsonify({'exists': False})

    db = get_db()

    # Case-insensitive exact match first
    existing = db.execute(
        'SELECT id, name, email, phone, is_active FROM contacts WHERE LOWER(name) = LOWER(?) AND user_id = ?  ORDER BY is_active DESC LIMIT 1',
        (name, user_id)
    ).fetchone()

    # If no exact match, try fuzzy match (contains or partial)
    if not existing:
        # Check if name is a substring of any existing contact or vice versa
        fuzzy_contacts = db.execute(
            'SELECT id, name, email, phone, is_active FROM contacts WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(?) LIKE LOWER(name)) AND user_id = ?  ORDER BY is_active DESC, LENGTH(name) LIMIT 3',
            ('%{' + name + '}%', '%{' + name + '}%', user_id)
        ).fetchall()

        if fuzzy_contacts:
            db.close()
            return jsonify({
                'exists': True,
                'fuzzy': True,
                'matches': [dict(c) for c in fuzzy_contacts],
                'new_data': {
                    'name': name,
                    'email': email,
                    'phone': phone
                }
            })

    db.close()

    if existing:
        existing_dict = dict(existing)
        # Check if new data has info that existing contact is missing
        has_new_info = (
            (email and not existing_dict.get('email')) or
            (phone and not existing_dict.get('phone'))
        )

        return jsonify({
            'exists': True,
            'fuzzy': False,
            'contact': existing_dict,
            'has_new_info': has_new_info,
            'new_data': {
                'name': name,
                'email': email,
                'phone': phone
            }
        })
    else:
        return jsonify({'exists': False})

@app.route('/api/contacts/merge', methods=['POST'])
@login_required
def merge_contact():
    """Merge new contact data into existing contact"""
    user_id = session['user_id']
    data = request.json
    contact_id = data.get('contact_id')
    new_email = data.get('email', '').strip()
    new_phone = normalize_phone_number(data.get('phone', ''))

    if not contact_id:
        return jsonify({'success': False, 'error': 'Contact ID required'}), 400

    db = get_db()

    # Verify contact belongs to user
    existing = db.execute(
        'SELECT id, name, email, phone FROM contacts WHERE id = ? AND user_id = ?',
        (contact_id, user_id)
    ).fetchone()

    if not existing:
        db.close()
        return jsonify({'success': False, 'error': 'Contact not found'}), 404

    # Merge: only update fields that are currently empty
    update_fields = []
    update_values = []

    if new_email and not existing['email']:
        update_fields.append('email = ?')
        update_values.append(new_email)

    if new_phone and not existing['phone']:
        update_fields.append('phone = ?')
        update_values.append(new_phone)

    if update_fields:
        query = f"UPDATE contacts SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        update_values.extend([contact_id, user_id])
        db.execute(query, update_values)
        db.commit()

    db.close()

    return jsonify({'success': True, 'message': 'Contact merged successfully'})

@app.route('/api/contacts/reactivate', methods=['POST'])
@login_required
def reactivate_contact():
    """Reactivate a previously soft-deleted contact"""
    user_id = session['user_id']
    data = request.json
    contact_id = data.get('contact_id')

    if not contact_id:
        return jsonify({'success': False, 'error': 'Contact ID required'}), 400

    db = get_db()

    # Verify contact belongs to user and is currently inactive
    contact = db.execute(
        'SELECT id, name, email, phone, is_active FROM contacts WHERE id = ? AND user_id = ?',
        (contact_id, user_id)
    ).fetchone()

    if not contact:
        db.close()
        return jsonify({'success': False, 'error': 'Contact not found'}), 404

    if contact['is_active'] == 1:
        db.close()
        return jsonify({'success': False, 'error': 'Contact is already active'}), 400

    # Reactivate
    db.execute('UPDATE contacts SET is_active = 1 WHERE id = ?', (contact_id,))

    # Audit log
    log_audit(db, user_id, 'update', 'contact', contact_id, contact['name'], {'action': 'reactivated'})

    db.commit()
    db.close()

    return jsonify({'success': True, 'contact_id': contact_id, 'name': contact['name']})

@app.route('/api/items/reactivate', methods=['POST'])
@login_required
def reactivate_item():
    """Reactivate a previously soft-deleted item"""
    user_id = session['user_id']
    data = request.json
    item_id = data.get('item_id')

    if not item_id:
        return jsonify({'success': False, 'error': 'Item ID required'}), 400

    db = get_db()

    # Verify item belongs to user and is currently inactive
    item = db.execute(
        'SELECT id, name, description, photo_uri, is_active FROM items WHERE id = ? AND user_id = ?',
        (item_id, user_id)
    ).fetchone()

    if not item:
        db.close()
        return jsonify({'success': False, 'error': 'Item not found'}), 404

    if item['is_active'] == 1:
        db.close()
        return jsonify({'success': False, 'error': 'Item is already active'}), 400

    # Reactivate
    db.execute('UPDATE items SET is_active = 1 WHERE id = ?', (item_id,))

    # Audit log
    log_audit(db, user_id, 'update', 'item', item_id, item['name'], {'action': 'reactivated'})

    db.commit()
    db.close()

    return jsonify({'success': True, 'item_id': item_id, 'name': item['name']})

@app.route('/loan', methods=['GET', 'POST'])
@login_required
def loan():
    """Create a new loan"""
    if request.method == 'POST':
        user_id = session['user_id']
        item_id = request.form.get('item_id')  # Existing item
        item_name = request.form.get('item_name', '').strip()  # New item name
        item_description = request.form.get('item_description', '').strip()  # New item description
        return_date = request.form.get('return_date')
        notes = request.form.get('notes')
        # Extract quantity (default to 1 if not provided or invalid)
        quantity = request.form.get("quantity", "1").strip()
        try:
            quantity = int(quantity)
            if quantity < 1 or quantity > 10:
                quantity = 1
        except ValueError:
            quantity = 1
        photo_files = request.files.getlist('photo')

        db = get_db()
        # Process all uploaded photos
        uploaded_photos = []  # list of (photo_uri, filename) tuples
        for pf in photo_files:
            if pf and pf.filename and allowed_file(pf.filename):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                filename = f'JPEG_{timestamp}_{secure_filename(pf.filename)}'
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                fpath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pf.save(fpath)
                uri = f'{config.URL_PREFIX}/static/images/{filename}'
                uploaded_photos.append((uri, filename))

        # First photo URI for backward compat (items.photo_uri)
        photo_uri = uploaded_photos[0][0] if uploaded_photos else None

        # Determine if using existing item or creating new one
        if item_id and item_id.strip():
            # Using existing item - verify it belongs to current user
            item_id = int(item_id)
            existing_item = db.execute('SELECT id FROM items WHERE id = ? AND user_id = ?',
                                      (item_id, user_id)).fetchone()

            if not existing_item:
                db.close()
                return redirect(url_for('loan', error='Item not found'))

            # Update photos if new ones were uploaded
            if uploaded_photos:
                existing_count = db.execute('SELECT COUNT(*) FROM item_photos WHERE item_id = ?', (item_id,)).fetchone()[0]
                for i, (p_uri, p_fname) in enumerate(uploaded_photos):
                    is_def = 1 if existing_count == 0 and i == 0 else 0
                    # Generate image variants (thumb + display)
                    p_thumb = None
                    p_display = None
                    try:
                        fpath = os.path.join(app.config['UPLOAD_FOLDER'], p_fname)
                        variants = generate_image_variants(fpath, config.URL_PREFIX)
                        p_thumb = variants['thumb']
                        p_display = variants['display']
                    except Exception as e:
                        print(f"Warning: Could not generate image variants for loan upload: {e}")
                    db.execute(
                        "INSERT INTO item_photos (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
                        (item_id, p_uri, p_fname, p_thumb, p_display, is_def, user_id)
                    )
                sync_default_photo(db, item_id)
                db.commit()
        else:
            # Create new item
            cursor = db.execute('INSERT INTO items (name, description, photo_uri, user_id) VALUES (?, ?, ?, ?)',
                              (item_name.title(), item_description, photo_uri, user_id))
            item_id = cursor.lastrowid

            # Also insert into item_photos for all uploaded photos
            for i, (p_uri, p_fname) in enumerate(uploaded_photos):
                is_def = 1 if i == 0 else 0
                db.execute(
                    "INSERT INTO item_photos (item_id, photo_uri, filename, is_default, created_at, user_id) VALUES (?, ?, ?, ?, datetime('now'), ?)",
                    (item_id, p_uri, p_fname, is_def, user_id)
                )

        # Add or select contact
        contact_id_param = request.form.get('contact_id')  # Existing contact
        contact_name = request.form.get('contact_name')  # New contact name
        contact_email = request.form.get('contact_email', '')
        contact_phone = normalize_phone_number(request.form.get('contact_phone', ''))

        # Determine if using existing contact or creating new one
        if contact_id_param and contact_id_param.strip():
            # Using existing contact - verify it belongs to current user
            contact_id = int(contact_id_param)
            existing_contact = db.execute('SELECT id FROM contacts WHERE id = ? AND user_id = ?',
                                         (contact_id, user_id)).fetchone()

            if not existing_contact:
                db.close()
                return redirect(url_for('loan', error='Contact not found'))
        else:
            # Create new contact - validate name is provided
            if not contact_name or not contact_name.strip():
                db.close()
                return redirect(url_for('loan', error='Contact name is required'))

            cursor = db.execute(
                'INSERT INTO contacts (name, email, phone, user_id, is_active) VALUES (?, ?, ?, ?, 1)',
                (contact_name.strip().title(), contact_email.strip(), contact_phone, user_id)
            )
            contact_id = cursor.lastrowid

        print(f"DEBUG: About to insert loan item_id={item_id} contact_id={contact_id}")
        # Add loan
        date_loaned = datetime.now().strftime('%Y-%m-%d')
        db.execute('''INSERT INTO loans
                     (item_id, contact_id, return_date, disposition, date_loaned, notes, user_id, quantity)
                     VALUES (?, ?, ?, 1, ?, ?, ?, ?)''',
                  (item_id, contact_id, return_date, date_loaned, notes, user_id, quantity))

        db.commit()

        # Get item and contact names for success message
        item_row = db.execute('SELECT name FROM items WHERE id = ?', (item_id,)).fetchone()
        final_item_name = item_row['name'] if item_row else item_name

        contact_row = db.execute('SELECT name FROM contacts WHERE id = ?', (contact_id,)).fetchone()
        final_contact_name = contact_row['name'] if contact_row else 'Unknown'

        # Audit log
        loan_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        log_audit(db, user_id, 'create', 'loan', loan_id, f'{final_item_name} → {final_contact_name}', {'item_id': item_id, 'contact_id': contact_id, 'return_date': return_date, 'notes': notes, 'quantity': quantity})

        db.commit()
        db.close()

        qty_text = f' (qty: {quantity})' if quantity > 1 else ''
        return redirect(url_for('index', message=f'{final_item_name}{qty_text} loaned to {final_contact_name}'))

    user = get_current_user()
    return render_template('loan.html', current_user=user)
@app.route('/where')
@login_required
def where():
    """View all loaned items"""
    user_id = session['user_id']
    db = get_db()
    loans = db.execute('''
        SELECT l.*, i.name as item_name, i.description, i.photo_uri,
               i.photo_uri_thumb, i.photo_uri_display,
               c.name as contact_name
        FROM loans l
        JOIN items i ON l.item_id = i.id
        JOIN contacts c ON l.contact_id = c.id
        WHERE l.disposition = 1 AND l.user_id = ?
        ORDER BY l.date_loaned
    ''', (user_id,)).fetchall()
    db.close()

    # Calculate days loaned for each
    loans_data = []
    for loan in loans:
        loan_dict = dict(loan)
        date_loaned = datetime.strptime(loan['date_loaned'], '%Y-%m-%d')

        if loan['return_date']:
            return_date = datetime.strptime(loan['return_date'], '%Y-%m-%d')
            days = (return_date - date_loaned).days
            if days < 0:
                loan_dict['duration'] = f'Overdue by {-days} days'
            else:
                loan_dict['duration'] = f'{days} days'
        else:
            loan_dict['duration'] = 'No due date'

        loans_data.append(loan_dict)

    user = get_current_user()
    return render_template('where.html', loans=loans_data, current_user=user)

@app.route('/api/loans')
@app.route('/api/loans')
@login_required
def api_loans():
    """API endpoint for loans data"""
    user_id = session['user_id']
    db = get_db()
    loans = db.execute('SELECT * FROM loans WHERE disposition = 1 AND user_id = ?',
                      (user_id,)).fetchall()
    db.close()
    return jsonify([dict(loan) for loan in loans])

@app.route("/loan/<int:loan_id>/edit", methods=["GET", "POST"])
@login_required
def edit_loan(loan_id):
    """Edit an existing loan"""
    user_id = session["user_id"]
    db = get_db()

    # Verify loan belongs to current user
    loan = db.execute("""
        SELECT l.*, i.name as item_name, c.name as contact_name
        FROM loans l
        JOIN items i ON l.item_id = i.id
        JOIN contacts c ON l.contact_id = c.id
        WHERE l.id = ? AND l.user_id = ?
    """, (loan_id, user_id)).fetchone()

    if not loan:
        db.close()
        return redirect(url_for("where"))

    if request.method == "POST":
        return_date = request.form.get("return_date")
        notes = request.form.get("notes")
        # Extract quantity (default to 1 if not provided or invalid)
        quantity = request.form.get("quantity", "1").strip()
        try:
            quantity = int(quantity)
            if quantity < 1 or quantity > 10:
                quantity = 1
        except ValueError:
            quantity = 1

        db.execute("""
            UPDATE loans
            SET return_date = ?, notes = ?, quantity = ?
            WHERE id = ? AND user_id = ?
        """, (return_date if return_date else None, notes, quantity, loan_id, user_id))

        db.commit()
        db.close()
        item_name = loan["item_name"] if loan else "Loan"
        return redirect(url_for("where", message=f"{item_name} updated"))

    db.close()
    user = get_current_user()
    return render_template("edit_loan.html", loan=dict(loan), current_user=user)


@app.route("/loan/<int:loan_id>/details", methods=["GET"])
@login_required
def loan_details(loan_id):
    """Get loan details including notes for display in modal"""
    user_id = session["user_id"]
    db = get_db()

    loan = db.execute("""
        SELECT notes
        FROM loans
        WHERE id = ? AND user_id = ?
    """, (loan_id, user_id)).fetchone()

    db.close()

    if not loan:
        return jsonify({"error": "Loan not found"}), 404

    return jsonify({"notes": loan['notes']})

@app.route("/loan/<int:loan_id>/complete", methods=["POST"])
@login_required
def complete_loan(loan_id):
    """Mark loan as complete with optional additional notes and return photo"""
    user_id = session["user_id"]

    # Get form data (not JSON anymore)
    disposition = int(request.form.get('disposition', DISPOSITION_RETURNED))
    additional_notes = request.form.get('additional_notes', '').strip()
    return_photo = request.files.get('return_photo')
    update_item_photo = request.form.get('update_item_photo') == 'on'  # Checkbox value

    # Validate disposition
    if disposition not in [DISPOSITION_RETURNED, DISPOSITION_CANCELLED, DISPOSITION_LOST, DISPOSITION_DAMAGED]:
        return jsonify({"error": "Invalid disposition"}), 400

    db = get_db()

    # Verify loan belongs to user and get item_id and existing notes
    loan = db.execute(
        """
        SELECT id, item_id, notes, quantity
        FROM loans
        WHERE id = ? AND user_id = ?
        """,
        (loan_id, user_id)
    ).fetchone()

    if not loan:
        db.close()
        return jsonify({"error": "Loan not found"}), 404

    item_id = loan['item_id']
    existing_notes = loan['notes'] or ''
    return_photo_uri = None

    item_row = db.execute('SELECT name FROM items WHERE id = ?', (item_id,)).fetchone()
    item_name_str = item_row['name'] if item_row else 'Unknown'

    # Append additional notes if provided
    updated_notes = existing_notes
    if additional_notes:
        if existing_notes:
            updated_notes = f"{existing_notes}\n\n--- Return Notes ---\n{additional_notes}"
        else:
            updated_notes = additional_notes

    # Handle return photo upload (OPTIONAL)
    if return_photo and return_photo.filename and allowed_file(return_photo.filename):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'RETURN_{timestamp}_{secure_filename(return_photo.filename)}'

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        return_photo.save(filepath)

        return_photo_uri = f'{config.URL_PREFIX}/static/images/{filename}'

        # Generate variants
        photo_uri_thumb = None
        photo_uri_display = None
        try:
            variants = generate_image_variants(filepath, config.URL_PREFIX)
            photo_uri_thumb = variants['thumb']
            photo_uri_display = variants['display']
        except Exception as e:
            print(f"Warning: Could not generate image variants: {e}")

        # Always insert return photo into item_photos
        is_return_default = 1 if update_item_photo else 0
        if is_return_default:
            db.execute('UPDATE item_photos SET is_default = 0 WHERE item_id = ? AND user_id = ?', (item_id, user_id))
        db.execute(
            "INSERT INTO item_photos (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            (item_id, return_photo_uri, filename, photo_uri_thumb, photo_uri_display, is_return_default, user_id)
        )

        # Update item's primary photo with return photo ONLY if checkbox is checked
        if update_item_photo:
            sync_default_photo(db, item_id)
            log_audit(db, user_id, 'update', 'item_photo', item_id, item_name_str, {"action": "photo_replaced_from_return", "filename": filename})

    # Append return notes to item description if provided
    if additional_notes:
        # Get current item description
        item_desc_row = db.execute('SELECT description FROM items WHERE id = ?', (item_id,)).fetchone()
        current_description = item_desc_row['description'] if item_desc_row and item_desc_row['description'] else ''
        
        # Format the return note with date
        return_date = datetime.now().strftime('%m/%d/%Y')
        return_note_entry = f"Return note from: {return_date} - {additional_notes}"
        
        # Append to description
        if current_description:
            updated_description = current_description + chr(10) + chr(10) + return_note_entry
        else:
            updated_description = return_note_entry
        
        # Update item description
        db.execute('UPDATE items SET description = ? WHERE id = ?', (updated_description, item_id))
        log_audit(db, user_id, 'update', 'item_description', item_id, item_name_str, {"action": "return_note_appended", "date": return_date})

    # Update loan with disposition, updated notes, and return photo
    db.execute(
        """
        UPDATE loans
        SET disposition = ?, notes = ?, return_photo_uri = ?
        WHERE id = ? AND user_id = ?
        """,
        (disposition, updated_notes if updated_notes else None, return_photo_uri, loan_id, user_id)
    )

    # Audit log
    details = {'disposition': disposition}
    if additional_notes:
        details['notes'] = additional_notes[:50]  # First 50 chars
    log_audit(db, user_id, 'update', 'loan', loan_id, f'{item_name_str} (returned)', details)

    db.commit()
    db.close()

    disposition_messages = {
        DISPOSITION_RETURNED: "marked as returned",
        DISPOSITION_CANCELLED: "cancelled",
        DISPOSITION_LOST: "marked as lost/not returned",
        DISPOSITION_DAMAGED: "marked as damaged",
    }
    action_text = disposition_messages.get(disposition, "updated")
    qty_text = f" (qty: {loan['quantity']})" if 'quantity' in loan.keys() and loan['quantity'] and loan['quantity'] > 1 else ""
    message = f"{item_name_str}{qty_text} {action_text}" if item_name_str else f"Loan {action_text}"

    return jsonify({"success": True, "message": message})
@app.route("/contacts")
@login_required
def contacts():
    """View all contacts"""
    user_id = session["user_id"]
    db = get_db()

    print(f"DEBUG contacts(): user_id = {user_id}")

    contacts_list = db.execute("""
        SELECT c.id, c.name, c.email, c.phone,
               COUNT(DISTINCT l.id) as loan_count,
               MAX(l.date_loaned) as last_loaned,
               COALESCE(SUM(CASE WHEN l.disposition = 1 THEN 1 ELSE 0 END), 0) as active_loans,
               SUM(CASE WHEN b.disposition = 1 THEN 1 ELSE 0 END) as active_borrows
        FROM contacts c
        LEFT JOIN loans l ON c.id = l.contact_id AND l.user_id = ?
        LEFT JOIN borrows b ON c.id = b.contact_id AND b.user_id = ?
        WHERE c.user_id = ? AND (c.is_active = 1 OR c.is_active IS NULL)
        GROUP BY c.id
        ORDER BY c.name ASC
    """, (user_id, user_id, user_id)).fetchall()

    print(f"DEBUG contacts(): Found {len(contacts_list)} contacts")
    for contact in contacts_list:
        print(f"  - {contact['id']}: {contact['name']}")

    db.close()
    user = get_current_user()
    return render_template("contacts.html", contacts=contacts_list, current_user=user)

@app.route("/contacts/add", methods=["GET", "POST"])
@login_required
def add_contact():
    """Add a new contact"""
    if request.method == "POST":
        user_id = session["user_id"]
        name = request.form.get("name", "").strip().title()
        email = request.form.get("email", "").strip()
        phone = normalize_phone_number(request.form.get("phone", ""))

        if not name:
            return redirect(url_for("contacts", error="Name is required"))

        db = get_db()
        cursor = db.execute(
            "INSERT INTO contacts (name, email, phone, user_id, is_active) VALUES (?, ?, ?, ?, 1)",
            (name, email, phone, user_id)
        )
        contact_id = cursor.lastrowid

        # Audit log
        log_audit(db, user_id, 'create', 'contact', contact_id, name)

        db.commit()
        db.close()

        return redirect(url_for("contacts", message=f"Contact {name} added"))

    user = get_current_user()
    return render_template("add_contact.html", current_user=user)
    user = get_current_user()
    return render_template("add_contact.html", current_user=user)

@app.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contact(contact_id):
    """Edit a contact"""
    user_id = session["user_id"]
    db = get_db()

    existing = db.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id)).fetchone()

    if not existing:
        db.close()
        return redirect(url_for("contacts", error="Contact not found"))

    if request.method == "POST":
        name = request.form.get("name", "").strip().title()
        email = request.form.get("email", "").strip()
        phone = normalize_phone_number(request.form.get("phone", ""))

        if not name:
            return redirect(url_for("edit_contact", contact_id=contact_id, error="Name is required"))

        db.execute(
            "UPDATE contacts SET name = ?, email = ?, phone = ? WHERE id = ? AND user_id = ?",
            (name, email, phone, contact_id, user_id)
        )
        # Audit log
        #         log_audit(user_id, "update", "contact", contact_id, name)

        db.commit()
        db.close()

        # Check for next parameter (e.g., when coming from loan page)
        next_page = request.args.get('next')
        if next_page == 'loan':
            return redirect(url_for("loan", message=f"Contact {name} updated"))
        return redirect(url_for("contacts", message=f"Contact {name} updated"))

    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ? AND user_id = ?",
        (contact_id, user_id)
    ).fetchone()
    db.close()

    if not contact:
        return redirect(url_for("items", error="Item not found"))

    user = get_current_user()
    return render_template("edit_contact.html", contact=contact, current_user=user)

@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    """Soft-delete a contact"""
    user_id = session["user_id"]
    db = get_db()

    # Check if contact has active loans
    active_loans = db.execute(
        "SELECT COUNT(*) as count FROM loans WHERE contact_id = ? AND disposition = 1 AND user_id = ?",
        (contact_id, user_id)
    ).fetchone()

    if active_loans["count"] > 0:
        db.close()
        return redirect(url_for("contacts", error="Cannot delete contact with active loans"))

    # Get contact name for audit
    contact = db.execute("SELECT name FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id)).fetchone()
    contact_name = contact['name'] if contact else 'Unknown'

    # Soft delete
    db.execute(
        "UPDATE contacts SET is_active = 0 WHERE id = ? AND user_id = ?",
        (contact_id, user_id)
    )

    # Audit log
    log_audit(db, user_id, 'delete', 'contact', contact_id, contact_name)

    db.commit()
    db.close()

    return redirect(url_for("contacts", message="Contact deleted"))

# Items Management Routes

@app.route("/items")
@login_required
def items():
    """View all items"""
    user_id = session["user_id"]
    db = get_db()

    items_list = db.execute("""
        SELECT i.id, i.name, i.description, i.photo_uri, i.photo_uri_thumb, i.photo_uri_display,
               COUNT(DISTINCT l.id) as loan_count,
               MAX(l.date_loaned) as last_loaned,
               COALESCE(SUM(CASE WHEN l.disposition = 1 THEN 1 ELSE 0 END), 0) as active_loans
        FROM items i
        LEFT JOIN loans l ON i.id = l.item_id AND l.user_id = ?
        WHERE i.user_id = ? AND (i.is_active = 1 OR i.is_active IS NULL)
        GROUP BY i.id
        ORDER BY i.name ASC
    """, (user_id, user_id)).fetchall()

    db.close()
    user = get_current_user()
    return render_template("items.html", items=items_list, current_user=user)



@app.route('/api/items/<int:item_id>/photos')
@login_required
def api_item_photos(item_id):
    """Get all photos for an item"""
    user_id = session['user_id']
    db = get_db()

    item = db.execute('SELECT id FROM items WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()
    if not item:
        db.close()
        return jsonify({'error': 'Item not found'}), 404

    photos = db.execute(
        'SELECT id, photo_uri, photo_uri_thumb, photo_uri_display, filename, is_default, created_at FROM item_photos WHERE item_id = ? AND user_id = ? ORDER BY is_default DESC, created_at ASC',
        (item_id, user_id)
    ).fetchall()
    db.close()

    return jsonify([dict(p) for p in photos])


@app.route('/api/items/<int:item_id>/photos', methods=['POST'])
@login_required
def api_add_item_photos(item_id):
    """Upload one or more photos for an item"""
    user_id = session['user_id']
    db = get_db()

    item = db.execute('SELECT id, name FROM items WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()
    if not item:
        db.close()
        return jsonify({'error': 'Item not found'}), 404

    files = request.files.getlist('photos')
    if not files or not any(f.filename for f in files):
        db.close()
        return jsonify({'error': 'No files provided'}), 400

    existing_count = db.execute('SELECT COUNT(*) FROM item_photos WHERE item_id = ?', (item_id,)).fetchone()[0]

    new_photos = []
    for idx, photo_file in enumerate(files):
        if not photo_file.filename or not allowed_file(photo_file.filename):
            continue

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'JPEG_{timestamp}_{idx}_{secure_filename(photo_file.filename)}'

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        photo_file.save(filepath)

        photo_uri = f'{config.URL_PREFIX}/static/images/{filename}'

        # Generate variants
        photo_uri_thumb = None
        photo_uri_display = None
        try:
            variants = generate_image_variants(filepath, config.URL_PREFIX)
            photo_uri_thumb = variants['thumb']
            photo_uri_display = variants['display']
        except Exception as e:
            print(f"Warning: Could not generate image variants: {e}")

        is_default = 1 if (existing_count == 0 and idx == 0 and not new_photos) else 0

        db.execute(
            "INSERT INTO item_photos (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, user_id)
        )

        photo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        new_photos.append({'id': photo_id, 'photo_uri': photo_uri, 'photo_uri_thumb': photo_uri_thumb, 'photo_uri_display': photo_uri_display, 'filename': filename, 'is_default': is_default})

        log_audit(db, user_id, 'create', 'item_photo', photo_id, item['name'], {'filename': filename})

    if new_photos:
        sync_default_photo(db, item_id)
        db.commit()

    db.close()
    return jsonify({'success': True, 'photos': new_photos})


@app.route('/api/items/<int:item_id>/photos/<int:photo_id>/set_default', methods=['POST'])
@login_required
def api_set_default_photo(item_id, photo_id):
    """Set a photo as the default for an item"""
    user_id = session['user_id']
    db = get_db()

    photo = db.execute(
        'SELECT id, filename FROM item_photos WHERE id = ? AND item_id = ? AND user_id = ?',
        (photo_id, item_id, user_id)
    ).fetchone()
    if not photo:
        db.close()
        return jsonify({'error': 'Photo not found'}), 404

    db.execute('UPDATE item_photos SET is_default = 0 WHERE item_id = ? AND user_id = ?', (item_id, user_id))
    db.execute('UPDATE item_photos SET is_default = 1 WHERE id = ?', (photo_id,))

    sync_default_photo(db, item_id)

    item = db.execute('SELECT name FROM items WHERE id = ?', (item_id,)).fetchone()
    log_audit(db, user_id, 'update', 'item_photo', photo_id, item['name'] if item else 'Unknown', {'action': 'set_default', 'filename': photo['filename']})

    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/items/<int:item_id>/photos/<int:photo_id>', methods=['DELETE'])
@login_required
def api_delete_item_photo(item_id, photo_id):
    """Delete a photo from an item"""
    user_id = session['user_id']
    db = get_db()

    photo = db.execute(
        'SELECT id, filename, is_default FROM item_photos WHERE id = ? AND item_id = ? AND user_id = ?',
        (photo_id, item_id, user_id)
    ).fetchone()
    if not photo:
        db.close()
        return jsonify({'error': 'Photo not found'}), 404

    was_default = photo['is_default'] == 1

    db.execute('DELETE FROM item_photos WHERE id = ?', (photo_id,))

    if was_default:
        next_photo = db.execute(
            'SELECT id FROM item_photos WHERE item_id = ? AND user_id = ? ORDER BY created_at ASC LIMIT 1',
            (item_id, user_id)
        ).fetchone()
        if next_photo:
            db.execute('UPDATE item_photos SET is_default = 1 WHERE id = ?', (next_photo['id'],))

    sync_default_photo(db, item_id)

    item = db.execute('SELECT name FROM items WHERE id = ?', (item_id,)).fetchone()
    log_audit(db, user_id, 'delete', 'item_photo', photo_id, item['name'] if item else 'Unknown', {'filename': photo['filename']})

    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/items/check_duplicate', methods=['POST'])
@login_required
def check_duplicate_item():
    """Check if item name already exists (case-insensitive, fuzzy match)"""
    user_id = session['user_id']
    data = request.json
    name = data.get('name', '').strip()
    description = data.get('description', '').strip() if 'description' in data else None
    has_photo = data.get('has_photo', False)

    if not name:
        return jsonify({'exists': False})

    db = get_db()

    # Case-insensitive exact match first
    existing = db.execute(
        'SELECT id, name, description, photo_uri, is_active FROM items WHERE LOWER(name) = LOWER(?) AND user_id = ?  LIMIT 1',
        (name, user_id)
    ).fetchone()

    # If no exact match, try fuzzy match (contains or partial)
    if not existing:
        # Check if name is a substring of any existing item or vice versa
        fuzzy_items = db.execute(
            'SELECT id, name, description, photo_uri, is_active FROM items WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(?) LIKE LOWER(name)) AND user_id = ?  ORDER BY LENGTH(name) LIMIT 3',
            ('%{' + name + '}%', '%{' + name + '}%', user_id)
        ).fetchall()

        if fuzzy_items:
            db.close()
            return jsonify({
                'exists': True,
                'fuzzy': True,
                'matches': [dict(i) for i in fuzzy_items],
                'new_data': {
                    'name': name,
                    'description': description,
                    'has_photo': has_photo
                }
            })

    db.close()

    if existing:
        existing_dict = dict(existing)
        # Check if new data has info that existing item is missing
        has_new_info = (
            (description and not existing_dict.get('description')) or
            (has_photo and not existing_dict.get('photo_uri'))
        )

        return jsonify({
            'exists': True,
            'fuzzy': False,
            'item': existing_dict,
            'has_new_info': has_new_info,
            'new_data': {
                'name': name,
                'description': description,
                'has_photo': has_photo
            }
        })
    else:
        return jsonify({'exists': False})

@app.route('/api/items/merge', methods=['POST'])
@login_required
def merge_item():
    """Merge new item data into existing item"""
    user_id = session['user_id']
    data = request.json
    item_id = data.get('item_id')
    new_description = data.get('description', '').strip()
    photo_data = data.get('photo_uri')  # This will be handled separately via form upload

    if not item_id:
        return jsonify({'success': False, 'error': 'Item ID required'}), 400

    db = get_db()

    # Verify item belongs to user
    existing = db.execute(
        'SELECT id, name, description, photo_uri FROM items WHERE id = ? AND user_id = ?',
        (item_id, user_id)
    ).fetchone()

    if not existing:
        db.close()
        return jsonify({'success': False, 'error': 'Item not found'}), 404

    # Merge: only update fields that are currently empty
    update_fields = []
    update_values = []

    if new_description and not existing['description']:
        update_fields.append('description = ?')
        update_values.append(new_description)

    # Note: photo will be handled via regular form upload, not here
    # The frontend will redirect to edit page for photo upload

    if update_fields:
        query = f"UPDATE items SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        update_values.extend([item_id, user_id])
        db.execute(query, update_values)
        db.commit()

    db.close()

    return jsonify({'success': True, 'message': 'Item merged successfully', 'item_id': item_id})
@app.route("/items/add", methods=["GET", "POST"])
@login_required
def add_item():
    """Add a new item"""
    if request.method == "POST":
        user_id = session["user_id"]
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        photo_files = request.files.getlist("photo")

        if not name:
            return redirect(url_for("items", error="Name is required"))

        # Process first valid photo for items.photo_uri (default photo)
        photo_uri = None
        photo_filename = None
        all_photos = []
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

        for idx, photo_file in enumerate(photo_files):
            if not photo_file or not photo_file.filename or not allowed_file(photo_file.filename):
                continue
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"JPEG_{timestamp}_{idx}_{secure_filename(photo_file.filename)}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], fname)
            photo_file.save(filepath)
            puri = f"{config.URL_PREFIX}/static/images/{fname}"

            # Generate variants (thumb and display)
            try:
                variants = generate_image_variants(filepath, config.URL_PREFIX)
                all_photos.append((puri, fname, variants['thumb'], variants['display']))
            except Exception as e:
                print(f"Warning: Could not generate image variants: {e}")
                all_photos.append((puri, fname, None, None))

            if photo_uri is None:
                photo_uri = puri
                photo_filename = fname

        db = get_db()
        cursor = db.execute(
            "INSERT INTO items (name, description, photo_uri, user_id) VALUES (?, ?, ?, ?)",
            (name, description, photo_uri, user_id)
        )
        item_id = cursor.lastrowid

        # Audit log
        log_audit(db, user_id, 'create', 'item', item_id, name)

        # Insert all photos into item_photos table
        for idx, photo_data in enumerate(all_photos):
            is_default = 1 if idx == 0 else 0
            puri, fname = photo_data[0], photo_data[1]
            photo_uri_thumb = photo_data[2] if len(photo_data) > 2 else None
            photo_uri_display = photo_data[3] if len(photo_data) > 3 else None

            db.execute(
                "INSERT INTO item_photos (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
                (item_id, puri, fname, photo_uri_thumb, photo_uri_display, is_default, user_id)
            )
            log_audit(db, user_id, 'create', 'item_photo', item_id, name, {"action": "photo_added", "filename": fname})

        db.commit()
        db.close()

        return redirect(url_for("items", message=f"Item {name} added"))

    user = get_current_user()
    return render_template("add_item.html", current_user=user)
@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    """Edit an item"""
    user_id = session["user_id"]
    db = get_db()

    existing = db.execute("SELECT * FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
    if not existing:
        db.close()
        return redirect(url_for("items", error="Item not found"))

    if request.method == "POST":
        name = request.form.get("name", "").strip().capitalize()
        description = request.form.get("description", "").strip()
        photo_file = request.files.get("photo")

        if not name:
            db.close()
            return redirect(url_for("edit_item", item_id=item_id, error="Name is required"))

        new_photo_uri = None
        new_photo_filename = None
        new_photo_uri_thumb = None
        new_photo_uri_display = None
        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_photo_filename = f"JPEG_{timestamp}_{secure_filename(photo_file.filename)}"

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], new_photo_filename)
            photo_file.save(filepath)
            new_photo_uri = f"{config.URL_PREFIX}/static/images/{new_photo_filename}"

            try:
                variants = generate_image_variants(filepath, config.URL_PREFIX)
                new_photo_uri_thumb = variants['thumb']
                new_photo_uri_display = variants['display']
            except Exception as e:
                print(f"Warning: Could not generate image variants: {e}")

            db.execute(
                "UPDATE items SET name = ?, description = ?, photo_uri = ? WHERE id = ? AND user_id = ?",
                (name, description, new_photo_uri, item_id, user_id)
            )
        else:
            db.execute(
                "UPDATE items SET name = ?, description = ? WHERE id = ? AND user_id = ?",
                (name, description, item_id, user_id)
            )

        # Audit log
        log_audit(db, user_id, 'update', 'item', item_id, name)
        if new_photo_uri:
            action = "photo_added" if not existing['photo_uri'] else "photo_replaced"
            log_audit(db, user_id, 'update', 'item_photo', item_id, name, {"action": action, "filename": new_photo_filename})
            # Also insert into item_photos table
            db.execute('UPDATE item_photos SET is_default = 0 WHERE item_id = ? AND user_id = ?', (item_id, user_id))
            db.execute(
                "INSERT INTO item_photos (item_id, photo_uri, filename, photo_uri_thumb, photo_uri_display, is_default, created_at, user_id) VALUES (?, ?, ?, ?, ?, 1, datetime('now'), ?)",
                (item_id, new_photo_uri, new_photo_filename, new_photo_uri_thumb, new_photo_uri_display, user_id)
            )
            sync_default_photo(db, item_id)

        db.commit()
        db.close()

        # Check for next parameter (e.g., when coming from loan page)
        next_page = request.args.get('next')
        if next_page == 'loan':
            return redirect(url_for("loan", message=f"Item {name} updated"))
        return redirect(url_for("items", message=f"Item {name} updated"))

    db.close()
    user = get_current_user()
    return render_template("edit_item.html", item=existing, current_user=user)
@app.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    """Soft delete an item (mark as inactive) and delete its photo"""
    user_id = session["user_id"]
    db = get_db()

    item = db.execute("SELECT name, photo_uri FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
    item_name = item['name'] if item else 'Unknown'
    photo_uri = item['photo_uri'] if item else None
    photo_filename = None

    if photo_uri:
        photo_filename = photo_uri.rsplit('/', 1)[-1]
        photo_path = Path(app.config["UPLOAD_FOLDER"]) / photo_filename
        try:
            if photo_path.exists():
                photo_path.unlink()
        except Exception:
            # Ignore file removal errors but continue with DB and audit
            pass

    db.execute(
        "UPDATE items SET is_active = 0, photo_uri = NULL WHERE id = ? AND user_id = ?",
        (item_id, user_id)
    )

    # Audit logs
    log_audit(db, user_id, 'delete', 'item', item_id, item_name)
    if photo_uri:
        log_audit(db, user_id, 'delete', 'item_photo', item_id, item_name, {"action": "photo_deleted", "filename": photo_filename})

    db.commit()
    db.close()

    message = "Item deleted"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": message})
    return redirect(url_for("items", message=message))
@app.route('/admin')
@admin_required
def admin():
    """Admin panel"""
    user = get_current_user()
    return render_template('admin.html', current_user=user)


# Audit Log API Endpoints

@app.route('/api/admin/audit_log')
@admin_required
def api_audit_log():
    """Get audit log entries with filters"""
    user_id = request.args.get('user_id')
    action = request.args.get('action')
    entity_type = request.args.get('entity_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    limit = int(request.args.get('limit', 100))

    db = get_db()

    # Build query with filters
    where_clauses = []
    params = []

    if user_id:
        where_clauses.append('user_id = ?')
        params.append(user_id)

    if action:
        where_clauses.append('action = ?')
        params.append(action)

    if entity_type:
        where_clauses.append('entity_type = ?')
        params.append(entity_type)

    if date_from:
        where_clauses.append('timestamp >= ?')
        params.append(date_from)

    if date_to:
        where_clauses.append('timestamp <= ?')
        params.append(date_to)

    where_sql = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''

    query = f"""
        SELECT * FROM audit_log
        {where_sql}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    params.append(limit)

    logs = db.execute(query, params).fetchall()
    db.close()

    return jsonify([dict(log) for log in logs])

@app.route('/api/admin/audit_log/clear', methods=['POST'])
@admin_required
def api_audit_log_clear():
    """Clear audit logs older than specified date"""
    data = request.json
    date_before = data.get('date_before')

    if not date_before:
        return jsonify({'error': 'date_before required'}), 400

    db = get_db()
    cursor = db.execute('DELETE FROM audit_log WHERE timestamp < ?', (date_before,))
    deleted_count = cursor.rowcount
    db.commit()
    db.close()

    return jsonify({'success': True, 'deleted_count': deleted_count})

@app.route('/api/admin/audit_log/stats')
@admin_required
def api_audit_log_stats():
    """Get audit log statistics for filters"""
    db = get_db()

    # Get unique users
    users = db.execute("""
        SELECT DISTINCT user_id, user_email
        FROM audit_log
        ORDER BY user_email
    """).fetchall()

    # Get date range
    date_range = db.execute("""
        SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest
        FROM audit_log
    """).fetchone()

    # Get action counts
    action_counts = db.execute("""
        SELECT action, COUNT(*) as count
        FROM audit_log
        GROUP BY action
    """).fetchall()

    db.close()

    return jsonify({
        'users': [dict(u) for u in users],
        'date_range': dict(date_range) if date_range else None,
        'action_counts': [dict(a) for a in action_counts]
    })


if __name__ == "__main__":
    # Initialize database if it doesn't exist
    if not os.path.exists(app.config["DATABASE"]):
        os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
        init_db()

    # Run the app
    app.run(host="0.0.0.0", port=5000, debug=False)
