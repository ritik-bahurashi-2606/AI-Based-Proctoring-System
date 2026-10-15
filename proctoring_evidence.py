import base64
import binascii
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath


def _safe_component(value):
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(value)).strip(".-")


def save_evidence_image(image_base64, student_id, exam_id, event_types, directory=None, timestamp=None):
    """Write one validated JPEG frame for a confirmed event and return its relative path."""
    if not isinstance(image_base64, str) or not image_base64:
        raise ValueError("Proctoring evidence image is missing")
    encoded = image_base64.split(",", 1)[-1] if image_base64.startswith("data:") else image_base64
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Proctoring evidence is not valid base64 image data") from error
    if not image_bytes.startswith(b"\xff\xd8"):
        raise ValueError("Proctoring evidence is not a valid JPEG image (missing SOI marker)")
    # The JPEG EOI marker (\xff\xd9) must appear within the last 16 bytes.
    # OpenCV-encoded frames are valid but may have minor trailing variation.
    if b"\xff\xd9" not in image_bytes[-16:]:
        raise ValueError("Proctoring evidence is not a complete JPEG image (missing EOI marker)")

    root = Path(directory or os.getenv(
        "PROCTORING_EVIDENCE_DIR",
        str(Path(__file__).resolve().parent / "proctoring_evidence"),
    ))
    exam_dirname = _safe_component(exam_id)
    if not exam_dirname:
        raise ValueError("Exam ID cannot be used for an evidence path")

    event_slug = "-".join(
        _safe_component(re.sub(r"[^A-Za-z0-9_-]", "-", str(event))).lower()
        for event in sorted(set(event_types))
    ) or "proctoring-event"
    event_slug = event_slug[:100]
    timestamp = _safe_component(timestamp or datetime.now().strftime("%Y%m%dT%H%M%S%f"))
    filename = (
        f"student-{_safe_component(student_id) or 'unknown'}_"
        f"{event_slug}_{timestamp}_{uuid.uuid4().hex}.jpg"
    )
    exam_directory = root / exam_dirname
    exam_directory.mkdir(parents=True, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=exam_directory, prefix=".evidence-", suffix=".tmp", delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(image_bytes)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, exam_directory / filename)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return str(PurePosixPath(exam_dirname) / filename)


def delete_evidence_image(relative_path, directory=None):
    """Remove a previously saved image, refusing paths outside the evidence root."""
    root = Path(directory or os.getenv(
        "PROCTORING_EVIDENCE_DIR",
        str(Path(__file__).resolve().parent / "proctoring_evidence"),
    )).resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Evidence path is outside the configured evidence directory")
    target.unlink(missing_ok=True)
