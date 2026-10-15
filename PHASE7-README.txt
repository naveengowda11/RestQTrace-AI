RESQTRACE AI - PHASE 7: VISUAL CHANGE REVIEW

New feature:
- Visual Compare page lets a signed-in user select two uploaded images from the same zone.
- It produces a simple pixel-difference percentage, mean grayscale difference, and grayscale difference heatmap.
- A warning explains that lighting, camera angle, zoom, alignment, and compression can cause differences; it is not a validated flood/change detector.
- Navigation links added to relevant pages.

Run:
1. Back up your current project and instance folder.
2. Extract this ZIP into a new folder.
3. Copy your existing instance folder into the new project if you need your accounts and saved uploads.
4. Activate your virtual environment and run: pip install -r requirements.txt
5. Run: python app.py
6. Sign in, upload at least two images with the exact same zone name, then click Visual Compare.

This is a local prototype. Test with similar-angle images. The score is not a probability and must not be used alone for emergency decisions.
