import proctoring_policy as policy


def _frame(eyes=2, yaw=0.0):
    return {
        "person_status": 1,
        "face_in_frame_status": 1,
        "eye_movements": eyes,
        "head_yaw": yaw,
        "head_pitch": 0.0,
        "head_roll": 0.0,
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
        "sustained", _frame(eyes=3, yaw=50.0), 0, ""
    )["should_log"]

    clock[0] = 6.1
    result = policy.evaluate_proctoring_event(
        "sustained", _frame(eyes=3, yaw=50.0), 0, ""
    )
    assert result["should_log"]
    assert result["events"][0]["event_type"] == "head_turned_right"
    assert len(result["events"]) == 1
