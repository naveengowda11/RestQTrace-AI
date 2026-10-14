import os
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / 'instance'
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = INSTANCE_DIR / 'resqtrace.sqlite3'

app = Flask(__name__)
# Persist a local development key so sessions survive restarts. Set RESQTRACE_SECRET_KEY
# from the environment in any deployed environment instead.
def load_secret_key():
    env_key = os.environ.get('RESQTRACE_SECRET_KEY')
    if env_key:
        return env_key
    key_file = INSTANCE_DIR / '.secret_key'
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    return key_file.read_text(encoding='utf-8').strip()

app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('RESQTRACE_HTTPS', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=45),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'rescue')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_username TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
    ''')
    db.commit()


@app.before_request
def prepare_request():
    init_db()
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    g.current_user = None
    user_id = session.get('user_id')
    if user_id:
        user = get_db().execute(
            'SELECT id, username, role, active FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if user and user['active']:
            g.current_user = user
        else:
            session.clear()


def csrf_protect():
    submitted = request.form.get('csrf_token', '')
    expected = session.get('csrf_token', '')
    if not submitted or not expected or not secrets.compare_digest(submitted, expected):
        abort(400, description='Your form expired or was invalid. Refresh the page and try again.')


@app.context_processor
def inject_globals():
    return {'current_user': getattr(g, 'current_user', None), 'csrf_token': session.get('csrf_token', '')}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.current_user:
            flash('Please sign in with an authorized rescue-team account.', 'info')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.current_user['role'] != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def audit(action, target=None):
    if g.current_user:
        get_db().execute(
            'INSERT INTO audit_log (user_id, action, target_username) VALUES (?, ?, ?)',
            (g.current_user['id'], action, target),
        )
        get_db().commit()


# Demonstration data only. These are not live locations or real rescue reports.
ZONES = [
    {"name": "Zone A-01", "key": "detected", "status": "Person detected", "area": "North settlement", "time": "10:20 AM (demo)", "note": "A person-like object is marked in the sample record; human verification is required.", "action": "Review the image and escalate for human assessment.", "lat": 12.3020, "lng": 76.6350},
    {"name": "Zone B-14", "key": "uncertain", "status": "Uncertain", "area": "Eastern tree line", "time": "09:45 AM (demo)", "note": "Sample image is partially obscured, so the available evidence is inconclusive.", "action": "Consider another observation if risk and access conditions justify it.", "lat": 12.2995, "lng": 76.6500},
    {"name": "Zone C-03", "key": "outdated", "status": "Evidence outdated", "area": "Riverside road", "time": "07:30 AM (demo)", "note": "A simulated rising-water report means the earlier observation may need review.", "action": "Reassess the old evidence and verify current access conditions.", "lat": 12.2890, "lng": 76.6420},
    {"name": "Zone D-08", "key": "unsearched", "status": "Not searched", "area": "Southern blocks", "time": "No observation recorded", "note": "No relevant search evidence is stored for this sample zone.", "action": "Assess whether this area should be included in the next search.", "lat": 12.2850, "lng": 76.6300},
    {"name": "Zone E-05", "key": "reviewed", "status": "Searched — no detection", "area": "Western access road", "time": "10:05 AM (demo)", "note": "The sample record says an image was reviewed with no person detected; this does not prove safety.", "action": "Retain the record and reassess if new evidence or conditions change.", "lat": 12.3060, "lng": 76.6460},
    {"name": "Zone F-11", "key": "uncertain", "status": "Uncertain", "area": "Low-lying houses", "time": "09:10 AM (demo)", "note": "Sample visibility is limited and no reliable conclusion can be drawn.", "action": "Review image quality and consider further inspection based on risk.", "lat": 12.2920, "lng": 76.6220},
]
PRIORITIES = [
    {"name": "Zone A-01", "status": "Human review", "pill": "pill-red", "reason": "A person-like object is marked in the sample record; verify the detection.", "score": 92},
    {"name": "Zone B-14", "status": "Uncertain", "pill": "pill-amber", "reason": "Obscured imagery leaves an important evidence gap.", "score": 78},
    {"name": "Zone C-03", "status": "Reassess", "pill": "pill-orange", "reason": "A simulated hazard update may make the old observation unreliable.", "score": 71},
]


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.current_user:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        csrf_protect()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_db().execute(
            'SELECT id, username, password_hash, role, active FROM users WHERE username = ? COLLATE NOCASE',
            (username,),
        ).fetchone()
        if user and user['active'] and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['csrf_token'] = secrets.token_urlsafe(32)
            session.permanent = True
            g.current_user = user
            audit('login_success')
            destination = request.args.get('next', '')
            if not destination.startswith('/') or destination.startswith('//'):
                destination = url_for('dashboard')
            return redirect(destination)
        # Keep the message generic so the page does not reveal whether a username exists.
        flash('Invalid username or password, or this account is inactive.', 'error')
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    csrf_protect()
    audit('logout')
    session.clear()
    flash('You have been signed out.', 'success')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    metrics = {
        'total': len(ZONES),
        'detected': sum(1 for zone in ZONES if zone['key'] == 'detected'),
        'uncertain': sum(1 for zone in ZONES if zone['key'] == 'uncertain'),
        'review': sum(1 for zone in ZONES if zone['key'] in {'unsearched', 'outdated'}),
    }
    return render_template('dashboard.html', zones=ZONES, priorities=PRIORITIES, metrics=metrics)


@app.route('/admin/users', methods=['GET', 'POST'])
@admin_required
def manage_users():
    db = get_db()
    if request.method == 'POST':
        csrf_protect()
        action = request.form.get('action', '')
        username = request.form.get('username', '').strip()
        if action == 'create':
            password = request.form.get('password', '')
            role = request.form.get('role', 'rescue')
            if len(username) < 3 or len(username) > 60 or not username.replace('_', '').replace('-', '').isalnum():
                flash('Username must be 3–60 characters and use letters, numbers, hyphens, or underscores.', 'error')
            elif len(password) < 12:
                flash('Use a temporary password of at least 12 characters.', 'error')
            elif role not in {'admin', 'rescue'}:
                flash('Choose a valid role.', 'error')
            else:
                try:
                    db.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                               (username, generate_password_hash(password), role))
                    db.commit()
                    audit('user_created', username)
                    flash(f'Account created for {username}. Share its temporary password securely.', 'success')
                except sqlite3.IntegrityError:
                    flash('That username already exists.', 'error')
        elif action == 'toggle':
            target = db.execute('SELECT id, username, active, role FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
            if not target:
                flash('Account not found.', 'error')
            elif target['id'] == g.current_user['id']:
                flash('You cannot deactivate your own account.', 'error')
            elif target['role'] == 'admin' and target['active'] and db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                flash('At least one active administrator must remain.', 'error')
            else:
                db.execute('UPDATE users SET active = ? WHERE id = ?', (0 if target['active'] else 1, target['id']))
                db.commit()
                audit('user_deactivated' if target['active'] else 'user_activated', username)
                flash(f'Account {username} updated.', 'success')
        return redirect(url_for('manage_users'))
    users = db.execute('SELECT username, role, active, created_at FROM users ORDER BY created_at DESC').fetchall()
    logs = db.execute('''SELECT audit_log.action, audit_log.target_username, audit_log.created_at, users.username AS actor
                         FROM audit_log LEFT JOIN users ON users.id = audit_log.user_id
                         ORDER BY audit_log.id DESC LIMIT 20''').fetchall()
    return render_template('admin_users.html', users=users, logs=logs)


@app.cli.command('create-admin')
@click.argument('username')
def create_admin(username):
    """Create an administrator account interactively; no default credentials exist."""
    init_db()
    password = click.prompt('Set admin password', hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        raise click.ClickException('Password must be at least 12 characters.')
    try:
        get_db().execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                         (username.strip(), generate_password_hash(password), 'admin'))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise click.ClickException('That username already exists.')
    click.echo(f'Administrator account created for {username}.')


@app.errorhandler(403)
def forbidden(_error):
    return render_template('error.html', code=403, title='Access denied', message='Your account does not have permission to access this page.'), 403


@app.errorhandler(400)
def bad_request(error):
    return render_template('error.html', code=400, title='Request could not be verified', message=getattr(error, 'description', 'Please refresh and try again.')), 400


if __name__ == '__main__':
    # Debug mode is convenient locally. Do not enable it on a public deployment.
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
