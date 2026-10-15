import os
import secrets
import sqlite3
import json
import math
import uuid
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageStat, ImageChops, ImageEnhance, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / 'instance'
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = INSTANCE_DIR / 'resqtrace.sqlite3'
UPLOAD_DIR = INSTANCE_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}

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
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
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
        CREATE TABLE IF NOT EXISTS condition_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_name TEXT NOT NULL,
            condition_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            reported_by INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(reported_by) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS search_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_name TEXT NOT NULL COLLATE NOCASE,
            search_status TEXT NOT NULL CHECK(search_status IN ('not_searched','in_progress','searched','needs_recheck')),
            searched_at TEXT,
            searched_by INTEGER,
            notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(searched_by) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_search_records_zone ON search_records(zone_name, updated_at);
        CREATE TABLE IF NOT EXISTS person_detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            person_index INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            bbox_json TEXT NOT NULL DEFAULT '[]',
            review_score INTEGER NOT NULL DEFAULT 40,
            priority_label TEXT NOT NULL DEFAULT 'Review required',
            priority_reason TEXT NOT NULL DEFAULT 'Human review required.',
            latitude REAL, longitude REAL,
            location_status TEXT NOT NULL DEFAULT 'unmapped',
            location_source TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(analysis_id, person_index),
            FOREIGN KEY(analysis_id) REFERENCES image_analyses(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_person_detections_analysis ON person_detections(analysis_id);
        CREATE INDEX IF NOT EXISTS idx_person_detections_priority ON person_detections(review_score DESC);
        CREATE TABLE IF NOT EXISTS rescue_team_locations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE, latitude REAL NOT NULL, longitude REAL NOT NULL, accuracy REAL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS image_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uploaded_by INTEGER,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            image_quality TEXT NOT NULL,
            analysis_mode TEXT NOT NULL,
            detections_json TEXT NOT NULL DEFAULT '[]',
            condition_results_json TEXT NOT NULL DEFAULT '[]',
            inference_status TEXT NOT NULL DEFAULT 'not_run',
            summary TEXT NOT NULL,
            zone_name TEXT NOT NULL DEFAULT 'Unassigned zone',
            evidence_status TEXT NOT NULL DEFAULT 'uncertain',
            priority_score INTEGER NOT NULL DEFAULT 50,
            priority_reason TEXT NOT NULL DEFAULT 'Evidence requires human review.',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL
        );
    ''')
    # Lightweight migration for databases created by earlier project phases.
    existing_columns = {row['name'] for row in db.execute('PRAGMA table_info(image_analyses)').fetchall()}
    migrations = {
        'zone_name': "ALTER TABLE image_analyses ADD COLUMN zone_name TEXT NOT NULL DEFAULT 'Unassigned zone'",
        'evidence_status': "ALTER TABLE image_analyses ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'uncertain'",
        'priority_score': 'ALTER TABLE image_analyses ADD COLUMN priority_score INTEGER NOT NULL DEFAULT 50',
        'priority_reason': "ALTER TABLE image_analyses ADD COLUMN priority_reason TEXT NOT NULL DEFAULT 'Evidence requires human review.'",
        'condition_results_json': "ALTER TABLE image_analyses ADD COLUMN condition_results_json TEXT NOT NULL DEFAULT '[]'",
        'inference_status': "ALTER TABLE image_analyses ADD COLUMN inference_status TEXT NOT NULL DEFAULT 'not_run'",
    }
    for column, statement in migrations.items():
        if column not in existing_columns:
            db.execute(statement)
    db.commit()

    # Optional first-admin bootstrap for hosts where interactive Shell access is unavailable.
    # Set both variables in the hosting provider's environment settings; never hardcode passwords.
    admin_username = os.environ.get('RESQTRACE_ADMIN_USERNAME', '').strip()
    admin_password = os.environ.get('RESQTRACE_ADMIN_PASSWORD', '')
    if admin_username and admin_password:
        if (len(admin_username) < 3 or len(admin_username) > 60
                or not admin_username.replace('_', '').replace('-', '').isalnum()):
            raise RuntimeError('RESQTRACE_ADMIN_USERNAME must be 3-60 characters using letters, numbers, hyphens, or underscores.')
        if len(admin_password) < 12:
            raise RuntimeError('RESQTRACE_ADMIN_PASSWORD must be at least 12 characters.')
        existing_admin = db.execute(
            'SELECT id FROM users WHERE username = ? COLLATE NOCASE',
            (admin_username,),
        ).fetchone()
        if not existing_admin:
            db.execute(
                'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                (admin_username, generate_password_hash(admin_password), 'admin'),
            )
            db.commit()


def load_georeference(uploaded_file):
    """Read an optional affine pixel-to-WGS84 transform sidecar; never infer coordinates."""
    if not uploaded_file or not getattr(uploaded_file, 'filename', ''):
        return None
    try:
        uploaded_file.stream.seek(0)
        if len(uploaded_file.read(256 * 1024 + 1)) > 256 * 1024:
            raise ValueError('Georeference JSON must be 256 KB or smaller.')
        uploaded_file.stream.seek(0)
        data = json.load(uploaded_file.stream)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('Georeference file must be valid JSON.') from exc
    finally:
        try: uploaded_file.stream.seek(0)
        except Exception: pass
    if not isinstance(data, dict) or str(data.get('crs', '')).upper() not in ('EPSG:4326', 'WGS84', 'WGS 84'):
        raise ValueError('Coordinates must use EPSG:4326 / WGS84.')
    transform = data.get('pixel_to_geo', {})
    lat, lon = transform.get('lat'), transform.get('lon')
    if not (isinstance(lat, list) and isinstance(lon, list) and len(lat) == 3 and len(lon) == 3):
        raise ValueError('JSON must include pixel_to_geo.lat and pixel_to_geo.lon arrays with three coefficients each.')
    try:
        lat = [float(v) for v in lat]; lon = [float(v) for v in lon]
    except (TypeError, ValueError) as exc:
        raise ValueError('Transform coefficients must be numeric.') from exc
    import math
    if not all(math.isfinite(v) for v in lat + lon):
        raise ValueError('Transform coefficients must be finite numbers.')
    return {'lat': lat, 'lon': lon}


def load_geotiff_georeference(file_stream, filename):
    """Read georeferencing from a GeoTIFF itself; never infer it from a plain photograph."""
    if Path(filename or '').suffix.lower() not in ('.tif', '.tiff'):
        return None
    try:
        file_stream.seek(0)
        import rasterio
        with rasterio.open(file_stream) as dataset:
            if dataset.crs is None:
                raise ValueError('This TIFF has no coordinate reference system. Use a georeferenced GeoTIFF or provide a verified JSON transform.')
            if dataset.transform is None:
                raise ValueError('This TIFF has no pixel-to-map transform; coordinates cannot be calculated.')
            transform = dataset.transform
            result = {
                'kind': 'geotiff',
                'crs': dataset.crs.to_string(),
                'affine': [float(transform.a), float(transform.b), float(transform.c),
                           float(transform.d), float(transform.e), float(transform.f)],
                'width': int(dataset.width), 'height': int(dataset.height),
            }
            if dataset.width <= 0 or dataset.height <= 0:
                raise ValueError('GeoTIFF has invalid dimensions.')
            return result
    except ImportError as exc:
        raise ValueError('GeoTIFF support is not installed. Run: pip install -r requirements-gis.txt') from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Could not read GeoTIFF georeferencing. Verify the file and try again.') from exc
    finally:
        try: file_stream.seek(0)
        except Exception: pass


def map_pixel_to_geo(box, transform):
    """Return WGS84 coordinates only from a supplied verified transform or GeoTIFF CRS."""
    if not transform or not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x = (float(box[0]) + float(box[2])) / 2
        y = (float(box[1]) + float(box[3])) / 2
        if transform.get('kind') == 'geotiff':
            a, b, c, d, e, f = transform['affine']
            map_x, map_y = a*x + b*y + c, d*x + e*y + f
            from pyproj import Transformer
            converter = Transformer.from_crs(transform['crs'], 'EPSG:4326', always_xy=True)
            lon, lat = converter.transform(map_x, map_y)
        else:
            lat = transform['lat'][0] * x + transform['lat'][1] * y + transform['lat'][2]
            lon = transform['lon'][0] * x + transform['lon'][1] * y + transform['lon'][2]
    except (TypeError, ValueError, KeyError, IndexError, ImportError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 7), round(lon, 7)


def person_review_priority(detection, condition_results, quality):
    """Explainable triage heuristic only; not a validated danger or survival prediction."""
    score = 40
    reasons = ['Candidate person detection needs human verification']
    try: confidence = float(detection.get('confidence', 0))
    except (TypeError, ValueError): confidence = 0
    if confidence >= 0.65:
        score += 15; reasons.append('detector confidence is at least 0.65')
    if 'Low contrast' in quality or 'Low resolution' in quality:
        reasons.append('image quality may reduce reliability')
    if condition_results:
        label = str(condition_results[0].get('label', '')).lower()
        if 'flood' in label:
            score += 15; reasons.append('image-level screening ranked flood highest; this does not prove the person is in danger')
        elif any(word in label for word in ('landslide', 'mudslide', 'collapsed', 'damaged', 'wildfire', 'burned')):
            score += 8; reasons.append('image-level screening suggests a possible hazard; location-specific danger is unverified')
    score = min(score, 70)
    priority = 'High review priority' if score >= 60 else ('Medium review priority' if score >= 48 else 'Review required')
    return score, priority, '; '.join(reasons) + '. This is a review queue score, not a probability.'


def assess_evidence(analysis_mode, quality, detections, created_at=None):
    """Transparent prototype rules; not a validated rescue-risk model."""
    person_detections = [d for d in detections if str(d.get('label', '')).lower() == 'person']
    age_hours = None
    if created_at:
        try:
            stamp = datetime.strptime(str(created_at), '%Y-%m-%d %H:%M:%S')
            age_hours = max(0, (datetime.utcnow() - stamp).total_seconds() / 3600)
        except (TypeError, ValueError):
            pass

    if age_hours is not None and age_hours >= 24:
        status = 'outdated'
        score = 72
        reason = 'This observation is at least 24 hours old; conditions may have changed. Request a fresh observation if appropriate.'
    elif 'Low contrast' in quality or 'Low resolution' in quality or analysis_mode == 'detector-error':
        status = 'uncertain'
        score = 78
        reason = 'Image quality or processing limitations reduce confidence; request human review or a clearer observation.'
    elif person_detections:
        status = 'person_detected'
        score = 92
        reason = 'The model marked one or more person-like objects. Verify each detection; these are not confirmed survivors.'
    elif analysis_mode in ('ai-screening-complete', 'person-detection-complete'):
        status = 'searched_no_detection'
        score = 58
        reason = 'The detector ran but returned no person detections. This is not proof that people are absent or the area is safe.'
    else:
        status = 'uncertain'
        score = 76
        reason = 'No configured detector result is available, so the image cannot be classified as a completed search.'
    return status, score, reason


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
    db = get_db()
    total = db.execute("SELECT COUNT(DISTINCT zone_name) FROM image_analyses").fetchone()[0]
    recent_evidence = [dict(row) for row in db.execute("SELECT id, zone_name, original_name, evidence_status, priority_score, priority_reason, image_quality, analysis_mode, detections_json, created_at FROM image_analyses ORDER BY id DESC LIMIT 8").fetchall()]
    for item in recent_evidence:
        try:
            dets = json.loads(item.get('detections_json') or '[]')
            if not isinstance(dets, list): dets = []
        except (TypeError, json.JSONDecodeError): dets = []
        status, score, reason = assess_evidence(item.get('analysis_mode',''), item.get('image_quality',''), dets, item.get('created_at'))
        item.update(evidence_status=status, priority_score=score, priority_reason=reason)
    reports = [dict(row) for row in db.execute("SELECT cr.*, u.username AS reporter FROM condition_reports cr LEFT JOIN users u ON u.id=cr.reported_by ORDER BY cr.id DESC LIMIT 10").fetchall()]
    evidence_counts = {
        'total': db.execute('SELECT COUNT(*) FROM image_analyses').fetchone()[0],
        'uncertain': db.execute("SELECT COUNT(*) FROM image_analyses WHERE evidence_status='uncertain'").fetchone()[0],
        'detected': db.execute("SELECT COUNT(*) FROM image_analyses WHERE evidence_status='person_detected'").fetchone()[0],
        'review': db.execute("SELECT COUNT(*) FROM image_analyses WHERE evidence_status IN ('uncertain','outdated','searched_no_detection')").fetchone()[0],
    }
    metrics = {'total': total, 'detected': evidence_counts['detected'], 'uncertain': evidence_counts['uncertain'], 'review': evidence_counts['review']}
    return render_template('dashboard.html', zones=[], priorities=[], metrics=metrics,
                           recent_evidence=recent_evidence, evidence_counts=evidence_counts,
                           recent_condition_alerts=reports)

@app.route('/analysis', methods=['GET', 'POST'])
@login_required
def image_analysis():
    # Upload an aerial image and run the configured local inference services.
    db = get_db()
    if request.method == 'POST':
        csrf_protect()
        uploaded = request.files.get('image')
        if not uploaded or not uploaded.filename:
            flash('Choose an image file before submitting.', 'error')
            return redirect(url_for('image_analysis'))

        original_name = secure_filename(uploaded.filename) or 'uploaded-image'
        try:
            georeference = load_georeference(request.files.get('georeference'))
            embedded_georeference = load_geotiff_georeference(uploaded.stream, original_name)
            if embedded_georeference:
                georeference = embedded_georeference
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('image_analysis'))

        zone_name = request.form.get('zone_name', '').strip()[:80] or 'Unassigned zone'
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            flash('Use a JPG, JPEG, PNG, WEBP, or georeferenced TIFF/GeoTIFF image.', 'error')
            return redirect(url_for('image_analysis'))

        stored_name = f'{uuid.uuid4().hex}{suffix}'
        stored_path = UPLOAD_DIR / stored_name
        try:
            # Decode and validate the image before keeping it. Pillow verifies file content,
            # not just the filename extension.
            uploaded.stream.seek(0)
            with Image.open(uploaded.stream) as image:
                image.verify()
            uploaded.stream.seek(0)
            with Image.open(uploaded.stream) as image:
                image = image.convert('RGB')
                width, height = image.size
                if width < 64 or height < 64:
                    flash('Image is too small for useful analysis. Upload an image at least 64 × 64 pixels.', 'error')
                    return redirect(url_for('image_analysis'))
                # A simple technical quality hint, not a determination of search completeness.
                gray = image.convert('L').resize((min(256, width), min(256, height)))
                contrast = ImageStat.Stat(gray).stddev[0]
                if contrast < 18:
                    quality = 'Low contrast — review manually'
                elif width < 640 or height < 480:
                    quality = 'Low resolution — review manually'
                else:
                    quality = 'Basic image checks passed — visual review still required'
                save_format = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP', '.tif': 'TIFF', '.tiff': 'TIFF'}[suffix]
                save_options = {'quality': 92} if save_format == 'JPEG' else {}
                image.save(stored_path, format=save_format, optimize=True, **save_options)
                stored_name = stored_path.name
        except (UnidentifiedImageError, OSError, ValueError):
            flash('The uploaded file could not be read as a valid image.', 'error')
            return redirect(url_for('image_analysis'))

        from services.inference import run_image_analysis
        inference = run_image_analysis(stored_path)
        detections = inference['detections']
        condition_results = inference['conditions']
        person_status = inference['person_status']
        condition_status = inference['condition_status']
        completed_tasks = sum(status == 'completed' for status in (person_status, condition_status))
        if completed_tasks == 2:
            analysis_mode = 'ai-screening-complete'
        elif completed_tasks == 1:
            analysis_mode = 'person-detection-complete' if person_status == 'completed' else 'condition-screening-complete'
        else:
            analysis_mode = 'detector-error'
        people = len(detections)
        if completed_tasks:
            top_condition = condition_results[0] if condition_results else None
            condition_text = (f" Top visual condition match: {top_condition['label']} (similarity {top_condition['score']:.2f}; not a calibrated probability)." if top_condition else '')
            summary = (f"Analysis completed for {completed_tasks} of 2 tasks. {people} possible person detection(s) were returned."
                       f"{condition_text} Review the original image and all outputs manually; these are not confirmed survivors or verified damage.")
        else:
            summary = 'The image was saved and validated, but AI analysis did not run. No prediction was generated. Install the AI dependencies and check the setup before retrying.'
        if inference['errors']:
            summary += ' ' + ' '.join(inference['errors'])

        evidence_status, priority_score, priority_reason = assess_evidence(
            analysis_mode, quality, detections
        )
        db.execute('''INSERT INTO image_analyses
            (uploaded_by, original_name, stored_name, width, height, image_quality,
             analysis_mode, detections_json, condition_results_json, inference_status,
             summary, zone_name, evidence_status, priority_score, priority_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (g.current_user['id'], original_name, stored_name, width, height, quality,
             analysis_mode, json.dumps(detections), json.dumps(condition_results),
             f"person:{person_status};conditions:{condition_status}", summary, zone_name,
             evidence_status, priority_score, priority_reason))
        db.commit()
        analysis_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        for idx, detection in enumerate([d for d in detections if str(d.get('label', '')).lower() == 'person'], start=1):
            box = detection.get('box', [])
            geo = map_pixel_to_geo(box, georeference)
            review_score, priority_label, priority_reason = person_review_priority(detection, condition_results, quality)
            db.execute('''INSERT OR REPLACE INTO person_detections
                (analysis_id, person_index, confidence, bbox_json, review_score, priority_label,
                 priority_reason, latitude, longitude, location_status, location_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (analysis_id, idx, float(detection.get('confidence', 0) or 0), json.dumps(box),
                 review_score, priority_label, priority_reason,
                 geo[0] if geo else None, geo[1] if geo else None,
                 'mapped' if geo else 'coordinates unavailable',
                 ('GeoTIFF embedded affine transform + CRS converted to WGS84' if georeference and georeference.get('kind') == 'geotiff' else 'Supplied WGS84 affine transform for georeferenced orthomosaic') if geo else 'none'))
        db.commit()
        audit('image_uploaded_and_analyzed', original_name[:100])
        return redirect(url_for('analysis_detail', analysis_id=analysis_id))

    analyses = db.execute('''SELECT id, original_name, width, height, image_quality,
        analysis_mode, summary, created_at FROM image_analyses ORDER BY id DESC LIMIT 20''').fetchall()
    return render_template('analysis.html', analyses=analyses)


@app.route('/analysis/<int:analysis_id>')
@login_required
def analysis_detail(analysis_id):
    record = get_db().execute('''SELECT image_analyses.*, users.username AS uploader
        FROM image_analyses LEFT JOIN users ON users.id = image_analyses.uploaded_by
        WHERE image_analyses.id = ?''', (analysis_id,)).fetchone()
    if not record:
        abort(404)
    record = dict(record)
    record['detections'] = json.loads(record.pop('detections_json'))
    record['condition_results'] = json.loads(record.pop('condition_results_json', '[]') or '[]')
    record['inference_status'] = record.get('inference_status', 'not_run')
    record['people'] = [dict(row) for row in get_db().execute('SELECT * FROM person_detections WHERE analysis_id = ? ORDER BY review_score DESC, person_index', (analysis_id,)).fetchall()]
    for person in record['people']:
        try: person['bbox'] = json.loads(person.pop('bbox_json') or '[]')
        except (TypeError, json.JSONDecodeError): person['bbox'] = []
    # Re-evaluate age so old evidence becomes visibly outdated over time.
    status, score, reason = assess_evidence(
        record['analysis_mode'], record['image_quality'], record['detections'], record['created_at']
    )
    record['evidence_status'] = status
    record['priority_score'] = score
    record['priority_reason'] = reason
    return render_template('analysis_detail.html', record=record)


@app.route('/people-map')
@login_required
def people_map():
    rows = get_db().execute("""SELECT p.*, a.zone_name, a.original_name, a.created_at AS observation_time
        FROM person_detections p JOIN image_analyses a ON a.id=p.analysis_id
        ORDER BY p.review_score DESC, p.id DESC""").fetchall()
    people = [dict(row) for row in rows]
    mapped_count = sum(1 for person in people if person.get('latitude') is not None and person.get('longitude') is not None)
    return render_template('people_map.html', people=people, mapped_count=mapped_count)



@app.route('/rescue-teams')
@login_required
def rescue_teams():
    rows = get_db().execute("SELECT r.user_id, u.username, r.latitude, r.longitude, r.accuracy, r.updated_at FROM rescue_team_locations r JOIN users u ON u.id=r.user_id ORDER BY r.updated_at DESC").fetchall()
    return render_template('rescue_teams.html', teams=[dict(row) for row in rows])

@app.route('/api/rescue-team/location', methods=['POST'])
@login_required
def update_rescue_location():
    data = request.get_json(silent=True) or {}
    try:
        lat, lon = float(data.get('latitude')), float(data.get('longitude'))
        accuracy = float(data.get('accuracy', 0) or 0)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'Latitude and longitude are required.'}, 400
    if not (11.3 <= lat <= 18.5 and 74.0 <= lon <= 78.8):
        return {'ok': False, 'error': 'Location is outside the Karnataka operating area.'}, 400
    db = get_db()
    db.execute("INSERT INTO rescue_team_locations(user_id, latitude, longitude, accuracy, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET latitude=excluded.latitude, longitude=excluded.longitude, accuracy=excluded.accuracy, updated_at=CURRENT_TIMESTAMP", (g.current_user['id'], lat, lon, accuracy))
    db.commit()
    return {'ok': True, 'message': 'Location updated', 'latitude': lat, 'longitude': lon}

@app.route('/api/rescue-team/locations')
@login_required
def rescue_locations():
    rows = get_db().execute("SELECT r.user_id, u.username, r.latitude, r.longitude, r.accuracy, r.updated_at FROM rescue_team_locations r JOIN users u ON u.id=r.user_id ORDER BY r.updated_at DESC").fetchall()
    return {'teams': [dict(row) for row in rows]}

@app.route('/memory-map')
@login_required
def memory_map():
    """Show a zone-by-zone history and compare the latest two observations."""
    rows = get_db().execute("""SELECT id, zone_name, original_name, width, height,
        image_quality, analysis_mode, detections_json, summary, evidence_status,
        priority_score, priority_reason, created_at
        FROM image_analyses ORDER BY zone_name COLLATE NOCASE, id DESC""").fetchall()
    groups = {}
    for row in rows:
        item = dict(row)
        try:
            detections = json.loads(item.get('detections_json') or '[]')
            if not isinstance(detections, list):
                detections = []
        except (TypeError, json.JSONDecodeError):
            detections = []
        item['detections'] = detections
        item['label_counts'] = {}
        for detection in detections:
            label = str(detection.get('label', 'unknown')).strip().title() or 'Unknown'
            item['label_counts'][label] = item['label_counts'].get(label, 0) + 1
        status, score, reason = assess_evidence(
            item.get('analysis_mode', ''), item.get('image_quality', ''), detections,
            item.get('created_at'))
        item.update(evidence_status=status, priority_score=score, priority_reason=reason)
        groups.setdefault(item['zone_name'] or 'Unassigned zone', []).append(item)

    zone_history = []
    for zone_name, history in groups.items():
        latest = history[0]
        previous = history[1] if len(history) > 1 else None
        changes = []
        if previous:
            labels = sorted(set(latest['label_counts']) | set(previous['label_counts']))
            for label in labels:
                before = previous['label_counts'].get(label, 0)
                after = latest['label_counts'].get(label, 0)
                if before != after:
                    changes.append({'label': label, 'before': before, 'after': after, 'delta': after - before})
            if latest['evidence_status'] != previous['evidence_status']:
                changes.append({'label': 'Evidence status', 'before': previous['evidence_status'].replace('_', ' ').title(),
                                'after': latest['evidence_status'].replace('_', ' ').title(), 'delta': None})
            if latest['image_quality'] != previous['image_quality']:
                changes.append({'label': 'Image quality', 'before': previous['image_quality'],
                                'after': latest['image_quality'], 'delta': None})
        zone_history.append({
            'zone_name': zone_name, 'history': history, 'latest': latest,
            'previous': previous, 'changes': changes,
            'observation_count': len(history),
            'has_comparison': previous is not None,
        })
    zone_history.sort(key=lambda group: (-group['latest']['priority_score'], group['zone_name'].lower()))
    return render_template('memory_map.html', zone_history=zone_history,
                           total_observations=len(rows), total_zones=len(groups))



@app.route('/visual-compare', methods=['GET', 'POST'])
@login_required
def visual_compare():
    """Compare two uploaded images from one zone using a simple pixel-difference preview."""
    db = get_db()
    zones = db.execute("""SELECT zone_name, COUNT(*) AS image_count
        FROM image_analyses GROUP BY zone_name ORDER BY zone_name COLLATE NOCASE""").fetchall()
    selected_zone = request.values.get('zone_name', '').strip()
    images = []
    comparison = None
    error = None
    if selected_zone:
        images = db.execute("""SELECT id, original_name, stored_name, width, height, image_quality,
            analysis_mode, created_at FROM image_analyses WHERE zone_name = ? ORDER BY id DESC""",
            (selected_zone,)).fetchall()
    if request.method == 'POST':
        csrf_protect()
        try:
            older_id = int(request.form.get('older_id', '0'))
            newer_id = int(request.form.get('newer_id', '0'))
        except ValueError:
            older_id, newer_id = 0, 0
        if not selected_zone:
            error = 'Choose a zone first.'
        elif older_id == newer_id or not older_id or not newer_id:
            error = 'Choose two different observations to compare.'
        else:
            rows = db.execute("""SELECT id, zone_name, original_name, stored_name, width, height, created_at
                FROM image_analyses WHERE id IN (?, ?)""", (older_id, newer_id)).fetchall()
            by_id = {row['id']: dict(row) for row in rows}
            if len(by_id) != 2 or any((row['zone_name'] or '').strip().casefold() != selected_zone.casefold() for row in by_id.values()):
                error = 'Both observations must belong to the selected zone.'
            else:
                older, newer = by_id[older_id], by_id[newer_id]
                try:
                    old_path, new_path = (UPLOAD_DIR / older['stored_name']).resolve(), (UPLOAD_DIR / newer['stored_name']).resolve()
                    if UPLOAD_DIR.resolve() not in old_path.parents or UPLOAD_DIR.resolve() not in new_path.parents or not old_path.is_file() or not new_path.is_file():
                        raise OSError('Stored image is missing')
                    with Image.open(old_path) as im:
                        old_image = im.convert('RGB')
                    with Image.open(new_path) as im:
                        new_image = im.convert('RGB')
                    # Normalized thumbnail comparison is a rough screening aid only; images may not be aligned.
                    size = (320, 320)
                    old_thumb = old_image.copy(); old_thumb.thumbnail(size)
                    new_thumb = new_image.copy(); new_thumb.thumbnail(size)
                    canvas_size = (max(old_thumb.width, new_thumb.width), max(old_thumb.height, new_thumb.height))
                    old_canvas = Image.new('RGB', canvas_size, 'white')
                    new_canvas = Image.new('RGB', canvas_size, 'white')
                    old_canvas.paste(old_thumb, ((canvas_size[0]-old_thumb.width)//2, (canvas_size[1]-old_thumb.height)//2))
                    new_canvas.paste(new_thumb, ((canvas_size[0]-new_thumb.width)//2, (canvas_size[1]-new_thumb.height)//2))
                    diff = ImageChops.difference(old_canvas, new_canvas).convert('L')
                    diff = ImageEnhance.Contrast(diff).enhance(2.5)
                    mean_diff = sum(ImageStat.Stat(diff).mean) / len(ImageStat.Stat(diff).mean)
                    # Fraction of pixels with a visible intensity difference, useful for triage not truth.
                    changed = sum(1 for value in diff.getdata() if value > 35)
                    total = diff.width * diff.height
                    change_pct = round((changed / total) * 100, 1) if total else 0
                    buf = BytesIO(); diff.save(buf, format='PNG'); diff_data = buf.getvalue()
                    comparison = {
                        'older': older, 'newer': newer, 'change_pct': change_pct,
                        'mean_difference': round(mean_diff, 1),
                        'diff_data': __import__('base64').b64encode(diff_data).decode('ascii'),
                        'warning': 'Pixel differences can come from camera angle, zoom, lighting, image alignment, or compression. This score does not identify flooding or prove physical change.'
                    }
                except (OSError, ValueError) as exc:
                    error = 'Could not compare these files. Check that both uploaded images are still available.'
    return render_template('visual_compare.html', zones=zones, images=images,
                           selected_zone=selected_zone, comparison=comparison, error=error)


@app.route('/coverage', methods=['GET', 'POST'])
@login_required
def search_coverage():
    """Track explicitly recorded search coverage per zone."""
    db = get_db()
    if request.method == 'POST':
        csrf_protect()
        zone = request.form.get('zone_name', '').strip()[:80]
        status = request.form.get('search_status', '')
        notes = request.form.get('notes', '').strip()[:1000]
        allowed = {'not_searched', 'in_progress', 'searched', 'needs_recheck'}
        if not zone or status not in allowed:
            flash('Enter a zone and choose a valid search status.', 'error')
        else:
            searched_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') if status == 'searched' else None
            db.execute('INSERT INTO search_records (zone_name, search_status, searched_at, searched_by, notes, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                       (zone, status, searched_at, g.current_user['id'], notes))
            db.commit()
            flash('Search coverage record saved.', 'success')
        return redirect(url_for('search_coverage'))

    names = set()
    for row in db.execute('SELECT DISTINCT zone_name FROM image_analyses').fetchall(): names.add(row['zone_name'])
    for row in db.execute('SELECT DISTINCT zone_name FROM condition_reports').fetchall(): names.add(row['zone_name'])
    for row in db.execute('SELECT DISTINCT zone_name FROM search_records').fetchall(): names.add(row['zone_name'])
    latest_records = {}
    for row in db.execute('SELECT sr.*, u.username AS reporter FROM search_records sr LEFT JOIN users u ON u.id=sr.searched_by ORDER BY sr.id DESC').fetchall():
        latest_records.setdefault(row['zone_name'].strip().casefold(), dict(row))
    zones = []
    for name in sorted(names, key=str.casefold):
        key = name.strip().casefold()
        record = latest_records.get(key)
        image_count = db.execute('SELECT COUNT(*) FROM image_analyses WHERE zone_name=?', (name,)).fetchone()[0]
        report_count = db.execute('SELECT COUNT(*) FROM condition_reports WHERE zone_name=? COLLATE NOCASE', (name,)).fetchone()[0]
        status = record['search_status'] if record else 'not_searched'
        zones.append({'name': name, 'status': status, 'record': record, 'image_count': image_count, 'report_count': report_count,
                      'label': {'not_searched':'Not searched','in_progress':'In progress','searched':'Search recorded','needs_recheck':'Needs recheck'}.get(status, status)})
    counts = {key: sum(1 for z in zones if z['status'] == key) for key in ['not_searched','in_progress','searched','needs_recheck']}
    return render_template('coverage.html', zones=zones, counts=counts)


@app.route('/recommendations')
@login_required
def search_recommendations():
    """Explainable, rules-based review suggestions; not a validated rescue-risk model."""
    db = get_db()
    rows = db.execute("""SELECT * FROM image_analyses ORDER BY id DESC""").fetchall()
    reports = db.execute("""SELECT * FROM condition_reports ORDER BY id DESC""").fetchall()
    latest_report = {}
    for report in reports:
        latest_report.setdefault(report['zone_name'].strip().casefold(), dict(report))

    recommendations = []
    now = datetime.utcnow()
    for row in rows:
        item = dict(row)
        try:
            detections = json.loads(item.get('detections_json') or '[]')
        except (TypeError, json.JSONDecodeError):
            detections = []
        status, base_score, base_reason = assess_evidence(
            item.get('analysis_mode', ''), item.get('image_quality', ''),
            detections, item.get('created_at')
        )
        score = int(base_score)
        reasons = [base_reason]
        # A recent, human-reported condition change is a reason to recheck, not a verified measurement.
        report = latest_report.get(item.get('zone_name', '').strip().casefold())
        if report and report.get('severity') in {'High', 'Moderate'}:
            boost = 20 if report['severity'] == 'High' else 10
            score = min(100, score + boost)
            reasons.append(f"A human-reported {report['severity'].lower()} update ({report['condition_type']}) is recorded for this zone; verify the report.")
        if 'Low contrast' in str(item.get('image_quality', '')) or 'Low resolution' in str(item.get('image_quality', '')):
            reasons.append('Image quality is limited; a clearer observation may reduce uncertainty.')
        try:
            stamp = datetime.strptime(str(item.get('created_at')), '%Y-%m-%d %H:%M:%S')
            age_hours = max(0, (now - stamp).total_seconds() / 3600)
        except (TypeError, ValueError):
            age_hours = None
        if age_hours is not None and age_hours >= 6 and status != 'outdated':
            reasons.append(f"Observation is approximately {age_hours:.0f} hours old; consider freshness in the current conditions.")
            score = min(100, score + (8 if age_hours >= 12 else 4))
        if status == 'person_detected':
            action = 'Human-verify the marked detection and follow the response team protocol.'
        elif status == 'searched_no_detection':
            action = 'Do not mark the zone safe; review visibility and consider a repeat search if warranted.'
        elif status == 'outdated':
            action = 'Consider collecting a fresh observation if it is safe and operationally appropriate.'
        else:
            action = 'Review the image and evidence gaps; consider a clearer or additional observation.'
        if report and report.get('severity') == 'High':
            action = 'Promptly review the human-reported change, verify it, and reassess this zone.'
        recommendations.append({
            'id': item['id'], 'zone_name': item['zone_name'], 'original_name': item['original_name'],
            'created_at': item['created_at'], 'status': status, 'score': score,
            'reasons': reasons, 'action': action, 'condition_report': report,
        })
    recommendations.sort(key=lambda x: (-x['score'], x['created_at']), reverse=False)
    return render_template('recommendations.html', recommendations=recommendations)


@app.route('/conditions', methods=['GET', 'POST'])
@login_required
def conditions_watch():
    """Record human-reported changes; do not infer real-world conditions from metadata."""
    db = get_db()
    if request.method == 'POST':
        csrf_protect()
        zone_name = request.form.get('zone_name', '').strip()[:80]
        condition_type = request.form.get('condition_type', '').strip()
        severity = request.form.get('severity', '').strip()
        notes = request.form.get('notes', '').strip()[:1000]
        allowed_types = {'Water level changed', 'Road access changed', 'New obstruction', 'Weather changed', 'New visual evidence', 'Other'}
        allowed_severity = {'Low', 'Moderate', 'High', 'Unknown'}
        if not zone_name or condition_type not in allowed_types or severity not in allowed_severity:
            flash('Enter a zone and choose valid condition and severity values.', 'error')
        else:
            db.execute('INSERT INTO condition_reports (zone_name, condition_type, severity, notes, reported_by) VALUES (?, ?, ?, ?, ?)',
                       (zone_name, condition_type, severity, notes, g.current_user['id']))
            db.commit()
            flash('Condition update recorded. The report is a human-provided observation, not an automated verification.', 'success')
            return redirect(url_for('conditions_watch'))
    reports = db.execute("""SELECT condition_reports.*, users.username AS reporter
        FROM condition_reports LEFT JOIN users ON users.id = condition_reports.reported_by
        ORDER BY condition_reports.id DESC LIMIT 100""").fetchall()
    zones = db.execute("""SELECT zone_name, MAX(id) AS latest_id FROM image_analyses
        GROUP BY zone_name ORDER BY zone_name COLLATE NOCASE""").fetchall()
    return render_template('conditions.html', reports=reports, zones=zones)


@app.route('/analysis/<int:analysis_id>/image')
@login_required
def analysis_image(analysis_id):
    record = get_db().execute('SELECT stored_name FROM image_analyses WHERE id = ?', (analysis_id,)).fetchone()
    if not record:
        abort(404)
    path = UPLOAD_DIR / record['stored_name']
    if not path.is_file():
        abort(404)
    mimetype = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}.get(path.suffix.lower(), 'application/octet-stream')
    return send_file(path, mimetype=mimetype, as_attachment=False, download_name='resqtrace-image' + path.suffix.lower())


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


@app.errorhandler(404)
def not_found(_error):
    return render_template('error.html', code=404, title='Not found', message='The requested record or page could not be found.'), 404


@app.errorhandler(403)
def forbidden(_error):
    return render_template('error.html', code=403, title='Access denied', message='Your account does not have permission to access this page.'), 403


@app.errorhandler(400)
def bad_request(error):
    return render_template('error.html', code=400, title='Request could not be verified', message=getattr(error, 'description', 'Please refresh and try again.')), 400


if __name__ == '__main__':
    # Debug mode is convenient locally. Do not enable it on a public deployment.
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
