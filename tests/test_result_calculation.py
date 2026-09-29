from app import _process_webcam_frame, _score_objective_answers, _upsert_exam_response


class _Cursor:
    def __init__(self, existing=False):
        self.existing = existing
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if query.startswith('SELECT 1 FROM'):
            return 1 if self.existing else 0
        return 1


def test_objective_score_uses_submitted_answers_and_question_marks():
    questions = [
        {'qid': '1', 'correct': 'a', 'marks': 2},
        {'qid': '2', 'correct': 'c', 'marks': 3},
        {'qid': '3', 'correct': 'd', 'marks': 5},
    ]

    marks, correct, wrong, attempted = _score_objective_answers(
        questions, {'1': 'A', '2': 'B'}, 0
    )

    assert marks == 2
    assert correct == 1
    assert wrong == 1
    assert attempted == 2


def test_objective_score_applies_negative_marks_and_ignores_unanswered():
    questions = [
        {'qid': '1', 'correct': 'a', 'marks': 4},
        {'qid': '2', 'correct': 'b', 'marks': 2},
    ]

    marks, correct, wrong, attempted = _score_objective_answers(
        questions, {'1': 'D'}, 25
    )

    assert marks == -1
    assert correct == 0
    assert wrong == 1
    assert attempted == 1


def test_subjective_response_upsert_avoids_duplicate_rows():
    insert_cursor = _Cursor(existing=False)
    _upsert_exam_response(insert_cursor, 'longtest', 'student@example.com', 'exam-1', '2', '', 7)
    assert any('INSERT INTO longtest' in query for query, _ in insert_cursor.calls)

    update_cursor = _Cursor(existing=True)
    _upsert_exam_response(update_cursor, 'longtest', 'student@example.com', 'exam-1', '2', 'answer', 7)
    assert any('UPDATE longtest' in query for query, _ in update_cursor.calls)


def test_webcam_processing_is_automatable_without_hardware(monkeypatch):
    import app

    expected = {'jpg_as_text': 'frame', 'mob_status': 0, 'person_status': 1}
    monkeypatch.setattr(app.camera, 'get_frame', lambda image: expected)

    assert _process_webcam_frame('test-frame') == expected