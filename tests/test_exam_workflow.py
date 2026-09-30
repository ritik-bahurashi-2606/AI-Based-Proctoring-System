from datetime import datetime, timedelta, timezone

from exam_workflow import (
    exam_schedule_now,
    save_submitted_answers,
    student_safe_question_payload,
)


def test_exam_schedule_clock_uses_india_local_wall_time():
    india_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    actual = exam_schedule_now()

    assert actual.tzinfo is None
    assert abs((actual - india_now.replace(tzinfo=None)).total_seconds()) < 2


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return 0


def test_student_question_payload_never_includes_correct_answers():
    question_ids, questions = student_safe_question_payload([
        {
            'qid': 'Q-17',
            'q': 'Question',
            'a': 'A',
            'b': 'B',
            'c': 'C',
            'd': 'D',
            'ans': 'c',
            'marks': 2,
        },
    ])

    assert question_ids == ['Q-17']
    assert questions['Q-17'] == {
        'q': 'Question',
        'a': 'A',
        'b': 'B',
        'c': 'C',
        'd': 'D',
        'marks': 2,
    }


def test_submitted_answers_use_atomic_upserts_and_clear_unanswered_rows():
    cursor = RecordingCursor()

    saved = save_submitted_answers(
        cursor,
        'student@example.com',
        'exam-1',
        23,
        {'Q-9': 'b', 'Q-2': '', 'Q-17': 'a'},
    )

    assert saved == 2
    assert len(cursor.calls) == 3
    assert 'ON DUPLICATE KEY UPDATE' in cursor.calls[0][0]
    assert cursor.calls[0][1][2] == 'Q-9'
    assert 'DELETE FROM students' in cursor.calls[1][0]
    assert cursor.calls[1][1][1] == 'Q-2'
    assert 'ON DUPLICATE KEY UPDATE' in cursor.calls[2][0]
    assert cursor.calls[2][1][2] == 'Q-17'
