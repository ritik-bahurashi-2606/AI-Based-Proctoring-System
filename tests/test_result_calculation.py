from app import _score_objective_answers


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