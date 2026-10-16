import json

import proctoring_policy as policy


def _frame(eyes=2, yaw=0.0, pitch=0.0, roll=0.0):
    return {
        "person_status": 1,
        "face_in_frame_status": 1,
        "eye_movements": eyes,
        "head_yaw": yaw,
        "head_pitch": pitch,
        "head_roll": roll,
        "mob_status": 0,
    }


def test_brief_gaze_is_warned_but_not_logged(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_CALIBRATION_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_GAZE_WARNING_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_GAZE_DEVIATION_SECONDS", 3.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_TURN_SECONDS", 3.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)

    for second in (0.0, 1.0, 2.0):
        clock[0] = second
        assert not policy.evaluate_proctoring_event("brief", _frame(), 0, "")["should_log"]

    clock[0] = 3.0
    result = policy.evaluate_proctoring_event("brief", _frame(eyes=3), 0, "")
    assert not result["should_log"]

    clock[0] = 4.0
    result = policy.evaluate_proctoring_event("brief", _frame(eyes=3), 0, "")
    assert not result["should_log"]
    assert result["warnings"]

    clock[0] = 5.0
    result = policy.evaluate_proctoring_event("brief", _frame(), 0, "")
    assert not result["should_log"]


def test_sustained_gaze_and_head_turn_are_logged(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_CALIBRATION_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_GAZE_WARNING_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_GAZE_DEVIATION_SECONDS", 3.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_TURN_SECONDS", 3.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)

    for second in (0.0, 1.0, 2.0):
        clock[0] = second
        policy.evaluate_proctoring_event("sustained", _frame(), 0, "")

    clock[0] = 3.0
    assert not policy.evaluate_proctoring_event(
        "sustained", _frame(eyes=3, yaw=51.0), 0, ""
    )["should_log"]

    clock[0] = 6.1
    result = policy.evaluate_proctoring_event(
        "sustained", _frame(eyes=3, yaw=51.0), 0, ""
    )
    assert result["should_log"]
    assert result["events"][0]["event_type"] == "head_turned_right"
    assert len(result["events"]) == 1


def test_phone_electronics_book_and_multiple_people_warn_after_confirmation(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_MULTIPLE_PERSONS_SECONDS", 2.0)

    frame = {
        **_frame(),
        "person_status": 2,
        "mob_status": 1,
        "phone_confidence": 0.72,
        "device_status": 1,
        "device_confidence": 0.81,
        "device_names": ["laptop", "keyboard"],
        "book_status": 1,
        "book_confidence": 0.68,
        "person_count": 2,
    }
    first = policy.evaluate_proctoring_event(
        "object-detections",
        frame,
        0,
        "",
    )
    assert not first["should_log"]
    assert first["warnings"] == []

    clock[0] = 2.0
    result = policy.evaluate_proctoring_event("object-detections", frame, 0, "")

    warning_types = {event["event_type"] for event in result["warnings"]}
    assert warning_types == {
        "mobile_phone",
        "electronic_device",
        "book_detected",
        "multiple_persons",
    }
    device_warning = next(
        event for event in result["warnings"]
        if event["event_type"] == "electronic_device"
    )
    assert device_warning["detected_devices"] == ["keyboard", "laptop"]
    assert "keyboard, laptop" in device_warning["message"]
    assert result["should_log"]


def test_failed_log_save_rearms_persistent_event_for_retry(monkeypatch):
    policy._state.clear()
    clock = [100.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 10.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("retry-phone", frame, 0, "")["should_log"]
    clock[0] = 101.0
    failed_save = policy.evaluate_proctoring_event("retry-phone", frame, 0, "")
    assert failed_save["should_log"]
    policy.reject_events_save("retry-phone", failed_save["events"])

    clock[0] = 102.0
    retried = policy.evaluate_proctoring_event("retry-phone", frame, 0, "")
    assert retried["should_log"]
    assert retried["events"][0]["event_type"] == "mobile_phone"


def test_head_pose_uses_separate_50_degree_angles_and_cooldown_reset(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_CALIBRATION_SECONDS", 0.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_TURN_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_YAW_THRESHOLD", 50.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_PITCH_THRESHOLD", 50.0)
    monkeypatch.setattr(policy, "PROCTOR_HEAD_ROLL_THRESHOLD", 50.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)

    policy.evaluate_proctoring_event("pose", _frame(), 0, "")
    clock[0] = 1.0
    assert not policy.evaluate_proctoring_event("pose", _frame(yaw=50.0), 0, "")["should_log"]
    clock[0] = 2.0
    assert not policy.evaluate_proctoring_event("pose", _frame(yaw=51.0), 0, "")["should_log"]
    clock[0] = 3.1
    assert not policy.evaluate_proctoring_event("pose", _frame(yaw=51.0), 0, "")["should_log"]
    clock[0] = 4.1
    result = policy.evaluate_proctoring_event("pose", _frame(yaw=51.0), 0, "")
    assert result["events"][0]["event_type"] == "head_turned_right"

    clock[0] = 5.0
    policy.evaluate_proctoring_event("pose", _frame(), 0, "")
    clock[0] = 6.0
    policy.evaluate_proctoring_event("pose", _frame(pitch=51.0), 0, "")
    clock[0] = 8.1
    result = policy.evaluate_proctoring_event("pose", _frame(pitch=51.0), 0, "")
    assert result["events"][0]["event_type"] == "head_tilted_up"


def test_continuous_phone_event_logs_once_and_rearms_after_clear(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("phone", frame, 0, "")["should_log"]
    clock[0] = 2.0
    assert policy.evaluate_proctoring_event("phone", frame, 0, "")["should_log"]
    clock[0] = 3.0
    assert not policy.evaluate_proctoring_event("phone", frame, 0, "")["should_log"]

    clock[0] = 11.0
    policy.evaluate_proctoring_event("phone", _frame(), 0, "")
    clock[0] = 12.0
    assert not policy.evaluate_proctoring_event("phone", frame, 0, "")["should_log"]
    clock[0] = 13.0
    assert policy.evaluate_proctoring_event("phone", frame, 0, "")["should_log"]


def test_interrupted_object_sightings_accumulate_within_tracking_window(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_TRACK_WINDOW_SECONDS", 15.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_MISS_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_SAMPLE_CREDIT_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("intermittent", frame, 0, "")["should_log"]
    clock[0] = 4.0
    assert policy.evaluate_proctoring_event("intermittent", frame, 0, "")["should_log"]


def test_object_exposure_expires_outside_tracking_window(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_TRACK_WINDOW_SECONDS", 10.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_SAMPLE_CREDIT_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("expired", frame, 0, "")["should_log"]
    clock[0] = 11.0
    assert not policy.evaluate_proctoring_event("expired", frame, 0, "")["should_log"]


def test_long_gap_restarts_unreported_object_tracking(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_TRACK_WINDOW_SECONDS", 15.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_MISS_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_SAMPLE_CREDIT_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("long-gap", frame, 0, "")["should_log"]
    clock[0] = 6.0
    assert not policy.evaluate_proctoring_event("long-gap", frame, 0, "")["should_log"]
    clock[0] = 7.0
    assert policy.evaluate_proctoring_event("long-gap", frame, 0, "")["should_log"]


def test_single_missed_frame_does_not_reset_object_tracking(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_MISS_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_SAMPLE_CREDIT_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    assert not policy.evaluate_proctoring_event("missed-frame", frame, 0, "")["should_log"]
    clock[0] = 1.0
    assert not policy.evaluate_proctoring_event(
        "missed-frame", _frame(), 0, ""
    )["should_log"]
    clock[0] = 2.0
    assert policy.evaluate_proctoring_event(
        "missed-frame", frame, 0, ""
    )["should_log"]


def test_object_tracker_rearms_after_miss_grace_expires(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_PERSIST_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_MISS_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(policy, "PROCTOR_OBJECT_SAMPLE_CREDIT_SECONDS", 1.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)
    frame = {**_frame(), "mob_status": 1, "phone_confidence": 0.8}

    policy.evaluate_proctoring_event("rearm", frame, 0, "")
    clock[0] = 1.0
    assert policy.evaluate_proctoring_event("rearm", frame, 0, "")["should_log"]
    clock[0] = 7.0
    policy.evaluate_proctoring_event("rearm", _frame(), 0, "")
    clock[0] = 8.0
    assert not policy.evaluate_proctoring_event("rearm", frame, 0, "")["should_log"]
    clock[0] = 9.0
    assert policy.evaluate_proctoring_event("rearm", frame, 0, "")["should_log"]


def test_absence_and_face_out_of_frame_log_after_two_seconds(monkeypatch):
    policy._state.clear()
    clock = [0.0]
    monkeypatch.setattr(policy, "_now", lambda: clock[0])
    monkeypatch.setattr(policy, "PROCTOR_ABSENT_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_FACE_OUT_OF_FRAME_SECONDS", 2.0)
    monkeypatch.setattr(policy, "PROCTOR_EVENT_COOLDOWN_SECONDS", 0.0)

    absent = {**_frame(), "person_status": 0, "face_in_frame_status": 0}
    assert not policy.evaluate_proctoring_event("absent", absent, 0, "")["should_log"]
    clock[0] = 2.0
    result = policy.evaluate_proctoring_event("absent", absent, 0, "")
    assert result["events"][0]["event_type"] == "student_absent"

    policy._state.clear()
    clock[0] = 3.0
    face_missing = {**_frame(), "face_in_frame_status": 0}
    assert not policy.evaluate_proctoring_event("face-missing", face_missing, 0, "")["should_log"]
    clock[0] = 5.0
    result = policy.evaluate_proctoring_event("face-missing", face_missing, 0, "")
    assert result["events"][0]["event_type"] == "face_fully_out_of_frame"


def test_risk_score_uses_each_event_weight_and_tab_switches():
    event_counts = {event_type: 1 for event_type in policy.EVENT_RISK}

    score = policy.calculate_risk_score(event_counts, tab_switch_count=2)

    assert score == sum(policy.EVENT_RISK.values()) - policy.EVENT_RISK["tab_switch"] + 40
    assert policy.calculate_risk_score({"unknown_event": 3}) == 0
    assert policy.calculate_risk_score({"tab_switch": 3}, tab_switch_count=2) == 40
    assert policy.calculate_risk_score({"device": 1}) == policy.EVENT_RISK["electronic_device"]


def test_event_counting_merges_json_and_legacy_rows_without_losing_absence():
    rows = [
        {
            "event_data": json.dumps({
                "events": [
                    {"event_type": "mobile_phone"},
                    {"event_type": "tab_switch"},
                ],
            }),
            "phone_detection": 1,
        },
        {
            "event_data": None,
            "person_status": 0,
            "user_movements_eyes": 0,
        },
        {
            "event_data": None,
            "person_status": 2,
            "device_detection": 1,
            "user_movements_lr": 3,
            "user_movements_eyes": 3,
        },
    ]

    assert policy.count_proctoring_events(rows) == {
        "mobile_phone": 1,
        "tab_switch": 1,
        "student_absent": 1,
        "multiple_persons": 1,
        "electronic_device": 1,
        "head_movement": 1,
        "looking_away": 1,
    }
