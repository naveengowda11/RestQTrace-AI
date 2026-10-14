# ResQTrace AI — Phase 1 Foundation

A software-only student prototype for Innovation Mission 6. This version includes a landing page and a functional illustrative dashboard. All zone records and priority scores are sample data, not live emergency information.

## Requirements
- Python 3.10 or newer
- Internet connection for Google Fonts and Leaflet/OpenStreetMap tiles (the rest of the page can load without map tiles)

## Run on Windows
Open a terminal in this folder and run:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` for the landing page and select **Explore dashboard**, or open `http://127.0.0.1:5000/dashboard` directly.

## Current functionality
- Responsive landing page with navigation to the dashboard.
- Flask routes for `/` and `/dashboard`.
- Dashboard metrics calculated from the current sample records.
- Interactive Leaflet map with sample zone markers and popups.
- Evidence register with status filtering and an Inspect details modal.
- Clear labels that the data is illustrative and not suitable for real-world rescue decisions.

## Not implemented yet
- SQLite persistence
- Aerial image upload and actual AI detection
- Live weather integration
- Evidence-aware priority calculations based on stored observations
- Route optimization

These are planned later phases. Do not treat the current sample recommendations as validated predictions.
