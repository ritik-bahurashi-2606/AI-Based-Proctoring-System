import base64
import os
from pathlib import Path
import pytest
import proctoring_evidence as pe

def _make_minimal_jpeg(extra_trailing=b''):
    app0_payload = b'JFIF' + bytes([0, 1, 1, 0, 0, 1, 0, 1, 0, 0])
    app0_len = len(app0_payload) + 2
    header = bytes([0xff, 0xd8, 0xff, 0xe0]) + app0_len.to_bytes(2, 'big') + app0_payload
    eoi = bytes([0xff, 0xd9])
    return header + eoi + extra_trailing

def test_save_evidence_valid_jpeg(tmp_path):
    jpeg_bytes = _make_minimal_jpeg()
    b64 = 'data:image/jpeg;base64,' + base64.b64encode(jpeg_bytes).decode('ascii')
    rel_path = pe.save_evidence_image(
        image_base64=b64,
        student_id='test@student.edu',
        exam_id='EXAM_42',
        event_types=['mobile_phone'],
        directory=str(tmp_path),
    )
    assert rel_path.startswith('EXAM_42')
    assert 'mobile_phone' in rel_path
    full_path = tmp_path / rel_path
    assert full_path.exists()
    assert full_path.read_bytes() == jpeg_bytes

def test_save_evidence_opencv_trailing_bytes(tmp_path):
    jpeg_bytes = _make_minimal_jpeg(extra_trailing=bytes([0, 0, 0]))
    b64 = base64.b64encode(jpeg_bytes).decode('ascii')
    rel_path = pe.save_evidence_image(
        image_base64=b64,
        student_id='student1',
        exam_id='exam1',
        event_types=['device'],
        directory=str(tmp_path),
    )
    full_path = tmp_path / rel_path
    assert full_path.exists()

def test_save_evidence_missing_data_raises(tmp_path):
    with pytest.raises(ValueError, match='missing'):
        pe.save_evidence_image('', 's1', 'e1', ['phone'], directory=str(tmp_path))
    with pytest.raises(ValueError, match='missing'):
        pe.save_evidence_image(None, 's1', 'e1', ['phone'], directory=str(tmp_path))

def test_save_evidence_invalid_base64_raises(tmp_path):
    with pytest.raises(ValueError, match='not valid base64'):
        pe.save_evidence_image('not-valid-base64!', 's1', 'e1', ['phone'], directory=str(tmp_path))

def test_save_evidence_missing_soi_raises(tmp_path):
    b64 = base64.b64encode(b'GIF89a' + bytes([0] * 20)).decode('ascii')
    with pytest.raises(ValueError, match='missing SOI marker'):
        pe.save_evidence_image(b64, 's1', 'e1', ['phone'], directory=str(tmp_path))

def test_save_evidence_missing_eoi_raises(tmp_path):
    truncated = bytes([0xff, 0xd8, 0xff, 0xe0, 0, 16]) + b'JFIF' + bytes([0, 1, 1, 0, 0, 1, 0, 1, 0, 0]) + b'123' * 50
    b64 = base64.b64encode(truncated).decode('ascii')
    with pytest.raises(ValueError, match='missing EOI marker'):
        pe.save_evidence_image(b64, 's1', 'e1', ['phone'], directory=str(tmp_path))

def test_save_evidence_safe_paths(tmp_path):
    jpeg_bytes = _make_minimal_jpeg()
    b64 = base64.b64encode(jpeg_bytes).decode('ascii')
    rel_path = pe.save_evidence_image(
        image_base64=b64,
        student_id='../../etc/evil',
        exam_id='../../escape',
        event_types=['phone'],
        directory=str(tmp_path),
    )
    full_path = (tmp_path / rel_path).resolve()
    assert full_path.is_relative_to(tmp_path.resolve())

def test_delete_evidence_image(tmp_path):
    jpeg_bytes = _make_minimal_jpeg()
    b64 = base64.b64encode(jpeg_bytes).decode('ascii')
    rel_path = pe.save_evidence_image(
        image_base64=b64,
        student_id='s1',
        exam_id='e1',
        event_types=['phone'],
        directory=str(tmp_path),
    )
    full_path = tmp_path / rel_path
    assert full_path.exists()
    pe.delete_evidence_image(rel_path, directory=str(tmp_path))
    assert not full_path.exists()

def test_delete_evidence_traversal_prevention(tmp_path):
    with pytest.raises(ValueError, match='outside'):
        pe.delete_evidence_image('../../outside.jpg', directory=str(tmp_path))
