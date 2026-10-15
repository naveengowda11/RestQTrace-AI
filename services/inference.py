"""Local image inference services.

The web interface intentionally describes capabilities, not implementation brands.
All outputs are screening evidence and require human review.
"""
import os
from functools import lru_cache
from pathlib import Path

PERSON_THRESHOLD = float(os.environ.get('RESQTRACE_PERSON_THRESHOLD', '0.25'))
CONDITION_THRESHOLD = float(os.environ.get('RESQTRACE_CONDITION_THRESHOLD', '0.20'))


@lru_cache(maxsize=1)
def _person_model():
    from ultralytics import YOLO
    weights = os.environ.get('RESQTRACE_PERSON_WEIGHTS', 'yolo11n.pt')
    return YOLO(weights)


@lru_cache(maxsize=1)
def _condition_pipeline():
    from transformers import pipeline
    model_id = os.environ.get('RESQTRACE_CONDITION_MODEL', 'openai/clip-vit-base-patch32')
    return pipeline('zero-shot-image-classification', model=model_id)


def detect_people(image_path):
    """Return actual detector boxes. Raises if dependencies/weights cannot run."""
    model = _person_model()
    results = model(str(image_path), verbose=False)
    detections = []
    for result in results:
        if result.boxes is None:
            continue
        names = result.names
        for box in result.boxes:
            class_id = int(box.cls[0].item())
            label = str(names.get(class_id, class_id))
            confidence = float(box.conf[0].item())
            if label.casefold() != 'person' or confidence < PERSON_THRESHOLD:
                continue
            coords = [round(float(value), 1) for value in box.xyxy[0].tolist()]
            detections.append({'label': 'person', 'confidence': round(confidence, 4), 'box': coords})
    return detections


CONDITION_LABELS = [
    'an aerial image showing floodwater covering roads or buildings',
    'an aerial image showing a dry area with no visible flooding',
    'an aerial image showing landslide or mudslide damage',
    'an aerial image showing damaged buildings or collapsed structures',
    'an aerial image showing wildfire or burned land',
    'an aerial image showing a normal landscape without obvious disaster damage',
]


def screen_conditions(image_path):
    """Return zero-shot image/text similarity rankings, not calibrated probabilities."""
    classifier = _condition_pipeline()
    results = classifier(str(image_path), candidate_labels=CONDITION_LABELS)
    cleaned = []
    for item in results[:5]:
        cleaned.append({
            'label': item['label'],
            'score': round(float(item['score']), 4),
            'above_screening_threshold': float(item['score']) >= CONDITION_THRESHOLD,
        })
    return cleaned


def run_image_analysis(image_path):
    """Run independent tasks; keep partial success if one task is unavailable."""
    output = {
        'detections': [],
        'conditions': [],
        'person_status': 'not_run',
        'condition_status': 'not_run',
        'errors': [],
    }
    try:
        output['detections'] = detect_people(image_path)
        output['person_status'] = 'completed'
    except Exception as exc:
        output['person_status'] = 'failed'
        output['errors'].append('Person detection could not run. Install the AI dependencies and allow the required weights to download.')
        # Detailed exception is kept in server logs, not shown to the user.
        import logging
        logging.getLogger(__name__).warning('Person inference failed: %s', exc)
    try:
        output['conditions'] = screen_conditions(image_path)
        output['condition_status'] = 'completed'
    except Exception as exc:
        output['condition_status'] = 'failed'
        output['errors'].append('Disaster-condition screening could not run. Install the AI dependencies and check network access for first-time model setup.')
        import logging
        logging.getLogger(__name__).warning('Condition screening failed: %s', exc)
    return output
