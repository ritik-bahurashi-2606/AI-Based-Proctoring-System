import json

import numpy as np

import face_verifier as verifier


class _Predictor:
    def __call__(self, gray, face):
        return object()


def test_liveness_metrics_are_json_serializable(monkeypatch):
    landmarks = np.zeros((68, 2), dtype=np.int64)
    eye = np.array(
        [[0, 0], [1, 2], [3, 2], [4, 0], [3, -2], [1, -2]], dtype=np.int64
    )
    landmarks[verifier._LEFT_EYE_IDX] = eye
    landmarks[verifier._RIGHT_EYE_IDX] = eye

    monkeypatch.setattr(
        verifier, "_detect_faces", lambda image: (np.zeros((8, 8), dtype=np.uint8), [object()])
    )
    monkeypatch.setattr(verifier, "_predictor", _Predictor())
    monkeypatch.setattr(verifier, "_landmark_to_np", lambda shape: landmarks)

    result = verifier.check_liveness(np.zeros((8, 8, 3), dtype=np.uint8))

    assert result["face_detected"] is True
    assert result["is_live"] is True
    json.dumps(result)
