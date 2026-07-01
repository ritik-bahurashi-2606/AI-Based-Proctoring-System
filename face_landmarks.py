import cv2
import numpy as np
import os
import tensorflow as tf
from tensorflow import keras


def _saved_model_complete(saved_model):
    variables_dir = os.path.join(saved_model, 'variables')
    if not os.path.isdir(saved_model):
        return False
    if not os.path.isfile(os.path.join(saved_model, 'saved_model.pb')):
        return False
    if not os.path.isdir(variables_dir):
        return False
    return any(
        os.path.isfile(os.path.join(variables_dir, fname))
        for fname in ('variables.index', 'variables.data-00000-of-00001')
    )


def get_landmark_model(saved_model="models/pose_model"):
    if not _saved_model_complete(saved_model):
        raise FileNotFoundError(
            f"SavedModel at '{saved_model}' is incomplete or missing variables/ files. "
            "Expected 'saved_model.pb' and a 'variables/' directory."
        )
    try:
        return tf.saved_model.load(saved_model)
    except Exception as e:
        try:
            return keras.models.load_model(saved_model)
        except Exception as e2:
            raise RuntimeError(
                f"Cannot load landmark model from '{saved_model}': {e}; fallback failed: {e2}"
            )

def get_square_box(box):
    left_x = box[0]
    top_y = box[1]
    right_x = box[2]
    bottom_y = box[3]

    box_width = right_x - left_x
    box_height = bottom_y - top_y

    diff = box_height - box_width
    delta = int(abs(diff) / 2)

    if diff == 0:                   # Already a square.
        return box
    elif diff > 0:                  # Height > width, a slim box.
        left_x -= delta
        right_x += delta
        if diff % 2 == 1:
            right_x += 1
    else:                           # Width > height, a short box.
        top_y -= delta
        bottom_y += delta
        if diff % 2 == 1:
            bottom_y += 1

    assert ((right_x - left_x) == (bottom_y - top_y)), 'Box is not square.'

    return [left_x, top_y, right_x, bottom_y]

def move_box(box, offset):
        left_x = box[0] + offset[0]
        top_y = box[1] + offset[1]
        right_x = box[2] + offset[0]
        bottom_y = box[3] + offset[1]
        return [left_x, top_y, right_x, bottom_y]

def detect_marks(img, model, face):
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
    
    face_img = img[facebox[1]: facebox[3],
                     facebox[0]: facebox[2]]
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
