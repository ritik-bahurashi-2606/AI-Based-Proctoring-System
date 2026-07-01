"""
Face verification helpers for MyProctor.ai.

The module keeps authentication checks in one place:
- registration capture validation (quality + liveness)
- login identity verification with a configurable match threshold
- a bool compatibility wrapper for older call sites
"""

import base64
import logging
import os

import cv2
import dlib
import numpy as np

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDERS = {"", "no_camera"}
# Minimum face-match confidence (0–100 %) required for login.
# Can be overridden via the FACE_MATCH_THRESHOLD environment variable.
DEFAULT_FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "66"))
EAR_LIVENESS_THRESHOLD = float(os.getenv("EAR_LIVENESS_THRESHOLD", "0.10"))
MIN_FACE_AREA_RATIO = float(os.getenv("FACE_MIN_AREA_RATIO", "0.08"))
MIN_BLUR_VARIANCE = float(os.getenv("FACE_MIN_BLUR_VARIANCE", "75"))
MIN_BRIGHTNESS = float(os.getenv("FACE_MIN_BRIGHTNESS", "45"))
MAX_BRIGHTNESS = float(os.getenv("FACE_MAX_BRIGHTNESS", "220"))
MAX_FACE_CENTER_OFFSET = float(os.getenv("FACE_MAX_CENTER_OFFSET", "0.22"))

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DAT_PATH = os.path.join(
    _BASE_DIR,
    "gaze_tracking",
    "trained_models",
    "shape_predictor_68_face_landmarks.dat",
)

_deepface = None
_face_detector = None
_predictor = None

_LEFT_EYE_IDX = list(range(36, 42))
_RIGHT_EYE_IDX = list(range(42, 48))


def _get_deepface():
    global _deepface
    if _deepface is None:
        from deepface import DeepFace  # noqa: PLC0415

        _deepface = DeepFace
    return _deepface


def _load_dlib():
    global _face_detector, _predictor
    if _face_detector is None:
        _face_detector = dlib.get_frontal_face_detector()
    if _predictor is None:
        if not os.path.exists(_DAT_PATH):
            raise FileNotFoundError(
                "Dlib landmark model not found at "
                f"{_DAT_PATH}. Expected gaze_tracking/trained_models/"
                "shape_predictor_68_face_landmarks.dat"
            )
        _predictor = dlib.shape_predictor(_DAT_PATH)


def _empty_result(ok=False, message="Face verification failed. Please try again.", **extra):
    result = {"ok": ok, "message": message}
    result.update(extra)
    return result


def _b64_to_bgr(b64_string):
    if not b64_string or b64_string in IMAGE_PLACEHOLDERS:
        return None
    try:
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        raw = base64.b64decode(b64_string)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Image decode error: %s", exc)
        return None


def _landmark_to_np(shape, dtype="int"):
    coords = np.zeros((68, 2), dtype=dtype)
    for i in range(68):
        coords[i] = (shape.part(i).x, shape.part(i).y)
    return coords


def _eye_aspect_ratio(eye_points):
    vertical_a = np.linalg.norm(eye_points[1] - eye_points[5])
    vertical_b = np.linalg.norm(eye_points[2] - eye_points[4])
    horizontal = np.linalg.norm(eye_points[0] - eye_points[3])
    if horizontal == 0:
        return 0.0
    return (vertical_a + vertical_b) / (2.0 * horizontal)


def _detect_faces(image_bgr):
    _load_dlib()
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    faces = _face_detector(gray, 1)
    return gray, list(faces)


def check_liveness(image_bgr):
    result = {
        "face_detected": False,
        "ear_left": 0.0,
        "ear_right": 0.0,
        "ear_avg": 0.0,
        "is_live": False,
    }
    try:
        if image_bgr is None:
            return result
        gray, faces = _detect_faces(image_bgr)
        if not faces:
            return result

        result["face_detected"] = True
        shape = _predictor(gray, faces[0])
        landmarks = _landmark_to_np(shape)
        left_eye = landmarks[_LEFT_EYE_IDX]
        right_eye = landmarks[_RIGHT_EYE_IDX]
        ear_left = _eye_aspect_ratio(left_eye)
        ear_right = _eye_aspect_ratio(right_eye)
        ear_avg = (ear_left + ear_right) / 2.0

        result["ear_left"] = round(ear_left, 4)
        result["ear_right"] = round(ear_right, 4)
        result["ear_avg"] = round(ear_avg, 4)
        result["is_live"] = ear_avg >= EAR_LIVENESS_THRESHOLD
    except Exception as exc:
        logger.warning("Liveness check error: %s", exc)
    return result


def assess_face_capture(image_bgr, require_liveness=False):
    if image_bgr is None:
        return _empty_result(
            message="Invalid face image. Please capture a fresh webcam photo."
        )

    height, width = image_bgr.shape[:2]
    if width < 240 or height < 180:
        return _empty_result(
            message="Photo quality is too low. Please retake a larger, clearer photo."
        )

    try:
        gray, faces = _detect_faces(image_bgr)
    except Exception as exc:
        logger.warning("Face capture assessment error: %s", exc)
        return _empty_result(
            message="Face verification could not run. Please try again."
        )

    if not faces:
        return _empty_result(
            message="No clear face was detected. Look at the camera and retake the photo."
        )
    if len(faces) > 1:
        return _empty_result(
            message="Multiple faces detected. Only one person should be visible."
        )

    face = faces[0]
    face_width = max(face.right() - face.left(), 1)
    face_height = max(face.bottom() - face.top(), 1)
    face_area_ratio = (face_width * face_height) / float(width * height)
    if face_area_ratio < MIN_FACE_AREA_RATIO:
        return _empty_result(
            message="Your face is too far from the camera. Move closer and retake the photo."
        )

    face_center_x = (face.left() + face.right()) / 2.0
    face_center_y = (face.top() + face.bottom()) / 2.0
    if (
        abs(face_center_x - (width / 2.0)) / width > MAX_FACE_CENTER_OFFSET
        or abs(face_center_y - (height / 2.0)) / height > MAX_FACE_CENTER_OFFSET
    ):
        return _empty_result(
            message="Keep your face centered and front-facing, then retake the photo."
        )

    x1, y1 = max(face.left(), 0), max(face.top(), 0)
    x2, y2 = min(face.right(), width), min(face.bottom(), height)
    face_gray = gray[y1:y2, x1:x2]
    brightness = float(np.mean(face_gray)) if face_gray.size else 0.0
    blur_variance = float(cv2.Laplacian(face_gray, cv2.CV_64F).var()) if face_gray.size else 0.0

    if blur_variance < MIN_BLUR_VARIANCE:
        return _empty_result(
            message="The face photo is blurry. Hold still and retake a clear photo.",
            blur_variance=round(blur_variance, 2),
        )
    if brightness < MIN_BRIGHTNESS:
        return _empty_result(
            message="The photo is too dark. Improve lighting and retake the photo.",
            brightness=round(brightness, 2),
        )
    if brightness > MAX_BRIGHTNESS:
        return _empty_result(
            message="The photo is overexposed. Reduce glare and retake the photo.",
            brightness=round(brightness, 2),
        )

    liveness = check_liveness(image_bgr) if require_liveness else None
    if require_liveness and not liveness["face_detected"]:
        return _empty_result(
            message="Liveness detection failed because no clear face was found."
        )
    if require_liveness and not liveness["is_live"]:
        return _empty_result(
            message="Liveness detection failed. Use your live face, not a photo, screenshot, or video.",
            liveness=liveness,
        )

    return _empty_result(
        ok=True,
        message="Face capture is valid.",
        brightness=round(brightness, 2),
        blur_variance=round(blur_variance, 2),
        liveness=liveness,
    )


def validate_registration_capture(image_b64):
    image_bgr = _b64_to_bgr(image_b64)
    if image_bgr is None:
        return _empty_result(
            message="Unsupported image format. Please capture a fresh webcam photo."
        )
    return assess_face_capture(image_bgr, require_liveness=True)


def _similarity_score_from_deepface(result):
    distance = float(result.get("distance", 1.0))
    metric = str(result.get("distance_metric", "cosine")).lower()
    if metric == "cosine":
        return max(0.0, min(100.0, (1.0 - distance) * 100.0))

    threshold = float(result.get("threshold", 1.0)) or 1.0
    return max(0.0, min(100.0, (1.0 - (distance / threshold)) * 100.0))


def verify_face_match_result(captured_image_b64, stored_image_b64, threshold=None):
    threshold = DEFAULT_FACE_MATCH_THRESHOLD if threshold is None else float(threshold)

    if captured_image_b64 in IMAGE_PLACEHOLDERS:
        return _empty_result(
            message="Face verification is required. Please capture your photo before signing in.",
            score=0.0,
            threshold=threshold,
        )
    if stored_image_b64 in IMAGE_PLACEHOLDERS:
        return _empty_result(
            message="This account does not have a registered face photo. Please register again with a valid photo.",
            score=0.0,
            threshold=threshold,
        )

    captured_bgr = _b64_to_bgr(captured_image_b64)
    stored_bgr = _b64_to_bgr(stored_image_b64)
    live_capture = assess_face_capture(captured_bgr, require_liveness=True)
    if not live_capture["ok"]:
        live_capture.update({"score": 0.0, "threshold": threshold})
        return live_capture

    stored_capture = assess_face_capture(stored_bgr, require_liveness=False)
    if not stored_capture["ok"]:
        return _empty_result(
            message="The registered face image is not usable. Please register again with a clear face photo.",
            score=0.0,
            threshold=threshold,
        )

    try:
        deepface = _get_deepface()
        result = deepface.verify(
            captured_bgr,
            stored_bgr,
            enforce_detection=True,
            model_name="VGG-Face",
            distance_metric="cosine",
        )
        score = round(_similarity_score_from_deepface(result), 2)
    except Exception as exc:
        logger.error("DeepFace verification error: %s", exc)
        return _empty_result(
            message="Face matching could not be completed. Please retake a clear photo and try again.",
            score=0.0,
            threshold=threshold,
        )

    logger.info(
        "Face match result: score=%.2f%% | threshold=%.0f%% | passed=%s",
        score,
        threshold,
        score >= threshold,
    )

    if score < threshold:
        return _empty_result(
            message=(
                f"Face verification failed. Match confidence {score:.1f}% is below "
                f"the required threshold of {threshold:.0f}%. "
                "Please ensure your face is fully visible, well-lit, and matches "
                "the photo registered with your account."
            ),
            score=score,
            threshold=threshold,
        )

    return _empty_result(
        ok=True,
        message=f"Face verified successfully. Match confidence: {score:.1f}%.",
        score=score,
        threshold=threshold,
    )


def verify_face_match(captured_image_b64, stored_image_b64, threshold=None):
    return verify_face_match_result(captured_image_b64, stored_image_b64, threshold)["ok"]
