import os

import cv2
import numpy as np
import tensorflow as tf
from tensorflow import keras


def _saved_model_complete(saved_model):
    variables_dir = os.path.join(saved_model, "variables")
    if not os.path.isdir(saved_model):
        return False
    if not os.path.isfile(os.path.join(saved_model, "saved_model.pb")):
        return False
    if not os.path.isdir(variables_dir):
        return False
    return any(
        os.path.isfile(os.path.join(variables_dir, fname))
        for fname in ("variables.index", "variables.data-00000-of-00001")
    )


def _has_mediapipe():
    try:
        import mediapipe as _  # noqa: F401
        return True
    except Exception:
        return False


def get_landmark_model(saved_model="models/pose_model"):
    backend = os.getenv("PROCTOR_LANDMARK_BACKEND", "auto").lower()
    if backend in {"mediapipe", "auto"} and _has_mediapipe():
        return {"backend": "mediapipe"}

    if not _saved_model_complete(saved_model):
        raise FileNotFoundError(
            f"SavedModel at '{saved_model}' is incomplete or missing variables/ files. "
            "Expected 'saved_model.pb' and a 'variables/' directory."
        )
    try:
        return tf.saved_model.load(saved_model)
    except Exception as exc:
        try:
            return keras.models.load_model(saved_model)
        except Exception as exc2:
            raise RuntimeError(
                f"Cannot load landmark model from '{saved_model}': {exc}; fallback failed: {exc2}"
            ) from exc2


def get_square_box(box):
    left_x = box[0]
    top_y = box[1]
    right_x = box[2]
    bottom_y = box[3]

    box_width = right_x - left_x
    box_height = bottom_y - top_y

    diff = box_height - box_width
    delta = int(abs(diff) / 2)

    if diff == 0:
        return box
    if diff > 0:
        left_x -= delta
        right_x += delta
        if diff % 2 == 1:
            right_x += 1
    else:
        top_y -= delta
        bottom_y += delta
        if diff % 2 == 1:
            bottom_y += 1

    assert (right_x - left_x) == (bottom_y - top_y), "Box is not square."
    return [left_x, top_y, right_x, bottom_y]


def move_box(box, offset):
    left_x = box[0] + offset[0]
    top_y = box[1] + offset[1]
    right_x = box[2] + offset[0]
    bottom_y = box[3] + offset[1]
    return [left_x, top_y, right_x, bottom_y]


def _detect_marks_with_mediapipe(img, face):
    try:
        from mediapipe.python.solutions import face_mesh

        mesh = face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.5,
        )
        h, w = img.shape[:2]
        left_x = max(0, int(face[0]))
        top_y = max(0, int(face[1]))
        right_x = min(w, int(face[2]))
        bottom_y = min(h, int(face[3]))
        face_img = img[top_y:bottom_y, left_x:right_x]
        if face_img.size == 0:
            return np.zeros((55, 2), dtype=np.float32)
        rgb = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
        results = mesh.process(rgb)
        if not results.multi_face_landmarks:
            return np.zeros((55, 2), dtype=np.float32)
        landmarks = results.multi_face_landmarks[0].landmark
        marks = np.zeros((55, 2), dtype=np.float32)
        for i in range(min(55, len(landmarks))):
            marks[i, 0] = landmarks[i].x * (right_x - left_x) + left_x
            marks[i, 1] = landmarks[i].y * (bottom_y - top_y) + top_y
        return marks
    except Exception:
        return np.zeros((55, 2), dtype=np.float32)


def detect_marks(img, model, face):
    backend = os.getenv("PROCTOR_LANDMARK_BACKEND", "auto").lower()
    if backend in {"mediapipe", "auto"} and _has_mediapipe():
        marks = _detect_marks_with_mediapipe(img, face)
        if marks.size:
            return marks

    offset_y = int(abs((face[3] - face[1]) * 0.1))
    box_moved = move_box(face, [0, offset_y])
    facebox = get_square_box(box_moved)

    h, w = img.shape[:2]
    if facebox[0] < 0:
        facebox[0] = 0
    if facebox[1] < 0:
        facebox[1] = 0
    if facebox[2] > w:
        facebox[2] = w
    if facebox[3] > h:
        facebox[3] = h

    face_img = img[facebox[1]: facebox[3], facebox[0]: facebox[2]]
    face_img = cv2.resize(face_img, (320, 320))
    face_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)

    signature = model.signatures.get("predict")
    if signature is None:
        signature = model.signatures.get("serving_default")
    if signature is None:
        signature = next(iter(model.signatures.values()), None)
    if signature is None:
        raise RuntimeError("Landmark model has no callable signatures.")

    predictions = signature(tf.constant([face_img], dtype=tf.uint8))
    if isinstance(predictions, dict):
        output_tensor = predictions.get("output")
        if output_tensor is None:
            output_tensor = next(iter(predictions.values()), None)
    else:
        output_tensor = predictions
    if output_tensor is None:
        raise RuntimeError("Landmark model returned no output tensor.")

    marks = np.array(output_tensor).flatten()[:136]
    marks = np.reshape(marks, (-1, 2))

    marks *= (facebox[2] - facebox[0])
    marks[:, 0] += facebox[0]
    marks[:, 1] += facebox[1]
    marks = marks.astype(np.uint32)

    return marks
