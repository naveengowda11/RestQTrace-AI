ResQTrace AI - Phase 8: Explainable Search Recommendations

What's added:
- A Search Recommendations page at /recommendations.
- Recommendations are generated from saved image-analysis records.
- Each card explains evidence status and contributing factors, including image quality, observation age, and the latest matching human-reported condition update.
- Suggested next steps are specific to the evidence status and never treat a no-detection result as proof of safety.
- Navigation links are added to the main application pages.

Run:
1. Back up the current project and instance folder.
2. Extract this ZIP into a new folder.
3. Copy the existing instance folder into the new project if you want to keep local accounts, images, and reports.
4. In PowerShell from the ResQTrace-AI folder:
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
5. Sign in and choose Search Recommendations from the navigation, or open http://127.0.0.1:5000/recommendations.

Important limitations:
- Scores are transparent prototype rules, not a validated rescue-risk model.
- Condition reports are user-entered and not automatically verified.
- The app does not guarantee survivor detection and must not be used as a standalone real-world rescue decision system.

Testing note: Python syntax and archive integrity should be checked after packaging. End-to-end operation depends on the local environment and existing database; please test locally before presenting it as fully functional.
