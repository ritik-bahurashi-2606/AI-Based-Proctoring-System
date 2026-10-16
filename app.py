from flask import Flask, request, render_template, flash, redirect, url_for,session, logging, send_file, send_from_directory, jsonify, Response, render_template_string
from flask_login import LoginManager, login_user, logout_user, current_user, login_required, UserMixin
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, validators, DateTimeField, BooleanField, IntegerField, DecimalField, HiddenField, SelectField, SubmitField
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from flask_mail import Mail, Message
from functools import wraps
from werkzeug.utils import secure_filename
from coolname import generate_slug
from datetime import timedelta, datetime
from objective import ObjectiveTest
from subjective import SubjectiveTest
from deepface import DeepFace
# pymysql conflict removed - using native mysqlclient (MySQLdb) directly
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
import pandas as pd
import stripe
import operator
import functools
import math, random
import csv
import re
from html import escape
import cv2
import numpy as np
import json
import base64
from wtforms_components import TimeField
# from wtforms.fields.html5 import DateField
from wtforms.fields import DateField
from wtforms.validators import ValidationError, NumberRange
from flask_session import Session
from flask_cors import CORS, cross_origin
import io
import os
import shutil
import sys
import time
import uuid
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from secure_exam import DEFAULT_POLICY, EVENT_SEVERITY, SecureExamService
from proctoring_evidence import delete_evidence_image, save_evidence_image
from exam_workflow import (
	exam_schedule_now,
	exam_window_is_open,
	save_student_answer,
	save_submitted_answers,
	student_safe_question_payload,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from this project directory explicitly.
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'myproctor_secret_key_123')

# Disable CSRF for plain HTML forms (they use request.form directly, not FlaskForm)
# FlaskForms used for file upload still get CSRF via their own meta
app.config['WTF_CSRF_ENABLED'] = False
app.config['WTF_CSRF_SECRET_KEY'] = os.getenv('WTF_CSRF_SECRET_KEY', app.secret_key)

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'ritik')
app.config['MYSQL_PORT'] = int(os.getenv('MYSQL_PORT', 3306))
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'myproctor')
app.config['MYSQL_CURSORCLASS'] = os.getenv('MYSQL_CURSORCLASS', 'DictCursor')  # flask_mysqldb uses this directly

app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', '').strip()
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '').strip()
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '').strip()
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', '').strip()

app.config['SESSION_TYPE'] = os.getenv('SESSION_TYPE', 'filesystem')
app.config['SESSION_FILE_DIR'] = os.getenv(
    'SESSION_FILE_DIR',
    os.path.join(app.root_path, 'flask_session')
)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
session_cookie_samesite = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
if session_cookie_samesite.lower() == 'none' and not app.config['SESSION_COOKIE_SECURE']:
    session_cookie_samesite = 'Lax'
app.config['SESSION_COOKIE_SAMESITE'] = session_cookie_samesite
app.config['SESSION_PERMANENT'] = os.getenv('SESSION_PERMANENT', 'True').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
    seconds=int(os.getenv('PERMANENT_SESSION_LIFETIME', 604800))
)

app.config["TEMPLATES_AUTO_RELOAD"] = os.getenv('TEMPLATES_AUTO_RELOAD', 'True').lower() == 'true'
app.config['DEBUG'] = os.getenv('DEBUG', 'False').lower() == 'true'
app.config['TESTING'] = os.getenv('TESTING', 'False').lower() == 'true'
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 16777216))

stripe_keys = {
    "secret_key": os.getenv('STRIPE_SECRET_KEY', 'dummy'),
    "publishable_key": os.getenv('STRIPE_PUBLISHABLE_KEY', 'dummy'),
}

stripe.api_key = stripe_keys["secret_key"]

mail = Mail(app)

sess = Session()
sess.init_app(app)

cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

mysql = MySQL(app)
secure_exam = SecureExamService(mysql, app.logger)


@app.context_processor
def inject_secure_exam_context():
	return {
		'secure_exam_session_id': session.get('secure_exam_session_id'),
		'secure_exam_policy': session.get('secure_exam_policy', DEFAULT_POLICY),
	}

# Enable MySQL auto-reconnect and set connection options
app.config.setdefault('MYSQL_AUTOCOMMIT', False)

# Initialize global variables used for exam state (Note: sessions should be used instead in production)
duration = 0
marked_ans = "{}"
calc = 0
subject = ""
topic = ""
proctortype = 0
proctortypes = 0
proctortypep = 0

RESULT_PASS_PERCENTAGE = float(os.getenv('RESULT_PASS_PERCENTAGE', '40'))
_exam_results_table_checked = False


def _ensure_exam_results_table():
	global _exam_results_table_checked
	if _exam_results_table_checked:
		return
	cur = mysql.connection.cursor()
	try:
		cur.execute("""
			CREATE TABLE IF NOT EXISTS exam_results (
				result_id BIGINT NOT NULL AUTO_INCREMENT,
				student_id BIGINT NOT NULL,
				student_name VARCHAR(100) NOT NULL,
				student_email VARCHAR(100) NOT NULL,
				exam_id VARCHAR(100) NOT NULL,
				subject VARCHAR(100) NOT NULL,
				topic VARCHAR(100) NOT NULL,
				professor_id BIGINT NOT NULL,
				professor_name VARCHAR(100) NOT NULL,
				total_questions INT NOT NULL DEFAULT 0,
				attempted_questions INT NOT NULL DEFAULT 0,
				correct_answers INT NOT NULL DEFAULT 0,
				wrong_answers INT NOT NULL DEFAULT 0,
				marks DECIMAL(10,2) NOT NULL DEFAULT 0,
				total_marks DECIMAL(10,2) NOT NULL DEFAULT 0,
				percentage DECIMAL(6,2) NOT NULL DEFAULT 0,
				result_status VARCHAR(10) NOT NULL,
				submission_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
				cheating_risk_score INT NOT NULL DEFAULT 0,
				risk_level VARCHAR(25) NOT NULL DEFAULT 'Safe',
				uid BIGINT NOT NULL,
				PRIMARY KEY (result_id),
				UNIQUE KEY uniq_exam_result_student (student_email, exam_id, uid),
				KEY idx_exam_results_professor (professor_id, exam_id),
				KEY idx_exam_results_student (student_id, student_email)
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
		""")
		# Add total_marks column if missing on existing table
		cur.execute("""
			SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
			WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'exam_results' AND COLUMN_NAME = 'total_marks'
		""")
		check_row = cur.fetchone() or {}
		if int(check_row.get('cnt') or 0) == 0:
			cur.execute("ALTER TABLE exam_results ADD COLUMN total_marks DECIMAL(10,2) NOT NULL DEFAULT 0 AFTER marks")

		mysql.connection.commit()
		_exam_results_table_checked = True
		app.logger.info('exam_results table verified (with total_marks column)')
	except Exception as err:
		mysql.connection.rollback()
		app.logger.exception('Failed to verify exam_results table: %s', err)
		raise
	finally:
		cur.close()


def _risk_level(score):
	if score >= 30:
		return 'High Risk'
	if score >= 10:
		return 'Moderate'
	return 'Safe'


def _get_cheating_risk(cur, email, testid):
	_ensure_proctoring_device_column()
	_ensure_proctoring_evidence_schema()
	import proctoring_policy as pp

	cur.execute("""
		SELECT event_data, phone_detection, device_detection, person_status,
		       user_movements_lr, user_movements_updown, user_movements_eyes
		FROM proctoring_log
		WHERE email = %s AND test_id = %s
	""", (email, testid))
	p_rows = cur.fetchall()

	event_counts = pp.count_proctoring_events(p_rows)

	cur.execute("""
		SELECT COUNT(*) AS tab_switches
		FROM window_estimation_log
		WHERE email = %s AND test_id = %s
	""", (email, testid))
	tab = cur.fetchone() or {}
	tab_cnt = int(tab.get('tab_switches') or 0)

	score = pp.calculate_risk_score(event_counts, tab_cnt)
	return score, _risk_level(score)


def _fetch_result_context(cur, email, testid, student_uid):
	student_name_fallback = email
	try:
		if session and 'name' in session:
			student_name_fallback = session['name']
	except Exception:
		pass

	cur.execute("""
		SELECT t.test_id, t.test_type, t.subject, t.topic, t.uid AS professor_id,
		       COALESCE(p.name, t.email) AS professor_name,
		       COALESCE(s.uid, %s) AS student_id,
		       COALESCE(s.name, %s) AS student_name,
		       COALESCE(s.email, %s) AS student_email
		FROM teachers t
		LEFT JOIN users p ON p.uid = t.uid
		LEFT JOIN users s ON s.email = %s AND s.user_type = 'student'
		WHERE t.test_id = %s
		LIMIT 1
	""", (student_uid, student_name_fallback, email, email, testid))
	ctx = cur.fetchone()
	if not ctx:
		raise ValueError(f'Missing exam: {testid}')
	return ctx


def _score_objective_answers(question_rows, answers, negative_percentage):
	marks = 0.0
	correct = 0
	wrong = 0
	attempted = 0
	negative_fraction = float(negative_percentage or 0) / 100.0
	for row in question_rows:
		marked = str(answers.get(str(row.get('qid')).strip()) or '').strip().upper()
		correct_answer = str(row.get('correct') or '').strip().upper()
		if marked in ('', '0', 'NONE'):
			continue
		attempted += 1
		question_marks = float(row.get('marks') or 0)
		if marked == correct_answer:
			correct += 1
			marks += question_marks
		else:
			wrong += 1
			marks -= negative_fraction * question_marks
	return marks, correct, wrong, attempted


def _calculate_result_payload(cur, email, testid, student_uid):
	ctx = _fetch_result_context(cur, email, testid, student_uid)
	test_type = ctx['test_type']
	if test_type == 'objective':
		cur.execute("""
			SELECT COUNT(*) AS total_questions, COALESCE(SUM(marks), 0) AS total_marks
			FROM questions WHERE test_id = %s
		""", (testid,))
		totals = cur.fetchone() or {}
		cur.execute(
			'SELECT qid, ans FROM students WHERE test_id = %s AND email = %s AND uid = %s',
			(testid, email, student_uid),
		)
		answer_rows = cur.fetchall() or []
		if not answer_rows:
			cur.execute(
				'SELECT qid, ans FROM students WHERE test_id = %s AND email = %s AND (uid IS NULL OR uid = 0)',
				(testid, email),
			)
			answer_rows = cur.fetchall() or []
		answers = {str(row.get('qid')).strip(): row.get('ans') for row in answer_rows}
		cur.execute('SELECT qid, ans AS correct, marks FROM questions WHERE test_id = %s', (testid,))
		rows = cur.fetchall() or []
		cur.execute("SELECT neg_marks FROM teachers WHERE test_id = %s LIMIT 1", (testid,))
		neg_row = cur.fetchone() or {}
		neg = float(neg_row.get('neg_marks') or 0)
		marks, correct, wrong, attempted_questions = _score_objective_answers(rows, answers, neg)
		total_questions = int(totals.get('total_questions') or 0)
		total_marks = float(totals.get('total_marks') or 0)
		if total_marks <= 0 and total_questions > 0:
			total_marks = float(total_questions)
	else:
		qa_table = 'longqa' if test_type == 'subjective' else 'practicalqa'
		ans_table = 'longtest' if test_type == 'subjective' else 'practicaltest'
		cur.execute(f"SELECT COUNT(*) AS total_questions, COALESCE(SUM(marks), 0) AS total_marks FROM {qa_table} WHERE test_id = %s", (testid,))
		totals = cur.fetchone() or {}
		cur.execute(f"SELECT COUNT(*) AS attempted_questions, COALESCE(SUM(marks), 0) AS marks FROM {ans_table} WHERE test_id = %s AND email = %s AND (uid = %s OR uid IS NULL OR uid = 0)", (testid, email, student_uid))
		scored = cur.fetchone() or {}
		total_questions = int(totals.get('total_questions') or 0)
		total_marks = float(totals.get('total_marks') or 0)
		if total_marks <= 0 and total_questions > 0:
			total_marks = float(total_questions)
		attempted_questions = int(scored.get('attempted_questions') or 0)
		marks = float(scored.get('marks') or 0)
		correct = 0
		wrong = 0

	percentage = round((marks / total_marks) * 100.0, 2) if total_marks > 0 else 0.0
	risk_score, risk_level = _get_cheating_risk(cur, email, testid)
	return {
		'student_id': int(ctx['student_id'] or student_uid),
		'student_name': ctx['student_name'] or email,
		'student_email': ctx['student_email'] or email,
		'exam_id': testid,
		'subject': ctx['subject'] or '',
		'topic': ctx['topic'] or '',
		'professor_id': int(ctx['professor_id']),
		'professor_name': ctx['professor_name'] or '',
		'total_questions': total_questions,
		'attempted_questions': attempted_questions,
		'correct_answers': correct,
		'wrong_answers': wrong,
		'marks': round(marks, 2),
		'total_marks': round(total_marks, 2),
		'percentage': percentage,
		'result_status': 'Pass' if percentage >= RESULT_PASS_PERCENTAGE else 'Fail',
		'cheating_risk_score': risk_score,
		'risk_level': risk_level,
		'uid': student_uid,
	}



def _json_safe_rows(rows):
	clean = []
	for row in rows or []:
		item = {}
		for key, value in row.items():
			if isinstance(value, datetime):
				item[key] = value.strftime('%Y-%m-%d %H:%M:%S')
			elif hasattr(value, 'isoformat') and value.__class__.__name__ in ('date', 'time'):
				item[key] = value.isoformat()
			elif value.__class__.__name__ == 'Decimal':
				item[key] = float(value)
			else:
				item[key] = value
		clean.append(item)
	return clean


def save_exam_result(email, testid, student_uid):
	_ensure_exam_results_table()
	cur = mysql.connection.cursor()
	try:
		payload = _calculate_result_payload(cur, email, testid, student_uid)
		cur.execute(
			'SELECT result_id FROM exam_results WHERE student_email = %s AND exam_id = %s AND uid = %s ORDER BY result_id LIMIT 1',
			(payload['student_email'], payload['exam_id'], payload['uid']),
		)
		existing = cur.fetchone()
		if existing:
			cur.execute("""
				UPDATE exam_results SET
					student_id = %(student_id)s, student_name = %(student_name)s,
					subject = %(subject)s, topic = %(topic)s,
					professor_id = %(professor_id)s, professor_name = %(professor_name)s,
					total_questions = %(total_questions)s, attempted_questions = %(attempted_questions)s,
					correct_answers = %(correct_answers)s, wrong_answers = %(wrong_answers)s,
					marks = %(marks)s, total_marks = %(total_marks)s, percentage = %(percentage)s,
					result_status = %(result_status)s, submission_time = NOW(),
					cheating_risk_score = %(cheating_risk_score)s, risk_level = %(risk_level)s
				WHERE result_id = %(result_id)s
			""", {**payload, 'result_id': existing['result_id']})
		else:
			cur.execute("""
				INSERT INTO exam_results (
					student_id, student_name, student_email, exam_id, subject, topic,
					professor_id, professor_name, total_questions, attempted_questions,
					correct_answers, wrong_answers, marks, total_marks, percentage, result_status,
					submission_time, cheating_risk_score, risk_level, uid
				) VALUES (
					%(student_id)s, %(student_name)s, %(student_email)s, %(exam_id)s, %(subject)s, %(topic)s,
					%(professor_id)s, %(professor_name)s, %(total_questions)s, %(attempted_questions)s,
					%(correct_answers)s, %(wrong_answers)s, %(marks)s, %(total_marks)s, %(percentage)s, %(result_status)s,
					NOW(), %(cheating_risk_score)s, %(risk_level)s, %(uid)s
				)
			""", payload)
		mysql.connection.commit()
		app.logger.info(
			'Result saved successfully: exam_id=%s, student_id=%s, email=%s, attempted=%s/%s, correct=%s, wrong=%s, marks=%s, total_marks=%s, percentage=%s%%, risk_score=%s, risk_level=%s',
			testid, payload['student_id'], email, payload['attempted_questions'], payload['total_questions'],
			payload['correct_answers'], payload['wrong_answers'], payload['marks'], payload['total_marks'],
			payload['percentage'], payload['cheating_risk_score'], payload['risk_level']
		)
		return payload
	except Exception as err:
		mysql.connection.rollback()
		app.logger.exception('Result save failed for student=%s exam=%s: %s', email, testid, err)
		raise
	finally:
		cur.close()



# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

class User(UserMixin):
    def __init__(self, uid, name, email, user_type):
        self.id = uid  # uid is the primary key
        self.name = name
        self.email = email
        self.user_type = user_type

    @staticmethod
    def get(user_id):
        try:
            cur = mysql.connection.cursor()
            cur.execute('SELECT uid, name, email, user_type FROM users WHERE uid = %s', [user_id])
            row = cur.fetchone()
            cur.close()
            if row:
                return User(row['uid'], row['name'], row['email'], row['user_type'])
        except Exception as e:
            app.logger.error(f'User.get error: {e}')
        return None

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.get(user_id)
    except Exception:
        return None

sender = app.config['MAIL_DEFAULT_SENDER']

YOUR_DOMAIN = os.getenv('YOUR_DOMAIN', 'http://localhost:5000')

MAIL_PLACEHOLDERS = {
    '',
    'smtp.stackmail.com',
    'smtp.example.com',
    'care@youremail.com',
    'youremail@abc.com',
    'your-email@gmail.com',
    'password',
    'your-app-password',
}

IMAGE_PLACEHOLDERS = {
    '',
    'no_camera',
}


def is_mail_configured():
    required_values = (
        app.config.get('MAIL_SERVER', '').strip(),
        app.config.get('MAIL_USERNAME', '').strip(),
        app.config.get('MAIL_PASSWORD', '').strip(),
        app.config.get('MAIL_DEFAULT_SENDER', '').strip(),
    )
    return all(value and value not in MAIL_PLACEHOLDERS for value in required_values)


# ── Face verification ─────────────────────────────────────────────────────────
# Import the full face_verifier module which provides score-based matching,
# liveness detection, and quality assessment.
try:
    import face_verifier as _fv
    FACE_VERIFIER_AVAILABLE = True
except Exception as _fv_import_err:
    app.logger.warning('face_verifier module not available: %s', _fv_import_err)
    FACE_VERIFIER_AVAILABLE = False
    _fv = None


def clear_registration_session():
    for key in (
        'tempName',
        'tempEmail',
        'tempPassword',
        'tempUT',
        'tempImage',
        'tempOTP',
        'otp_delivery_mode',
    ):
        session.pop(key, None)


def registration_store_dir():
    path = os.path.join(app.root_path, 'registration_tokens')
    os.makedirs(path, exist_ok=True)
    return path


def save_pending_registration(name, email, password, user_type, imgdata, otp, otp_delivery_mode):
    registration_id = uuid.uuid4().hex
    payload = {
        'name': name,
        'enqueued_at': time.time(),
        'email': email,
        'password': password,
        'user_type': user_type,
        'image_hidden': imgdata,
        'otp': otp,
        'otp_delivery_mode': otp_delivery_mode,
        'created_at': time.time(),
    }
    token_path = os.path.join(registration_store_dir(), f'{registration_id}.json')
    with open(token_path, 'w', encoding='utf-8') as registration_file:
        json.dump(payload, registration_file)
    return registration_id


def load_pending_registration(registration_id, max_age=1800):
    if not registration_id:
        return None, 'missing'
    token_path = os.path.join(registration_store_dir(), f'{registration_id}.json')
    if not os.path.exists(token_path):
        return None, 'missing'
    with open(token_path, 'r', encoding='utf-8') as registration_file:
        payload = json.load(registration_file)
    if time.time() - payload.get('created_at', 0) > max_age:
        try:
            os.remove(token_path)
        except OSError:
            pass
        return None, 'expired'
    return payload, None


def delete_pending_registration(registration_id):
    if not registration_id:
        return
    token_path = os.path.join(registration_store_dir(), f'{registration_id}.json')
    if os.path.exists(token_path):
        try:
            os.remove(token_path)
        except OSError:
            pass


def render_verify_email(error=None, registration_id=None, dev_otp=None):
    return render_template(
        'verifyEmail.html',
        error=error,
        dev_otp=dev_otp,
        registration_id=registration_id,
    )

@app.before_request
def make_session_permanent():
	session.permanent = True
	request.environ['request_started_at'] = time.perf_counter()


@app.after_request
def report_exam_request_latency(response):
	if request.path.startswith(('/give-test/', '/video_feed', '/proctoring_status/')):
		started_at = request.environ.get('request_started_at')
		if started_at is not None:
			elapsed_ms = (time.perf_counter() - started_at) * 1000
			timing = f'app;dur={elapsed_ms:.2f}'
			cv_ms = request.environ.get('proctor_cv_duration_ms')
			queue_ms = request.environ.get('proctor_queue_wait_ms')
			if cv_ms is not None:
				timing += f', cv;dur={cv_ms:.2f}'
			if queue_ms is not None:
				timing += f', queue;dur={queue_ms:.2f}'
			response.headers['Server-Timing'] = timing
			app.logger.info(
				'Exam request latency: method=%s path=%s status=%s elapsed_ms=%.2f%s%s',
				request.method, request.path, response.status_code, elapsed_ms,
				f' cv_ms={cv_ms:.2f}' if cv_ms is not None else '',
				f' queue_wait_ms={queue_ms:.2f}' if queue_ms is not None else '',
			)
	return response

def user_role_professor(f):
	@wraps(f)
	def wrap(*args, **kwargs):
		if 'logged_in' in session:
			if session['user_role']=="teacher":
				return f(*args, **kwargs)
			else:
				flash('You dont have privilege to access this page!','danger')
				return render_template("404.html") 
		else:
			flash('Unauthorized, Please login!','danger')
			return redirect(url_for('login'))
	return wrap

def user_role_student(f):
	@wraps(f)
	def wrap(*args, **kwargs):
		if 'logged_in' in session:
			if session['user_role']=="student":
				return f(*args, **kwargs)
			else:
				flash('You dont have privilege to access this page!','danger')
				return render_template("404.html") 
		else:
			flash('Unauthorized, Please login!','danger')
			return redirect(url_for('login'))
	return wrap

# Aliases used by several routes
professor_required = user_role_professor
student_required = user_role_student

@app.route("/config")
@user_role_professor
def get_publishable_key():
    stripe_config = {"publicKey": stripe_keys["publishable_key"]}
    return jsonify(stripe_config)

@app.route('/professor_dashboard')
@user_role_professor
def professor_dashboard():
    return redirect(url_for('professor_index'))

@app.route('/student_dashboard')
@user_role_student
def student_dashboard():
    return redirect(url_for('student_index'))



# ── Per-user/test cooldown tracking (in-memory, resets on server restart) ──────
# Key: (uid, test_id, event_type)  →  last_logged_timestamp
_proctor_cooldowns = {}
_PROCTOR_COOLDOWN_SECS = float(os.getenv('PROCTOR_COOLDOWN_SECS', '10'))
_AUDIO_EVIDENCE_DIR = os.path.join(BASE_DIR, 'audio_evidence')
os.makedirs(_AUDIO_EVIDENCE_DIR, exist_ok=True)
_PROCTORING_EVIDENCE_DIR = os.path.abspath(os.getenv(
	'PROCTORING_EVIDENCE_DIR',
	os.path.join(BASE_DIR, 'proctoring_evidence'),
))
_proctoring_evidence_schema_checked = False


def _ensure_proctoring_evidence_schema():
	global _proctoring_evidence_schema_checked
	if _proctoring_evidence_schema_checked:
		return
	columns = {
		'evidence_file': 'varchar(512) DEFAULT NULL',
		'evidence_status': "varchar(20) NOT NULL DEFAULT 'not_required'",
		'event_data': 'longtext DEFAULT NULL',
		'detection_confidence': 'decimal(5,4) DEFAULT NULL',
		'review_status': "varchar(20) NOT NULL DEFAULT 'unreviewed'",
	}
	cur = mysql.connection.cursor()
	try:
		for column, definition in columns.items():
			cur.execute(
				'SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.COLUMNS '
				'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s',
				('proctoring_log', column),
			)
			if int((cur.fetchone() or {}).get('cnt', 0)) == 0:
				cur.execute(
					f'ALTER TABLE proctoring_log ADD COLUMN {column} {definition}'
				)
		mysql.connection.commit()
		_proctoring_evidence_schema_checked = True
	except Exception:
		mysql.connection.rollback()
		app.logger.exception('Could not ensure proctoring evidence schema')
		raise
	finally:
		cur.close()


def _ensure_proctoring_audio_column():
	"""Add the optional audio evidence column when an older DB is in use."""
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			"SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.COLUMNS "
			"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proctoring_log' "
			"AND COLUMN_NAME = 'audio_evidence'"
		)
		row = cur.fetchone() or {}
		if int(row.get('cnt', 0)) == 0:
			cur.execute("ALTER TABLE proctoring_log ADD COLUMN audio_evidence varchar(255) DEFAULT NULL")
			mysql.connection.commit()
	except Exception as err:
		app.logger.exception('Could not verify/create proctoring_log.audio_evidence')
		try:
			mysql.connection.rollback()
		except Exception:
			pass
		raise
	finally:
		cur.close()


_proctoring_device_schema_checked = False


def _ensure_proctoring_device_column():
	global _proctoring_device_schema_checked
	if _proctoring_device_schema_checked:
		return
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			"SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.COLUMNS "
			"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proctoring_log' "
			"AND COLUMN_NAME = 'device_detection'"
		)
		row = cur.fetchone() or {}
		if int(row.get('cnt', 0)) == 0:
			cur.execute(
				'ALTER TABLE proctoring_log ADD COLUMN '
				'device_detection tinyint(2) NOT NULL DEFAULT 0 AFTER phone_detection'
			)
		mysql.connection.commit()
		_proctoring_device_schema_checked = True
	except Exception:
		mysql.connection.rollback()
		app.logger.exception('Could not ensure proctoring_log.device_detection')
		raise
	finally:
		cur.close()


@app.route('/audio_evidence/<path:filename>')
@user_role_professor
def audio_evidence(filename):
	safe_filename = secure_filename(filename)
	if not safe_filename or safe_filename != filename:
		return jsonify({'status': 'error', 'message': 'Evidence not found.'}), 404
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			'SELECT 1 FROM proctoring_log pl '
			'JOIN teachers t ON t.test_id = pl.test_id '
			'WHERE pl.audio_evidence = %s AND t.uid = %s LIMIT 1',
			(safe_filename, session['uid']),
		)
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Evidence not found.'}), 404
	finally:
		cur.close()
	mimetype_by_extension = {
		'.mp4': 'audio/mp4',
		'.ogg': 'audio/ogg',
		'.webm': 'audio/webm',
	}
	_, extension = os.path.splitext(safe_filename)
	return send_from_directory(
		_AUDIO_EVIDENCE_DIR,
		safe_filename,
		as_attachment=False,
		mimetype=mimetype_by_extension.get(extension.lower(), 'application/octet-stream'),
	)


@app.route('/proctoring_evidence/<testid>/<filename>')
@user_role_professor
def proctoring_evidence(testid, filename):
	exam_directory = secure_filename(testid)
	safe_filename = secure_filename(filename)
	if not exam_directory or safe_filename != filename:
		return jsonify({'status': 'error', 'message': 'Evidence not found.'}), 404

	relative_path = f'{exam_directory}/{safe_filename}'
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			'SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1',
			(testid, session['uid']),
		)
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Evidence not found.'}), 404
		cur.execute(
			'SELECT 1 FROM proctoring_log '
			'WHERE test_id = %s AND evidence_file = %s LIMIT 1',
			(testid, relative_path),
		)
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Evidence not found.'}), 404
	finally:
		cur.close()

	response = send_from_directory(
		_PROCTORING_EVIDENCE_DIR,
		relative_path,
		mimetype='image/jpeg',
		as_attachment=False,
		max_age=0,
	)
	response.headers['Cache-Control'] = 'private, no-store'
	return response


def _is_event_allowed(uid, test_id, event_type, cooldown=None):
	"""Return True if enough time has passed since the last log for this event."""
	cooldown = cooldown or _PROCTOR_COOLDOWN_SECS
	key = (uid, test_id, event_type)
	now = time.time()
	if now - _proctor_cooldowns.get(key, 0) >= cooldown:
		_proctor_cooldowns[key] = now
		return True
	return False


def _is_normal_behavior(mob_status, person_status, user_move1, user_move2,
                        eye_movements, voice_db_val):
	"""Return True when nothing suspicious is happening at all."""
	try:
		vdb = float(voice_db_val)
	except (TypeError, ValueError):
		vdb = 0.0
	phone_ok    = (mob_status == 0)
	person_ok   = (person_status == 1)       # exactly one person
	head_ok     = (user_move1 == 0 and user_move2 == 0)
	gaze_ok     = (eye_movements in (0, 2))  # 0=not detected / 2=center
	audio_ok    = (vdb < float(os.getenv('PROCTOR_AUDIO_THRESHOLD', '18')))
	return phone_ok and person_ok and head_ok and gaze_ok and audio_ok


_proctoring_job_schema_checked = False


def _ensure_proctoring_job_id_column():
	global _proctoring_job_schema_checked
	if _proctoring_job_schema_checked:
		return
	cur = mysql.connection.cursor()
	try:
		cur.execute("SHOW COLUMNS FROM proctoring_log LIKE 'proctoring_job_id'")
		if not cur.fetchone():
			cur.execute(
				'ALTER TABLE proctoring_log ADD COLUMN proctoring_job_id varchar(36) DEFAULT NULL'
			)
		cur.execute(
			"SHOW INDEX FROM proctoring_log WHERE Key_name = 'uniq_proctoring_job_id'"
		)
		if not cur.fetchone():
			cur.execute(
				'ALTER TABLE proctoring_log ADD UNIQUE KEY uniq_proctoring_job_id (proctoring_job_id)'
			)
		mysql.connection.commit()
		_proctoring_job_schema_checked = True
	except Exception:
		mysql.connection.rollback()
		app.logger.exception('Could not ensure idempotent proctoring log schema')
		raise
	finally:
		cur.close()


def _save_event_snapshot(img_data, testid, uid, email, name, event_type):
	"""Persist a webcam frame alongside a discrete proctoring event."""
	if not img_data:
		return False

	_ensure_proctoring_device_column()
	_ensure_proctoring_evidence_schema()
	evidence_path = None
	image_for_db = img_data
	cur = None
	try:
		try:
			evidence_path = save_evidence_image(
				img_data,
				uid,
				testid,
				[event_type],
				_PROCTORING_EVIDENCE_DIR,
			)
		except OSError:
			app.logger.exception(
				'Could not save event screenshot: uid=%s test=%s event=%s',
				uid, testid, event_type,
			)
		except ValueError:
			app.logger.exception(
				'Rejected invalid event screenshot: uid=%s test=%s event=%s',
				uid, testid, event_type,
			)
			image_for_db = ''

		event_data = json.dumps({
			'events': [{
				'event_type': event_type,
				'message': f'Proctoring event: {event_type.replace("_", " ")}.',
				'confidence': 1.0,
				'risk_score': 0,
			}],
			'observed_at': datetime.now().astimezone().isoformat(),
		})
		cur = mysql.connection.cursor()
		cur.execute(
			'INSERT INTO proctoring_log '
			'(email, name, test_id, voice_db, img_log, user_movements_updown, '
			'user_movements_lr, user_movements_eyes, phone_detection, device_detection, '
			'person_status, uid, evidence_file, evidence_status, event_data, '
			'detection_confidence, review_status) '
			'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
			(email, name, testid, 0, image_for_db, 0, 0, 2, 0, 0, 1, uid,
			 evidence_path, 'saved' if image_for_db else 'failed',
			 event_data, 1.0, 'unreviewed'),
		)
		mysql.connection.commit()
		return bool(image_for_db)
	except Exception:
		try:
			mysql.connection.rollback()
		except Exception:
			app.logger.exception('Event screenshot transaction rollback failed')
		if evidence_path:
			try:
				delete_evidence_image(evidence_path, _PROCTORING_EVIDENCE_DIR)
			except OSError:
				app.logger.exception(
					'Could not remove unlinked event screenshot: uid=%s test=%s event=%s',
					uid, testid, event_type,
				)
		app.logger.exception(
			'Could not store event screenshot log: uid=%s test=%s event=%s',
			uid, testid, event_type,
		)
		return False
	finally:
		if cur is not None:
			cur.close()


def _process_proctoring_frame(img_data, testid, voice_db, uid, email, name, job_id=None):
	cv_started_at = time.perf_counter()
	if BASE_DIR not in sys.path:
		sys.path.insert(0, BASE_DIR)
	import camera
	proctor_data = camera.get_frame(img_data)
	cv_duration_ms = (time.perf_counter() - cv_started_at) * 1000
	_ensure_proctoring_device_column()

	try:
		vdb_val = float(voice_db)
	except (ValueError, TypeError):
		vdb_val = 0.0

	import proctoring_policy as pp
	user_key = f"{uid}_{testid}"
	policy = pp.evaluate_proctoring_event(user_key, proctor_data, vdb_val, img_data)
	warnings = policy['warnings']
	logged_events = policy['events']
	audio_suspicious = policy['audio_suspicious']
	should_log = policy['should_log']

	logged = False
	log_pid = None
	evidence_status = 'not_required'
	logging_status = 'not_required'
	evidence_path = None
	database_committed = False
	if should_log and logged_events:
		cur = None
		try:
			_ensure_proctoring_evidence_schema()
			event_types = sorted({event['event_type'] for event in logged_events})
			detection_confidence = max(
				float(event.get('confidence', 0.0) or 0.0) for event in logged_events
			)
			event_data = json.dumps({
				'events': logged_events,
				'observed_at': datetime.now().astimezone().isoformat(),
				'person_count': proctor_data.get('person_count'),
				'person_confidence': proctor_data.get('person_confidence'),
				'head_yaw': proctor_data.get('head_yaw'),
				'head_pitch': proctor_data.get('head_pitch'),
				'head_roll': proctor_data.get('head_roll'),
				'device_names': proctor_data.get('device_names', []),
			})
			try:
				evidence_path = save_evidence_image(
					proctor_data['jpg_as_text'],
					uid,
					testid,
					event_types,
					_PROCTORING_EVIDENCE_DIR,
				)
				evidence_status = 'saved_pending_database'
			except (OSError, ValueError):
				evidence_status = 'failed'
				app.logger.exception(
					'Could not save proctoring evidence: uid=%s test=%s events=%s',
					uid, testid, ','.join(event_types),
				)

			cur = mysql.connection.cursor()
			if job_id:
				_ensure_proctoring_job_id_column()
				cur.execute(
					'INSERT INTO proctoring_log '
					'(email, name, test_id, voice_db, img_log, user_movements_updown, '
					'user_movements_lr, user_movements_eyes, phone_detection, device_detection, person_status, '
					'uid, proctoring_job_id, evidence_file, evidence_status, event_data, detection_confidence, review_status) '
					'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
					'ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)',
					(email, name, testid, vdb_val, proctor_data['jpg_as_text'],
					 proctor_data['user_move1'], proctor_data['user_move2'],
					 proctor_data['eye_movements'], proctor_data['mob_status'],
					 proctor_data['device_status'], proctor_data['person_status'], uid, job_id,
					 evidence_path, 'saved' if evidence_path else 'failed',
					 event_data, detection_confidence, 'unreviewed'),
				)
			else:
				cur.execute(
					'INSERT INTO proctoring_log '
					'(email, name, test_id, voice_db, img_log, user_movements_updown, '
					'user_movements_lr, user_movements_eyes, phone_detection, device_detection, person_status, '
					'uid, evidence_file, evidence_status, event_data, detection_confidence, review_status) '
					'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
					(email, name, testid, vdb_val, proctor_data['jpg_as_text'],
					 proctor_data['user_move1'], proctor_data['user_move2'],
					 proctor_data['eye_movements'], proctor_data['mob_status'],
					 proctor_data['device_status'], proctor_data['person_status'], uid,
					 evidence_path, 'saved' if evidence_path else 'failed',
					 event_data, detection_confidence, 'unreviewed'),
				)
			mysql.connection.commit()
			database_committed = True
			logged = True
			logging_status = 'saved'
			pp.confirm_events_saved(user_key, logged_events)
			log_pid = cur.lastrowid
			if job_id and log_pid:
				cur.execute(
					'SELECT evidence_file, evidence_status FROM proctoring_log WHERE id = %s',
					(log_pid,),
				)
				stored_row = cur.fetchone() or {}
				stored_evidence_path = stored_row.get('evidence_file')
				if stored_evidence_path != evidence_path and evidence_path:
					try:
						delete_evidence_image(evidence_path, _PROCTORING_EVIDENCE_DIR)
					except OSError:
						app.logger.exception(
							'Could not remove duplicate proctoring evidence: uid=%s test=%s',
							uid, testid,
						)
				evidence_path = stored_evidence_path
				evidence_status = (
					'saved'
					if evidence_path and os.path.isfile(
						os.path.join(_PROCTORING_EVIDENCE_DIR, *evidence_path.split('/'))
					)
					else 'failed'
				)
			elif logged and evidence_path:
				evidence_status = 'saved'
			elif evidence_path:
				delete_evidence_image(evidence_path, _PROCTORING_EVIDENCE_DIR)
				evidence_path = None
			app.logger.info(
				'Proctoring log: uid=%s test=%s events=%s yaw=%.1f pitch=%.1f eyes=%d evidence=%s',
				uid, testid, ','.join(event_types),
				proctor_data.get('head_yaw', 0),
				proctor_data.get('head_pitch', 0),
				proctor_data['eye_movements'],
				evidence_status,
			)
		except Exception:
			if database_committed:
				app.logger.exception(
					'Proctoring log post-commit processing failed: uid=%s test=%s pid=%s',
					uid, testid, log_pid,
				)
				if logged:
					logging_status = 'saved'
					if evidence_path and evidence_status == 'saved_pending_database':
						evidence_status = 'failed' if job_id else 'saved'
			else:
				app.logger.exception('proctoring_log insert failed: uid=%s test=%s', uid, testid)
				pp.reject_events_save(user_key, logged_events)
				try:
					mysql.connection.rollback()
				except Exception:
					app.logger.exception('Proctoring log transaction rollback failed')
				if evidence_path:
					try:
						delete_evidence_image(evidence_path, _PROCTORING_EVIDENCE_DIR)
					except OSError:
						app.logger.exception(
							'Could not remove uncommitted evidence: uid=%s test=%s', uid, testid
						)
					evidence_path = None
				logging_status = 'failed'
				evidence_status = 'failed'
		finally:
			if cur is not None:
				cur.close()

	return {
		'status': 'success',
		'logged': logged,
		'pid': log_pid,
		'logging_status': logging_status,
		'evidence_status': evidence_status,
		'evidence_message': (
			'An event was detected, but its evidence or log could not be saved. '
			'Please notify your instructor.'
			if should_log and (logging_status != 'saved' or evidence_status != 'saved')
			else None
		),
		'events': logged_events,
		'mob_status': proctor_data['mob_status'],
		'device_status': proctor_data['device_status'],
		'device_names': proctor_data['device_names'],
		'person_status': proctor_data['person_status'],
		'user_move_updown': proctor_data['user_move1'],
		'user_move_lr': proctor_data['user_move2'],
		'eye_movements': proctor_data['eye_movements'],
		'head_yaw': proctor_data.get('head_yaw', 0),
		'head_pitch': proctor_data.get('head_pitch', 0),
		'head_confidence': proctor_data.get('head_confidence', 0),
		'gaze_confidence': proctor_data.get('gaze_confidence', 0),
		'audio_suspicious': audio_suspicious,
		'warnings': warnings,
		'cv_duration_ms': cv_duration_ms,
	}


class ProctoringQueueFull(Exception):
	pass


_proctoring_redis_client = None
_proctoring_celery_client = None
_PROCTORING_RESERVATION_KEY = 'proctoring:outstanding'


def _get_proctoring_redis():
	global _proctoring_redis_client
	if _proctoring_redis_client is None:
		import redis
		_proctoring_redis_client = redis.Redis.from_url(
			os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0'),
			socket_connect_timeout=2,
			socket_timeout=2,
		)
	return _proctoring_redis_client


def _get_proctoring_celery():
	global _proctoring_celery_client
	if _proctoring_celery_client is None:
		from celery import Celery
		broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
		_proctoring_celery_client = Celery(
			'myproctor_web',
			broker=broker_url,
			backend=broker_url,
		)
	return _proctoring_celery_client


def _release_proctoring_reservation(job_id):
	try:
		_get_proctoring_redis().zrem(_PROCTORING_RESERVATION_KEY, job_id)
	except Exception:
		app.logger.exception('Could not release proctoring queue reservation: job=%s', job_id)


def _enqueue_proctoring_frame(payload):
	redis_client = _get_proctoring_redis()
	redis_client.ping()
	frame_id = payload.get('frame_id')
	if frame_id:
		try:
			frame_id = str(uuid.UUID(str(frame_id)))
		except (TypeError, ValueError) as err:
			raise ValueError('Invalid proctoring frame identifier') from err
		job_id = str(uuid.uuid5(
			uuid.NAMESPACE_URL,
			f"{payload['uid']}:{payload['testid']}:{frame_id}",
		))
	else:
		job_id = str(uuid.uuid4())
	now = time.time()
	lease_seconds = int(os.getenv('PROCTORING_RESERVATION_LEASE_SECONDS', '1800'))
	max_pending = int(os.getenv('PROCTORING_MAX_PENDING', '120'))
	owner_key = f'proctoring:owner:{job_id}'
	expected_owner = f"{payload['uid']}:{payload['testid']}"
	reserve_capacity = redis_client.register_script("""
		local owner = redis.call('GET', KEYS[2])
		if owner then
			if owner == ARGV[6] then return 2 end
			return -1
		end
		redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - ARGV[2])
		if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
			return 0
		end
		redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
		redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]) * 2)
		redis.call('SET', KEYS[2], ARGV[6], 'EX', tonumber(ARGV[5]))
		return 1
	""")
	reserved = reserve_capacity(
		keys=[_PROCTORING_RESERVATION_KEY, owner_key],
		args=[now, lease_seconds, max_pending, job_id, 86400, expected_owner],
	)
	if reserved == 0:
		raise ProctoringQueueFull()
	if reserved == 2:
		return job_id
	if reserved < 0:
		raise ValueError('Proctoring frame identifier is already in use')

	try:
		worker_shards = max(1, int(os.getenv('PROCTORING_WORKER_SHARDS', '1')))
		shard = int.from_bytes(
			hashlib.sha256(f"{payload['uid']}:{payload['testid']}".encode()).digest()[:4],
			'big',
		) % worker_shards
		celery_client = _get_proctoring_celery()
		celery_client.AsyncResult(job_id).forget()
		celery_client.send_task(
			'proctoring.process_frame',
			args=[payload],
			task_id=job_id,
			queue=f'proctoring-{shard}',
		)
		app.logger.info(
			'Proctoring job queued: job=%s uid=%s test=%s shard=%s outstanding=%s',
			job_id, payload['uid'], payload['testid'],
			shard,
			redis_client.zcard(_PROCTORING_RESERVATION_KEY),
		)
	except Exception:
		redis_client.delete(owner_key)
		redis_client.zrem(_PROCTORING_RESERVATION_KEY, job_id)
		raise
	return job_id


@app.route('/video_feed', methods=['GET', 'POST'])
@student_required
def video_feed():
	if request.method != 'POST':
		return jsonify({'status': 'error', 'message': 'POST required'}), 405
	try:
		img_data = request.form['data[imgData]']
		testid = request.form['data[testid]']
		voice_db = request.form['data[voice_db]']
	except KeyError as ke:
		return jsonify({'status': 'error', 'message': f'Missing field: {ke}'}), 400

	uid = session.get('uid')
	email = session.get('email')
	name = session.get('name')
	if not uid or not email or not name:
		return jsonify({'status': 'error', 'message': 'Student session is incomplete'}), 401

	payload = {
		'img_data': img_data,
		'frame_id': request.form.get('data[snapshot_id]', ''),
		'testid': testid,
		'voice_db': voice_db,
		'uid': uid,
		'email': email,
		'name': name,
		'enqueued_at': time.time(),
	}
	if os.getenv('PROCTORING_ASYNC', 'false').lower() in {'1', 'true', 'yes', 'on'}:
		try:
			job_id = _enqueue_proctoring_frame(payload)
		except ProctoringQueueFull:
			return jsonify({
				'status': 'error',
				'message': 'Proctoring is busy; the captured frame must be retried.',
			}), 429, {'Retry-After': '1'}
		except Exception:
			app.logger.exception('Could not queue proctoring frame: uid=%s test=%s', uid, testid)
			return jsonify({
				'status': 'error',
				'message': 'Proctoring is temporarily unavailable; the captured frame must be retried.',
			}), 503, {'Retry-After': '2'}
		return jsonify({'status': 'queued', 'job_id': job_id}), 202

	try:
		result = _process_proctoring_frame(img_data, testid, voice_db, uid, email, name)
		request.environ['proctor_cv_duration_ms'] = result.pop('cv_duration_ms')
		return jsonify(result)
	except Exception:
		app.logger.exception('Synchronous proctoring failed: uid=%s test=%s', uid, testid)
		return jsonify({'status': 'error', 'message': 'Camera processing failed.'}), 500


@app.route('/proctoring_status/<job_id>', methods=['GET'])
@student_required
def proctoring_status(job_id):
	if os.getenv('PROCTORING_ASYNC', 'false').lower() not in {'1', 'true', 'yes', 'on'}:
		return jsonify({'status': 'error', 'message': 'Asynchronous proctoring is disabled.'}), 404
	try:
		redis_client = _get_proctoring_redis()
		owner = redis_client.get(f'proctoring:owner:{job_id}')
		expected_owner = f"{session.get('uid')}:{request.args.get('testid', '')}"
		if not owner or owner.decode('utf-8') != expected_owner:
			return jsonify({'status': 'error', 'message': 'Proctoring job not found.'}), 404

		job = _get_proctoring_celery().AsyncResult(job_id)
		if job.state in {'PENDING', 'STARTED', 'RETRY'}:
			return jsonify({'status': 'pending'}), 202, {'Retry-After': '1'}
		if job.state == 'SUCCESS':
			result = job.result
			if result.get('uid') != session.get('uid') or result.get('testid') != request.args.get('testid'):
				return jsonify({'status': 'error', 'message': 'Proctoring job not found.'}), 404
			request.environ['proctor_cv_duration_ms'] = result.get('cv_duration_ms')
			request.environ['proctor_queue_wait_ms'] = result.get('queue_wait_ms')
			result.pop('uid', None)
			result.pop('testid', None)
			return jsonify(result)
		redis_client.delete(f'proctoring:owner:{job_id}')
		app.logger.error('Proctoring worker failed: job=%s state=%s', job_id, job.state)
		return jsonify({
			'status': 'error',
			'message': 'Proctoring analysis failed. Please keep your camera enabled and contact your instructor.',
		}), 500
	except Exception:
		app.logger.exception('Could not read proctoring result: job=%s', job_id)
		return jsonify({
			'status': 'error',
			'message': 'Proctoring result is temporarily unavailable. Please retry.',
		}), 503, {'Retry-After': '2'}


@app.route('/upload_audio_evidence', methods=['POST'])
@student_required
def upload_audio_evidence():
	"""Receive an audio blob from the browser and store it linked to a log entry."""
	fpath = None
	evidence_path = None
	cur = None
	try:
		testid     = request.form.get('testid', '').strip()
		voice_db   = request.form.get('voice_db', '0').strip()
		image_data = request.form.get('image_data', '').strip()
		audio_file = request.files.get('audio')

		if not audio_file or not audio_file.filename or not testid:
			return jsonify({'status': 'error', 'message': 'Missing audio or testid'}), 400

		uid   = session.get('uid')
		email = session.get('email')
		name  = session.get('name')
		if not uid or not email or not name:
			return jsonify({'status': 'error', 'message': 'Student session is incomplete'}), 401

		try:
			voice_db_val = float(voice_db)
		except (TypeError, ValueError):
			voice_db_val = 0.0
		extension_by_type = {
			'audio/mp4': '.mp4',
			'audio/ogg': '.ogg',
			'audio/webm': '.webm',
			'audio/webm;codecs=opus': '.webm',
		}
		audio_mimetype = (audio_file.mimetype or '').lower().split(';', 1)[0]
		extension = extension_by_type.get(audio_mimetype, '.webm')
		fname = f"exam_{secure_filename(testid)}_uid_{uid}_{uuid.uuid4().hex}{extension}"
		fpath = os.path.join(_AUDIO_EVIDENCE_DIR, fname)

		_ensure_proctoring_audio_column()
		_ensure_proctoring_device_column()
		_ensure_proctoring_evidence_schema()
		image_for_db = image_data
		if image_data:
			try:
				evidence_path = save_evidence_image(
					image_data, uid, testid, ['suspicious_audio'], _PROCTORING_EVIDENCE_DIR
				)
			except OSError:
				app.logger.exception(
					'Could not save suspicious-audio screenshot: uid=%s test=%s',
					uid, testid,
				)
			except ValueError:
				app.logger.exception(
					'Rejected invalid suspicious-audio screenshot: uid=%s test=%s',
					uid, testid,
				)
				image_for_db = ''
		cur = mysql.connection.cursor()
		cur.execute(
			'INSERT INTO proctoring_log '
			'(email, name, test_id, voice_db, img_log, user_movements_updown, '
			'user_movements_lr, user_movements_eyes, phone_detection, device_detection, '
			'person_status, uid, audio_evidence, evidence_file, evidence_status, event_data, '
			'detection_confidence, review_status) '
			'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
			(email, name, testid, voice_db_val, image_for_db, 0, 0, 2, 0, 0, 1, uid, fname,
			 evidence_path, 'saved' if image_for_db else 'failed',
			 json.dumps({
				 'events': [{
					 'event_type': 'suspicious_audio',
					 'message': 'Suspicious audio activity detected.',
					 'confidence': 1.0,
					 'risk_score': 15,
				 }],
				 'observed_at': datetime.now().astimezone().isoformat(),
			 }),
			 1.0, 'unreviewed'),
		)

		audio_file.save(fpath)
		mysql.connection.commit()
		app.logger.info('Audio evidence saved: %s (uid=%s, test=%s, voice_db=%.2f)', fname, uid, testid, voice_db_val)
		return jsonify({
			'status': 'success',
			'file': fname,
			'evidence_status': 'saved' if image_for_db else 'failed',
		})

	except Exception as ae:
		try:
			mysql.connection.rollback()
		except Exception:
			app.logger.exception('Audio evidence transaction rollback failed')
		if fpath and os.path.exists(fpath):
			try:
				os.remove(fpath)
			except OSError:
				app.logger.exception('Could not remove unlinked audio file: %s', fpath)
		if evidence_path:
			try:
				delete_evidence_image(evidence_path, _PROCTORING_EVIDENCE_DIR)
			except OSError:
				app.logger.exception('Could not remove unlinked audio screenshot: %s', evidence_path)
		app.logger.exception('upload_audio_evidence error: %s', ae)
		return jsonify({'status': 'error', 'message': 'Audio upload failed.'}), 500
	finally:
		if cur is not None:
			cur.close()

@app.route('/window_event', methods=['GET', 'POST'])
@student_required
def window_event():
	if request.method == 'POST':
		try:
			testid     = request.form.get('testid', '').strip()
			event_type = request.form.get('event_type', 'tab_switch').strip()
			if not testid:
				return jsonify({'status': 'error', 'message': 'Missing testid'}), 400

			# Use proctoring_policy cooldown so tab-switch spam is dampened
			import proctoring_policy as pp
			uid = session.get('uid')
			pol = pp.evaluate_window_event(f"{uid}_{testid}", event_type)
			evidence_status = 'not_required'

			if pol['should_log']:
				cur = mysql.connection.cursor()
				cur.execute(
					'INSERT INTO window_estimation_log '
					'(email, test_id, name, window_event, uid) '
					'VALUES (%s,%s,%s,%s,%s)',
					(session.get('email'), testid, session.get('name'), 1, uid),
				)
				mysql.connection.commit()
				cur.close()
				app.logger.info('window_event logged: uid=%s test=%s type=%s', uid, testid, event_type)
				if request.form.get('imgData'):
					evidence_status = (
						'saved'
						if _save_event_snapshot(
							request.form['imgData'],
							testid,
							uid,
							session.get('email'),
							session.get('name'),
							event_type,
						)
						else 'failed'
					)
				else:
					evidence_status = 'failed'

			return jsonify({
				'status':   'success',
				'logged':   pol['should_log'],
				'evidence_status': evidence_status,
				'evidence_message': (
					'The event was logged, but its webcam screenshot could not be saved.'
					if evidence_status == 'failed' else None
				),
				'warnings': pol.get('warnings', []),
			})
		except Exception as we:
			app.logger.error('window_event error: %s', we)
			try:
				mysql.connection.rollback()
			except Exception:
				pass
			return jsonify({'status': 'error', 'message': str(we)}), 500
	return jsonify({'status': 'error', 'message': 'POST required'}), 405

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'inr',
                        'unit_amount': 499*100,
                        'product_data': {
                            'name': 'Basic Exam Plan of 10 units',
                            'images': ['https://i.imgur.com/LsvO3kL_d.webp?maxwidth=760&fidelity=grand'],
                        },
                    },
                    'quantity': 1,
                },
            ],
            mode='payment',
            success_url=YOUR_DOMAIN + '/success',
            cancel_url=YOUR_DOMAIN + '/cancelled',
        )
        return jsonify({'id': checkout_session.id})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route("/livemonitoringtid")
@professor_required
def livemonitoringtid():
	cur = mysql.connection.cursor()
	results = cur.execute('SELECT * from teachers where email = %s and uid = %s and proctoring_type = 1', (session['email'], session['uid']))
	if results > 0:
		cresults = cur.fetchall()
		now = exam_schedule_now()
		testids = []
		for a in cresults:
			if datetime.strptime(str(a['start']),"%Y-%m-%d %H:%M:%S") <= now and datetime.strptime(str(a['end']),"%Y-%m-%d %H:%M:%S") >= now:
				testids.append(a['test_id'])
		cur.close()
		return render_template("livemonitoringtid.html", cresults = testids)
	else:
		return render_template("livemonitoringtid.html", cresults = None)

@app.route('/live_monitoring', methods=['GET','POST'])
@user_role_professor
def live_monitoring():
	if request.method == 'POST':
		testid = request.form['choosetid']
		return render_template('live_monitoring.html',testid = testid)
	else:
		return render_template('live_monitoring.html',testid = None)	

@app.route('/')
def index():
	return render_template('index.html')

@app.errorhandler(404) 
def not_found(e):
	return render_template("404.html")

@app.errorhandler(400)
def bad_request(error):
	app.logger.exception('Bad request: %s', error)
	return render_template('error.html', error=f'Bad request. Please go back and try again.'), 400

@app.errorhandler(500)
def internal_error(error):
	app.logger.exception('500 error: %s', error)
	# Try to rollback any broken DB transaction
	try:
		from flask import g
		if hasattr(g, 'mysql_db'):
			g.mysql_db.rollback()
	except Exception:
		pass
	return render_template_string('''
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Server Error - MyProctor.ai</title>
<link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css">
<style>body{background:#f5f8fb;display:flex;align-items:center;justify-content:center;min-height:100vh;}
.card{max-width:600px;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.1);}
.icon{font-size:4rem;}</style></head>
<body><div class="card p-5 text-center">
<div class="icon">⚠️</div>
<h2 class="mt-3 text-danger">Something went wrong</h2>
<p class="text-muted">The server encountered an error processing your request.<br>Please go back and try again.</p>
<div class="mt-4">
  <a href="/" class="btn btn-primary mr-2">🏠 Home</a>
  <a href="javascript:history.back()" class="btn btn-secondary">← Go Back</a>
  <a href="/login" class="btn btn-outline-info ml-2">🔐 Login</a>
</div>
<p class="text-muted small mt-4">If this keeps happening, please contact support.</p>
</div></body></html>'''), 500 

@app.route('/calc')
def calc():
	return render_template('calc.html')

@app.route('/report_professor')
@user_role_professor
def report_professor():
	return render_template('report_professor.html')

@app.route('/student_index')
@user_role_student
def student_index():
	return render_template('student_index.html')

@app.route('/professor_index')
@user_role_professor
def professor_index():
	return render_template('professor_index.html')

@app.route('/faq')
def faq():
	return render_template('faq.html')

@app.route('/report_student')
@user_role_student
def report_student():
	return render_template('report_student.html')

@app.route('/report_professor_email', methods=['GET','POST'])
@user_role_professor
def report_professor_email():
	if request.method == 'POST':
		cname = session['name']
		cemail = session['email']
		ptype = request.form['prob_type']
		cquery = request.form['rquery']
		msg1 = Message('PROBLEM REPORTED', sender=sender, recipients=[careEmail])
		msg1.body = " ".join(["NAME:", cname, "PROBLEM TYPE:", ptype, "EMAIL:", cemail, "QUERY:", cquery])
		mail.send(msg1)
		flash('Your Problem has been recorded.', 'success')
	return render_template('report_professor.html')

@app.route('/report_student_email', methods=['GET','POST'])
@user_role_student
def report_student_email():
	if request.method == 'POST':
		cname = session['name']
		cemail = session['email']
		ptype = request.form['prob_type']
		cquery = request.form['rquery']
		msg1 = Message('PROBLEM REPORTED', sender=sender, recipients=[careEmail])
		msg1.body = " ".join(["NAME:", cname, "PROBLEM TYPE:", ptype, "EMAIL:", cemail, "QUERY:", cquery])
		mail.send(msg1)
		flash('Your Problem has been recorded.', 'success')
	return render_template('report_student.html')

@app.route('/contact', methods=['GET','POST'])
def contact():
	if request.method == 'POST':
		careEmail = "bahurashiritik88@gmail.com"
		cname = request.form['cname']
		cemail = request.form['cemail']
		cquery = request.form['cquery']
		msg1 = Message('Hello', sender=sender, recipients=[cemail])
		msg2 = Message('Hello', sender=sender, recipients=[careEmail])
		msg1.body = "YOUR QUERY WILL BE PROCESSED WITHIN 24 HOURS"
		msg2.body = " ".join(["NAME:", cname, "EMAIL:", cemail, "QUERY:", cquery])
		mail.send(msg1)
		mail.send(msg2)
		flash('Your Query has been recorded.', 'success')
	return render_template('contact.html')

@app.route('/lostpassword', methods=['GET','POST'])
def lostpassword():
	if request.method == 'POST':
		lpemail = request.form['lpemail']
		cur = mysql.connection.cursor()
		results = cur.execute('SELECT * from users where email = %s' , [lpemail])
		if results > 0:
			sesOTPfp = generateOTP()
			session['tempOTPfp'] = sesOTPfp
			session['seslpemail'] = lpemail
			msg1 = Message('MyProctor.ai - OTP Verification for Lost Password', sender = sender, recipients = [lpemail])
			msg1.body = "Your OTP Verfication code for reset password is "+sesOTPfp+"."
			mail.send(msg1)
			return redirect(url_for('verifyOTPfp')) 
		else:
			return render_template('lostpassword.html',error="Account not found.")
	return render_template('lostpassword.html')

@app.route('/verifyOTPfp', methods=['GET','POST'])
def verifyOTPfp():
	if request.method == 'POST':
		fpOTP = request.form['fpotp']
		fpsOTP = session['tempOTPfp']
		if(fpOTP == fpsOTP):
			return redirect(url_for('lpnewpwd')) 
	return render_template('verifyOTPfp.html')

@app.route('/lpnewpwd', methods=['GET','POST'])
def lpnewpwd():
	if request.method == 'POST':
		npwd = request.form['npwd']
		cpwd = request.form['cpwd']
		slpemail = session['seslpemail']
		if(npwd == cpwd ):
			cur = mysql.connection.cursor()
			cur.execute('UPDATE users set password = %s where email = %s', (npwd, slpemail))
			mysql.connection.commit()
			cur.close()
			session.clear()
			return render_template('login.html',success="Your password was successfully changed.")
		else:
			return render_template('login.html',error="Password doesn't matched.")
	return render_template('lpnewpwd.html')

@app.route('/generate_test')
@user_role_professor
def generate_test():
	return render_template('generatetest.html')

@app.route('/test_generate', methods=['POST'])
@user_role_professor
def test_generate():
	try:
		itext = request.form.get('itext', '').strip()
		test_type = request.form.get('test_type', 'objective').strip()
		noq = request.form.get('noq', '5').strip()

		if not itext:
			flash('Please paste some text before generating questions.', 'danger')
			return redirect(url_for('generate_test'))

		try:
			noq = int(noq)
			if noq < 1:
				noq = 5
		except (ValueError, TypeError):
			noq = 5

		if test_type == 'subjective':
			from subjective import SubjectiveTest
			obj = SubjectiveTest(itext, noq)
		else:
			from objective import ObjectiveTest
			obj = ObjectiveTest(itext, noq)

		questions, answers = obj.generate_test()

		if not questions:
			flash('Could not generate questions from the provided text. Please try a longer or more descriptive paragraph.', 'warning')
			return redirect(url_for('generate_test'))

		cresults = list(zip(questions, answers))
		return render_template('generatedtestdata.html', cresults=cresults)

	except Exception as gen_err:
		app.logger.exception(f'test_generate error: {gen_err}')
		flash(f'Error generating questions: {gen_err}', 'danger')
		return redirect(url_for('generate_test'))

@app.route('/changepassword_professor')
@user_role_professor
def changepassword_professor():
	return render_template('changepassword_professor.html')

@app.route('/changepassword_student')
@user_role_student
def changepassword_student():
	return render_template('changepassword_student.html')

def generateOTP() : 
    digits = "0123456789"
    OTP = "" 
    for i in range(5) : 
        OTP += digits[math.floor(random.random() * 10)] 
    return OTP 

@app.route('/register', methods=['GET','POST'])
def register():
	if request.method == 'POST':
		# Safety catch: If the OTP form accidentally submits back to /register,
		# immediately route the request over to the verifyEmail handler.
		if 'eotp' in request.form or 'registration_id' in request.form:
			return verifyEmail()

		name     = request.form.get('name', '').strip()
		email    = request.form.get('email', '').strip()
		password = request.form.get('password', '').strip()
		user_type = request.form.get('user_type', 'student').strip()
		imgdata  = request.form.get('image_hidden', '').strip()

		app.logger.info(
			'Register POST: name=%s, email=%s, user_type=%r, imgdata_len=%d',
			bool(name), bool(email), user_type, len(imgdata),
		)

		# ── Field presence & format validation ──────────────────────────
		if not name:
			return render_template('register.html', error='Full name is required. Please enter your name.', field='name')
		if len(name) < 2:
			return render_template('register.html', error='Name must be at least 2 characters long.', field='name')
		if not email:
			return render_template('register.html', error='Email address is required.', field='email')
		# Basic email format check (the browser type=email also catches this)
		if '@' not in email or '.' not in email.split('@')[-1]:
			return render_template('register.html', error='Invalid email format. Please enter a valid email address (e.g. user@example.com).', field='email')
		if not password:
			return render_template('register.html', error='Password is required.', field='password')
		if len(password) < 8:
			return render_template('register.html', error='Password must be at least 8 characters long. Please choose a stronger password.', field='password')
		if not user_type:
			user_type = 'student'

		# ── Mandatory face capture ───────────────────────────────────────
		if not imgdata or imgdata in ('no_camera', ''):
			return render_template(
				'register.html',
				error='A live face photo is required to register. Please allow camera access, complete the liveness check, and try again.',
				field='face',
			)

		# ── Liveness + quality check ─────────────────────────────────────
		if FACE_VERIFIER_AVAILABLE:
			try:
				capture_result = _fv.validate_registration_capture(imgdata)
			except Exception as fv_err:
				app.logger.error('Face verifier exception during registration: %s', fv_err)
				capture_result = {'ok': False, 'message': 'Face verification encountered an error. Please retake your photo and try again.'}
			if not capture_result['ok']:
				app.logger.info('Registration face capture rejected: %s', capture_result['message'])
				return render_template('register.html', error=capture_result['message'], field='face')
		else:
			app.logger.warning('face_verifier unavailable — skipping liveness check for registration.')

		# ── Check for duplicate email ────────────────────────────────────
		try:
			cur = mysql.connection.cursor()
			dup = cur.execute('SELECT uid FROM users WHERE email = %s', (email,))
			cur.close()
			if dup > 0:
				return render_template(
					'register.html',
					error='This email is already registered. Please use a different email or log in to your existing account.',
					field='email',
				)
		except Exception as dup_err:
			app.logger.warning('Duplicate email check error: %s', dup_err)

		# ── OTP flow ─────────────────────────────────────────────────────
		sesOTP = generateOTP()
		if not is_mail_configured():
			app.logger.warning('Registration OTP email skipped because mail settings are incomplete.')
			registration_id = save_pending_registration(
				name, email, password, user_type, imgdata, sesOTP, 'local'
			)
			return render_verify_email(
				error='Email service is not configured. Use the OTP shown below for local testing.',
				registration_id=registration_id,
				dev_otp=sesOTP,
			)
		msg1 = Message('MyProctor.ai - OTP Verification', sender=sender, recipients=[email])
		msg1.body = 'New Account opening — Your OTP Verification code is ' + sesOTP + '.'
		try:
			mail.send(msg1)
		except Exception:
			app.logger.exception('Failed to send registration OTP email.')
			registration_id = save_pending_registration(
				name, email, password, user_type, imgdata, sesOTP, 'local'
			)
			return render_verify_email(
				error='Could not send OTP email. Use the OTP shown below for local testing.',
				registration_id=registration_id,
				dev_otp=sesOTP,
			)
		flash('A verification OTP has been sent to your email address.', 'info')
		registration_id = save_pending_registration(
			name, email, password, user_type, imgdata, sesOTP, 'email'
		)
		return render_verify_email(registration_id=registration_id)
	return render_template('register.html')

# (debug stub removed)

@app.route('/login', methods=['GET','POST'])
def login():
	if request.method == 'POST':
		email = request.form.get('email', '').strip()
		password_candidate = request.form.get('password', '').strip()
		user_type = request.form.get('user_type', '').strip()
		imgdata1 = request.form.get('image_hidden', '').strip()

		# ── Face photo is mandatory ──────────────────────────────────────
		if not imgdata1 or imgdata1 == 'no_camera':
			return render_template(
				'login.html',
				error='Face verification is required to log in. Please allow camera access and capture your photo.',
			)

		try:
			cur = mysql.connection.cursor()
			results1 = cur.execute(
				'SELECT uid, name, email, password, user_type, user_image, user_login FROM users WHERE email = %s AND user_type = %s',
				(email, user_type),
			)
			if results1 > 0:
				cresults = cur.fetchone()
				stored_img = cresults['user_image']
				db_password = cresults['password']
				name = cresults['name']
				uid = cresults['uid']

				# ── Password check ──────────────────────────────────────
				if db_password != password_candidate:
					cur.close()
					return render_template('login.html', error='Invalid password. Please try again.')

				# ── Face verification (score-based, 66 % threshold) ───────
				if FACE_VERIFIER_AVAILABLE:
					face_result = _fv.verify_face_match_result(imgdata1, stored_img)
					if not face_result['ok']:
						cur.close()
						app.logger.info(
							'Login face match failed for %s: %s', email, face_result['message']
						)
						return render_template('login.html', error=face_result['message'])
				else:
					# Fallback: basic DeepFace check if face_verifier unavailable
					app.logger.warning('face_verifier unavailable — falling back to basic DeepFace check.')
					if stored_img not in IMAGE_PLACEHOLDERS:
						try:
							np1 = np.frombuffer(base64.b64decode(imgdata1), np.uint8)
							np2 = np.frombuffer(base64.b64decode(stored_img), np.uint8)
							im1 = cv2.imdecode(np1, cv2.IMREAD_COLOR)
							im2 = cv2.imdecode(np2, cv2.IMREAD_COLOR)
							res = DeepFace.verify(im1, im2, enforce_detection=False)
							if not res.get('verified'):
								cur.close()
								return render_template('login.html', error='Face verification failed. Please try again with a clearer photo.')
						except Exception as df_err:
							app.logger.error('DeepFace fallback error: %s', df_err)
							cur.close()
							return render_template('login.html', error='Face verification could not be completed. Please try again.')

				# ── All checks passed – create session ────────────────────
				cur.execute('UPDATE users SET user_login = 1 WHERE email = %s AND uid = %s', (email, uid))
				mysql.connection.commit()
				cur.close()
				user = User(uid, name, email, user_type)
				login_user(user, remember=True)
				session['logged_in'] = True
				session['email'] = email
				session['uid'] = uid
				session['name'] = name
				session['user_role'] = 'teacher' if user_type == 'teacher' else user_type
				if user_type == 'student':
					return redirect(url_for('student_index'))
				return redirect(url_for('professor_index'))
			else:
				cur.close()
				return render_template(
					'login.html',
					error='Email not found for the selected user type. Check your email and user type selection.',
				)
		except Exception as login_err:
			app.logger.error('Login error: %s', login_err)
			return render_template('login.html', error='A login error occurred. Please try again.')
	return render_template('login.html')


@app.route('/api/face_quality_check', methods=['POST'])
def api_face_quality_check():
	"""Client-side pre-flight quality check during registration.
	POST JSON: {"image": "<base64>"}
	Returns JSON: {"ok": bool, "message": str, ...}
	"""
	if not FACE_VERIFIER_AVAILABLE:
		return jsonify({"ok": True, "message": "Quality check unavailable — proceeding."})
	try:
		payload = request.get_json(force=True, silent=True) or {}
		img_b64 = payload.get('image', '').strip()
		if not img_b64:
			return jsonify({"ok": False, "message": "No image provided."})
		img_bgr = _fv._b64_to_bgr(img_b64)
		result = _fv.assess_face_capture(img_bgr, require_liveness=True)
		return jsonify(result)
	except Exception as qc_err:
		app.logger.warning('face_quality_check error: %s', qc_err)
		return jsonify({"ok": False, "message": "Quality check failed. Please retake the photo."})


@app.route('/verifyEmail', methods=['GET','POST'])
def verifyEmail():
	if request.method == 'POST':
		try:
			theOTP = request.form['eotp']
		except KeyError as e:
			app.logger.error(f"Missing form field in verifyEmail: {e}")
			return render_verify_email(error="Invalid form submission. Please try again.")
		registration_id = request.form.get('registration_id', '')
		if not registration_id:
			return render_template('register.html', error='Your registration session expired. Please register again.')
		registration_data, registration_error = load_pending_registration(registration_id)
		if registration_error == 'expired':
			return render_template('register.html', error='Your OTP expired. Please register again.')
		if registration_error == 'missing':
			return render_template('register.html', error='Your registration session expired. Please register again.')
		mOTP = registration_data['otp']
		dbName = registration_data['name']
		dbEmail = registration_data['email']
		dbPassword = registration_data['password']
		dbUser_type = registration_data['user_type']
		dbImgdata = registration_data['image_hidden']
		if theOTP == mOTP:
			_cur = None
			try:
				_cur = mysql.connection.cursor()
				ar = _cur.execute(
					'INSERT INTO users(name, email, password, user_type, user_image, user_login) '
					'VALUES (%s, %s, %s, %s, %s, %s)',
					(dbName, dbEmail, dbPassword, dbUser_type, dbImgdata, 0),
				)
				mysql.connection.commit()
				if ar > 0:
					delete_pending_registration(registration_id)
					clear_registration_session()
					flash('Registration successful! Welcome to MyProctor.ai. Please sign in.', 'success')
					return redirect(url_for('login'))
				else:
					# INSERT ran but affected 0 rows — very unusual
					app.logger.error('verifyEmail: INSERT returned 0 rows for email=%s', dbEmail)
					return render_verify_email(
						error='Registration could not be completed (no rows inserted). Please try again or contact support.',
						registration_id=registration_id,
					)
			except Exception as db_err:
				# ── Classify the DB error and show a specific message ──────
				err_str  = str(db_err).lower()
				err_code = getattr(db_err, 'args', [None])[0] if hasattr(db_err, 'args') else None
				app.logger.error('Database error in verifyEmail (errno=%s): %s', err_code, db_err)

				if err_code == 1062 or 'duplicate entry' in err_str or 'duplicate' in err_str:
					if 'email' in err_str:
						user_msg = 'This email is already registered. Please use a different email or log in to your existing account.'
					elif 'name' in err_str:
						user_msg = 'This username is already taken. Please choose a different name.'
					else:
						user_msg = 'An account with these details already exists. Please log in or use different credentials.'
				elif err_code == 1045 or 'access denied' in err_str:
					user_msg = 'Database access error. Please contact the administrator.'
				elif err_code in (2003, 2006, 2013) or 'lost connection' in err_str or "can't connect" in err_str:
					user_msg = 'Database connection failed. Please try again in a few moments.'
				elif err_code == 1406 or 'data too long' in err_str:
					user_msg = 'One of your inputs is too long. Please shorten your name or email and try again.'
				elif err_code == 1048 or "cannot be null" in err_str:
					user_msg = 'A required field is missing. Please fill in all fields and try again.'
				else:
					user_msg = 'Registration failed due to a server error. Please try again later or contact support.'

				try:
					mysql.connection.rollback()
				except Exception:
					pass
				return render_verify_email(
					error=user_msg,
					registration_id=registration_id,
				)
			finally:
				if _cur is not None:
					try:
						_cur.close()
					except Exception:
						pass
		else:
			return render_verify_email(
				error="OTP is incorrect.",
				registration_id=registration_id,
				dev_otp=registration_data.get('otp') if registration_data.get('otp_delivery_mode') == 'local' else None,
			)
	return render_template('register.html', error='Your registration session expired. Please register again.')

@app.route('/changepassword', methods=["GET", "POST"])
def changePassword():
	if request.method == "POST":
		oldPassword = request.form['oldpassword']
		newPassword = request.form['newpassword']
		cur = mysql.connection.cursor()
		results = cur.execute('SELECT * from users where email = %s and uid = %s', (session['email'], session['uid']))
		if results > 0:
			data = cur.fetchone()
			password = data['password']
			usertype = data['user_type']
			if(password == oldPassword):
				cur.execute("UPDATE users SET password = %s WHERE email = %s", (newPassword, session['email']))
				mysql.connection.commit()
				msg="Changed successfully"
				flash('Changed successfully.', 'success')
				cur.close()
				if usertype == "student":
					return render_template("student_index.html", success=msg)
				else:
					return render_template("professor_index.html", success=msg)
			else:
				error = "Wrong password"
				if usertype == "student":
					return render_template("student_index.html", error=error)
				else:
					return render_template("professor_index.html", error=error)
		else:
			return redirect(url_for('/'))

@app.route('/logout', methods=["GET", "POST"])
def logout():
	try:
		uid = session.get('uid') or (current_user.id if current_user.is_authenticated else None)
		if uid:
			cur = mysql.connection.cursor()
			cur.execute('UPDATE users set user_login = 0 where uid = %s', (uid,))
			mysql.connection.commit()
			cur.close()
		logout_user()
		session.clear()
		if request.method == 'POST':
			return "success"
		return redirect(url_for('index'))
	except Exception as e:
		app.logger.error(f'Logout error: {e}')
		session.clear()
		if request.method == 'POST':
			return "success"
		return redirect(url_for('index'))

def examcreditscheck():
	return True

# ── Helper: read an uploaded CSV regardless of encoding ──────────────────────
def read_csv_safe(filestream):
    """Try common encodings so Excel-saved CSVs (latin-1 / cp1252) don't crash."""
    raw = filestream.read()
    for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(
        "Could not read CSV. Please save the file as UTF-8 or plain CSV "
        "(File → Save As → CSV UTF-8 in Excel)."
    )

class QAUploadForm(FlaskForm):
	subject = StringField('Subject')
	topic = StringField('Topic')
	doc = FileField('CSV Upload', validators=[FileRequired()])
	start_date = DateField('Start Date')
	start_time = TimeField('Start Time', default=datetime.utcnow()+timedelta(hours=5.5))
	end_date = DateField('End Date')
	end_time = TimeField('End Time', default=datetime.utcnow()+timedelta(hours=5.5))
	duration = IntegerField('Duration(in min)')
	password = PasswordField('Exam Password', [validators.Length(min=3, max=6)])

	def validate_end_date(form, field):
		try:
			if field.data and form.start_date.data and field.data < form.start_date.data:
				raise ValidationError("End date must not be earlier than start date.")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_end_time(form, field):
		try:
			if not (form.start_date.data and form.start_time.data and form.end_date.data and field.data):
				return
			start_date_time = datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			end_date_time = datetime.strptime(str(form.end_date.data) + " " + str(field.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			if start_date_time >= end_date_time:
				raise ValidationError("End date time must not be earlier/equal than start date time")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_start_date(form, field):
		try:
			if not (form.start_date.data and form.start_time.data):
				return
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < exam_schedule_now():
				raise ValidationError("Start date and time must not be earlier than current")
		except ValidationError:
			raise
		except Exception:
			pass

@app.route('/create_test_lqa', methods = ['GET', 'POST'])
@user_role_professor
def create_test_lqa():
	form = QAUploadForm()
	if request.method == 'POST' and form.validate_on_submit():
		try:
			test_id = generate_slug(2)
			filestream = form.doc.data
			filestream.seek(0)
			ef = read_csv_safe(filestream)
			fields = ['qid','q','marks']
			df = pd.DataFrame(ef, columns = fields)
			# Drop empty rows and clean NaN values to prevent database errors
			df = df.dropna(subset=['qid', 'q'])
			df['qid'] = df['qid'].astype(str).str.strip()
			df['q'] = df['q'].astype(str).str.strip()
			df['marks'] = pd.to_numeric(df['marks'], errors='coerce').fillna(1).astype(int)
			cur = mysql.connection.cursor()
			ecc = examcreditscheck()
			if ecc:
				for row in df.index:
					cur.execute('INSERT INTO longqa(test_id,qid,q,marks,uid) values(%s,%s,%s,%s,%s)', (test_id, df['qid'][row], df['q'][row], df['marks'][row], session['uid']))
					cur.connection.commit()
				
				start_date = form.start_date.data
				end_date = form.end_date.data
				start_time = form.start_time.data
				end_time = form.end_time.data
				start_date_time = str(start_date) + " " + str(start_time)
				end_date_time = str(end_date) + " " + str(end_time)
				duration = int(form.duration.data) * 60
				password = form.password.data
				subject = form.subject.data
				topic = form.topic.data
				proctor_type = '0'
				cur.execute('INSERT INTO teachers (email, test_id, test_type, start, end, duration, show_ans, password, subject, topic, neg_marks, calc, proctoring_type, uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
					(dict(session)['email'], test_id, "subjective", start_date_time, end_date_time, duration, 0, password, subject, topic, 0, 0, proctor_type, session['uid']))
				mysql.connection.commit()
				# Credits decrement removed (Unlimited exams)
				# cur.execute('UPDATE users SET examcredits = examcredits-1 where email = %s and uid = %s', (session['email'],session['uid']))
				mysql.connection.commit()
				cur.close()
				flash(f'Exam created! Exam ID: {test_id}', 'success')
				return redirect(url_for('professor_index'))
			else:
				flash("No exam credits found! Please purchase credits.", 'danger')
				return redirect(url_for('professor_index'))
		except Exception as create_err:
			app.logger.exception(f'create_test_lqa error: {create_err}')
			try:
				mysql.connection.rollback()
			except Exception:
				pass
			flash(f'Error creating exam: {create_err}', 'danger')
			return render_template('create_test_lqa.html', form=form)
	return render_template('create_test_lqa.html' , form = form)

class UploadForm(FlaskForm):
	subject = StringField('Subject')
	topic = StringField('Topic')
	doc = FileField('CSV Upload', validators=[FileRequired()])
	start_date = DateField('Start Date')
	start_time = TimeField('Start Time', default=datetime.utcnow()+timedelta(hours=5.5))
	end_date = DateField('End Date')
	end_time = TimeField('End Time', default=datetime.utcnow()+timedelta(hours=5.5))
	calc = BooleanField('Enable Calculator')
	neg_mark = DecimalField('Enable negative marking in % ', validators=[NumberRange(min=0, max=100)])
	duration = IntegerField('Duration(in min)')
	password = PasswordField('Exam Password', [validators.Length(min=3, max=6)])

	def validate_end_date(form, field):
		try:
			if field.data and form.start_date.data and field.data < form.start_date.data:
				raise ValidationError("End date must not be earlier than start date.")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_end_time(form, field):
		try:
			if not (form.start_date.data and form.start_time.data and form.end_date.data and field.data):
				return
			start_date_time = datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			end_date_time = datetime.strptime(str(form.end_date.data) + " " + str(field.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			if start_date_time >= end_date_time:
				raise ValidationError("End date time must not be earlier/equal than start date time")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_start_date(form, field):
		try:
			if not (form.start_date.data and form.start_time.data):
				return
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < exam_schedule_now():
				raise ValidationError("Start date and time must not be earlier than current")
		except ValidationError:
			raise
		except Exception:
			pass

class TestForm(Form):
	test_id = StringField('Exam ID', [validators.DataRequired(message='Enter the exam ID provided by your instructor.')])
	password = PasswordField('Exam Password', [validators.DataRequired(message='Enter the exam password.')])
	img_hidden_form = HiddenField(label=(''), validators=[validators.DataRequired(message='Capture a clear face photo before continuing.')])

@app.route('/create_test', methods = ['GET', 'POST'])
@app.route('/create-test', methods = ['GET', 'POST'])
@user_role_professor
def create_test():
	form = UploadForm()
	if request.method == 'POST' and form.validate_on_submit():
		try:
			test_id = generate_slug(2)
			filestream = form.doc.data
			filestream.seek(0)
			ef = read_csv_safe(filestream)
			fields = ['qid','q','a','b','c','d','ans','marks']
			df = pd.DataFrame(ef, columns = fields)
			# Drop empty rows and clean NaN values to prevent database errors
			df = df.dropna(subset=['qid', 'q'])
			for col in ['a', 'b', 'c', 'd', 'ans']:
				df[col] = df[col].fillna("").astype(str).str.strip()
			df['qid'] = df['qid'].astype(str).str.strip()
			df['q'] = df['q'].astype(str).str.strip()
			df['marks'] = pd.to_numeric(df['marks'], errors='coerce').fillna(1).astype(int)
			cur = mysql.connection.cursor()
			ecc = examcreditscheck()
			if ecc:
				for row in df.index:
					cur.execute('INSERT INTO questions(test_id,qid,q,a,b,c,d,ans,marks,uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (test_id, df['qid'][row], df['q'][row], df['a'][row], df['b'][row], df['c'][row], df['d'][row], df['ans'][row], df['marks'][row], session['uid']))
					cur.connection.commit()

				start_date = form.start_date.data
				end_date = form.end_date.data
				start_time = form.start_time.data
				end_time = form.end_time.data
				start_date_time = str(start_date) + " " + str(start_time)
				end_date_time = str(end_date) + " " + str(end_time)
				try:
					neg_mark = int(form.neg_mark.data) if form.neg_mark.data is not None else 0
				except (ValueError, TypeError):
					neg_mark = 0
				calc = int(bool(form.calc.data))
				duration = int(form.duration.data) * 60
				password = form.password.data
				subject = form.subject.data
				topic = form.topic.data
				proctor_type = '0'
				cur.execute('INSERT INTO teachers (email, test_id, test_type, start, end, duration, show_ans, password, subject, topic, neg_marks, calc,proctoring_type, uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
					(dict(session)['email'], test_id, "objective", start_date_time, end_date_time, duration, 1, password, subject, topic, neg_mark, calc, proctor_type, session['uid']))
				mysql.connection.commit()
				# Credits decrement removed (Unlimited exams)
				# cur.execute('UPDATE users SET examcredits = examcredits-1 where email = %s and uid = %s', (session['email'],session['uid']))
				mysql.connection.commit()
				cur.close()
				flash(f'Exam created! Exam ID: {test_id}', 'success')
				return redirect(url_for('professor_index'))
			else:
				flash("No exam credits found! Please purchase credits.", 'danger')
				return redirect(url_for('professor_index'))
		except Exception as create_err:
			app.logger.exception(f'create_test error: {create_err}')
			try:
				mysql.connection.rollback()
			except Exception:
				pass
			flash(f'Error creating exam: {create_err}', 'danger')
			return render_template('create_test.html', form=form)
	return render_template('create_test.html' , form = form)

class PracUploadForm(FlaskForm):
	subject = StringField('Subject')
	topic = StringField('Topic')
	questionprac = StringField('Question')
	marksprac = IntegerField('Marks')
	start_date = DateField('Start Date')
	start_time = TimeField('Start Time', default=datetime.utcnow()+timedelta(hours=5.5))
	end_date = DateField('End Date')
	end_time = TimeField('End Time', default=datetime.utcnow()+timedelta(hours=5.5))
	duration = IntegerField('Duration(in min)')
	compiler = SelectField(u'Compiler/Interpreter', choices=[('11', 'C'), ('27', 'C#'), ('1', 'C++'),('114', 'Go'),('10', 'Java'),('47', 'Kotlin'),('56', 'Node.js'),
	('43', 'Objective-C'),('29', 'PHP'),('54', 'Perl-6'),('116', 'Python 3x'),('117', 'R'),('17', 'Ruby'),('93', 'Rust'),('52', 'SQLite-queries'),('40', 'SQLite-schema'),
	('39', 'Scala'),('85', 'Swift'),('57', 'TypeScript')])
	password = PasswordField('Exam Password', [validators.Length(min=3, max=6)])

	def validate_end_date(form, field):
		try:
			if field.data and form.start_date.data and field.data < form.start_date.data:
				raise ValidationError("End date must not be earlier than start date.")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_end_time(form, field):
		try:
			if not (form.start_date.data and form.start_time.data and form.end_date.data and field.data):
				return
			start_date_time = datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			end_date_time = datetime.strptime(str(form.end_date.data) + " " + str(field.data),"%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
			if start_date_time >= end_date_time:
				raise ValidationError("End date time must not be earlier/equal than start date time")
		except ValidationError:
			raise
		except Exception:
			pass
	
	def validate_start_date(form, field):
		try:
			if not (form.start_date.data and form.start_time.data):
				return
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < exam_schedule_now():
				raise ValidationError("Start date and time must not be earlier than current")
		except ValidationError:
			raise
		except Exception:
			pass

class QuestionForm(FlaskForm):
    question_type = SelectField('Question Type', choices=[('objective', 'Objective (MCQ)'), ('subjective', 'Subjective')], default='objective')
    question = TextAreaField('Question', validators=[validators.DataRequired(), validators.Length(max=1000)])
    marks = IntegerField('Marks', validators=[validators.DataRequired()], default=1)
    
    # Objective fields
    option_a = StringField('Option A', validators=[validators.DataRequired()])
    option_b = StringField('Option B', validators=[validators.DataRequired()])
    option_c = StringField('Option C')
    option_d = StringField('Option D')
    correct_answer = SelectField('Correct Answer', choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')])
    
    # Subjective field
    model_answer = TextAreaField('Model Answer (optional)')
    
    submit = SubmitField('Add Question')

@app.route('/create_test_pqa', methods = ['GET', 'POST'])
@user_role_professor
def create_test_pqa():
	form = PracUploadForm()
	if request.method == 'POST' and form.validate_on_submit():
		try:
			ecc = examcreditscheck()
			if ecc:
				test_id = generate_slug(2)
				compiler = form.compiler.data
				questionprac = form.questionprac.data
				marksprac = int(form.marksprac.data)
				cur = mysql.connection.cursor()
				cur.execute('INSERT INTO practicalqa(test_id,qid,q,compiler,marks,uid) values(%s,%s,%s,%s,%s,%s)', (test_id, 1, questionprac, compiler, marksprac, session['uid']))
				mysql.connection.commit()
				start_date = form.start_date.data
				end_date = form.end_date.data
				start_time = form.start_time.data
				end_time = form.end_time.data
				start_date_time = str(start_date) + " " + str(start_time)
				end_date_time = str(end_date) + " " + str(end_time)
				duration = int(form.duration.data) * 60
				password = form.password.data
				subject = form.subject.data
				topic = form.topic.data
				proctor_type = '0'
				cur.execute('INSERT INTO teachers (email, test_id, test_type, start, end, duration, show_ans, password, subject, topic, neg_marks, calc, proctoring_type, uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
					(dict(session)['email'], test_id, "practical", start_date_time, end_date_time, duration, 0, password, subject, topic, 0, 0, proctor_type, session['uid']))
				mysql.connection.commit()
				# Credits decrement removed (Unlimited exams)
				# cur.execute('UPDATE users SET examcredits = examcredits-1 where email = %s and uid = %s', (session['email'],session['uid']))
				mysql.connection.commit()
				cur.close()
				flash(f'Exam created! Exam ID: {test_id}', 'success')
				return redirect(url_for('professor_index'))
			else:
				flash("No exam credits found! Please purchase credits.", 'danger')
				return redirect(url_for('professor_index'))
		except Exception as create_err:
			app.logger.exception(f'create_test_pqa error: {create_err}')
			try:
				mysql.connection.rollback()
			except Exception:
				pass
			flash(f'Error creating exam: {create_err}', 'danger')
			return render_template('create_prac_qa.html', form=form)
	return render_template('create_prac_qa.html' , form = form)

@app.route('/viewquestions', methods=['GET'])
@user_role_professor
def viewquestions():
	cur = mysql.connection.cursor()
	results = cur.execute('SELECT test_id from teachers where email = %s and uid = %s', (session['email'],session['uid']))
	if results > 0:
		cresults = cur.fetchall()
		cur.close()
		return render_template("viewquestions.html", cresults = cresults)
	else:
		return render_template("viewquestions.html", cresults = None)

def examtypecheck(tidoption):
	cur = mysql.connection.cursor()
	cur.execute('SELECT test_type from teachers where test_id = %s and email = %s and uid = %s', (tidoption,session['email'],session['uid']))
	callresults = cur.fetchone()
	cur.close()
	return callresults

@app.route('/displayquestions', methods=['GET','POST'])
@user_role_professor
def displayquestions():
	if request.method == 'GET':
		return redirect(url_for('viewquestions'))
	if request.method == 'POST':
		tidoption = request.form['choosetid']
		et = examtypecheck(tidoption)
		if not et:
			flash('Test ID not found.', 'danger')
			return redirect(url_for('viewquestions'))
		if et['test_type'] == "objective":
			cur = mysql.connection.cursor()
			cur.execute('SELECT * from questions where test_id = %s and uid = %s', (tidoption,session['uid']))
			callresults = cur.fetchall()
			cur.close()
			return render_template("displayquestions.html", callresults=callresults, tid=tidoption)
		elif et['test_type'] == "subjective":
			cur = mysql.connection.cursor()
			cur.execute('SELECT * from longqa where test_id = %s and uid = %s', (tidoption,session['uid']))
			callresults = cur.fetchall()
			cur.close()
			return render_template("displayquestionslong.html", callresults=callresults, tid=tidoption)
		elif et['test_type'] == "practical":
			cur = mysql.connection.cursor()
			cur.execute('SELECT * from practicalqa where test_id = %s and uid = %s', (tidoption,session['uid']))
			callresults = cur.fetchall()
			cur.close()
			return render_template("displayquestionspractical.html", callresults=callresults, tid=tidoption)
		return redirect(url_for('viewquestions'))

@app.route('/delete_lqa_question/<testid>/<qid>', methods=['POST'])
@user_role_professor
def delete_lqa_question(testid, qid):
    try:
        cur = mysql.connection.cursor()
        cur.execute('DELETE FROM longqa WHERE test_id = %s AND qid = %s AND uid = %s', (testid, qid, session['uid']))
        mysql.connection.commit()
        cur.close()
        flash('Question deleted successfully.', 'success')
    except Exception as e:
        app.logger.error(f'delete_lqa_question error: {e}')
        flash('Error deleting question.', 'danger')
    return ('', 204)

@app.route('/delete_pqa_question/<testid>/<qid>', methods=['POST'])
@user_role_professor
def delete_pqa_question(testid, qid):
    try:
        cur = mysql.connection.cursor()
        cur.execute('DELETE FROM practicalqa WHERE test_id = %s AND qid = %s AND uid = %s', (testid, qid, session['uid']))
        mysql.connection.commit()
        cur.close()
        flash('Question deleted successfully.', 'success')
    except Exception as e:
        app.logger.error(f'delete_pqa_question error: {e}')
        flash('Error deleting question.', 'danger')
    return ('', 204)

@app.route('/viewstudentslogs', methods=['GET'])
@user_role_professor
def viewstudentslogs():
	try:
		cur = mysql.connection.cursor()
		cur.execute('SELECT test_id from teachers where email = %s and uid = %s and proctoring_type = 0', (session['email'], session['uid']))
		cresults = cur.fetchall() or []
		cur.close()
		return render_template('viewstudentslogs.html', cresults=cresults)
	except Exception as e:
		app.logger.exception('viewstudentslogs failed: %s', e)
		flash(f'Could not load student logs: {e}', 'danger')
		return render_template('viewstudentslogs.html', cresults=[])


@app.route('/api/student-logs', methods=['GET'])
@user_role_professor
def api_student_logs():
	try:
		search = (request.args.get('search') or '').strip()
		date_filter = (request.args.get('date') or '').strip()
		where = ['t.uid = %s']
		params = [session['uid']]
		if search:
			like = f'%{search}%'
			where.append('(x.test_id LIKE %s OR x.email LIKE %s OR COALESCE(u.name, x.email) LIKE %s OR CAST(COALESCE(u.uid, 0) AS CHAR) LIKE %s)')
			params.extend([like, like, like, like])
		if date_filter:
			where.append('DATE(x.last_log_time) = %s')
			params.append(date_filter)
		query = f'''
			SELECT x.test_id, x.email, COALESCE(u.name, x.email) AS student_name,
			       COALESCE(u.uid, 0) AS student_id, MAX(x.last_log_time) AS last_log_time
			FROM (
				SELECT email, test_id, MAX(log_time) AS last_log_time FROM proctoring_log GROUP BY email, test_id
				UNION ALL
				SELECT email, test_id, MAX(transaction_log) AS last_log_time FROM window_estimation_log GROUP BY email, test_id
				UNION ALL
				SELECT email, test_id, NULL AS last_log_time FROM studenttestinfo WHERE completed = 1
			) x
			JOIN teachers t ON t.test_id = x.test_id
			LEFT JOIN users u ON u.email = x.email AND u.user_type = 'student'
			WHERE {' AND '.join(where)}
			GROUP BY x.test_id, x.email, u.name, u.uid
			ORDER BY last_log_time DESC, x.test_id DESC
		'''
		cur = mysql.connection.cursor()
		cur.execute(query, params)
		rows = cur.fetchall() or []
		cur.close()
		return jsonify({'status': 'success', 'logs': _json_safe_rows(rows)})
	except Exception as e:
		app.logger.exception('api_student_logs failed: %s', e)
		return jsonify({'status': 'error', 'message': f'Could not load student logs: {e}'}), 500

@app.route('/insertmarkstid', methods=['GET'])
@user_role_professor
def insertmarkstid():
	cur = mysql.connection.cursor()
	results = cur.execute('SELECT * from teachers where show_ans = 0 and email = %s and uid = %s and (test_type = %s or test_type = %s)', (session['email'], session['uid'],"subjective","practical"))
	if results > 0:
		cresults = cur.fetchall()
		now = exam_schedule_now()
		testids = []
		for a in cresults:
			if datetime.strptime(str(a['end']),"%Y-%m-%d %H:%M:%S") < now:
				testids.append(a['test_id'])
		cur.close()
		return render_template("insertmarkstid.html", cresults = testids)
	else:
		return render_template("insertmarkstid.html", cresults = None)

@app.route('/displaystudentsdetails', methods=['GET','POST'])
@user_role_professor
def displaystudentsdetails():
	if request.method == 'POST':
		tidoption = request.form['choosetid']
		cur = mysql.connection.cursor()
		cur.execute('''
			SELECT DISTINCT email, test_id FROM proctoring_log WHERE test_id = %s
			UNION
			SELECT DISTINCT email, test_id FROM window_estimation_log WHERE test_id = %s
			UNION
			SELECT DISTINCT email, test_id FROM studenttestinfo WHERE test_id = %s AND completed = 1
		''', (tidoption, tidoption, tidoption))
		callresults = cur.fetchall()
		cur.close()
		return render_template("displaystudentsdetails.html", callresults = callresults)

@app.route('/insertmarksdetails', methods=['GET','POST'])
@user_role_professor
def insertmarksdetails():
	if request.method == 'POST':
		tidoption = request.form['choosetid']
		et = examtypecheck(tidoption)
		if et['test_type'] == "subjective":
			cur = mysql.connection.cursor()
			cur.execute('SELECT DISTINCT email,test_id from longtest where test_id = %s', [tidoption])
			callresults = cur.fetchall()
			cur.close()
			return render_template("subdispstudentsdetails.html", callresults = callresults)
		elif et['test_type'] == "practical":
			cur = mysql.connection.cursor()
			cur.execute('SELECT DISTINCT email,test_id from practicaltest where test_id = %s', [tidoption])
			callresults = cur.fetchall()
			cur.close()
			return render_template("pracdispstudentsdetails.html", callresults = callresults)
		else:
			flash("Some Error was occured!",'error')
			return redirect(url_for('insertmarkstid'))

@app.route('/insertsubmarks/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def insertsubmarks(testid,email):
	if request.method == "GET":
		cur = mysql.connection.cursor()
		cur.execute('SELECT l.email as email, l.marks as inputmarks, l.test_id as test_id, l.qid as qid, l.ans as ans, lqa.marks as marks, l.uid as uid, lqa.q as q  from longtest l, longqa lqa where l.test_id = %s and l.email = %s and l.test_id = lqa.test_id and l.qid = lqa.qid ORDER BY qid ASC', (testid, email))
		callresults = cur.fetchall()
		cur.close()
		return render_template("insertsubmarks.html", callresults = callresults)
	if request.method == "POST":
		cur = mysql.connection.cursor()
		results1 = cur.execute('SELECT COUNT(qid) from longtest where test_id = %s and email = %s',(testid, email))
		results1 = cur.fetchone()
		cur.close()
		for sa in range(1,results1['COUNT(qid)']+1):
			marksByProfessor = request.form[str(sa)]
			cur = mysql.connection.cursor()
			cur.execute('UPDATE longtest SET marks = %s WHERE test_id = %s and email = %s and qid = %s', (marksByProfessor, testid, email, sa))
			mysql.connection.commit()
		cur.close()
		try:
			cur_user = mysql.connection.cursor()
			cur_user.execute('SELECT uid FROM users WHERE email = %s AND user_type = %s', (email, 'student'))
			student_row = cur_user.fetchone()
			cur_user.close()
			if student_row:
				save_exam_result(email, testid, student_row['uid'])
		except Exception as err:
			flash(f'Marks saved, but result refresh failed: {err}', 'danger')
			return redirect(url_for('insertmarkstid'))
		flash('Marks Entered Sucessfully!', 'success')
		return redirect(url_for('insertmarkstid'))

@app.route('/insertpracmarks/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def insertpracmarks(testid,email):
	if request.method == "GET":
		cur = mysql.connection.cursor()
		cur.execute('SELECT l.email as email, l.marks as inputmarks, l.test_id as test_id, l.qid as qid, l.code as code, l.input as input, l.executed as executed, lqa.marks as marks, l.uid as uid, lqa.q as q  from practicaltest l, practicalqa lqa where l.test_id = %s and l.email = %s and l.test_id = lqa.test_id and l.qid = lqa.qid ORDER BY qid ASC', (testid, email))
		callresults = cur.fetchall()
		cur.close()
		return render_template("insertpracmarks.html", callresults = callresults)
	if request.method == "POST":
		cur = mysql.connection.cursor()
		results1 = cur.execute('SELECT COUNT(qid) from practicaltest where test_id = %s and email = %s',(testid, email))
		results1 = cur.fetchone()
		cur.close()
		for sa in range(1,results1['COUNT(qid)']+1):
			marksByProfessor = request.form[str(sa)]
			cur = mysql.connection.cursor()
			cur.execute('UPDATE practicaltest SET marks = %s WHERE test_id = %s and email = %s and qid = %s', (marksByProfessor, testid, email, sa))
			mysql.connection.commit()
		cur.close()
		try:
			cur_user = mysql.connection.cursor()
			cur_user.execute('SELECT uid FROM users WHERE email = %s AND user_type = %s', (email, 'student'))
			student_row = cur_user.fetchone()
			cur_user.close()
			if student_row:
				save_exam_result(email, testid, student_row['uid'])
		except Exception as err:
			flash(f'Marks saved, but result refresh failed: {err}', 'danger')
			return redirect(url_for('insertmarkstid'))
		flash('Marks Entered Sucessfully!', 'success')
		return redirect(url_for('insertmarkstid'))

def displaywinstudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from window_estimation_log where test_id = %s and email = %s and window_event = 1', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return callresults

def countwinstudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT COUNT(*) as wincount from window_estimation_log where test_id = %s and email = %s and window_event = 1', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	winc = [i['wincount'] for i in callresults]
	return winc

def countMobStudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT COUNT(*) as mobcount from proctoring_log where test_id = %s and email = %s and phone_detection = 1', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	mobc = [i['mobcount'] for i in callresults]
	return mobc

def countMTOPstudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT COUNT(*) as percount from proctoring_log where test_id = %s and email = %s and person_status = 2', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	perc = [i['percount'] for i in callresults]
	return perc

def countTotalstudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT COUNT(*) as total from proctoring_log where test_id = %s and email = %s', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	tot = [i['total'] for i in callresults]
	return tot


def _prepare_proctoring_log_rows(rows, testid):
	for row in rows:
		try:
			metadata = json.loads(row.get('event_data') or '{}')
		except (TypeError, ValueError):
			metadata = {}
		row['event_names'] = ', '.join(
			str(event.get('event_type', '')).replace('_', ' ')
			for event in metadata.get('events', [])
			if isinstance(event, dict) and event.get('event_type')
		)
		evidence_file = row.get('evidence_file')
		row['evidence_url'] = (
			url_for(
				'proctoring_evidence',
				testid=testid,
				filename=str(evidence_file).split('/')[-1],
			)
			if evidence_file else None
		)
	return rows

@app.route('/studentmonitoringstats/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def studentmonitoringstats(testid,email):
	return render_template("stat_student_monitoring.html", testid = testid, email = email)

@app.route('/ajaxstudentmonitoringstats/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def ajaxstudentmonitoringstats(testid,email):
	win = countwinstudentslogs(testid,email)
	mob = countMobStudentslogs(testid,email)
	per = countMTOPstudentslogs(testid,email)
	tot = countTotalstudentslogs(testid,email)
	return jsonify({"win":win,"mob":mob,"per":per,"tot":tot})

@app.route('/displaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def displaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1', (testid, session['uid']))
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
		cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s', (testid, email))
		callresults = _prepare_proctoring_log_rows(cur.fetchall(), testid)
	finally:
		cur.close()
	return render_template("displaystudentslogs.html", testid = testid, email = email, callresults = callresults)

@app.route('/mobdisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def mobdisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1', (testid, session['uid']))
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
		cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s and phone_detection = 1', (testid, email))
		callresults = _prepare_proctoring_log_rows(cur.fetchall(), testid)
	finally:
		cur.close()
	return render_template("mobdisplaystudentslogs.html", testid = testid, email = email, callresults = callresults)

@app.route('/persondisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def persondisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1', (testid, session['uid']))
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
		cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s and person_status = 2', (testid, email))
		callresults = _prepare_proctoring_log_rows(cur.fetchall(), testid)
	finally:
		cur.close()
	return render_template("persondisplaystudentslogs.html",testid = testid, email = email, callresults = callresults)

@app.route('/audiodisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def audiodisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	try:
		_ensure_proctoring_audio_column()
		cur.execute(
			'SELECT name, voice_db, audio_evidence, log_time '
			'FROM proctoring_log WHERE test_id = %s AND email = %s ORDER BY log_time DESC',
			(testid, email),
		)
		callresults = cur.fetchall()
		audio_recordings = [row for row in callresults if row.get('audio_evidence')]
		return render_template(
			"audiodisplaystudentslogs.html",
			testid=testid,
			email=email,
			callresults=audio_recordings,
		)
	except Exception:
		app.logger.exception('Audio evidence page failed: exam=%s email=%s', testid, email)
		raise
	finally:
		cur.close()

@app.route('/wineventstudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def wineventstudentslogs(testid,email):
	callresults = displaywinstudentslogs(testid,email)
	return render_template("wineventstudentlog.html", testid = testid, email = email, callresults = callresults)

@app.route('/<email>/<testid>/share_details', methods=['GET','POST'])
@user_role_professor
def share_details(testid,email):
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			'SELECT test_id, subject, topic, duration, `start`, `end`, password, neg_marks, calc '
			'FROM teachers WHERE test_id = %s AND uid = %s',
			(testid, session['uid']),
		)
		callresults = cur.fetchall()
	finally:
		cur.close()
	if not callresults:
		flash('Exam not found.', 'danger')
		return redirect(url_for('disptests', email=session['email']))
	return render_template("share_details.html", callresults = callresults)

@app.route('/share_details_emails', methods=['POST'])
@user_role_professor
def share_details_emails():
	tid = request.form.get('tid', '').strip()
	cur = mysql.connection.cursor()
	try:
		cur.execute(
			'SELECT test_id, subject, topic, duration, `start`, `end`, password, neg_marks, calc '
			'FROM teachers WHERE test_id = %s AND uid = %s',
			(tid, session['uid']),
		)
		exam = cur.fetchone()
	finally:
		cur.close()
	if not exam:
		flash('Exam not found.', 'danger')
		return redirect(url_for('disptests', email=session['email']))

	recipients = list(dict.fromkeys(
		address.strip()
		for address in request.form.get('emailssharelist', '').split(',')
		if address.strip()
	))
	email_pattern = re.compile(
		r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
		r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
		r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
	)
	if not recipients or any(
		len(address) > 254 or not email_pattern.fullmatch(address)
		for address in recipients
	):
		flash('Enter valid student email addresses separated by commas.', 'danger')
		return redirect(url_for(
			'share_details',
			email=session['email'],
			testid=tid,
		))

	details = [
		('TEST ID', str(exam['test_id'])),
		('SUBJECT', str(exam.get('subject') or '')),
		('TOPIC', str(exam.get('topic') or '')),
		('DURATION', f"{exam.get('duration') or ''} sec"),
		('START', str(exam.get('start') or '')),
		('END', str(exam.get('end') or '')),
		('PASSWORD', str(exam.get('password') or '')),
		('NEGATIVE MARKS', f"{exam.get('neg_marks') or 0} %"),
		('CALCULATOR ALLOWED', 'YES' if int(exam.get('calc') or 0) == 1 else 'NO'),
	]
	message = Message(
		'EXAM DETAILS - SafeExam',
		sender=sender,
		bcc=recipients,
	)
	message.body = 'EXAM DETAILS - SafeExam\n\n' + '\n'.join(
		f'{label}: {value}' for label, value in details
	)
	table_rows = ''.join(
		'<tr>'
		'<th scope="row" style="padding:12px;text-align:left;font-weight:400;'
		'border-bottom:1px solid #d8dee8;">'
		f'{escape(label)}</th>'
		'<td style="padding:12px;border-bottom:1px solid #d8dee8;">'
		f'{escape(value)}</td>'
		'</tr>'
		for label, value in details
	)
	message.html = (
		'<!doctype html><html><body style="margin:0;padding:24px;'
		'font-family:Arial,Helvetica,sans-serif;color:#172b4d;">'
		'<h2 style="margin:0 0 16px;font-size:20px;font-weight:500;">'
		'EXAM DETAILS - SafeExam</h2>'
		'<table role="presentation" cellpadding="0" cellspacing="0" '
		'style="width:100%;max-width:640px;border-collapse:collapse;'
		'border-top:1px solid #d8dee8;">'
		f'{table_rows}'
		'</table></body></html>'
	)
	try:
		mail.send(message)
	except Exception:
		app.logger.exception(
			'Could not send exam details: exam=%s professor_uid=%s recipient_count=%s',
			tid, session['uid'], len(recipients),
		)
		flash('Could not send exam details. Check the email settings and try again.', 'danger')
	else:
		flash(f'Exam details sent to {len(recipients)} student(s).', 'success')
	return redirect(url_for(
		'share_details',
		email=session['email'],
		testid=tid,
	))

@app.route('/test_update_time', methods=['GET','POST'])
@user_role_student
def test_update_time():
	if request.method == 'POST':
		cur = mysql.connection.cursor()
		time_left = request.form['time']
		testid = request.form['testid']
		cur.execute('UPDATE studentTestInfo set time_left=SEC_TO_TIME(%s) where test_id = %s and email = %s and uid = %s and completed=0', (time_left, testid, session['email'], session['uid']))
		mysql.connection.commit()
		t1 = cur.rowcount
		cur.close()
		if t1 > 0:
			return "time recorded updated"
		else:
			cur = mysql.connection.cursor()
			cur.execute('INSERT into studentTestInfo (email, test_id,time_left,uid) values(%s,%s,SEC_TO_TIME(%s),%s)', (session['email'], testid, time_left, session['uid']))
			t2 = mysql.connection.commit()
			t2 = cur.rowcount
			cur.close()
			if t2 > 0:
				return "time recorded inserted"
			else:
				return "time error"

def _secure_request_payload():
	return request.get_json(silent=True) or request.form.to_dict() or {}


def _secure_exam_context(testid):
	"""Return exam owner and policy without trusting a client-provided policy."""
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT uid FROM teachers WHERE test_id = %s LIMIT 1', (testid,))
		exam = cur.fetchone()
		if not exam:
			return None, None
		return exam['uid'], secure_exam.policy_for_exam(testid, exam['uid'])
	finally:
		cur.close()


def _complete_secure_exam_session(testid):
	"""Release the secure session only after the normal exam submission succeeds."""
	session_id = session.get('secure_exam_session_id')
	if not session_id:
		return
	secure_session = secure_exam.session_for_student(session_id, testid, session['email'], session['uid'])
	if secure_session and secure_session['status'] in ('active', 'paused'):
		secure_exam.record_event(session_id, testid, session['email'], 'EXAM_SUBMITTED', 'server',
			'Exam submission was confirmed by the application.')
		secure_exam.end_session(session_id, 'submitted')


@app.route('/secure-exam/<testid>')
@user_role_student
def secure_exam_readiness(testid):
	professor_uid, policy = _secure_exam_context(testid)
	if professor_uid is None:
		flash('Invalid exam ID.', 'danger')
		return redirect(url_for('give_test'))
	return render_template('secure_exam_readiness.html', testid=testid, policy=policy)


@app.route('/api/secure-exam/<testid>/readiness', methods=['GET'])
@user_role_student
def secure_exam_readiness_api(testid):
	professor_uid, policy = _secure_exam_context(testid)
	if professor_uid is None:
		return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
	return jsonify({'status': 'success', 'policy': policy, 'native_client_required': bool(policy['requireNativeClient'])})


@app.route('/api/secure-exam/<testid>/start', methods=['POST'])
@user_role_student
def secure_exam_start(testid):
	payload = _secure_request_payload()
	professor_uid, policy = _secure_exam_context(testid)
	if professor_uid is None:
		return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
	readiness = payload.get('readiness') or {}
	if policy['requireFullscreen'] and not readiness.get('fullscreenAvailable'):
		return jsonify({'status': 'blocked', 'message': 'Fullscreen must be enabled before the exam can start.'}), 409
	if policy['requireNativeClient'] and not readiness.get('nativeClientVerified'):
		return jsonify({'status': 'blocked', 'message': 'This exam requires the Secure Exam Client. A normal browser cannot enforce this policy.'}), 409
	client_info = payload.get('client') or {}
	secure_session_id, resumed = secure_exam.start_or_resume(
		testid, session['email'], session['uid'], policy, client_info, readiness
	)
	session['secure_exam_session_id'] = secure_session_id
	session['secure_exam_policy'] = policy
	return jsonify({
		'status': 'success', 'sessionId': secure_session_id, 'resumed': resumed,
		'examUrl': url_for('test', testid=testid), 'policy': policy,
	})


@app.route('/api/secure-exam/<testid>/heartbeat', methods=['POST'])
@user_role_student
def secure_exam_heartbeat(testid):
	payload = _secure_request_payload()
	session_id = payload.get('sessionId') or session.get('secure_exam_session_id')
	secure_session = secure_exam.session_for_student(session_id, testid, session['email'], session['uid']) if session_id else None
	if not secure_session:
		return jsonify({'status': 'error', 'message': 'Secure exam session not found.'}), 404
	secure_exam.heartbeat(session_id)
	return jsonify({'status': 'success', 'action': 'continue', 'sessionStatus': secure_session['status']})


@app.route('/api/secure-exam/<testid>/events', methods=['POST'])
@user_role_student
def secure_exam_event(testid):
	payload = _secure_request_payload()
	session_id = payload.get('sessionId') or session.get('secure_exam_session_id')
	secure_session = secure_exam.session_for_student(session_id, testid, session['email'], session['uid']) if session_id else None
	if not secure_session or secure_session['status'] not in ('active', 'paused'):
		return jsonify({'status': 'error', 'message': 'Secure exam session is not active.'}), 409
	event_type = str(payload.get('eventType') or '').upper()
	if event_type not in EVENT_SEVERITY:
		return jsonify({'status': 'error', 'message': 'Unsupported security event.'}), 400
	policy = secure_exam.normalize_policy(secure_session['policy_snapshot'])
	explanation = str(payload.get('explanation') or 'A secure exam event was detected.')
	severity = secure_exam.record_event(session_id, testid, session['email'], event_type,
		str(payload.get('source') or 'browser'), explanation, payload.get('metadata') or {})
	warnings = secure_exam.warning_count(session_id)
	action = 'continue'
	if severity == 'CRITICAL' and policy['criticalAction'] in ('lock', 'pause'):
		action = policy['criticalAction']
		secure_exam.end_session(session_id, 'paused')
	elif warnings >= policy['maxWarnings'] and policy['criticalAction'] in ('lock', 'pause'):
		action = policy['criticalAction']
		secure_exam.record_event(session_id, testid, session['email'], 'SECURITY_LOCK', 'server',
			'Configured warning threshold reached.', {'warningCount': warnings}, 'CRITICAL')
		secure_exam.end_session(session_id, 'paused')
	return jsonify({'status': 'success', 'severity': severity, 'warnings': warnings, 'action': action})


@app.route('/api/secure-exam/<testid>/emergency-exit', methods=['POST'])
@user_role_student
def secure_exam_emergency_exit(testid):
	payload = _secure_request_payload()
	session_id = payload.get('sessionId') or session.get('secure_exam_session_id')
	secure_session = secure_exam.session_for_student(session_id, testid, session['email'], session['uid']) if session_id else None
	if not secure_session:
		return jsonify({'status': 'error', 'message': 'Secure exam session not found.'}), 404
	reason = str(payload.get('reason') or 'Other')
	secure_exam.record_event(session_id, testid, session['email'], 'EMERGENCY_EXIT', 'student',
		'Emergency exit requested: ' + reason, {'reason': reason})
	secure_exam.end_session(session_id, 'paused')
	return jsonify({'status': 'success', 'message': 'Your exam was paused and the emergency exit was recorded.'})


@app.route('/api/secure-exam/<testid>/end', methods=['POST'])
@user_role_student
def secure_exam_end(testid):
	# A browser is not trusted to claim that answers were submitted. The normal
	# server-side answer handlers call _complete_secure_exam_session after saving.
	return jsonify({'status': 'accepted', 'message': 'Secure session closes after server-confirmed submission.'})


@app.route('/secure-exam-dashboard/<testid>')
@user_role_professor
def secure_exam_dashboard(testid):
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1', (testid, session['uid']))
		if not cur.fetchone():
			flash('Exam not found.', 'danger')
			return redirect(url_for('professor_dashboard'))
		policy = secure_exam.policy_for_exam(testid, session['uid'])
		cur.execute("""
			SELECT e.*, s.status AS session_status FROM secure_exam_events e
			JOIN secure_exam_sessions s ON s.secure_session_id = e.secure_session_id
			WHERE e.exam_id = %s ORDER BY e.created_at DESC LIMIT 200
		""", (testid,))
		events = cur.fetchall()
		return render_template('secure_exam_dashboard.html', testid=testid, policy=policy, events=events)
	finally:
		cur.close()


@app.route('/api/secure-exam/<testid>/policy', methods=['GET', 'POST'])
@user_role_professor
def secure_exam_policy_api(testid):
	cur = mysql.connection.cursor()
	try:
		cur.execute('SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1', (testid, session['uid']))
		if not cur.fetchone():
			return jsonify({'status': 'error', 'message': 'Exam not found.'}), 404
	finally:
		cur.close()
	if request.method == 'POST':
		policy = secure_exam.save_policy(testid, session['uid'], _secure_request_payload().get('policy') or _secure_request_payload())
		return jsonify({'status': 'success', 'policy': policy})
	return jsonify({'status': 'success', 'policy': secure_exam.policy_for_exam(testid, session['uid'])})


@app.route("/give-test", methods = ['GET', 'POST'])
@user_role_student
def give_test():
	global duration, marked_ans, calc, subject, topic, proctortype
	form = TestForm(request.form)
	if request.method == 'POST' and form.validate():
		test_id = form.test_id.data
		password_candidate = form.password.data
		imgdata1 = form.img_hidden_form.data
		
		cur1 = mysql.connection.cursor()
		results1 = cur1.execute('SELECT user_image from users where email = %s and user_type = %s ', (session['email'],'student'))
		if results1 > 0:
			cresults = cur1.fetchone()
			imgdata2 = cresults['user_image']
			cur1.close()
			
			# Perform face match verification
			face_verified = True
			if _fv and imgdata1 and imgdata2:
				try:
					match_res = _fv.verify_face_match_result(imgdata1, imgdata2)
					if not match_res.get('ok', False):
						# Fall back to checking if image data is valid face capture
						face_verified = match_res.get('score', 0) >= 40.0
						if not face_verified:
							flash(match_res.get('message', 'Face Verification Failed. Please ensure clear lighting.'), 'danger')
							return redirect(url_for('give_test'))
				except Exception as fv_err:
					app.logger.warning("Face verification error in give_test: %s", fv_err)
					face_verified = True
			
			if face_verified:
				cur = mysql.connection.cursor()
				results = cur.execute('SELECT * from teachers where test_id = %s', [test_id])
				if results > 0:
					data = cur.fetchone()
					password = data['password']
					duration = data['duration']
					calc = data['calc']
					subject = data['subject']
					topic = data['topic']
					start_raw = data['start']
					end_raw = data['end']
					proctortype = data['proctoring_type']
					
					if str(password).strip() == str(password_candidate).strip():
						now = exam_schedule_now()
						def _to_dt(val):
							if isinstance(val, datetime):
								return val
							val_str = str(val).split('.')[0]
							for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
								try:
									return datetime.strptime(val_str, fmt)
								except (ValueError, TypeError):
									pass
							return now

						start_dt = _to_dt(start_raw)
						end_dt = _to_dt(end_raw)
						
						# Allow a five-minute clock-skew buffer when checking the start time.
						if exam_window_is_open(start_dt, end_dt, now):
							results = cur.execute('SELECT time_to_sec(time_left) as time_left, completed from studentTestInfo where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
							marked_ans = {}
							if results > 0:
								row_info = cur.fetchone()
								is_completed = row_info['completed']
								if is_completed == 1:
									flash('You have already completed this exam.', 'warning')
									return redirect(url_for('give_test'))
								time_left = row_info['time_left']
								if time_left and time_left <= duration:
									duration = time_left
									results = cur.execute('SELECT qid, ans from students where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
									if results > 0:
										for row in cur.fetchall():
											marked_ans[str(row['qid'])] = row['ans']
							else:
								cur.execute('INSERT into studentTestInfo (email, test_id, time_left, uid) values(%s, %s, SEC_TO_TIME(%s), %s)', (session['email'], test_id, duration, session['uid']))
								mysql.connection.commit()
							
							cur.close()
							
							# Persist exam metadata into session to prevent reload state loss
							session['current_exam'] = {
								'test_id': test_id,
								'duration': duration,
								'calc': calc,
								'subject': subject,
								'topic': topic,
								'proctortype': proctortype,
								'marked_ans': json.dumps(marked_ans) if isinstance(marked_ans, dict) else marked_ans
							}
							return redirect(url_for('secure_exam_readiness', testid=test_id))
						else:
							cur.close()
							if start_dt > now:
								flash(f'Exam start time is scheduled for {start_dt.strftime("%Y-%m-%d %H:%M")}', 'warning')
							else:
								flash('This exam window has closed.', 'danger')
							return redirect(url_for('give_test'))
					else:
						cur.close()
						flash('Invalid exam password. Please try again.', 'danger')
						return redirect(url_for('give_test'))
				else:
					cur.close()
					flash('Invalid Exam ID. Please check the ID provided by your instructor.', 'danger')
					return redirect(url_for('give_test'))
		else:
			cur1.close()
			flash('Student record not found.', 'danger')
			return redirect(url_for('give_test'))

	return render_template('give_test.html', form = form)

@app.route('/give-test/<testid>', methods=['GET','POST'])
@user_role_student
def test(testid):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from teachers where test_id = %s ', [testid])
	exam_row = cur.fetchone()
	cur.close()
	if not exam_row:
		flash('Exam not found.', 'danger')
		return redirect(url_for('give_test'))

	if exam_row['test_type'] == "objective":
		global duration, marked_ans, calc, subject, topic, proctortype
		exam_state = session.get('current_exam', {})
		
		# Fallback to database values if session state is missing or empty
		ex_duration = exam_state.get('duration') or duration or exam_row.get('duration', 1800)
		ex_calc = exam_state.get('calc') or calc or exam_row.get('calc', 0)
		ex_subject = exam_state.get('subject') or subject or exam_row.get('subject', '')
		ex_topic = exam_state.get('topic') or topic or exam_row.get('topic', '')
		ex_proctortype = exam_state.get('proctortype')
		if ex_proctortype is None:
			ex_proctortype = proctortype if proctortype is not None else exam_row.get('proctoring_type', 0)
		ex_answers = exam_state.get('marked_ans') or (marked_ans if isinstance(marked_ans, str) else json.dumps(marked_ans or {}))

		if request.method == 'GET':
			data = {'duration': ex_duration, 'marks': '', 'q': '', 'a': '', 'b':'','c':'','d':'' }
			return render_template('testquiz.html', **data, answers=ex_answers, calc=ex_calc, subject=ex_subject, topic=ex_topic, tid=testid, proctortype=ex_proctortype)
		else:
			cur = mysql.connection.cursor()
			flag = request.form.get('flag')
			if flag == 'start':
				try:
					cur.execute(
						'SELECT qid, q, a, b, c, d, marks FROM questions'
						' WHERE test_id = %s',
						(testid,),
					)
					question_rows = cur.fetchall()
					question_ids, questions = student_safe_question_payload(question_rows)
					random.shuffle(question_ids)
					cur.close()
					return jsonify({'ids': question_ids, 'questions': questions})
				except Exception:
					cur.close()
					app.logger.exception(
						'Exam question preload failed: test=%s uid=%s',
						testid, session.get('uid'),
					)
					return jsonify({
						'status': 'error',
						'message': 'Could not load exam questions. Please retry.',
					}), 500
			if flag == 'get':
				num = request.form['no']
				results = cur.execute('SELECT test_id,qid,q,a,b,c,d,ans,marks from questions where test_id = %s and qid =%s',(testid, num))
				if results > 0:
					data = cur.fetchone()
					del data['ans']
					cur.close()
					return json.dumps(data)
			elif flag=='mark':
				qid = request.form.get('qid')
				ans = request.form.get('ans')
				if not qid:
					cur.close()
					return jsonify({'status': 'error', 'message': 'Missing qid'}), 400
				try:
					if not ans:
						cur.execute(
							'DELETE FROM students WHERE test_id = %s AND qid = %s'
							' AND email = %s AND uid = %s',
							(testid, str(qid), session['email'], session['uid']),
						)
						mysql.connection.commit()
						rowcount = cur.rowcount
						action = 'deleted'
					else:
						save_student_answer(
							cur, session['email'], testid, session['uid'],
							str(qid), ans,
						)
						action = 'saved'
						rowcount = cur.rowcount
						mysql.connection.commit()
					app.logger.info('Answer %s: uid=%s email=%s test=%s qid=%s', action, session['uid'], session['email'], testid, qid)
					return jsonify({'status': 'success', 'action': action, 'rows': rowcount})
				except Exception as e:
					mysql.connection.rollback()
					app.logger.exception('Answer save error: uid=%s test=%s qid=%s: %s', session.get('uid'), testid, qid, e)
					return jsonify({'status': 'error', 'message': f'Failed to save answer: {e}'}), 500
				finally:
					cur.close()
			elif flag=='time':
				cur = mysql.connection.cursor()
				time_left = request.form['time']
				try:
					cur.execute('UPDATE studentTestInfo set time_left=SEC_TO_TIME(%s) where test_id = %s and email = %s and uid = %s and completed=0', (time_left, testid, session['email'], session['uid']))
					mysql.connection.commit()
					cur.close()
					return json.dumps({'time':'fired'})
				except:
					pass
			else:
				cur = mysql.connection.cursor()
				try:
					# Persist the complete client payload before calculating the result.
					submitted_answers_raw = request.form.get('answers')
					try:
						submitted_answers = json.loads(submitted_answers_raw or '{}')
					except json.JSONDecodeError as decode_err:
						raise ValueError(f'Invalid submitted answers: {decode_err}') from decode_err
					saved_answers = save_submitted_answers(
						cur, session['email'], testid, session['uid'], submitted_answers
					)

					cur.execute('UPDATE studentTestInfo set completed=1,time_left=sec_to_time(0) where test_id = %s and email = %s and uid = %s', (testid, session['email'],session['uid']))
					mysql.connection.commit()
					rows = cur.rowcount
					app.logger.info('Answers persisted: exam_id=%s student_id=%s submitted=%s', testid, session['uid'], saved_answers)
				except Exception:
					mysql.connection.rollback()
					app.logger.exception('Exam answer persistence failed: exam_id=%s student_id=%s', testid, session.get('uid'))
					return jsonify({'status': 'error', 'message': 'Could not save submitted answers. Please try again.'}), 500
				finally:
					cur.close()

				try:
					result_payload = save_exam_result(session['email'], testid, session['uid'])
				except Exception as err:
					app.logger.exception('Exam submission result calculation failed: uid=%s email=%s test=%s: %s', session.get('uid'), session.get('email'), testid, err)
					return jsonify({'status': 'error', 'message': 'Result calculation failed. Please contact your instructor.'}), 500

				_complete_secure_exam_session(testid)
				app.logger.info(
					'Exam completed: uid=%s email=%s test=%s marks=%s/%s percentage=%s%% rows=%s',
					session['uid'], session['email'], testid,
					result_payload.get('marks'), result_payload.get('total_marks'), result_payload.get('percentage'), rows
				)
				flash("Exam submitted successfully", 'info')
				redirect_url = url_for('tests_given', email=session['email'])
				return jsonify({'status':'success', 'completed': True, 'rows': rows, 'result': result_payload, 'redirect_url': redirect_url})

	elif callresults['test_type'] == "subjective":
		if request.method == 'GET':
			cur = mysql.connection.cursor()
			cur.execute('SELECT test_id, qid, q, marks from longqa where test_id = %s ORDER BY RAND()',[testid])
			callresults1 = cur.fetchall()
			cur.execute('SELECT time_to_sec(time_left) as duration from studentTestInfo where completed = 0 and test_id = %s and email = %s and uid = %s', (testid, session['email'], session['uid']))
			studentTestInfo = cur.fetchone()
			if studentTestInfo != None:
				duration = studentTestInfo['duration']
				cur.execute('SELECT test_id, subject, topic, proctoring_type from teachers where test_id = %s',[testid])
				testDetails = cur.fetchone()
				subject = testDetails['subject']
				test_id = testDetails['test_id']
				topic = testDetails['topic']
				proctortypes = testDetails['proctoring_type']
				cur.close()
				return render_template("testsubjective.html", callresults = callresults1, subject = subject, duration = duration, test_id = test_id, topic = topic, proctortypes = proctortypes )
			else:
				cur = mysql.connection.cursor()
				cur.execute('SELECT test_id, duration, subject, topic from teachers where test_id = %s',[testid])
				testDetails = cur.fetchone()
				subject = testDetails['subject']
				duration = testDetails['duration']
				test_id = testDetails['test_id']
				topic = testDetails['topic']
				cur.close()
				return render_template("testsubjective.html", callresults = callresults1, subject = subject, duration = duration, test_id = test_id, topic = topic )
		elif request.method == 'POST':
			cur = mysql.connection.cursor()
			test_id = request.form["test_id"]
			cur = mysql.connection.cursor()
			results1 = cur.execute('SELECT COUNT(qid) from longqa where test_id = %s',[testid])
			results1 = cur.fetchone()
			cur.close()
			insertStudentData = None
			for sa in range(1,results1['COUNT(qid)']+1):
				answerByStudent = request.form[str(sa)]
				cur = mysql.connection.cursor()
				insertStudentData = cur.execute('INSERT INTO longtest(email,test_id,qid,ans,uid) values(%s,%s,%s,%s,%s)', (session['email'], testid, sa, answerByStudent, session['uid']))
				mysql.connection.commit()
			else:
				if insertStudentData > 0:
					insertStudentTestInfoData = cur.execute('UPDATE studentTestInfo set completed = 1 where test_id = %s and email = %s and uid = %s', (test_id, session['email'], session['uid']))
					mysql.connection.commit()
					cur.close()
					if insertStudentTestInfoData > 0:
						try:
							save_exam_result(session['email'], testid, session['uid'])
						except Exception as err:
							app.logger.exception('Subjective result save failed: exam_id=%s student_id=%s', testid, session.get('uid'))
							flash('Result calculation failed. Please contact your instructor.', 'danger')
							return redirect(url_for('student_index'))
						_complete_secure_exam_session(testid)
						flash('Successfully Exam Submitted', 'success')
						return redirect(url_for('tests_given', email=session['email']))
					else:
						cur.close()
						flash('Some Error was occured!', 'error')
						return redirect(url_for('student_index'))	
				else:
					cur.close()
					flash('Some Error was occured!', 'error')
					return redirect(url_for('student_index'))

	elif callresults['test_type'] == "practical":
		if request.method == 'GET':
			cur = mysql.connection.cursor()
			cur.execute('SELECT test_id, qid, q, marks, compiler from practicalqa where test_id = %s ORDER BY RAND()',[testid])
			callresults1 = cur.fetchall()
			cur.execute('SELECT time_to_sec(time_left) as duration from studentTestInfo where completed = 0 and test_id = %s and email = %s and uid = %s', (testid, session['email'], session['uid']))
			studentTestInfo = cur.fetchone()
			if studentTestInfo != None:
				duration = studentTestInfo['duration']
				cur.execute('SELECT test_id, subject, topic, proctoring_type from teachers where test_id = %s',[testid])
				testDetails = cur.fetchone()
				subject = testDetails['subject']
				test_id = testDetails['test_id']
				topic = testDetails['topic']
				proctortypep = testDetails['proctoring_type']
				cur.close()
				return render_template("testpractical.html", callresults = callresults1, subject = subject, duration = duration, test_id = test_id, topic = topic, proctortypep = proctortypep )
			else:
				cur = mysql.connection.cursor()
				cur.execute('SELECT test_id, duration, subject, topic from teachers where test_id = %s',[testid])
				testDetails = cur.fetchone()
				subject = testDetails['subject']
				duration = testDetails['duration']
				test_id = testDetails['test_id']
				topic = testDetails['topic']
				cur.close()
				return render_template("testpractical.html", callresults = callresults1, subject = subject, duration = duration, test_id = test_id, topic = topic )
		elif request.method == 'POST':
			test_id = request.form["test_id"]
			codeByStudent = request.form["codeByStudent"]
			inputByStudent = request.form["inputByStudent"]
			executedByStudent = request.form["executedByStudent"]
			cur = mysql.connection.cursor()
			insertStudentData = cur.execute('INSERT INTO practicaltest(email,test_id,qid,code,input,executed,uid) values(%s,%s,%s,%s,%s,%s,%s)', (session['email'], testid, "1", codeByStudent, inputByStudent, executedByStudent, session['uid']))
			mysql.connection.commit()
			if insertStudentData > 0:
				insertStudentTestInfoData = cur.execute('UPDATE studentTestInfo set completed = 1 where test_id = %s and email = %s and uid = %s', (test_id, session['email'], session['uid']))
				mysql.connection.commit()
				cur.close()
				if insertStudentTestInfoData > 0:
					try:
						save_exam_result(session['email'], testid, session['uid'])
					except Exception as err:
						app.logger.exception('Practical result save failed: exam_id=%s student_id=%s', testid, session.get('uid'))
						flash('Result calculation failed. Please contact your instructor.', 'danger')
						return redirect(url_for('student_index'))
					_complete_secure_exam_session(testid)
					flash('Successfully Exam Submitted', 'success')
					return redirect(url_for('tests_given', email=session['email']))
				else:
					cur.close()
					flash('Some Error was occured!', 'error')
					return redirect(url_for('student_index'))	
			else:
				cur.close()
				flash('Some Error was occured!', 'error')
				return redirect(url_for('student_index'))

@app.route('/randomize', methods = ['POST'])
def random_gen():
	if request.method == "POST":
		id = request.form['id']
		cur = mysql.connection.cursor()
		results = cur.execute('SELECT count(*) from questions where test_id = %s', [id])
		if results > 0:
			data = cur.fetchone()
			total = data['count(*)']
			nos = list(range(1,int(total)+1))
			random.Random(id).shuffle(nos)
			cur.close()
			return json.dumps(nos)

@app.route('/<email>/<testid>')
@user_role_student
def check_result(email, testid):
	if email == session['email']:
		cur = mysql.connection.cursor()
		results = cur.execute('SELECT * FROM teachers where test_id = %s', [testid])
		if results>0:
			results = cur.fetchone()
			check = results['show_ans']
			if check == 1:
				results = cur.execute('select q,a,b,c,d,marks,q.qid as qid, \
					q.ans as correct, ifnull(s.ans,0) as marked from questions q left join \
					students s on  s.test_id = q.test_id and s.test_id = %s \
					and s.email = %s and s.uid = %s and s.qid = q.qid group by q.qid \
					order by LPAD(lower(q.qid),10,0) asc', (testid, email, session['uid']))
				if results > 0:
					results = cur.fetchall()
					return render_template('tests_result.html', results= results)
			else:
				flash('You are not authorized to check the result', 'danger')
				return redirect(url_for('tests_given',email = email))
	else:
		return redirect(url_for('student_index'))

def neg_marks(email,testid,negm):
	cur=mysql.connection.cursor()
	try:
		negm = float(negm or 0)
		results = cur.execute("""
			select q.marks, q.qid as qid, q.ans as correct,
			       ifnull(MAX(s.ans),0) as marked
			from questions q
			left join students s on s.test_id = q.test_id
				and s.email = %s and s.qid = q.qid
			where q.test_id = %s
			group by q.qid, q.marks, q.ans
			order by LPAD(lower(q.qid),10,0) asc
		""", (email, testid))
		data=cur.fetchall()
	finally:
		cur.close()

	total = 0.0
	for row in data:
		marked = str(row.get('marked', '0')).upper()
		correct = str(row.get('correct', '')).upper()
		marks = float(row.get('marks') or 0)
		if marked != '0':
			if marked != correct:
				total -= (negm/100) * marks
			else:
				total += marks
	return total

def totmarks(email,tests): 
	cur = mysql.connection.cursor()
	for test in tests:
		testid = test['test_id']
		results=cur.execute("select neg_marks from teachers where test_id=%s",[testid])
		results=cur.fetchone()
		negm = results['neg_marks']
		data = neg_marks(email,testid,negm)
		return data

def marks_calc(email,testid):
    try:
        cur = mysql.connection.cursor()
        cur.execute("select neg_marks from teachers where test_id=%s",[testid])
        res = cur.fetchone()
        cur.close()
        if res:
            negm = res['neg_marks']
            return neg_marks(email,testid,negm) 
        return 0
    except Exception as e:
        app.logger.error(f"marks_calc Error: {e}")
        return 0
		
@app.route('/<email>/tests-given', methods = ['POST','GET'])
@user_role_student
def tests_given(email):
	if email != session['email']:
		flash('You are not authorized', 'danger')
		return redirect(url_for('student_index'))
	try:
		_ensure_exam_results_table()
		cur = mysql.connection.cursor()
		cur.execute('''
			SELECT * FROM exam_results
			WHERE student_email = %s AND (uid = %s OR student_id = %s)
			ORDER BY submission_time DESC
		''', (session['email'], session['uid'], session['uid']))
		results = cur.fetchall() or []
		cur.close()
		return render_template('tests_given.html', results=results, cresults=results)
	except Exception as e:
		app.logger.exception('Student results load failed for %s: %s', email, e)
		flash(f'Could not load student results: {e}', 'danger')
		return redirect(url_for('student_index'))


@app.route('/api/student-results', methods=['GET'])
@user_role_student
def api_student_results():
	try:
		_ensure_exam_results_table()
		cur = mysql.connection.cursor()
		cur.execute('''
			SELECT * FROM exam_results
			WHERE student_email = %s AND (uid = %s OR student_id = %s)
			ORDER BY submission_time DESC
		''', (session['email'], session['uid'], session['uid']))
		rows = cur.fetchall() or []
		cur.close()
		return jsonify({'status': 'success', 'results': _json_safe_rows(rows)})
	except Exception as e:
		app.logger.exception('api_student_results failed: %s', e)
		return jsonify({'status': 'error', 'message': f'Could not load student results: {e}'}), 500


@app.route('/<email>/tests-created')
@user_role_professor
def tests_created(email):
	if email != session['email']:
		flash('You are not authorized', 'danger')
		return redirect(url_for('professor_index'))
	try:
		_ensure_exam_results_table()
		cur = mysql.connection.cursor()
		cur.execute('''
			SELECT * FROM exam_results
			WHERE professor_id = %s
			ORDER BY submission_time DESC
		''', (session['uid'],))
		results = cur.fetchall() or []
		cur.close()
		return render_template('tests_created.html', results=results, tests=results)
	except Exception as e:
		app.logger.exception('Professor results load failed for %s: %s', email, e)
		flash(f'Could not load professor results: {e}', 'danger')
		return redirect(url_for('professor_index'))


@app.route('/api/professor-results', methods=['GET'])
@user_role_professor
def api_professor_results():
	try:
		_ensure_exam_results_table()
		search = (request.args.get('search') or '').strip()
		date_filter = (request.args.get('date') or '').strip()
		risk_level = (request.args.get('risk_level') or '').strip()
		result_status = (request.args.get('result_status') or '').strip()
		sort_by = (request.args.get('sort_by') or 'submission_time').strip()
		sort_dir = 'ASC' if (request.args.get('sort_dir') or '').lower() == 'asc' else 'DESC'
		where = ['professor_id = %s']
		params = [session['uid']]
		if search:
			like = f'%{search}%'
			where.append('(exam_id LIKE %s OR student_name LIKE %s OR student_email LIKE %s OR subject LIKE %s OR topic LIKE %s)')
			params.extend([like, like, like, like, like])
		if date_filter:
			where.append('DATE(submission_time) = %s')
			params.append(date_filter)
		if risk_level:
			where.append('risk_level = %s')
			params.append(risk_level)
		if result_status:
			where.append('result_status = %s')
			params.append(result_status)
		order_col = 'marks' if sort_by == 'marks' else 'submission_time'
		query = f"SELECT * FROM exam_results WHERE {' AND '.join(where)} ORDER BY {order_col} {sort_dir}"
		cur = mysql.connection.cursor()
		cur.execute(query, params)
		rows = cur.fetchall() or []
		cur.close()
		return jsonify({'status': 'success', 'results': _json_safe_rows(rows)})
	except Exception as e:
		app.logger.exception('api_professor_results failed: %s', e)
		return jsonify({'status': 'error', 'message': f'Could not load professor results: {e}'}), 500


@app.route('/<email>/tests-created/<testid>', methods = ['POST','GET'])
@user_role_professor
def student_results(email, testid):
	if email != session['email']:
		flash('You are not authorized', 'danger')
		return redirect(url_for('professor_index'))
	try:
		_ensure_exam_results_table()
		cur = mysql.connection.cursor()
		cur.execute('''
			SELECT * FROM exam_results
			WHERE professor_id = %s AND exam_id = %s
			ORDER BY marks DESC, submission_time DESC
		''', (session['uid'], testid))
		results = cur.fetchall() or []
		cur.close()
		return render_template('student_results.html', results=results, data=results)
	except Exception as e:
		app.logger.exception('student_results failed for exam=%s: %s', testid, e)
		flash(f'Could not load results: {e}', 'danger')
		return redirect(url_for('tests_created', email=email))

@app.route('/<email>/disptests')
@user_role_professor
def disptests(email):
	if email == session['email']:
		cur = mysql.connection.cursor()
		try:
			cur.execute(
				'SELECT t.*, ('
				't.`end` <= CURRENT_TIMESTAMP '
				'AND NOT EXISTS ('
				'SELECT 1 FROM studenttestinfo sti '
				'WHERE sti.test_id = t.test_id AND sti.uid = t.uid '
				'AND COALESCE(sti.completed, 0) = 0'
				') '
				'AND (SELECT COUNT(*) FROM teachers other '
				'WHERE other.test_id = t.test_id) = 1'
				') AS can_delete '
				'FROM teachers t WHERE t.email = %s AND t.uid = %s',
				(email, session['uid']),
			)
			results = cur.fetchall()
		finally:
			cur.close()
		return render_template('disptests.html', tests=results)
	else:
		flash('You are not authorized', 'danger')
		return redirect(url_for('professor_index'))

@app.route('/<email>/delete_completed_exam/<testid>', methods=['POST'])
@user_role_professor
def delete_completed_exam(email, testid):
	if email != session['email']:
		flash('You are not authorized to delete this exam.', 'danger')
		return redirect(url_for('professor_index'))

	try:
		secure_exam.ensure_tables()
		_ensure_exam_results_table()
		cur = mysql.connection.cursor()
		try:
			cur.execute(
				'SELECT t.test_id, ('
				't.`end` <= CURRENT_TIMESTAMP '
				'AND NOT EXISTS ('
				'SELECT 1 FROM studenttestinfo sti '
				'WHERE sti.test_id = t.test_id AND sti.uid = t.uid '
				'AND COALESCE(sti.completed, 0) = 0'
				') '
				'AND (SELECT COUNT(*) FROM teachers other '
				'WHERE other.test_id = t.test_id) = 1'
				') AS can_delete '
				'FROM teachers t WHERE t.test_id = %s AND t.uid = %s '
				'FOR UPDATE',
				(testid, session['uid']),
			)
			exam = cur.fetchone()
			if not exam or not exam.get('can_delete'):
				mysql.connection.rollback()
				flash(
					'Only completed exams with no unfinished student attempts can be deleted.',
					'warning',
				)
				return redirect(url_for('disptests', email=session['email']))

			cur.execute(
				'SELECT audio_evidence FROM proctoring_log WHERE test_id = %s',
				(testid,),
			)
			audio_files = [
				row.get('audio_evidence')
				for row in (cur.fetchall() or [])
				if row.get('audio_evidence')
			]

			delete_statements = [
				('exam_results', 'exam_id', 'professor_id', session['uid']),
				('longqa', 'test_id', 'uid', session['uid']),
				('practicalqa', 'test_id', 'uid', session['uid']),
				('questions', 'test_id', 'uid', session['uid']),
				('longtest', 'test_id', None, None),
				('practicaltest', 'test_id', None, None),
				('students', 'test_id', None, None),
				('studenttestinfo', 'test_id', None, None),
				('proctoring_log', 'test_id', None, None),
				('window_estimation_log', 'test_id', None, None),
				('secure_exam_events', 'exam_id', None, None),
				('secure_exam_sessions', 'exam_id', None, None),
				('exam_security_policies', 'exam_id', 'professor_uid', session['uid']),
			]
			for table, exam_column, owner_column, owner_uid in delete_statements:
				sql = f'DELETE FROM {table} WHERE {exam_column} = %s'
				params = [testid]
				if owner_column:
					sql += f' AND {owner_column} = %s'
					params.append(owner_uid)
				cur.execute(sql, tuple(params))
			cur.execute(
				'DELETE FROM teachers WHERE test_id = %s AND uid = %s',
				(testid, session['uid']),
			)
			mysql.connection.commit()
		finally:
			cur.close()
	except Exception:
		try:
			mysql.connection.rollback()
		except Exception:
			app.logger.exception('Could not roll back completed exam deletion: %s', testid)
		app.logger.exception(
			'Could not delete completed exam: exam=%s professor_uid=%s',
			testid, session['uid'],
		)
		flash('Could not delete the exam. No exam records were removed.', 'danger')
		return redirect(url_for('disptests', email=session['email']))

	evidence_cleanup_failed = False
	exam_directory = secure_filename(testid)
	if exam_directory == testid and exam_directory:
		evidence_root = Path(_PROCTORING_EVIDENCE_DIR).resolve()
		exam_evidence_dir = (evidence_root / exam_directory).resolve()
		if exam_evidence_dir.parent == evidence_root:
			try:
				shutil.rmtree(exam_evidence_dir, ignore_errors=False)
			except FileNotFoundError:
				pass
			except OSError:
				evidence_cleanup_failed = True
				app.logger.exception(
					'Could not remove proctoring evidence directory for exam=%s',
					testid,
				)

	audio_root = Path(_AUDIO_EVIDENCE_DIR).resolve()
	for audio_file in set(audio_files):
		if secure_filename(audio_file) != audio_file:
			evidence_cleanup_failed = True
			app.logger.error(
				'Skipping unsafe audio evidence path for deleted exam=%s: %s',
				testid, audio_file,
			)
			continue
		audio_path = (audio_root / audio_file).resolve()
		if audio_path.parent != audio_root:
			evidence_cleanup_failed = True
			app.logger.error(
				'Skipping audio evidence path outside storage root for deleted exam=%s',
				testid,
			)
			continue
		try:
			audio_path.unlink(missing_ok=True)
		except OSError:
			evidence_cleanup_failed = True
			app.logger.exception(
				'Could not remove audio evidence for deleted exam=%s',
				testid,
			)

	if evidence_cleanup_failed:
		flash(
			'The exam and its database records were deleted, but some evidence files could not be removed. Check the server logs.',
			'warning',
		)
	else:
		flash(
			'Completed exam and its related records and evidence were permanently deleted.',
			'success',
		)
	return redirect(url_for('disptests', email=session['email']))





@app.route('/<email>/student_test_history')
@user_role_student
def student_test_history(email):
	if email == session['email']:
		cur = mysql.connection.cursor()
		results = cur.execute('SELECT a.test_id, b.subject, b.topic \
			from studenttestinfo a, teachers b where a.test_id = b.test_id and a.email=%s  \
			and a.completed=1', [email])
		results = cur.fetchall()
		return render_template('student_test_history.html', tests=results)
	else:
		flash('You are not authorized', 'danger')
		return redirect(url_for('student_index'))

@app.route('/create_questions', methods=['GET', 'POST'])
@user_role_professor
def create_questions():
    """Manual question creation. Works with or without exam_id."""
    exam_id = str(request.args.get('exam_id') or request.form.get('exam_id') or 'DRAFT').strip()

    # -- POST: save a question -------------------------------------------------
    if request.method == 'POST' and request.form.get('form_action') == 'add_question':
        q_type    = request.form.get('question_type', 'objective').strip()
        question  = request.form.get('question', '').strip()
        marks_raw = request.form.get('marks', '1')

        if not question:
            flash('Question text cannot be empty.', 'danger')
            return redirect(url_for('create_questions', exam_id=exam_id))

        try:
            marks = max(1, int(marks_raw))
        except (ValueError, TypeError):
            marks = 1

        cur = mysql.connection.cursor()
        try:
            if q_type == 'objective':
                option_a = request.form.get('option_a', '').strip()
                option_b = request.form.get('option_b', '').strip()
                option_c = request.form.get('option_c', '').strip()
                option_d = request.form.get('option_d', '').strip()
                correct  = request.form.get('correct_answer', 'A').strip()
                if not option_a or not option_b:
                    flash('Option A and Option B are required.', 'danger')
                    return redirect(url_for('create_questions', exam_id=exam_id))
                cur.execute(
                    'SELECT COALESCE(MAX(CAST(qid AS UNSIGNED)), 0) AS max_qid'
                    ' FROM questions WHERE test_id = %s AND uid = %s',
                    (exam_id, session['uid'])
                )
                next_qid = int(cur.fetchone()['max_qid']) + 1
                cur.execute(
                    'INSERT INTO questions(test_id,qid,q,a,b,c,d,ans,marks,uid)'
                    ' VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (exam_id, next_qid, question, option_a, option_b,
                     option_c, option_d, correct, marks, session['uid'])
                )
                mysql.connection.commit()
                flash('Objective question added successfully!', 'success')
            else:  # subjective
                cur.execute(
                    'SELECT COALESCE(MAX(CAST(qid AS UNSIGNED)), 0) AS max_qid'
                    ' FROM longqa WHERE test_id = %s AND uid = %s',
                    (exam_id, session['uid'])
                )
                next_qid = int(cur.fetchone()['max_qid']) + 1
                cur.execute(
                    'INSERT INTO longqa(test_id,qid,q,marks,uid)'
                    ' VALUES(%s,%s,%s,%s,%s)',
                    (exam_id, next_qid, question, marks, session['uid'])
                )
                mysql.connection.commit()
                flash('Subjective question added successfully!', 'success')
        except Exception as db_err:
            try:
                mysql.connection.rollback()
            except Exception:
                pass
            app.logger.error(f'create_questions DB error: {db_err}')
            flash(f'Database error: {db_err}', 'danger')
        finally:
            try:
                cur.close()
            except Exception:
                pass
        return redirect(url_for('create_questions', exam_id=exam_id))

    # -- GET: render page ------------------------------------------------------
    questions = []
    all_tests = []
    exam_info = None
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            'SELECT test_id, COALESCE(subject,"") AS subject,'
            ' COALESCE(topic,"") AS topic, test_type'
            ' FROM teachers WHERE email = %s AND uid = %s ORDER BY test_id DESC',
            (session['email'], session['uid'])
        )
        all_tests = cur.fetchall() or []
        
        if exam_id and exam_id != 'DRAFT':
            cur.execute(
                'SELECT test_id, COALESCE(subject,"") AS subject,'
                ' COALESCE(topic,"") AS topic, test_type'
                ' FROM teachers WHERE test_id = %s AND uid = %s',
                (exam_id, session['uid'])
            )
            exam_info = cur.fetchone()
        
        # Always fetch questions for the current exam_id (could be 'DRAFT' or a real ID)
        cur.execute(
            'SELECT qid, q AS question, a AS option_a, b AS option_b,'
            ' c AS option_c, d AS option_d, ans AS correct_answer, marks'
            ' FROM questions WHERE test_id = %s AND uid = %s'
            ' ORDER BY CAST(qid AS UNSIGNED)',
            (exam_id, session['uid'])
        )
        for q in (cur.fetchall() or []):
            q['question_type'] = 'objective'
            questions.append(q)
        
        cur.execute(
            'SELECT qid, q AS question, marks'
            ' FROM longqa WHERE test_id = %s AND uid = %s'
            ' ORDER BY CAST(qid AS UNSIGNED)',
            (exam_id, session['uid'])
        )
        for q in (cur.fetchall() or []):
            q['question_type'] = 'subjective'
            q['model_answer']  = ''
            questions.append(q)
            
        cur.close()
    except Exception as get_err:
        app.logger.error(f'create_questions GET error: {get_err}')
        flash('Could not load questions. Check server logs.', 'danger')

    return render_template(
        'professor/create_questions.html',
        questions=questions,
        exam_id=exam_id,
        all_tests=all_tests,
        exam_info=exam_info,
    )

@app.route('/download_questions_csv/<exam_id>/<q_type>')
@user_role_professor
def download_questions_csv(exam_id, q_type):
    try:
        cur = mysql.connection.cursor()
        if q_type == 'objective':
            cur.execute(
                'SELECT qid, q, a, b, c, d, ans, marks'
                ' FROM questions WHERE test_id = %s AND uid = %s'
                ' ORDER BY CAST(qid AS UNSIGNED)',
                (exam_id, session['uid'])
            )
            fields = ['qid', 'q', 'a', 'b', 'c', 'd', 'ans', 'marks']
        else:
            cur.execute(
                'SELECT qid, q, marks'
                ' FROM longqa WHERE test_id = %s AND uid = %s'
                ' ORDER BY CAST(qid AS UNSIGNED)',
                (exam_id, session['uid'])
            )
            fields = ['qid', 'q', 'marks']
        
        results = cur.fetchall()
        cur.close()

        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(fields)
        for row in results:
            # Handle potential None values safely
            row_data = [row.get(field, '') if row.get(field) is not None else '' for field in fields]
            cw.writerow(row_data)
        
        response = Response(si.getvalue(), mimetype='text/csv')
        response.headers["Content-Disposition"] = f"attachment; filename={exam_id}_{q_type}_questions.csv"
        return response
    except Exception as e:
        app.logger.error(f"Download Error: {e}")
        flash(f"Error generating CSV: {e}", "danger")
        return redirect(url_for('create_questions', exam_id=exam_id))

@app.route('/delete_manual_question/<test_id>/<q_type>/<qid>', methods=['POST'])
@user_role_professor
def delete_manual_question(test_id, q_type, qid):
    try:
        cur = mysql.connection.cursor()
        if q_type == 'objective':
            cur.execute(
                'DELETE FROM questions WHERE test_id = %s AND qid = %s AND uid = %s',
                (test_id, qid, session['uid'])
            )
        else:
            cur.execute(
                'DELETE FROM longqa WHERE test_id = %s AND qid = %s AND uid = %s',
                (test_id, qid, session['uid'])
            )
        mysql.connection.commit()
        cur.close()
        flash('Question deleted successfully.', 'success')
    except Exception as e:
        app.logger.error(f"Delete Manual Question Error: {e}")
        flash('Error deleting question.', 'danger')
    return redirect(url_for('create_questions', exam_id=test_id))



# ──────────────────────────────────────────────────────────────
# CHEATING DETECTION REPORT
# ──────────────────────────────────────────────────────────────
@app.route('/cheat_report', methods=['GET', 'POST'])
@user_role_professor
def cheat_report():
    """GET  → show exam picker; POST → show risk report for chosen exam."""
    try:
        cur = mysql.connection.cursor()
        # Fetch only exams belonging to this professor
        cur.execute(
            'SELECT test_id, subject, topic, test_type, MAX(start) as max_start FROM teachers '
            'WHERE email = %s AND uid = %s '
            'GROUP BY test_id, subject, topic, test_type ORDER BY max_start DESC',
            (session['email'], session['uid'])
        )
        exams = cur.fetchall() or []
        cur.close()
    except Exception as e:
        app.logger.error(f'cheat_report – exam fetch error: {e}')
        flash('Could not load exam list. Please try again.', 'danger')
        exams = []

    if request.method == 'GET':
        return render_template('cheat_report_select.html', exams=exams)

    # ── POST: build the risk report ──────────────────────────────
    test_id = request.form.get('test_id', '').strip()
    if not test_id:
        flash('Please choose an exam first.', 'warning')
        return render_template('cheat_report_select.html', exams=exams)
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            'SELECT 1 FROM teachers WHERE test_id = %s AND uid = %s LIMIT 1',
            (test_id, session['uid']),
        )
        if not cur.fetchone():
            flash('Exam not found.', 'danger')
            return render_template('cheat_report_select.html', exams=exams)
    finally:
        cur.close()

    try:
        # Existing databases may predate the evidence migration. Ensure the
        # columns before the report queries evidence_file and event_data.
        _ensure_proctoring_evidence_schema()
        _ensure_proctoring_device_column()
        _ensure_proctoring_audio_column()
        cur = mysql.connection.cursor()

        # 1. Aggregate proctoring_log per student
        cur.execute(
            '''
            SELECT
                email, name,
                SUM(CASE WHEN img_log IS NOT NULL AND img_log NOT IN ('', 'no_camera') THEN 1 ELSE 0 END) AS total_snapshots,
                SUM(phone_detection)                           AS phone_flags,
                SUM(device_detection)                          AS device_flags,
                SUM(CASE WHEN person_status IN (0, 2) THEN 1 ELSE 0 END) AS person_flags,
                SUM(CASE WHEN user_movements_lr   NOT IN (0)  THEN 1 ELSE 0 END) AS head_flags_lr,
                SUM(CASE WHEN user_movements_updown NOT IN (0) THEN 1 ELSE 0 END) AS head_flags_ud,
                SUM(CASE WHEN user_movements_eyes NOT IN (2)  THEN 1 ELSE 0 END) AS eye_flags,
                AVG(voice_db)                                  AS avg_voice_db
            FROM proctoring_log
            WHERE test_id = %s
            GROUP BY email, name
            ''',
            (test_id,)
        )
        proctor_rows = cur.fetchall() or []

        # 2. Aggregate window_estimation_log per student
        cur.execute(
            '''
            SELECT email, transaction_log
            FROM window_estimation_log
            WHERE test_id = %s
            ORDER BY transaction_log
            ''',
            (test_id,)
        )
        tab_rows = {}
        for tab_row in cur.fetchall() or []:
            email = tab_row['email']
            if email not in tab_rows:
                tab_rows[email] = {'email': email, 'tab_switches': 0, 'events': []}
            tab_rows[email]['tab_switches'] += 1
            tab_rows[email]['events'].append(str(tab_row['transaction_log']))

        # 3. Fetch students who completed the exam, even if they only have window logs.
        cur.execute(
            '''
            SELECT sti.email, COALESCE(u.name, sti.email) AS name
            FROM studenttestinfo sti
            LEFT JOIN users u ON u.email = sti.email AND u.user_type = 'student'
            WHERE sti.test_id = %s AND sti.completed = 1
            GROUP BY sti.email, u.name
            ''',
            (test_id,)
        )
        completed_rows = cur.fetchall() or []

        # 4. Fetch all proctoring rows for event_data JSON parsing and snapshot gallery
        cur.execute(
            '''
            SELECT email, img_log, evidence_file, audio_evidence, evidence_status, event_data,
                   user_movements_lr, user_movements_updown,
                   user_movements_eyes, phone_detection, device_detection, person_status,
                   log_time
            FROM proctoring_log
            WHERE test_id = %s
            ORDER BY email, log_time
            ''',
            (test_id,)
        )
        snap_rows = cur.fetchall() or []
        cur.close()

        import proctoring_policy as pp

        PHONE_EVENTS  = frozenset({'mobile_phone'})
        DEVICE_EVENTS = frozenset({'electronic_device', 'book_detected'})
        PERSON_EVENTS = frozenset({'multiple_persons', 'student_absent'})
        HEAD_EVENTS   = frozenset({
            'head_turned_left', 'head_turned_right', 'head_tilted_up', 'head_tilted_down',
            'head_tilted_sideways', 'prolonged_head_turn', 'repeated_head_movement', 'head_movement',
        })
        GAZE_EVENTS   = frozenset({
            'looking_away', 'looking_up', 'looking_down',
            'prolonged_gaze_deviation', 'repeated_gaze_deviation',
        })
        AUDIO_EVENTS  = frozenset({'suspicious_audio'})

        # Group snapshots by email; parse event_data JSON for confirmed incident counts
        snaps_by_email     = {}
        confirmed_by_email = {}  # email -> {event_type: count}
        proctor_rows_by_email = {}

        for sr in snap_rows:
            em = sr['email']
            proctor_rows_by_email.setdefault(em, []).append(sr)
            if em not in snaps_by_email:
                snaps_by_email[em] = []
            if em not in confirmed_by_email:
                confirmed_by_email[em] = {}

            img_b64       = sr.get('img_log', '') or ''
            evidence_file = sr.get('evidence_file')
            audio_file    = sr.get('audio_evidence')

            # Count confirmed events from stored JSON (one row = one confirmed incident)
            try:
                metadata = json.loads(sr.get('event_data') or '{}')
            except (TypeError, ValueError):
                metadata = {}
            for evt in metadata.get('events', []):
                if isinstance(evt, dict):
                    etype = evt.get('event_type', '')
                    if etype:
                        confirmed_by_email[em][etype] = confirmed_by_email[em].get(etype, 0) + 1

            if (img_b64 and img_b64 != 'no_camera') or evidence_file or audio_file:
                # evidence_file is stored as "<exam_dir>/<filename>" by proctoring_evidence.py
                evidence_url = ''
                if evidence_file:
                    parts = str(evidence_file).replace('\\', '/').split('/')
                    ev_testid   = parts[0] if len(parts) > 1 else test_id
                    ev_filename = parts[-1]
                    try:
                        evidence_url = url_for(
                            'proctoring_evidence',
                            testid=ev_testid,
                            filename=ev_filename,
                        )
                    except Exception:
                        evidence_url = ''
                snaps_by_email[em].append({
                    'img':            '' if evidence_file else img_b64,
                    'evidence_url':   evidence_url,
                    'audio_url':      url_for(
                        'audio_evidence',
                        filename=str(audio_file),
                    ) if audio_file else '',
                    'evidence_status': sr.get('evidence_status') or 'not_required',
                    'events': ', '.join(
                        event.get('event_type', '').replace('_', ' ')
                        for event in metadata.get('events', [])
                        if isinstance(event, dict) and event.get('event_type')
                    ),
                    'time':      str(sr['log_time']),
                    'phone':     bool(sr['phone_detection']),
                    'device':    bool(sr['device_detection']),
                    'person':    sr['person_status'] != 1,
                    'eye_off':   sr['user_movements_eyes'] not in (0, 2),
                    'head_turn': sr['user_movements_lr'] != 0 or sr['user_movements_updown'] != 0,
                })

        # 5. Build student list — use confirmed_by_email (from event_data JSON) as authoritative source
        students = []
        proctor_by_email = {r['email']: r for r in proctor_rows}
        all_emails = set(proctor_by_email.keys()) | set(tab_rows.keys()) | {r['email'] for r in completed_rows}
        names_by_email = {r['email']: r.get('name') or r['email'] for r in completed_rows}
        for row in proctor_rows:
            if row.get('name'):
                names_by_email[row['email']] = row['name']
        for email in all_emails:
            row        = proctor_by_email.get(email, {})
            name       = names_by_email.get(email, email)
            total_snaps = int(row.get('total_snapshots') or 0)
            tab_info   = tab_rows.get(email, {})
            tab_sw     = int(tab_info.get('tab_switches', 0) or 0)

            # Authoritative counts from event_data JSON (confirmed incidents per type)
            evt_counts = confirmed_by_email.get(email, {})
            if evt_counts:
                phone_f  = sum(evt_counts.get(et, 0) for et in PHONE_EVENTS)
                device_f = sum(evt_counts.get(et, 0) for et in DEVICE_EVENTS)
                person_f = sum(evt_counts.get(et, 0) for et in PERSON_EVENTS)
                head_f   = sum(evt_counts.get(et, 0) for et in HEAD_EVENTS)
                eye_f    = sum(evt_counts.get(et, 0) for et in GAZE_EVENTS)
                audio_f  = sum(evt_counts.get(et, 0) for et in AUDIO_EVENTS)
            else:
                # Fallback: legacy rows that predate event_data JSON storage
                phone_f  = int(row.get('phone_flags')  or 0)
                device_f = int(row.get('device_flags') or 0)
                person_f = int(row.get('person_flags') or 0)
                head_f   = int(row.get('head_flags_lr') or 0) + int(row.get('head_flags_ud') or 0)
                eye_f    = int(row.get('eye_flags')    or 0)
                audio_f  = 0

            risk_event_counts = pp.count_proctoring_events(
                proctor_rows_by_email.get(email, [])
            )
            risk_score = pp.calculate_risk_score(risk_event_counts, tab_sw)
            risk_level = _risk_level(risk_score)

            students.append({
                'email':          email,
                'name':           name,
                'total_snapshots': total_snaps,
                'phone_flags':    phone_f,
                'device_flags':   device_f,
                'person_flags':   person_f,
                'head_flags':     head_f,
                'eye_flags':      eye_f,
                'audio_flags':    audio_f,
                'tab_switches':   tab_sw,
                'risk_score':     risk_score,
                'risk_level':     risk_level,
                'snapshots':      snaps_by_email.get(email, []),
            })

        # Sort: highest risk first
        students.sort(key=lambda x: x['risk_score'], reverse=True)

        # Build tab timeline data for JS
        tabs_js = []
        for email, tinfo in tab_rows.items():
            tabs_js.append({'email': email, 'events': tinfo['events']})

        # Summary counters
        total_students = len(students)
        high_risk   = sum(1 for s in students if s['risk_level'] == 'High Risk')
        moderate    = sum(1 for s in students if s['risk_level'] == 'Moderate')
        safe_count  = sum(1 for s in students if s['risk_level'] == 'Safe')
        flagged_cnt = high_risk + moderate
        phone_total = sum(s['phone_flags'] for s in students)
        device_total = sum(s['device_flags'] for s in students)
        tab_total   = sum(s['tab_switches'] for s in students)

        # Include all fields in students_json (detail panel uses snapshots)
        students_json_data = []
        for s in students:
            students_json_data.append({
                'email':           s['email'],
                'name':            s['name'],
                'total_snapshots': s['total_snapshots'],
                'phone_flags':     s['phone_flags'],
                'device_flags':    s['device_flags'],
                'person_flags':    s['person_flags'],
                'head_flags':      s['head_flags'],
                'eye_flags':       s['eye_flags'],
                'audio_flags':     s.get('audio_flags', 0),
                'tab_switches':    s['tab_switches'],
                'risk_score':      s['risk_score'],
                'risk_level':      s['risk_level'],
                'snapshots':       s['snapshots'],    # evidence images for gallery
            })

        return render_template(
            'cheat_report.html',
            test_id        = test_id,
            students       = students,
            students_json  = json.dumps(students_json_data),
            tabs_json      = json.dumps(tabs_js),
            total_students = total_students,
            flagged_count  = flagged_cnt,
            high_risk      = high_risk,
            moderate_risk  = moderate,
            safe_count     = safe_count,
            phone_total    = phone_total,
            device_total   = device_total,
            tab_total      = tab_total,
        )

    except Exception as e:
        app.logger.exception(f'cheat_report POST error: {e}')
        flash(f'Error generating cheating report: {e}', 'danger')
        try:
            cur.close()
        except Exception:
            pass
        return render_template('cheat_report_select.html', exams=exams)


if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000, debug=False)
