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

## Not implemented or validated yet
- A dedicated flood-segmentation model trained and evaluated on labelled aerial disaster imagery.
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

### Local AI image analysis

Install the additional inference dependencies to enable two separate tasks: possible-person detection with bounding boxes, and image-level disaster-condition screening.

```powershell
pip install -r requirements-ai.txt
python app.py
```

The first analysis may download model weights and package files, so allow time and ensure internet access. Later runs use cached weights when available. You can configure local person-detection weights with `RESQTRACE_PERSON_WEIGHTS`, and adjust screening thresholds with `RESQTRACE_PERSON_THRESHOLD` and `RESQTRACE_CONDITION_THRESHOLD`.

The condition task ranks text descriptions against the image. Its scores are similarity values, not calibrated probabilities, verified damage labels, or proof of flood extent. The person detector may miss small or obscured people in aerial imagery. Each task records its own completion or failure status; if a task cannot run, the application records that no result was generated rather than fabricating a prediction.

### AI analysis limitations

- A general pretrained person detector is not a validated search-and-rescue detector.
- Image-level condition screening is preliminary and does not replace a flood segmentation model trained and evaluated on suitable labelled aerial data.
- “No detections” never means a zone is safe or contains no survivors.
- Image analyses remain local to this prototype; production deployment needs storage, retention, access-control, security and model-evaluation review.


## Phase 3 — Unknown-Zone Intelligence

This phase adds an evidence-triage panel to every image result and a live local-record review queue to the dashboard. Uploaders can optionally label the zone. The prototype uses transparent rules to classify records as:
- **Person detected:** the detector marked a person-like object; human verification is required.
- **Searched — no detection:** the configured detector ran but returned no person detections; this does not establish that people are absent.
- **Uncertain:** image quality is limited, the detector failed, or no detector result is available.
- **Evidence outdated:** the observation is at least 24 hours old and may need refreshing.

The displayed 0–100 review priority is a hand-authored demonstration score based on the above rules, not a trained risk model, probability, or validated rescue recommendation. The dashboard's original map and its metrics remain illustrative sample data. The live review queue only represents locally uploaded images; it does not know which real-world areas were searched unless users provide reliable zone metadata. “Not searched” must not be inferred from the absence of an upload.

### Existing database compatibility
The application adds new columns to the existing SQLite `image_analyses` table on startup, preserving prior accounts and uploaded-image records. Back up `instance/resqtrace.sqlite3` before testing any project update.

### Test it
1. Start the app and sign in.
2. Open **Image analysis** and enter a zone label if known.
3. Upload a flood image.
4. On the result page, inspect **Unknown-Zone Intelligence** and the explanation.
5. Return to the dashboard and inspect the live local-record queue.

The rules are intended for a student demonstration and require evaluation against labeled data before any operational use.

## Phase 4 — Disaster Memory and Observation Comparison

The `/memory-map` page groups uploaded image records by the zone name entered at upload time. It shows the newest and previous observations, a timeline, and differences between stored detector-label counts, evidence status, and image-quality notes. Upload follow-up images using the exact same zone name to keep a zone's history together.

Important limits:
- This is a history/comparison feature, not a validated geospatial map or an automated flood-change detector.
- It compares stored model outputs and metadata; it does not claim pixel-level scene change or infer that a changed object count proves a real-world change.
- Use human review. A missing person detection is not proof that a zone is safe.
- The app remains a student prototype and must not be used as the sole basis for real emergency decisions.


## Phase 6 — Condition-linked review alerts

The dashboard now displays recent human-reported condition updates and links reports to image-analysis records when their zone names match (case-insensitive). High-severity reports add 20 points and Moderate reports add 10 points to the displayed review score, capped at 100. This is a transparent prototype heuristic, not a validated rescue-risk model. Reports are not automatically verified; unmatched zone names will not link to image records.


## Phase 9 — Search Coverage

The Search Coverage page (`/coverage`) records explicit zone search status: Not searched, In progress, Search recorded, or Needs recheck. Each submission is stored as a history record in SQLite; the latest record is shown per zone. Zones are derived from saved image analyses, condition reports, and search records. Uploading an image does not automatically mark a zone as searched.

## Visual Compare fix

Visual Compare now uses a separate GET form to load images for a selected zone and a POST form to compare two observations. This avoids browser-required-field validation preventing zone selection from loading the image list. Comparison requires two readable saved images in the same zone.

## Dashboard cleanup

Dashboard metrics and recent records are database-backed. Static example zones, example recommendation cards, the demo-data badge, and repeated prototype preview banner were removed. The map does not show guessed locations; it asks for recorded coordinates before plotting zone markers.


## Phase 11 — Person-level review and GIS

Phase 11 adds a person-level review table, detection-box overlay, transparent review-priority heuristic, and a map that plots only detections with supplied valid coordinates. The priority score is not a validated danger prediction.

### Optional georeference sidecar

On the image-analysis form, an optional JSON sidecar may be supplied for a **georeferenced orthomosaic**. It must use EPSG:4326/WGS84 and include an affine pixel-to-coordinate transform. Example structure:

```json
{
  "crs": "EPSG:4326",
  "pixel_to_geo": {
    "lat": [0.0, 0.00001, 12.0],
    "lon": [0.00001, 0.0, 76.0]
  }
}
```

Each array represents `[x_coefficient, y_coefficient, offset]`; coefficients must come from a real georeferencing workflow. Do not copy example numbers as actual coordinates. Standard drone photographs, EXIF GPS, or a visual image alone cannot determine the ground location of every detected person. Without a verified transform, GIS markers are intentionally omitted.

## Phase 11 — Person-level GIS and genuine coordinates

Person GIS stores candidate detections, bounding boxes, confidence, review-priority reasons, and location provenance. A person marker is drawn only when the detection can be mapped from an actual geospatial reference; ordinary camera EXIF GPS identifies the camera location, not the ground location of every person in the photograph.

### Supported coordinate sources

1. **GeoTIFF / georeferenced orthomosaic:** Install the optional GIS libraries with `pip install -r requirements-gis.txt`, then upload a TIFF/GeoTIFF whose embedded affine transform and coordinate reference system are valid. The app converts its pixel position into WGS84 for the map.
2. **Verified WGS84 affine JSON sidecar:** For an orthomosaic whose image pixels have a verified transform, upload JSON shaped like:

```json
{
  "crs": "EPSG:4326",
  "pixel_to_geo": {
    "lat": [0.000001, 0.0, 12.345678],
    "lon": [0.0, 0.000001, 76.543210]
  }
}
```

The numbers above are illustrative placeholders, **not usable location data**. Replace them only with coefficients derived from the actual orthomosaic/geospatial processing output. Do not use this example to geolocate a real incident.

### Important limits

- A normal JPG/PNG drone photo and its camera GPS alone do not provide enough information to compute a person's ground coordinates. Proper geolocation from an unrectified photo requires camera calibration/pose, terrain or elevation data, and a validated projection/intersection pipeline; this project does not claim to perform that pipeline.
- A map marker is a projected location derived from the supplied geospatial transform, not proof that the candidate is a survivor or in danger. Accuracy depends on source imagery, orthorectification, CRS and transform quality.
- Detection confidence and the review-priority score are not calibrated survivor probabilities. Human review remains mandatory.
- If coordinates are absent or invalid, the app records them as unavailable rather than inventing a location.

For a real evaluation, use an actual georeferenced orthomosaic/GeoTIFF with known CRS and ground-control accuracy, then compare sample mapped points against independent ground-truth coordinates before reporting location accuracy.


## Phase 12: UI and rescue-team GPS
- Added compact responsive visual styling to the dashboard and Person GIS.
- Added `/rescue-teams` for opt-in browser GPS sharing and team position display.
- Added authenticated `/api/rescue-team/location` and `/api/rescue-team/locations` endpoints.
- GPS is accepted only within broad Karnataka operating bounds (not an official district boundary polygon).
- Upload limit increased to 100 MB.
- For phone GPS access over a network, HTTPS is required. This prototype uses periodic polling and SQLite; validate security and reliability before real emergency deployment.
