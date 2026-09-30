from datetime import datetime, timedelta, timezone


_EXAM_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def exam_schedule_now():
	return datetime.now(_EXAM_TIMEZONE).replace(tzinfo=None)


def save_submitted_answers(cur, email, testid, student_uid, submitted_answers):
	if not isinstance(submitted_answers, dict):
		raise ValueError('Submitted answers must be an object')

	saved_count = 0
	for qid, answer in submitted_answers.items():
		qid_value = str(qid).strip()
		answer_value = str(answer or '').strip()
		if not qid_value:
			continue
		if not answer_value:
			cur.execute(
				'DELETE FROM students WHERE test_id = %s AND qid = %s'
				' AND email = %s AND uid = %s',
				(testid, qid_value, email, student_uid),
			)
			continue
		save_student_answer(
			cur, email, testid, student_uid, qid_value, answer_value
		)
		saved_count += 1
	return saved_count


def save_student_answer(cur, email, testid, student_uid, qid, answer):
	cur.execute(
		'INSERT INTO students(email, test_id, qid, ans, uid) '
		'VALUES(%s, %s, %s, %s, %s) '
		'ON DUPLICATE KEY UPDATE ans = %s',
		(email, testid, qid, answer, student_uid, answer),
	)


def student_safe_question_payload(question_rows):
	question_ids = [str(row['qid']) for row in question_rows]
	questions = {
		str(row['qid']): {
			field: row[field]
			for field in ('q', 'a', 'b', 'c', 'd', 'marks')
		}
		for row in question_rows
	}
	return question_ids, questions
