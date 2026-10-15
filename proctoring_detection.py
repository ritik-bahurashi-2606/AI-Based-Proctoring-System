import os
from collections.abc import Iterable, Mapping
from typing import Any


ELECTRONIC_DEVICE_LABELS = frozenset(
    label.strip().lower()
    for label in os.getenv(
        "PROCTOR_RESTRICTED_DEVICE_LABELS",
        "tv,tvmonitor,laptop,mouse,remote,keyboard,microwave,oven,toaster,refrigerator",
    ).split(",")
    if label.strip()
)


def _overlap_ratio(first, second):
    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, float(first[2]) - float(first[0])) * max(
        0.0, float(first[3]) - float(first[1])
    )
    second_area = max(0.0, float(second[2]) - float(second[0])) * max(
        0.0, float(second[3]) - float(second[1])
    )
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _unique_person_boxes(detections, score_min):
    boxes = [
        (float(detection["score"]), detection.get("bbox"))
        for detection in detections
        if str(detection.get("class_name", "")).strip().lower() == "person"
        and float(detection["score"]) >= score_min
        and detection.get("bbox") is not None
    ]
    selected = []
    for score, box in sorted(boxes, reverse=True):
        if not any(_overlap_ratio(box, existing) >= 0.65 for existing in selected):
            selected.append(box)
    return len(selected)


def resolve_person_count(detected_person_count, face_count):
    """Prefer live face detections over YOLO person boxes when available."""
    if face_count > 0:
        return face_count
    return detected_person_count


def summarize_object_detections(
    detections: Iterable[Mapping[str, Any]],
    person_score_min: float,
    phone_score_min: float,
    device_score_min: float,
    book_score_min: float,
) -> dict[str, Any]:
    detections = list(detections)
    person_count = 0
    person_confidence = 0.0
    phone_confidence = 0.0
    device_confidence = 0.0
    device_names = set()
    book_confidence = 0.0

    for detection in detections:
        label = str(detection.get("class_name", "")).strip().lower()
        score = float(detection["score"])
        if label == "person" and score >= person_score_min:
            person_confidence = max(person_confidence, score)
            if detection.get("bbox") is None:
                person_count += 1
        elif label == "cell phone" and score >= phone_score_min:
            phone_confidence = max(phone_confidence, score)
        elif label in ELECTRONIC_DEVICE_LABELS and score >= device_score_min:
            device_names.add(label)
            device_confidence = max(device_confidence, score)
        elif label == "book" and score >= book_score_min:
            book_confidence = max(book_confidence, score)

    person_count = max(person_count, _unique_person_boxes(detections, person_score_min))

    return {
        "person_count": person_count,
        "person_confidence": person_confidence,
        "person_status": 0 if person_count == 0 else (2 if person_count > 1 else 1),
        "phone_status": int(phone_confidence > 0),
        "phone_confidence": phone_confidence,
        "device_status": int(bool(device_names)),
        "device_confidence": device_confidence,
        "device_names": sorted(device_names),
        "book_status": int(book_confidence > 0),
        "book_confidence": book_confidence,
    }
