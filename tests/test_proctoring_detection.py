from proctoring_detection import resolve_person_count, summarize_object_detections


def test_summarize_object_detections_flags_person_phone_electronics_and_book():
    result = summarize_object_detections(
        [
            {"class_name": "person", "score": 0.62},
            {"class_name": "person", "score": 0.45},
            {"class_name": "cell phone", "score": 0.51},
            {"class_name": "laptop", "score": 0.72},
            {"class_name": "keyboard", "score": 0.64},
            {"class_name": "mouse", "score": 0.30},
            {"class_name": "book", "score": 0.71},
        ],
        person_score_min=0.30,
        phone_score_min=0.30,
        device_score_min=0.35,
        book_score_min=0.40,
    )

    assert result == {
        "person_count": 2,
        "person_confidence": 0.62,
        "person_status": 2,
        "phone_status": 1,
        "phone_confidence": 0.51,
        "device_status": 1,
        "device_confidence": 0.72,
        "device_names": ["keyboard", "laptop"],
        "book_status": 1,
        "book_confidence": 0.71,
    }


def test_summarize_object_detections_ignores_below_threshold_detections():
    result = summarize_object_detections(
        [
            {"class_name": "person", "score": 0.29},
            {"class_name": "cell phone", "score": 0.29},
            {"class_name": "laptop", "score": 0.34},
            {"class_name": "book", "score": 0.39},
        ],
        person_score_min=0.30,
        phone_score_min=0.30,
        device_score_min=0.35,
        book_score_min=0.40,
    )

    assert result["person_status"] == 0
    assert result["phone_status"] == 0
    assert result["device_status"] == 0
    assert result["book_status"] == 0


def test_lower_phone_and_device_thresholds_accept_weak_clear_predictions():
    result = summarize_object_detections(
        [
            {"class_name": "cell phone", "score": 0.26},
            {"class_name": "laptop", "score": 0.31},
        ],
        person_score_min=0.30,
        phone_score_min=0.25,
        device_score_min=0.30,
        book_score_min=0.40,
    )

    assert result["phone_status"] == 1
    assert result["device_status"] == 1


def test_overlapping_person_boxes_count_once():
    result = summarize_object_detections(
        [
            {"class_name": "person", "score": 0.91, "bbox": [10, 10, 100, 140]},
            {"class_name": "person", "score": 0.72, "bbox": [12, 12, 99, 139]},
            {"class_name": "person", "score": 0.80, "bbox": [150, 10, 230, 140]},
        ],
        person_score_min=0.3,
        phone_score_min=0.3,
        device_score_min=0.35,
        book_score_min=0.4,
    )

    assert result["person_count"] == 2
    assert result["person_status"] == 2
    assert result["person_confidence"] == 0.91


def test_clock_class_is_not_treated_as_smartwatch():
    result = summarize_object_detections(
        [{"class_name": "clock", "score": 0.98}],
        person_score_min=0.3,
        phone_score_min=0.3,
        device_score_min=0.35,
        book_score_min=0.4,
    )

    assert result["device_status"] == 0


def test_face_count_prevents_background_person_detections_from_becoming_multi_person():
    assert resolve_person_count(detected_person_count=2, face_count=1) == 1


def test_face_count_preserves_genuine_multiple_people():
    assert resolve_person_count(detected_person_count=1, face_count=2) == 2


def test_person_detector_remains_fallback_when_no_face_is_detected():
    assert resolve_person_count(detected_person_count=0, face_count=0) == 0
    assert resolve_person_count(detected_person_count=1, face_count=0) == 1
