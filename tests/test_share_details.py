import app as app_module


EXAM = {
    "test_id": "exam-1",
    "subject": "Mathematics",
    "topic": "Algebra",
    "duration": 3600,
    "start": "2025-01-01 10:00:00",
    "end": "2025-01-01 11:00:00",
    "password": "secret",
    "neg_marks": 25,
    "calc": 1,
}


class FakeCursor:
    def __init__(self, exam):
        self.exam = exam
        self.query = None
        self.params = None
        self.queries = []

    def execute(self, query, params):
        self.query = query
        self.params = params
        self.queries.append((query, params))

    def fetchone(self):
        return self.exam

    def fetchall(self):
        if self.query and "SELECT audio_evidence" in self.query:
            return self.exam.get("audio_files", [])
        return [self.exam] if self.exam else []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, exam):
        self.exam = exam
        self.cursors = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        cursor = FakeCursor(self.exam)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _professor_client():
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()
    with client.session_transaction() as professor_session:
        professor_session.update({
            "logged_in": True,
            "user_role": "teacher",
            "email": "professor@example.com",
            "uid": "professor-uid",
        })
    return client


def test_share_details_sends_bcc_recipients_using_database_exam(monkeypatch):
    connection = FakeConnection(EXAM)
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )
    sent_messages = []
    monkeypatch.setattr(app_module.mail, "send", sent_messages.append)
    client = _professor_client()

    response = client.post("/share_details_emails", data={
        "tid": "exam-1",
        "subject": "Tampered subject",
        "password": "tampered password",
        "emailssharelist": " first@example.com,second@example.com, first@example.com ",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Exam details sent to 2 student(s)." in response.data
    assert len(sent_messages) == 1
    assert sent_messages[0].subject == "EXAM DETAILS - SafeExam"
    assert sent_messages[0].bcc == ["first@example.com", "second@example.com"]
    assert sent_messages[0].body.startswith("EXAM DETAILS - SafeExam")
    assert "SUBJECT: Mathematics" in sent_messages[0].body
    assert "secret" in sent_messages[0].body
    assert "Tampered subject" not in sent_messages[0].body
    assert "tampered password" not in sent_messages[0].body
    assert "<table" in sent_messages[0].html
    assert "EXAM DETAILS - SafeExam" in sent_messages[0].html
    assert "<th" in sent_messages[0].html
    assert "<td" in sent_messages[0].html
    assert "Mathematics" in sent_messages[0].html
    assert "DURATION" in sent_messages[0].html
    assert "3600 sec" in sent_messages[0].html
    assert connection.cursors[0].params == ("exam-1", "professor-uid")


def test_share_details_escapes_html_in_exam_values(monkeypatch):
    exam = {**EXAM, "subject": "<script>alert('unsafe')</script>"}
    connection = FakeConnection(exam)
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )
    sent_messages = []
    monkeypatch.setattr(app_module.mail, "send", sent_messages.append)
    client = _professor_client()

    response = client.post("/share_details_emails", data={
        "tid": "exam-1",
        "emailssharelist": "student@example.com",
    })

    assert response.status_code == 302
    assert "&lt;script&gt;" in sent_messages[0].html
    assert "<script>" not in sent_messages[0].html


def test_share_details_rejects_invalid_recipients_without_sending(monkeypatch):
    connection = FakeConnection(EXAM)
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )
    sent_messages = []
    monkeypatch.setattr(app_module.mail, "send", sent_messages.append)
    client = _professor_client()

    response = client.post("/share_details_emails", data={
        "tid": "exam-1",
        "emailssharelist": "valid@example.com,not-an-email",
    })

    assert response.status_code == 302
    assert not sent_messages
    with client.session_transaction() as professor_session:
        assert "valid student email addresses" in professor_session["_flashes"][0][1]


def test_share_details_does_not_send_for_an_exam_owned_by_another_professor(monkeypatch):
    connection = FakeConnection(None)
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )
    sent_messages = []
    monkeypatch.setattr(app_module.mail, "send", sent_messages.append)
    client = _professor_client()

    response = client.post("/share_details_emails", data={
        "tid": "another-professors-exam",
        "emailssharelist": "student@example.com",
    })

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/professor@example.com/disptests")
    assert not sent_messages
    assert connection.cursors[0].params == (
        "another-professors-exam",
        "professor-uid",
    )


def test_share_details_reports_email_delivery_failure(monkeypatch):
    connection = FakeConnection(EXAM)
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )

    def fail_to_send(_message):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(app_module.mail, "send", fail_to_send)
    client = _professor_client()

    response = client.post("/share_details_emails", data={
        "tid": "exam-1",
        "emailssharelist": "student@example.com",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Could not send exam details." in response.data


def _configure_delete_test(monkeypatch, connection):
    monkeypatch.setattr(
        type(app_module.mysql),
        "connection",
        property(lambda _mysql: connection),
    )
    monkeypatch.setattr(app_module.secure_exam, "ensure_tables", lambda: None)
    monkeypatch.setattr(app_module, "_ensure_exam_results_table", lambda: None)


def test_professor_can_delete_completed_exam_and_its_records_and_evidence(
    monkeypatch, tmp_path
):
    audio_filename = "exam_exam-1_uid_1234_clip.webm"
    exam_dir = tmp_path / "proctoring" / "exam-1"
    exam_dir.mkdir(parents=True)
    (exam_dir / "evidence.jpg").write_bytes(b"image")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / audio_filename).write_bytes(b"audio")
    connection = FakeConnection({
        **EXAM,
        "can_delete": 1,
        "audio_files": [{"audio_evidence": audio_filename}],
    })
    _configure_delete_test(monkeypatch, connection)
    monkeypatch.setattr(app_module, "_PROCTORING_EVIDENCE_DIR", str(tmp_path / "proctoring"))
    monkeypatch.setattr(app_module, "_AUDIO_EVIDENCE_DIR", str(audio_dir))
    client = _professor_client()

    response = client.post(
        "/professor@example.com/delete_completed_exam/exam-1",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"permanently deleted" in response.data
    assert connection.committed
    assert not exam_dir.exists()
    assert not (audio_dir / audio_filename).exists()
    executed_sql = "\n".join(query for query, _params in connection.cursors[0].queries)
    for table in (
        "exam_results", "longqa", "practicalqa", "questions", "longtest",
        "practicaltest", "students", "studenttestinfo", "proctoring_log",
        "window_estimation_log", "secure_exam_events", "secure_exam_sessions",
        "exam_security_policies", "teachers",
    ):
        assert f"DELETE FROM {table}" in executed_sql


def test_professor_cannot_delete_an_exam_with_unfinished_attempts(monkeypatch):
    connection = FakeConnection({**EXAM, "can_delete": 0})
    _configure_delete_test(monkeypatch, connection)
    client = _professor_client()

    response = client.post(
        "/professor@example.com/delete_completed_exam/exam-1",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Only completed exams" in response.data
    assert connection.rolled_back
    assert not connection.committed
    executed_sql = "\n".join(query for query, _params in connection.cursors[0].queries)
    assert "DELETE FROM" not in executed_sql


def test_professor_exam_history_shows_delete_for_completed_exams(monkeypatch):
    connection = FakeConnection({**EXAM, "can_delete": 1})
    _configure_delete_test(monkeypatch, connection)
    client = _professor_client()

    response = client.get("/professor@example.com/disptests")

    assert response.status_code == 200
    assert b"Delete" in response.data
    assert b"delete_completed_exam" in response.data
    assert b"<br><br><br>" not in response.data
