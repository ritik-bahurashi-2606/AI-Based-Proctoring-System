from flask import Flask, request, render_template, flash, redirect, url_for,session, logging, send_file, send_from_directory, jsonify, Response, render_template_string
from flask_login import LoginManager, login_user, logout_user, current_user, login_required, UserMixin
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, validators, DateTimeField, BooleanField, IntegerField, DecimalField, HiddenField, SelectField, RadioField, SubmitField
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
import camera
import io
import os
import time
import uuid
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from this project directory explicitly.
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)

# Disable CSRF for plain HTML forms (they use request.form directly, not FlaskForm)
# FlaskForms used for file upload still get CSRF via their own meta
app.config['WTF_CSRF_ENABLED'] = False

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'ritik')
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

app.config["TEMPLATES_AUTO_RELOAD"] = os.getenv('TEMPLATES_AUTO_RELOAD', 'True').lower() == 'true'

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

app.secret_key = 'myproctor_secret_key_123'

mysql = MySQL(app)

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
		mysql.connection.commit()
		_exam_results_table_checked = True
		app.logger.info('exam_results table verified')
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
	cur.execute("""
		SELECT
			COALESCE(SUM(phone_detection), 0) AS phone_flags,
			COALESCE(SUM(CASE WHEN person_status IN (0, 2) THEN 1 ELSE 0 END), 0) AS person_flags,
			COALESCE(SUM(CASE WHEN user_movements_lr NOT IN (0) THEN 1 ELSE 0 END), 0) AS head_flags_lr,
			COALESCE(SUM(CASE WHEN user_movements_updown NOT IN (0) THEN 1 ELSE 0 END), 0) AS head_flags_ud,
			COALESCE(SUM(CASE WHEN user_movements_eyes NOT IN (2) THEN 1 ELSE 0 END), 0) AS eye_flags
		FROM proctoring_log
		WHERE email = %s AND test_id = %s
	""", (email, testid))
	proctor = cur.fetchone() or {}
	cur.execute("""
		SELECT COUNT(*) AS tab_switches
		FROM window_estimation_log
		WHERE email = %s AND test_id = %s
	""", (email, testid))
	tab = cur.fetchone() or {}
	score = (
		int(proctor.get('phone_flags') or 0) * 10
		+ int(proctor.get('person_flags') or 0) * 5
		+ int(tab.get('tab_switches') or 0) * 3
		+ int(proctor.get('head_flags_lr') or 0)
		+ int(proctor.get('head_flags_ud') or 0)
		+ int(proctor.get('eye_flags') or 0)
	)
	return score, _risk_level(score)


def _fetch_result_context(cur, email, testid, student_uid):
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
	""", (student_uid, session.get('name', email), email, email, testid))
	ctx = cur.fetchone()
	if not ctx:
		raise ValueError(f'Missing exam: {testid}')
	return ctx


def _calculate_result_payload(cur, email, testid, student_uid):
	ctx = _fetch_result_context(cur, email, testid, student_uid)
	test_type = ctx['test_type']
	if test_type == 'objective':
		cur.execute("""
			SELECT COUNT(*) AS total_questions, COALESCE(SUM(marks), 0) AS total_marks
			FROM questions WHERE test_id = %s AND uid = %s
		""", (testid, ctx['professor_id']))
		totals = cur.fetchone() or {}
		cur.execute("""
			SELECT COUNT(DISTINCT qid) AS attempted_questions
			FROM students
			WHERE test_id = %s AND email = %s AND uid = %s AND ans IS NOT NULL AND ans != ''
		""", (testid, email, student_uid))
		attempted = cur.fetchone() or {}
		cur.execute("""
			SELECT q.qid, q.ans AS correct, q.marks, MAX(s.ans) AS marked
			FROM questions q
			LEFT JOIN students s ON s.test_id = q.test_id AND s.qid = q.qid
				AND s.email = %s AND s.uid = %s
			WHERE q.test_id = %s AND q.uid = %s
			GROUP BY q.qid, q.ans, q.marks
		""", (email, student_uid, testid, ctx['professor_id']))
		rows = cur.fetchall() or []
		cur.execute("SELECT neg_marks FROM teachers WHERE test_id = %s LIMIT 1", (testid,))
		neg = float((cur.fetchone() or {}).get('neg_marks') or 0)
		marks = 0.0
		correct = 0
		wrong = 0
		for row in rows:
			marked = str(row.get('marked') or '').upper()
			if not marked:
				continue
			if marked == str(row.get('correct') or '').upper():
				correct += 1
				marks += float(row.get('marks') or 0)
			else:
				wrong += 1
				marks -= (neg / 100) * float(row.get('marks') or 0)
		total_questions = int(totals.get('total_questions') or 0)
		total_marks = float(totals.get('total_marks') or 0)
		attempted_questions = int(attempted.get('attempted_questions') or 0)
	else:
		qa_table = 'longqa' if test_type == 'subjective' else 'practicalqa'
		ans_table = 'longtest' if test_type == 'subjective' else 'practicaltest'
		cur.execute(f"SELECT COUNT(*) AS total_questions, COALESCE(SUM(marks), 0) AS total_marks FROM {qa_table} WHERE test_id = %s AND uid = %s", (testid, ctx['professor_id']))
		totals = cur.fetchone() or {}
		cur.execute(f"SELECT COUNT(*) AS attempted_questions, COALESCE(SUM(marks), 0) AS marks FROM {ans_table} WHERE test_id = %s AND email = %s AND uid = %s", (testid, email, student_uid))
		scored = cur.fetchone() or {}
		total_questions = int(totals.get('total_questions') or 0)
		total_marks = float(totals.get('total_marks') or 0)
		attempted_questions = int(scored.get('attempted_questions') or 0)
		marks = float(scored.get('marks') or 0)
		correct = 0
		wrong = 0
	percentage = round((marks / total_marks) * 100, 2) if total_marks else 0
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
		cur.execute("""
			INSERT INTO exam_results (
				student_id, student_name, student_email, exam_id, subject, topic,
				professor_id, professor_name, total_questions, attempted_questions,
				correct_answers, wrong_answers, marks, percentage, result_status,
				submission_time, cheating_risk_score, risk_level, uid
			) VALUES (
				%(student_id)s, %(student_name)s, %(student_email)s, %(exam_id)s, %(subject)s, %(topic)s,
				%(professor_id)s, %(professor_name)s, %(total_questions)s, %(attempted_questions)s,
				%(correct_answers)s, %(wrong_answers)s, %(marks)s, %(percentage)s, %(result_status)s,
				NOW(), %(cheating_risk_score)s, %(risk_level)s, %(uid)s
			)
			ON DUPLICATE KEY UPDATE
				student_name = VALUES(student_name),
				subject = VALUES(subject),
				topic = VALUES(topic),
				professor_id = VALUES(professor_id),
				professor_name = VALUES(professor_name),
				total_questions = VALUES(total_questions),
				attempted_questions = VALUES(attempted_questions),
				correct_answers = VALUES(correct_answers),
				wrong_answers = VALUES(wrong_answers),
				marks = VALUES(marks),
				percentage = VALUES(percentage),
				result_status = VALUES(result_status),
				submission_time = NOW(),
				cheating_risk_score = VALUES(cheating_risk_score),
				risk_level = VALUES(risk_level)
		""", payload)
		mysql.connection.commit()
		app.logger.info('Result saved: student=%s exam=%s marks=%s pct=%s risk=%s', email, testid, payload['marks'], payload['percentage'], payload['risk_level'])
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
		app.logger.warning('Could not verify/create proctoring_log.audio_evidence: %s', err)
		try:
			mysql.connection.rollback()
		except Exception:
			pass
	finally:
		cur.close()


@app.route('/audio_evidence/<path:filename>')
@professor_required
def audio_evidence(filename):
	return send_from_directory(_AUDIO_EVIDENCE_DIR, secure_filename(filename), as_attachment=False)


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


@app.route('/video_feed', methods=['GET', 'POST'])
@student_required
def video_feed():
	if request.method == 'POST':
		try:
			imgData  = request.form['data[imgData]']
			testid   = request.form['data[testid]']
			voice_db = request.form['data[voice_db]']
		except KeyError as ke:
			return jsonify({'status': 'error', 'message': f'Missing field: {ke}'}), 400

		# ── Run CV pipeline ───────────────────────────────────────────────────
		try:
			proctorData = camera.get_frame(imgData)
		except Exception as cam_err:
			app.logger.error('camera.get_frame error: %s', cam_err)
			return jsonify({'status': 'error', 'message': 'Camera processing failed.'}), 500

		jpg_as_text   = proctorData['jpg_as_text']
		mob_status    = proctorData['mob_status']
		person_status = proctorData['person_status']
		user_move1    = proctorData['user_move1']
		user_move2    = proctorData['user_move2']
		eye_movements = proctorData['eye_movements']

		uid   = session.get('uid')
		email = session.get('email')
		name  = session.get('name')

		try:
			vdb_val = float(voice_db)
		except (ValueError, TypeError):
			vdb_val = 0.0

		# ── Temporal smart evaluation (head+gaze history, cooldowns) ──────────
		import proctoring_policy as pp
		user_key = f"{uid}_{testid}"
		policy   = pp.evaluate_proctoring_event(user_key, proctorData, vdb_val, imgData)

		warnings         = policy['warnings']      # all events (for toasts)
		logged_events    = policy['events']         # cooldown-filtered events to log
		audio_suspicious = policy['audio_suspicious']
		should_log       = policy['should_log']

		# ── DB logging: one row per suspicious event batch ───────────────────
		logged  = False
		log_pid = None
		if should_log and logged_events:
			# Keep the annotated frame for every stored malpractice event so professor
			# reports have evidence instead of empty screenshots.
			store_img = jpg_as_text

			dominant = logged_events[0]['event_type']
			try:
				cur  = mysql.connection.cursor()
				rows = cur.execute(
					'INSERT INTO proctoring_log '
					'(email, name, test_id, voice_db, img_log, user_movements_updown, '
					'user_movements_lr, user_movements_eyes, phone_detection, person_status, uid) '
					'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
					(email, name, testid, vdb_val, store_img,
					 user_move1, user_move2, eye_movements,
					 mob_status, person_status, uid),
				)
				mysql.connection.commit()
				log_pid = cur.lastrowid
				cur.close()
				logged = (rows > 0)
				app.logger.info(
					'Proctoring log: uid=%s test=%s event=%s yaw=%.1f pitch=%.1f eyes=%d',
					uid, testid, dominant,
					proctorData.get('head_yaw', 0),
					proctorData.get('head_pitch', 0),
					eye_movements,
				)
			except Exception as db_err:
				app.logger.error('proctoring_log insert error: %s', db_err)
				try:
					mysql.connection.rollback()
				except Exception:
					pass

		return jsonify({
			'status':           'success',
			'logged':           logged,
			'pid':              log_pid,
			'mob_status':       mob_status,
			'person_status':    person_status,
			'user_move_updown': user_move1,
			'user_move_lr':     user_move2,
			'eye_movements':    eye_movements,
			'head_yaw':         proctorData.get('head_yaw', 0),
			'head_pitch':       proctorData.get('head_pitch', 0),
			'head_confidence':  proctorData.get('head_confidence', 0),
			'gaze_confidence':  proctorData.get('gaze_confidence', 0),
			'audio_suspicious': audio_suspicious,
			'warnings':         warnings,
		})

	return jsonify({'status': 'error', 'message': 'POST required'}), 405


@app.route('/upload_audio_evidence', methods=['POST'])
@student_required
def upload_audio_evidence():
	"""Receive an audio blob from the browser and store it linked to a log entry."""
	try:
		testid     = request.form.get('testid', '').strip()
		event_type = request.form.get('event_type', 'suspicious_audio').strip()
		pid        = request.form.get('pid', '').strip()
		audio_file = request.files.get('audio')

		if not audio_file or not testid:
			return jsonify({'status': 'error', 'message': 'Missing audio or testid'}), 400

		uid   = session.get('uid', 'unknown')
		ts    = int(time.time())
		fname = f"exam_{testid}_uid_{uid}_{ts}.webm"
		fpath = os.path.join(_AUDIO_EVIDENCE_DIR, fname)
		audio_file.save(fpath)

		# Link audio file path to the proctoring_log row if pid is known.
		# The primary key is pid, not id.
		if pid:
			try:
				_ensure_proctoring_audio_column()
				cur = mysql.connection.cursor()
				cur.execute(
					'UPDATE proctoring_log SET audio_evidence = %s '
					'WHERE pid = %s AND uid = %s',
					(fname, pid, uid),
				)
				mysql.connection.commit()
				cur.close()
			except Exception as db_err:
				app.logger.warning('audio_evidence update failed: %s', db_err)
				try:
					mysql.connection.rollback()
				except Exception:
					pass

		app.logger.info('Audio evidence saved: %s (pid=%s, uid=%s, test=%s)', fname, pid, uid, testid)
		return jsonify({'status': 'success', 'file': fname})

	except Exception as ae:
		app.logger.error('upload_audio_evidence error: %s', ae)
		return jsonify({'status': 'error', 'message': 'Audio upload failed.'}), 500

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

			return jsonify({
				'status':   'success',
				'logged':   pol['should_log'],
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
		now = datetime.now()
		now = now.strftime("%Y-%m-%d %H:%M:%S")
		now = datetime.strptime(now,"%Y-%m-%d %H:%M:%S")
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
	proctor_type = RadioField('Proctoring Type', choices=[('0','Automatic Monitoring'),('1','Live Monitoring')])

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
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < datetime.now():
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
				proctor_type = form.proctor_type.data
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
	proctor_type = RadioField('Proctoring Type', choices=[('0','Automatic Monitoring'),('1','Live Monitoring')])

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
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < datetime.now():
				raise ValidationError("Start date and time must not be earlier than current")
		except ValidationError:
			raise
		except Exception:
			pass

class TestForm(Form):
	test_id = StringField('Exam ID')
	password = PasswordField('Exam Password')
	img_hidden_form = HiddenField(label=(''))

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
				proctor_type = form.proctor_type.data
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
	password = PasswordField('Exam Password', [validators.Length(min=3, max=10)])
	proctor_type = RadioField('Proctoring Type', choices=[('0','Automatic Monitoring'),('1','Live Monitoring')])

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
			if datetime.strptime(str(form.start_date.data) + " " + str(form.start_time.data),"%Y-%m-%d %H:%M:%S") < datetime.now():
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
				proctor_type = form.proctor_type.data
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
		now = datetime.now()
		now = now.strftime("%Y-%m-%d %H:%M:%S")
		now = datetime.strptime(now,"%Y-%m-%d %H:%M:%S")
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
	cur.execute('SELECT COUNT(*) as percount from proctoring_log where test_id = %s and email = %s and person_status IN (0,2)', (testid, email))
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
	cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return render_template("displaystudentslogs.html", testid = testid, email = email, callresults = callresults)

@app.route('/mobdisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def mobdisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s and phone_detection = 1', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return render_template("mobdisplaystudentslogs.html", testid = testid, email = email, callresults = callresults)

@app.route('/persondisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def persondisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s and person_status IN (0,2)', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return render_template("persondisplaystudentslogs.html",testid = testid, email = email, callresults = callresults)

@app.route('/audiodisplaystudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def audiodisplaystudentslogs(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from proctoring_log where test_id = %s and email = %s', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return render_template("audiodisplaystudentslogs.html", testid = testid, email = email, callresults = callresults)

@app.route('/wineventstudentslogs/<testid>/<email>', methods=['GET','POST'])
@user_role_professor
def wineventstudentslogs(testid,email):
	callresults = displaywinstudentslogs(testid,email)
	return render_template("wineventstudentlog.html", testid = testid, email = email, callresults = callresults)

@app.route('/<email>/<testid>/share_details', methods=['GET','POST'])
@user_role_professor
def share_details(testid,email):
	cur = mysql.connection.cursor()
	cur.execute('SELECT * from teachers where test_id = %s and email = %s', (testid, email))
	callresults = cur.fetchall()
	cur.close()
	return render_template("share_details.html", callresults = callresults)

@app.route('/share_details_emails', methods=['GET','POST'])
@user_role_professor
def share_details_emails():
	if request.method == 'POST':
		tid = request.form['tid']
		subject = request.form['subject']
		topic = request.form['topic']
		duration = request.form['duration']
		start = request.form['start']
		end = request.form['end']
		password = request.form['password']
		neg_marks = request.form['neg_marks']
		calc = request.form['calc']
		emailssharelist = request.form['emailssharelist']
		msg1 = Message('EXAM DETAILS - MyProctor.ai', sender = sender, recipients = [emailssharelist])
		msg1.body = " ".join(["EXAM-ID:", tid, "SUBJECT:", subject, "TOPIC:", topic, "DURATION:", duration, "START", start, "END", end, "PASSWORD", password, "NEGATIVE MARKS in %:", neg_marks,"CALCULATOR ALLOWED:",calc ]) 
		mail.send(msg1)
		flash('Emails sended sucessfully!', 'success')
	return render_template('share_details.html')

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
			if _fv and _fv.verify_face_match(imgdata1, imgdata2):
				cur = mysql.connection.cursor()
				results = cur.execute('SELECT * from teachers where test_id = %s', [test_id])
				if results > 0:
					data = cur.fetchone()
					password = data['password']
					duration = data['duration']
					calc = data['calc']
					subject = data['subject']
					topic = data['topic']
					start = data['start']
					start = str(start)
					end = data['end']
					end = str(end)
					proctortype = data['proctoring_type']
					if password == password_candidate:
						now = datetime.now()
						now = now.strftime("%Y-%m-%d %H:%M:%S")
						now = datetime.strptime(now,"%Y-%m-%d %H:%M:%S")
						if datetime.strptime(start,"%Y-%m-%d %H:%M:%S") < now and datetime.strptime(end,"%Y-%m-%d %H:%M:%S") > now:
							results = cur.execute('SELECT time_to_sec(time_left) as time_left,completed from studentTestInfo where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
							if results > 0:
								results = cur.fetchone()
								is_completed = results['completed']
								if is_completed == 0:
									time_left = results['time_left']
									if time_left <= duration:
										duration = time_left
										results = cur.execute('SELECT qid , ans from students where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
										marked_ans = {}
										if results > 0:
											results = cur.fetchall()
											for row in results:
												print(row['qid'])
												qiddb = str(row['qid'])
												print(qiddb)
												marked_ans[qiddb] = row['ans']
											marked_ans = json.dumps(marked_ans)
								else:
									flash('Exam already given', 'success')
									return redirect(url_for('give_test'))
							else:
								cur.execute('INSERT into studentTestInfo (email, test_id,time_left,uid) values(%s,%s,SEC_TO_TIME(%s),%s)', (session['email'], test_id, duration, session['uid']))
								mysql.connection.commit()
								results = cur.execute('SELECT time_to_sec(time_left) as time_left,completed from studentTestInfo where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
								if results > 0:
									results = cur.fetchone()
									is_completed = results['completed']
									if is_completed == 0:
										time_left = results['time_left']
										if time_left <= duration:
											duration = time_left
											results = cur.execute('SELECT * from students where email = %s and test_id = %s and uid = %s', (session['email'], test_id, session['uid']))
											marked_ans = {}
											if results > 0:
												results = cur.fetchall()
												for row in results:
													marked_ans[row['qid']] = row['ans']
												marked_ans = json.dumps(marked_ans)
						else:
							if datetime.strptime(start,"%Y-%m-%d %H:%M:%S") > now:
								flash(f'Exam start time is {start}', 'danger')
							else:
								flash(f'Exam has ended', 'danger')
							return redirect(url_for('give_test'))
						return redirect(url_for('test' , testid = test_id))
					else:
						flash('Invalid password', 'danger')
						return redirect(url_for('give_test'))
				flash('Invalid testid', 'danger')
				return redirect(url_for('give_test'))
				cur.close()
			else:
				flash('Image not Verified', 'danger')
				return redirect(url_for('give_test'))
	return render_template('give_test.html', form = form)

@app.route('/give-test/<testid>', methods=['GET','POST'])
@user_role_student
def test(testid):
	cur = mysql.connection.cursor()
	cur.execute('SELECT test_type from teachers where test_id = %s ', [testid])
	callresults = cur.fetchone()
	cur.close()
	if callresults['test_type'] == "objective":
		global duration, marked_ans, calc, subject, topic, proctortype
		if request.method == 'GET':
			try:
				data = {'duration': duration, 'marks': '', 'q': '', 'a': '', 'b':'','c':'','d':'' }
				return render_template('testquiz.html' ,**data, answers=marked_ans, calc=calc, subject=subject, topic=topic, tid=testid, proctortype=proctortype)
			except:
				return redirect(url_for('give_test'))
		else:
			cur = mysql.connection.cursor()
			flag = request.form['flag']
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
				if not qid or not ans:
					cur.close()
					return jsonify({'status': 'error', 'message': 'Missing qid or answer'}), 400
				cur = mysql.connection.cursor()
				results = cur.execute('SELECT sid from students where test_id = %s and qid = %s and email = %s and uid = %s', (testid, qid, session['email'], session['uid']))
				if results > 0:
					cur.execute('UPDATE students set ans = %s where test_id = %s and qid = %s and email = %s and uid = %s', (ans, testid, qid, session['email'], session['uid']))
					action = 'updated'
				else:
					cur.execute('INSERT INTO students(email,test_id,qid,ans,uid) values(%s,%s,%s,%s,%s)', (session['email'], testid, qid, ans, session['uid']))
					action = 'inserted'
				mysql.connection.commit()
				rowcount = cur.rowcount
				cur.close()
				app.logger.info('Answer %s: uid=%s test=%s qid=%s ans=%s', action, session['uid'], testid, qid, ans)
				return jsonify({'status': 'success', 'action': action, 'rows': rowcount})
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
					cur.execute('UPDATE studentTestInfo set completed=1,time_left=sec_to_time(0) where test_id = %s and email = %s and uid = %s', (testid, session['email'],session['uid']))
					mysql.connection.commit()
					rows = cur.rowcount
				finally:
					cur.close()
				try:
					result_payload = save_exam_result(session['email'], testid, session['uid'])
				except Exception as err:
					return jsonify({'status': 'error', 'message': f'Result insert failed: {err}'}), 500
				app.logger.info('Exam completed: uid=%s email=%s test=%s rows=%s', session['uid'], session['email'], testid, rows)
				flash("Exam submitted successfully", 'info')
				return jsonify({'status':'success', 'completed': True, 'rows': rows, 'result': result_payload})

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
							flash(f'Result insert failed: {err}', 'danger')
							return redirect(url_for('student_index'))
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
						flash(f'Result insert failed: {err}', 'danger')
						return redirect(url_for('student_index'))
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
			WHERE student_email = %s AND uid = %s
			ORDER BY submission_time DESC
		''', (session['email'], session['uid']))
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
			WHERE student_email = %s AND uid = %s
			ORDER BY submission_time DESC
		''', (session['email'], session['uid']))
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
		results = cur.execute('select * from teachers where email = %s and uid = %s', (email,session['uid']))
		results = cur.fetchall()
		return render_template('disptests.html', tests=results)
	else:
		flash('You are not authorized', 'danger')
		return redirect(url_for('professor_index'))





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

    try:
        cur = mysql.connection.cursor()

        # 1. Aggregate proctoring_log per student
        cur.execute(
            '''
            SELECT
                email, name,
                COUNT(*)                                       AS total_snapshots,
                SUM(phone_detection)                           AS phone_flags,
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
            SELECT email, COUNT(*) AS tab_switches
            FROM window_estimation_log
            WHERE test_id = %s
            GROUP BY email
            ''',
            (test_id,)
        )
        tab_rows = {r['email']: r for r in (cur.fetchall() or [])}

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

        # 4. Fetch snapshots (img_log) per student  – limit per student to avoid huge payloads
        cur.execute(
            '''
            SELECT email, img_log,
                   user_movements_lr, user_movements_updown,
                   user_movements_eyes, phone_detection, person_status,
                   log_time
            FROM proctoring_log
            WHERE test_id = %s
            ORDER BY email, log_time
            ''',
            (test_id,)
        )
        snap_rows = cur.fetchall() or []
        cur.close()

        # Group snapshots by email
        snaps_by_email = {}
        for sr in snap_rows:
            em = sr['email']
            if em not in snaps_by_email:
                snaps_by_email[em] = []
            img_b64 = sr.get('img_log', '') or ''
            # Only keep non-empty images
            if img_b64 and img_b64 not in ('', 'no_camera'):
                snaps_by_email[em].append({
                    'img':       img_b64,
                    'time':      str(sr['log_time']),
                    'phone':     bool(sr['phone_detection']),
                    'person':    sr['person_status'] != 1,
                    'eye_off':   sr['user_movements_eyes'] not in (0, 2),
                    'head_turn': sr['user_movements_lr'] != 0 or sr['user_movements_updown'] != 0,
                })

        # 5. Build student list
        students = []
        proctor_by_email = {r['email']: r for r in proctor_rows}
        all_emails = set(proctor_by_email.keys()) | set(tab_rows.keys()) | {r['email'] for r in completed_rows}
        names_by_email = {r['email']: r.get('name') or r['email'] for r in completed_rows}
        for row in proctor_rows:
            if row.get('name'):
                names_by_email[row['email']] = row['name']
        for email in all_emails:
            row = proctor_by_email.get(email, {})
            name          = names_by_email.get(email, email)
            total_snaps   = int(row.get('total_snapshots') or 0)
            phone_f       = int(row.get('phone_flags') or 0)
            person_f      = int(row.get('person_flags') or 0)
            head_f        = int((row.get('head_flags_lr') or 0)) + int((row.get('head_flags_ud') or 0))
            eye_f         = int(row.get('eye_flags') or 0)
            tab_info      = tab_rows.get(email, {})
            tab_sw        = int(tab_info.get('tab_switches', 0) or 0)

            risk_score = phone_f * 10 + person_f * 5 + tab_sw * 3 + head_f + eye_f

            if risk_score >= 30:
                risk_level = 'High Risk'
            elif risk_score >= 10:
                risk_level = 'Moderate'
            else:
                risk_level = 'Safe'

            students.append({
                'email':          email,
                'name':           name,
                'total_snapshots': total_snaps,
                'phone_flags':    phone_f,
                'person_flags':   person_f,
                'head_flags':     head_f,
                'eye_flags':      eye_f,
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
            tabs_js.append({'email': email, 'events': []})

        # Summary counters
        total_students = len(students)
        high_risk   = sum(1 for s in students if s['risk_level'] == 'High Risk')
        moderate    = sum(1 for s in students if s['risk_level'] == 'Moderate')
        safe_count  = sum(1 for s in students if s['risk_level'] == 'Safe')
        flagged_cnt = high_risk + moderate
        phone_total = sum(s['phone_flags'] for s in students)
        tab_total   = sum(s['tab_switches'] for s in students)

        # Strip snapshots from students_json to keep payload small (only send minimal fields)
        students_json_data = []
        for s in students:
            students_json_data.append({
                'email':           s['email'],
                'name':            s['name'],
                'total_snapshots': s['total_snapshots'],
                'phone_flags':     s['phone_flags'],
                'person_flags':    s['person_flags'],
                'head_flags':      s['head_flags'],
                'eye_flags':       s['eye_flags'],
                'tab_switches':    s['tab_switches'],
                'risk_score':      s['risk_score'],
                'risk_level':      s['risk_level'],
                'snapshots':       s['snapshots'],    # base64 images included here
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
