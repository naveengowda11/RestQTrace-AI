# ResQTrace AI — Phase 1C: Authentication and Access Control

A software-only student prototype for Innovation Mission 6. This version includes the landing page, a protected illustrative dashboard, SQLite-backed user accounts, admin-managed accounts, and an audit log. Disaster-zone information and priority scores remain sample data, not live emergency information.

## Requirements
- Python 3.10 or newer
- Internet connection for Google Fonts and Leaflet/OpenStreetMap tiles (authentication and the rest of the application can run locally without map tiles)

## Run on Windows
Open a terminal in this folder and run:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. The dashboard is protected; opening `/dashboard` directly redirects to login.

## Create the first administrator
There are no default usernames or passwords. In a second terminal, from this folder with the virtual environment active, run:

```powershell
flask --app app create-admin admin
```

The command securely prompts you to enter and confirm a password. Use a unique password of at least 12 characters. Then sign in through the landing page's **Rescue team login** button.

## Create rescue-team accounts
Sign in as the administrator, open **Manage accounts** from the dashboard, and create accounts. Public self-registration is disabled. Use unique temporary passwords of at least 12 characters and share them securely. Administrators can deactivate or reactivate accounts. An admin cannot deactivate their own account, and the last active admin cannot be deactivated.

## Security features in this prototype
- Passwords are stored as Werkzeug password hashes, never as plaintext.
- Dashboard and account-management routes require authentication; admin functions also require the admin role.
- Session cookies are HttpOnly and SameSite=Lax, with a 45-minute session lifetime.
- CSRF tokens protect form submissions.
- Login errors use a generic message.
- Account creation/deactivation and sign-in/sign-out events are recorded in an audit log.
- No public registration or hardcoded default credentials.

## Important deployment notes
This is suitable for local development and demonstration, not yet a production emergency-response service. Before deployment, configure a strong `RESQTRACE_SECRET_KEY` environment variable, use HTTPS (`RESQTRACE_HTTPS=1` behind HTTPS), add persistent login rate limiting, password reset and rotation procedures, backups, and a security review. Never expose Flask's development server or debugger to the public internet. The dashboard's disaster data is illustrative and must not be used for real rescue decisions.

## Current functionality
- Responsive landing page.
- Rescue-team login and logout.
- SQLite user database with admin and rescue roles.
- Protected dashboard and admin-only account management.
- Account activation/deactivation and recent audit log.
- Illustrative Leaflet map, evidence register, and sample priority queue.

## Not implemented yet
- Aerial image upload and actual AI detection.
- Persistent disaster-zone evidence records.
- Live weather integration.
- Validated risk and uncertainty models.
- Route optimization based on verified real-world data.


## Phase 2 — Aerial image upload and analysis

The authenticated **Image analysis** page lets signed-in users upload JPG/JPEG/PNG/WEBP images up to 10 MB. Files are validated with Pillow and stored privately under `instance/uploads`; image records are stored in SQLite and can only be viewed through authenticated routes. The app records dimensions and a basic contrast/resolution hint. This is not a reliable survivor-detection or search-completeness score.

### Run the basic image-validation version

```powershell
pip install -r requirements.txt
python app.py
```

Sign in and choose **Image analysis** from the dashboard.

### Optional AI object detection

To enable the optional YOLO object detector, install the additional dependencies (this can be a large download and may require a compatible Python/PyTorch setup):

```powershell
pip install -r requirements-ai.txt
```

Then restart the app. On first use, Ultralytics may download model weights. You can set `RESQTRACE_YOLO_MODEL` to a locally available compatible model path. A general pretrained model may perform poorly on aerial imagery; every result needs human verification. If the optional package or model is unavailable, image validation still works and the page clearly reports that detections were not performed.

### Phase 2 limitations

- The default install does not include the optional AI detector.
- Generic object detection is not a validated search-and-rescue model.
- “No detections” never means a zone is safe or contains no survivors.
- Image analyses are private to authenticated users in this local prototype; production deployment needs stronger storage, retention, access-control, and security review.
