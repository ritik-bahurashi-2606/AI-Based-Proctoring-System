"""Server-side state and audit trail for Secure Exam Mode.

Browser telemetry is treated as a signal, never as proof of an OS-level lock.
Native-client-only checks are deliberately reported as such to the student.
"""

import json
import uuid
from datetime import datetime


DEFAULT_POLICY = {
    "name": "Standard Secure Exam",
    "lockdownLevel": "STANDARD",
    "allowCopy": False,
    "allowPaste": False,
    "allowPrinting": False,
    "allowDownloads": False,
    "allowNewTabs": False,
    "allowExternalWebsites": False,
    "allowMultipleDisplays": False,
    "allowVirtualMachine": False,
    "allowRemoteSession": False,
    "allowScreenCapture": False,
    "allowExternalApplications": False,
    "allowAccessibilityTools": True,
    "requireFullscreen": True,
    "requireNativeClient": False,
    "maxWarnings": 5,
    "criticalAction": "continue",
    "allowedOrigins": [],
}

EVENT_SEVERITY = {
    "SESSION_STARTED": "INFORMATION",
    "SESSION_RESUMED": "INFORMATION",
    "EXAM_SUBMITTED": "INFORMATION",
    "FOCUS_RESTORED": "INFORMATION",
    "NETWORK_RECONNECTED": "INFORMATION",
    "EMERGENCY_EXIT": "INFORMATION",
    "FOCUS_LOST": "WARNING",
    "FULLSCREEN_EXITED": "WARNING",
    "COPY_ATTEMPT": "WARNING",
    "PASTE_ATTEMPT": "WARNING",
    "PRINT_ATTEMPT": "WARNING",
    "URL_BLOCKED": "WARNING",
    "NEW_WINDOW_ATTEMPT": "WARNING",
    "NETWORK_DISCONNECTED": "WARNING",
    "MULTIPLE_DISPLAY_DETECTED": "WARNING",
    "REMOTE_SESSION_DETECTED": "WARNING",
    "VM_DETECTED": "WARNING",
    "PROHIBITED_APP_DETECTED": "WARNING",
    "SECURITY_LOCK": "CRITICAL",
}


class SecureExamService:
    def __init__(self, mysql, logger):
        self.mysql = mysql
        self.logger = logger
        self._tables_ready = False

    def ensure_tables(self):
        if self._tables_ready:
            return
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_security_policies (
                    policy_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    exam_id VARCHAR(100) NOT NULL,
                    professor_uid BIGINT NOT NULL,
                    policy_json JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_exam_security_policy (exam_id, professor_uid)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS secure_exam_sessions (
                    secure_session_id CHAR(36) PRIMARY KEY,
                    exam_id VARCHAR(100) NOT NULL,
                    student_email VARCHAR(100) NOT NULL,
                    student_uid BIGINT NOT NULL,
                    policy_snapshot JSON NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    client_info JSON NULL,
                    readiness_json JSON NULL,
                    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_heartbeat_at TIMESTAMP NULL DEFAULT NULL,
                    ended_at TIMESTAMP NULL DEFAULT NULL,
                    KEY idx_secure_exam_student (exam_id, student_email, student_uid, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS secure_exam_events (
                    event_id CHAR(36) PRIMARY KEY,
                    secure_session_id CHAR(36) NOT NULL,
                    exam_id VARCHAR(100) NOT NULL,
                    student_email VARCHAR(100) NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    severity VARCHAR(16) NOT NULL,
                    source VARCHAR(32) NOT NULL,
                    explanation VARCHAR(500) NOT NULL,
                    action_taken VARCHAR(64) NOT NULL DEFAULT 'recorded',
                    metadata_json JSON NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_secure_events_session (secure_session_id, created_at),
                    KEY idx_secure_events_exam (exam_id, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            self.mysql.connection.commit()
            self._tables_ready = True
        except Exception:
            self.mysql.connection.rollback()
            raise
        finally:
            cur.close()

    @staticmethod
    def normalize_policy(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        policy = dict(DEFAULT_POLICY)
        if isinstance(value, dict):
            for key in policy:
                if key in value:
                    policy[key] = value[key]
        policy["lockdownLevel"] = str(policy["lockdownLevel"]).upper()
        policy["criticalAction"] = str(policy["criticalAction"]).lower()
        policy["maxWarnings"] = max(1, min(int(policy["maxWarnings"] or 5), 20))
        policy["allowedOrigins"] = [str(item) for item in policy["allowedOrigins"] if item]
        return policy

    def policy_for_exam(self, exam_id, professor_uid):
        self.ensure_tables()
        cur = self.mysql.connection.cursor()
        try:
            cur.execute(
                "SELECT policy_json FROM exam_security_policies WHERE exam_id = %s AND professor_uid = %s",
                (exam_id, professor_uid),
            )
            row = cur.fetchone()
            raw = row["policy_json"] if row else None
            if isinstance(raw, str):
                raw = json.loads(raw)
            return self.normalize_policy(raw)
        finally:
            cur.close()

    def save_policy(self, exam_id, professor_uid, policy):
        self.ensure_tables()
        policy = self.normalize_policy(policy)
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO exam_security_policies (exam_id, professor_uid, policy_json)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE policy_json = VALUES(policy_json)
            """, (exam_id, professor_uid, json.dumps(policy)))
            self.mysql.connection.commit()
            return policy
        except Exception:
            self.mysql.connection.rollback()
            raise
        finally:
            cur.close()

    def start_or_resume(self, exam_id, email, uid, policy, client_info, readiness):
        self.ensure_tables()
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("""
                SELECT secure_session_id, status FROM secure_exam_sessions
                WHERE exam_id = %s AND student_email = %s AND student_uid = %s
                  AND status IN ('active', 'paused')
                ORDER BY started_at DESC LIMIT 1
            """, (exam_id, email, uid))
            existing = cur.fetchone()
            if existing:
                session_id = existing["secure_session_id"]
                cur.execute("""
                    UPDATE secure_exam_sessions
                    SET status = 'active', last_heartbeat_at = NOW(), client_info = %s, readiness_json = %s
                    WHERE secure_session_id = %s
                """, (json.dumps(client_info or {}), json.dumps(readiness or {}), session_id))
                resumed = True
            else:
                session_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO secure_exam_sessions
                    (secure_session_id, exam_id, student_email, student_uid, policy_snapshot, client_info, readiness_json, last_heartbeat_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """, (session_id, exam_id, email, uid, json.dumps(policy), json.dumps(client_info or {}), json.dumps(readiness or {})))
                resumed = False
            self.mysql.connection.commit()
        except Exception:
            self.mysql.connection.rollback()
            raise
        finally:
            cur.close()
        self.record_event(session_id, exam_id, email, "SESSION_RESUMED" if resumed else "SESSION_STARTED", "server",
                          "Previous secure session resumed." if resumed else "Secure exam session started.")
        return session_id, resumed

    def session_for_student(self, session_id, exam_id, email, uid):
        self.ensure_tables()
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("""
                SELECT * FROM secure_exam_sessions
                WHERE secure_session_id = %s AND exam_id = %s AND student_email = %s AND student_uid = %s
            """, (session_id, exam_id, email, uid))
            return cur.fetchone()
        finally:
            cur.close()

    def heartbeat(self, session_id):
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("UPDATE secure_exam_sessions SET last_heartbeat_at = NOW() WHERE secure_session_id = %s AND status = 'active'", (session_id,))
            self.mysql.connection.commit()
            return cur.rowcount > 0
        finally:
            cur.close()

    def record_event(self, session_id, exam_id, email, event_type, source, explanation, metadata=None, severity=None):
        self.ensure_tables()
        severity = severity or EVENT_SEVERITY.get(event_type, "INFORMATION")
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO secure_exam_events
                (event_id, secure_session_id, exam_id, student_email, event_type, severity, source, explanation, metadata_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (str(uuid.uuid4()), session_id, exam_id, email, event_type, severity, source,
                  explanation[:500], json.dumps(metadata or {})))
            self.mysql.connection.commit()
        except Exception:
            self.mysql.connection.rollback()
            raise
        finally:
            cur.close()
        return severity

    def warning_count(self, session_id):
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("SELECT COUNT(*) AS count FROM secure_exam_events WHERE secure_session_id = %s AND severity IN ('WARNING', 'CRITICAL')", (session_id,))
            return int((cur.fetchone() or {}).get("count", 0))
        finally:
            cur.close()

    def end_session(self, session_id, status="submitted"):
        cur = self.mysql.connection.cursor()
        try:
            cur.execute("UPDATE secure_exam_sessions SET status = %s, ended_at = NOW() WHERE secure_session_id = %s", (status, session_id))
            self.mysql.connection.commit()
        finally:
            cur.close()
