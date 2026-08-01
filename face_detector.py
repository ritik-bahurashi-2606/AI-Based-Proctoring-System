import os

import cv2
import numpy as np


def _has_mediapipe():
    try:
        import mediapipe as _  # noqa: F401
        return True
    except Exception:
        return False


def _has_retinaface():
    try:
        import retinaface  # noqa: F401
        return True
    except Exception:
        return False


def _create_mediapipe_detector():
    if not _has_mediapipe():
        return None
    try:
        from mediapipe.python.solutions import face_detection as mp_face_detection

        detector = mp_face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5,
        )
        return {"backend": "mediapipe", "detector": detector}
    except Exception:
        return None


def _create_retinaface_detector():
    if not _has_retinaface():
        return None
    try:
        import retinaface

        detector = retinaface.RetinaFace(quality="normal")
        return {"backend": "retinaface", "detector": detector}
    except Exception:
        return None


def get_face_detector(modelFile=None, configFile=None, quantized=False):
    backend = os.getenv("PROCTOR_FACE_BACKEND", "auto").lower()
    if backend == "mediapipe":
        detector = _create_mediapipe_detector()
        if detector is not None:
            return detector
    elif backend == "retinaface":
        detector = _create_retinaface_detector()
        if detector is not None:
            return detector
    elif backend == "auto":
        detector = _create_mediapipe_detector() or _create_retinaface_detector()
        if detector is not None:
            return detector

    if quantized:
        if modelFile is None:
            modelFile = "models/opencv_face_detector_uint8.pb"
        if configFile is None:
            configFile = "models/opencv_face_detector.pbtxt"
        model = cv2.dnn.readNetFromTensorflow(modelFile, configFile)
    else:
        if modelFile is None:
            modelFile = "models/res10_300x300_ssd_iter_140000.caffemodel"
        if configFile is None:
            configFile = "models/deploy.prototxt"
        model = cv2.dnn.readNetFromCaffe(configFile, modelFile)
    return model


def find_faces(img, model):
    if isinstance(model, dict):
        backend = model.get("backend")
        if backend == "mediapipe":
            detector = model.get("detector")
            if detector is None:
                return []
            try:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                results = detector.process(rgb)
                faces = []
                if results.detections:
                    h, w = img.shape[:2]
                    for detection in results.detections:
                        box = detection.location_data.relative_bounding_box
                        x = max(0, int(box.xmin * w))
                        y = max(0, int(box.ymin * h))
                        x1 = min(w, int((box.xmin + box.width) * w))
                        y1 = min(h, int((box.ymin + box.height) * h))
                        faces.append([x, y, x1, y1])
                return faces
            except Exception:
                return []

        if backend == "retinaface":
            detector = model.get("detector")
            if detector is None:
                return []
            try:
                detections = detector.detect_faces(img)
                faces = []
                if isinstance(detections, dict):
                    for detection in detections.values():
                        facial_area = detection.get("facial_area")
                        if facial_area:
                            x1, y1, x2, y2 = facial_area
                            faces.append([x1, y1, x2, y2])
                return faces
            except Exception:
                return []

    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(img, (300, 300)),
        1.0,
        (300, 300),
        (104.0, 177.0, 123.0),
    )
    model.setInput(blob)
    res = model.forward()
    faces = []
    for i in range(res.shape[2]):
        confidence = res[0, 0, i, 2]
        if confidence > 0.5:
            box = res[0, 0, i, 3:7] * np.array([w, h, w, h])
            (x, y, x1, y1) = box.astype("int")
            faces.append([x, y, x1, y1])
    return faces