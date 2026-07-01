import os
import time
from collections import defaultdict

import base64
import cv2
import numpy as np


PROCTOR_AUDIO_THRESHOLD = float(os.getenv("PROCTOR_AUDIO_THRESHOLD", "18"))
PROCTOR_LOW_LIGHT_THRESHOLD = float(os.getenv("PROCTOR_LOW_LIGHT_THRESHOLD", "35"))
PROCTOR_LOOK_AWAY_SECONDS = float(os.getenv("PROCTOR_LOOK_AWAY_SECONDS", "6"))
PROCTOR_HEAD_REPEAT_COUNT = int(os.getenv("PROCTOR_HEAD_REPEAT_COUNT", "3"))
PROCTOR_EVENT_COOLDOWN_SECONDS = float(os.getenv("PROCTOR_EVENT_COOLDOWN_SECONDS", "8"))

# New thresholds for improved detection
PROCTOR_FACE_OUT_OF_FRAME_SECONDS = float(os.getenv("PROCTOR_FACE_OUT_OF_FRAME_SECONDS", "4"))
PROCTOR_FACE_PARTIAL_SECONDS = float(os.getenv("PROCTOR_FACE_PARTIAL_SECONDS", "5"))
PROCTOR_HEAD_MOVE_WINDOW_SECONDS = float(os.getenv("PROCTOR_HEAD_MOVE_WINDOW_SECONDS", "10"))
PROCTOR_HEAD_YAW_THRESHOLD = float(os.getenv("PROCTOR_HEAD_YAW_THRESHOLD", "25")) # Degrees
PROCTOR_HEAD_PITCH_THRESHOLD = float(os.getenv("PROCTOR_HEAD_PITCH_THRESHOLD", "20")) # Degrees
PROCTOR_HEAD_TURN_SECONDS = float(os.getenv("PROCTOR_HEAD_TURN_SECONDS", "3"))
PROCTOR_HEAD_MOVE_REPEAT_COUNT_NEW = int(os.getenv("PROCTOR_HEAD_MOVE_REPEAT_COUNT_NEW", "4"))
PROCTOR_GAZE_DEVIATION_SECONDS = float(os.getenv("PROCTOR_GAZE_DEVIATION_SECONDS", "4"))
PROCTOR_GAZE_DEVIATION_WINDOW_SECONDS = float(os.getenv("PROCTOR_GAZE_DEVIATION_WINDOW_SECONDS", "8"))
PROCTOR_GAZE_DEVIATION_REPEAT_COUNT = int(os.getenv("PROCTOR_GAZE_DEVIATION_REPEAT_COUNT", "5"))
PROCTOR_ABSENT_SECONDS = float(os.getenv("PROCTOR_ABSENT_SECONDS", "4"))
PROCTOR_FACE_HIDDEN_SECONDS = float(os.getenv("PROCTOR_FACE_HIDDEN_SECONDS", "3"))
YOLO_PHONE_SCORE_MIN = float(os.getenv("YOLO_PHONE_SCORE_MIN", "0.52"))
YOLO_BOOK_SCORE_MIN = float(os.getenv("YOLO_BOOK_SCORE_MIN", "0.48"))
YOLO_PERSON_SCORE_MIN = float(os.getenv("YOLO_PERSON_SCORE_MIN", "0.38"))

EVENT_RISK = {
    "mobile_phone": 25,
    "book_detected": 22,
    "multiple_persons": 30,
    "student_absent": 30,
    "face_hidden": 20,
    "suspicious_audio": 15,
    "looking_away": 12,
    "head_movement": 10,
    "low_lighting": 8,
    "camera_obstruction": 20,
    "tab_switch": 20,
    "browser_minimized": 15,
    "face_fully_out_of_frame": 35,
    "face_partially_out_of_frame": 15,
    "head_turned_left": 10,
    "head_turned_right": 10,
    "head_tilted_up": 10,
    "head_tilted_down": 10,
    "prolonged_head_turn": 18,
    "repeated_head_movement": 15,
    "looking_up": 10,
    "looking_down": 10,
    "prolonged_gaze_deviation": 20,
    "repeated_gaze_deviation": 18,
}

EVENT_MESSAGES = {
    "mobile_phone": "Warning: Mobile phone detected.",
    "book_detected": "Warning: Book or document detected.",
    "multiple_persons": "Warning: Multiple persons detected.",
    "student_absent": "Warning: Face not visible. Stay in front of the camera.",
    "face_hidden": "Warning: Camera visibility issue detected.",
    "suspicious_audio": "Warning: Suspicious audio activity detected.",
    "looking_away": "Warning: Repeated looking away detected.",
    "head_movement": "Warning: Keep your head facing the screen.",
    "low_lighting": "Warning: Low lighting detected. Improve camera visibility.",
    "camera_obstruction": "Warning: Camera visibility issue detected.",
    "tab_switch": "Warning: Tab switching is prohibited during exam.",
    "browser_minimized": "Warning: Browser minimization is prohibited during exam.",
    "face_fully_out_of_frame": "Warning: Face out of frame. Please stay centered.",
    "face_partially_out_of_frame": "Warning: Face partially out of frame.",
    "head_turned_left": "Warning: Head turned left detected.",
    "head_turned_right": "Warning: Head turned right detected.",
    "head_tilted_up": "Warning: Head tilted up detected.",
    "head_tilted_down": "Warning: Head tilted down detected.",
    "prolonged_head_turn": "Warning: Prolonged head turn away from screen.",
    "repeated_head_movement": "Warning: Suspicious repeated head movement.",
    "looking_up": "Warning: Looking up away from screen.",
    "looking_down": "Warning: Looking down away from screen.",
    "prolonged_gaze_deviation": "Warning: Prolonged gaze away from screen.",
    "repeated_gaze_deviation": "Warning: Repeated gaze deviation detected.",
}

_state = defaultdict(lambda: {
    "look_away_started_at": None,
    "head_count": 0,
    "last_logged": {},
    "face_out_of_frame_start_time": None,
    "face_partial_started_at": None,
    "head_yaw_history": [],
    "head_pitch_history": [],
    "head_roll_history": [],
    "head_turn_prolong_start": None,
    "gaze_prolong_start": None,
    "last_head_movement_event_time": 0,
    "last_gaze_deviation_event_time": 0,
    "gaze_history": [],
    "absent_started_at": None,
    "face_hidden_started_at": None,
})


def _now():
    return time.time()


def _cooldown_ok(state, event_type, now):
    last_logged = state["last_logged"].get(event_type, 0)
    return now - last_logged >= PROCTOR_EVENT_COOLDOWN_SECONDS


def _mark_logged(state, event_type, now, duration=None):
    state["last_logged"][event_type] = now
    if duration is not None:
        # Store duration for temporal events
        state["last_logged"][f"{event_type}_duration"] = duration


def _image_brightness(img_b64):
    try:
        raw = img_b64 or ""
        if raw.startswith("TELEMETRY:"):
            raw = raw[len("TELEMETRY:") :]
        arr = np.frombuffer(base64.b64decode(raw), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return float(np.mean(img))
    except Exception:
        return None


def _event(event_type, confidence=1.0, risk=None, **kwargs):
    event_data = {
        "event_type": event_type,
        "message": EVENT_MESSAGES.get(event_type, "Warning: Suspicious activity detected."),
        "confidence": round(float(confidence), 2),
        "risk_score": int(EVENT_RISK.get(event_type, risk or 5)),
    }
    event_data.update(kwargs)
    return event_data


def evaluate_proctoring_event(user_key, proctor_data, voice_db, img_b64):
    now = _now()
    state = _state[user_key]
    candidates = []
    warnings = []

    voice_value = float(voice_db or 0)
    person_status = int(proctor_data.get("person_status", 0) or 0)
    phone_status = int(proctor_data.get("mob_status", 0) or 0)
    up_down = int(proctor_data.get("user_move1", 0) or 0)
    left_right = int(proctor_data.get("user_move2", 0) or 0)
    eyes = int(proctor_data.get("eye_movements", 0) or 0) # 0: not found, 1: blinking, 2: center, 3: left, 4: right
    
    head_pitch = float(proctor_data.get("head_pitch", 0.0) or 0.0)
    head_yaw = float(proctor_data.get("head_yaw", 0.0) or 0.0)
    head_roll = float(proctor_data.get("head_roll", 0.0) or 0.0)
    face_in_frame_status = int(proctor_data.get("face_in_frame_status", 0) or 0) # 0: absent, 1: full, 2: partial

    brightness = _image_brightness(img_b64)
    if brightness is not None and brightness < PROCTOR_LOW_LIGHT_THRESHOLD:
        candidates.append(_event("low_lighting", confidence=max(0.5, 1 - brightness / PROCTOR_LOW_LIGHT_THRESHOLD)))

    if phone_status == 1:
        conf = float(proctor_data.get("phone_confidence", 0.95) or 0.95)
        candidates.append(_event("mobile_phone", confidence=min(1.0, conf)))

    book_status = int(proctor_data.get("book_status", 0) or 0)
    if book_status == 1:
        bconf = float(proctor_data.get("book_confidence", 0.75) or 0.75)
        candidates.append(_event("book_detected", confidence=min(1.0, bconf)))

    if person_status == 2:
        candidates.append(_event("multiple_persons", confidence=0.95))

    if person_status == 0:
        if state["absent_started_at"] is None:
            state["absent_started_at"] = now
        absent_dur = now - state["absent_started_at"]
        if absent_dur >= PROCTOR_ABSENT_SECONDS:
            candidates.append(
                _event(
                    "student_absent",
                    confidence=min(1.0, absent_dur / max(PROCTOR_ABSENT_SECONDS, 0.01)),
                    duration=absent_dur,
                )
            )
    else:
        state["absent_started_at"] = None

    if person_status == 0:
        state["face_out_of_frame_start_time"] = None
        state["face_partial_started_at"] = None

    # Face in frame status (granular) — skip when YOLO already reports nobody (handled by student_absent)
    if face_in_frame_status == 0 and person_status != 0:
        if state["face_out_of_frame_start_time"] is None:
            state["face_out_of_frame_start_time"] = now
        duration = now - state["face_out_of_frame_start_time"]
        if duration >= PROCTOR_FACE_OUT_OF_FRAME_SECONDS:
            candidates.append(_event("face_fully_out_of_frame", confidence=min(1.0, duration / PROCTOR_FACE_OUT_OF_FRAME_SECONDS), duration=duration))
    else:
        state["face_out_of_frame_start_time"] = None
        if face_in_frame_status == 2: # Partially out
            if state["face_partial_started_at"] is None:
                state["face_partial_started_at"] = now
            duration = now - state["face_partial_started_at"]
            if duration >= PROCTOR_FACE_PARTIAL_SECONDS:
                candidates.append(_event("face_partially_out_of_frame", confidence=min(1.0, duration / PROCTOR_FACE_PARTIAL_SECONDS), duration=duration))
        else:
            state["face_partial_started_at"] = None

    # Old face hidden logic (can be replaced by face_in_frame_status)
    # if eyes == 0 and face_in_frame_status == 1: # Face detected but eyes not
    #     candidates.append(_event("face_hidden", confidence=0.8))

    if voice_value >= PROCTOR_AUDIO_THRESHOLD:
        confidence = min(1.0, voice_value / max(PROCTOR_AUDIO_THRESHOLD * 2.0, 1))
        candidates.append(_event("suspicious_audio", confidence=confidence))

    # --- Enhanced Head Movement Detection ---
    state["head_yaw_history"].append((now, head_yaw))
    state["head_pitch_history"].append((now, head_pitch))
    state["head_roll_history"].append((now, head_roll))

    # Keep history windowed
    state["head_yaw_history"] = [(t, v) for t, v in state["head_yaw_history"] if now - t < PROCTOR_HEAD_MOVE_WINDOW_SECONDS]
    state["head_pitch_history"] = [(t, v) for t, v in state["head_pitch_history"] if now - t < PROCTOR_HEAD_MOVE_WINDOW_SECONDS]
    state["head_roll_history"] = [(t, v) for t, v in state["head_roll_history"] if now - t < PROCTOR_HEAD_MOVE_WINDOW_SECONDS]

    # Detect specific head turns/tilts
    head_turned_away = False
    if abs(head_yaw) > PROCTOR_HEAD_YAW_THRESHOLD:
        event_type = "head_turned_left" if head_yaw < 0 else "head_turned_right"
        candidates.append(_event(event_type, confidence=min(1.0, abs(head_yaw) / PROCTOR_HEAD_YAW_THRESHOLD)))
        head_turned_away = True
    if abs(head_pitch) > PROCTOR_HEAD_PITCH_THRESHOLD:
        event_type = "head_tilted_up" if head_pitch > 0 else "head_tilted_down"
        candidates.append(_event(event_type, confidence=min(1.0, abs(head_pitch) / PROCTOR_HEAD_PITCH_THRESHOLD)))
        head_turned_away = True
    # Roll is less indicative of cheating, but can be logged if needed
    # if abs(head_roll) > PROCTOR_HEAD_ROLL_THRESHOLD:
    #     candidates.append(_event("head_tilted_side", confidence=min(1.0, abs(head_roll) / PROCTOR_HEAD_ROLL_THRESHOLD)))

    # Prolonged head turn (separate timer from gaze — avoids cancelling gaze timers)
    if head_turned_away:
        if state["head_turn_prolong_start"] is None:
            state["head_turn_prolong_start"] = now
        duration = now - state["head_turn_prolong_start"]
        if duration >= PROCTOR_HEAD_TURN_SECONDS:
            candidates.append(
                _event(
                    "prolonged_head_turn",
                    confidence=min(1.0, duration / PROCTOR_HEAD_TURN_SECONDS),
                    duration=duration,
                )
            )
    else:
        state["head_turn_prolong_start"] = None

    # Repeated head movement (using changes in angles)
    if len(state["head_yaw_history"]) > 1:
        significant_yaw_changes = sum(1 for i in range(1, len(state["head_yaw_history"])) if abs(state["head_yaw_history"][i][1] - state["head_yaw_history"][i-1][1]) > PROCTOR_HEAD_YAW_THRESHOLD / 2)
        significant_pitch_changes = sum(1 for i in range(1, len(state["head_pitch_history"])) if abs(state["head_pitch_history"][i][1] - state["head_pitch_history"][i-1][1]) > PROCTOR_HEAD_PITCH_THRESHOLD / 2)
        
        if (significant_yaw_changes + significant_pitch_changes) >= PROCTOR_HEAD_MOVE_REPEAT_COUNT_NEW:
            if now - state["last_head_movement_event_time"] > PROCTOR_EVENT_COOLDOWN_SECONDS:
                candidates.append(_event("repeated_head_movement", confidence=min(1.0, (significant_yaw_changes + significant_pitch_changes) / PROCTOR_HEAD_MOVE_REPEAT_COUNT_NEW)))
                state["last_head_movement_event_time"] = now

    # --- Enhanced Eye Gaze Detection ---
    gaze_deviated = False
    if eyes == 3: # Looking left
        candidates.append(_event("looking_away", confidence=0.7))
        candidates.append(_event("head_turned_left", confidence=0.7)) # Infer from gaze
        gaze_deviated = True
    elif eyes == 4: # Looking right
        candidates.append(_event("looking_away", confidence=0.7))
        candidates.append(_event("head_turned_right", confidence=0.7)) # Infer from gaze
        gaze_deviated = True
    elif eyes == 5: # Looking up
        candidates.append(_event("looking_up", confidence=0.7))
        gaze_deviated = True
    elif eyes == 6: # Looking down
        candidates.append(_event("looking_down", confidence=0.7))
        gaze_deviated = True
    # eyes == 0 or blink: handled below (sustained face_hidden), not as instantaneous gaze deviation

    # Combine head pitch with eye movements for vertical gaze inference (redundant but helps if gaze tracker misses)
    if not gaze_deviated and abs(head_pitch) > PROCTOR_HEAD_PITCH_THRESHOLD:
        if head_pitch > 0:
            candidates.append(_event("looking_up", confidence=min(1.0, head_pitch / PROCTOR_HEAD_PITCH_THRESHOLD)))
        else:
            candidates.append(_event("looking_down", confidence=min(1.0, abs(head_pitch) / PROCTOR_HEAD_PITCH_THRESHOLD)))
        gaze_deviated = True

    # Prolonged gaze deviation (directional gaze / head pitch only — not shared with head-turn timer)
    if gaze_deviated:
        if state["gaze_prolong_start"] is None:
            state["gaze_prolong_start"] = now
        duration = now - state["gaze_prolong_start"]
        if duration >= PROCTOR_GAZE_DEVIATION_SECONDS:
            candidates.append(
                _event(
                    "prolonged_gaze_deviation",
                    confidence=min(1.0, duration / PROCTOR_GAZE_DEVIATION_SECONDS),
                    duration=duration,
                )
            )
    else:
        state["gaze_prolong_start"] = None

    # Eyes not located while landmarks say face is present — sustained to ignore blinks
    if eyes == 0 and face_in_frame_status == 1 and person_status == 1:
        if state["face_hidden_started_at"] is None:
            state["face_hidden_started_at"] = now
        hid_dur = now - state["face_hidden_started_at"]
        if hid_dur >= PROCTOR_FACE_HIDDEN_SECONDS:
            candidates.append(
                _event(
                    "face_hidden",
                    confidence=min(1.0, hid_dur / PROCTOR_FACE_HIDDEN_SECONDS),
                    duration=hid_dur,
                )
            )
    else:
        state["face_hidden_started_at"] = None

    # Repeated gaze deviation (using history of 'eyes' status)
    state["gaze_history"].append((now, eyes))
    state["gaze_history"] = [(t, v) for t, v in state["gaze_history"] if now - t < PROCTOR_GAZE_DEVIATION_WINDOW_SECONDS]
    deviated_gaze_count = sum(
        1
        for t, v in state["gaze_history"]
        if v in (3, 4, 5, 6) or abs(head_pitch) > PROCTOR_HEAD_PITCH_THRESHOLD
    )
    if deviated_gaze_count >= PROCTOR_GAZE_DEVIATION_REPEAT_COUNT:
        if now - state["last_gaze_deviation_event_time"] > PROCTOR_EVENT_COOLDOWN_SECONDS:
            candidates.append(_event("repeated_gaze_deviation", confidence=min(1.0, deviated_gaze_count / PROCTOR_GAZE_DEVIATION_REPEAT_COUNT)))
            state["last_gaze_deviation_event_time"] = now

    logged_events = []
    for candidate in candidates:
        event_type = candidate["event_type"]
        warnings.append(candidate)
        if _cooldown_ok(state, event_type, now):
            duration = candidate.get("duration")
            _mark_logged(state, event_type, now, duration)
            # Add duration to event if it was a prolonged event
            if duration is not None: candidate['duration'] = round(duration, 2)
            logged_events.append(candidate)

    return {
        "should_log": bool(logged_events),
        "events": logged_events,
        "warnings": warnings,
        "audio_suspicious": any(e["event_type"] == "suspicious_audio" for e in warnings),
        "brightness": brightness,
    }


def evaluate_window_event(user_key, event_type="tab_switch"):
    now = _now()
    state = _state[user_key]
    event = _event(event_type, confidence=1.0)
    should_log = _cooldown_ok(state, event_type, now)
    if should_log:
        _mark_logged(state, event_type, now)
    return {
        "should_log": should_log,
        "events": [event] if should_log else [],
        "warnings": [event],
    }
