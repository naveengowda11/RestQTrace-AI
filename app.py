from flask import Flask, render_template

app = Flask(__name__)

# Demonstration data only. These are not live locations or real rescue reports.
ZONES = [
    {
        "name": "Zone A-01", "key": "detected", "status": "Person detected",
        "area": "North settlement", "time": "10:20 AM (demo)",
        "note": "A person-like object is marked in the sample record; human verification is required.",
        "action": "Review the image and escalate for human assessment.", "lat": 12.3020, "lng": 76.6350
    },
    {
        "name": "Zone B-14", "key": "uncertain", "status": "Uncertain",
        "area": "Eastern tree line", "time": "09:45 AM (demo)",
        "note": "Sample image is partially obscured, so the available evidence is inconclusive.",
        "action": "Consider another observation if risk and access conditions justify it.", "lat": 12.2995, "lng": 76.6500
    },
    {
        "name": "Zone C-03", "key": "outdated", "status": "Evidence outdated",
        "area": "Riverside road", "time": "07:30 AM (demo)",
        "note": "A simulated rising-water report means the earlier observation may need review.",
        "action": "Reassess the old evidence and verify current access conditions.", "lat": 12.2890, "lng": 76.6420
    },
    {
        "name": "Zone D-08", "key": "unsearched", "status": "Not searched",
        "area": "Southern blocks", "time": "No observation recorded",
        "note": "No relevant search evidence is stored for this sample zone.",
        "action": "Assess whether this area should be included in the next search.", "lat": 12.2850, "lng": 76.6300
    },
    {
        "name": "Zone E-05", "key": "reviewed", "status": "Searched — no detection",
        "area": "Western access road", "time": "10:05 AM (demo)",
        "note": "The sample record says an image was reviewed with no person detected; this does not prove safety.",
        "action": "Retain the record and reassess if new evidence or conditions change.", "lat": 12.3060, "lng": 76.6460
    },
    {
        "name": "Zone F-11", "key": "uncertain", "status": "Uncertain",
        "area": "Low-lying houses", "time": "09:10 AM (demo)",
        "note": "Sample visibility is limited and no reliable conclusion can be drawn.",
        "action": "Review image quality and consider further inspection based on risk.", "lat": 12.2920, "lng": 76.6220
    },
]

PRIORITIES = [
    {"name": "Zone A-01", "status": "Human review", "pill": "pill-red", "reason": "A person-like object is marked in the sample record; verify the detection.", "score": 92},
    {"name": "Zone B-14", "status": "Uncertain", "pill": "pill-amber", "reason": "Obscured imagery leaves an important evidence gap.", "score": 78},
    {"name": "Zone C-03", "status": "Reassess", "pill": "pill-orange", "reason": "A simulated hazard update may make the old observation unreliable.", "score": 71},
]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    metrics = {
        "total": len(ZONES),
        "detected": sum(1 for zone in ZONES if zone["key"] == "detected"),
        "uncertain": sum(1 for zone in ZONES if zone["key"] == "uncertain"),
        "review": sum(1 for zone in ZONES if zone["key"] in {"unsearched", "outdated"}),
    }
    return render_template('dashboard.html', zones=ZONES, priorities=PRIORITIES, metrics=metrics)

if __name__ == '__main__':
    app.run(debug=True)
