import os


def test_face_detector_auto_falls_back_to_opencv(monkeypatch):
    import face_detector

    sentinel = object()

    monkeypatch.setenv("PROCTOR_FACE_BACKEND", "auto")
    monkeypatch.setattr(face_detector, "_create_mediapipe_detector", lambda: None)
    monkeypatch.setattr(face_detector, "_create_retinaface_detector", lambda: None)
    monkeypatch.setattr(face_detector.cv2.dnn, "readNetFromTensorflow", lambda *_: sentinel)

    assert face_detector.get_face_detector(quantized=True) is sentinel


def test_face_detector_explicit_modern_backend(monkeypatch):
    import face_detector

    detector = {"backend": "mediapipe", "detector": object()}

    monkeypatch.setenv("PROCTOR_FACE_BACKEND", "mediapipe")
    monkeypatch.setattr(face_detector, "_create_mediapipe_detector", lambda: detector)

    assert face_detector.get_face_detector() is detector


def test_landmark_backend_auto_prefers_mediapipe(monkeypatch):
    import face_landmarks

    monkeypatch.setenv("PROCTOR_LANDMARK_BACKEND", "auto")
    monkeypatch.setattr(face_landmarks, "_has_mediapipe", lambda: True)

    assert face_landmarks.get_landmark_model() == {"backend": "mediapipe"}


def test_landmark_backend_fails_clearly_when_legacy_model_missing(monkeypatch, tmp_path):
    import face_landmarks

    missing_model = tmp_path / "pose_model"

    monkeypatch.setenv("PROCTOR_LANDMARK_BACKEND", "tensorflow")

    try:
        face_landmarks.get_landmark_model(str(missing_model))
    except FileNotFoundError as exc:
        assert "SavedModel" in str(exc)
        assert "variables/" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing TensorFlow landmark model")


def test_face_match_backend_auto_uses_insightface_embedding(monkeypatch):
    import face_verifier

    class Face:
        bbox = [0, 0, 10, 10]
        embedding = [1.0, 0.0, 0.0]

    class Backend:
        def get(self, image):
            return [Face()]

    monkeypatch.setenv("PROCTOR_FACE_MATCH_BACKEND", "auto")
    monkeypatch.setattr(face_verifier, "_get_insightface_backend", lambda: Backend())

    assert face_verifier._get_face_embedding(object()) == [1.0, 0.0, 0.0]


def test_face_match_explicit_deepface_skips_insightface(monkeypatch):
    import face_verifier

    calls = []

    monkeypatch.setenv("PROCTOR_FACE_MATCH_BACKEND", "deepface")
    monkeypatch.setattr(face_verifier, "_get_insightface_backend", lambda: calls.append("insightface"))

    assert face_verifier._get_face_embedding(object()) is None
    assert calls == []


def test_env_example_documents_only_used_variables():
    root = os.path.dirname(os.path.dirname(__file__))
    env_path = os.path.join(root, ".env.example")
    with open(env_path, encoding="utf-8") as handle:
        env_names = {
            line.split("=", 1)[0]
            for line in handle
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }

    unsupported = {"SERVER_NAME"}

    assert not env_names.intersection(unsupported)
    assert {
        "PROCTOR_FACE_BACKEND",
        "PROCTOR_LANDMARK_BACKEND",
        "PROCTOR_FACE_MATCH_BACKEND",
        "PROCTOR_OBJECT_BACKEND",
        "PROCTOR_OBJECT_MODEL_PATH",
        "PROCTOR_OBJECT_MODEL_NAME",
    }.issubset(env_names)
