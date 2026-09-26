import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
import csv
import json
import unicodedata
from datetime import datetime, date, timedelta
from functools import wraps

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from openpyxl import load_workbook, Workbook
except ImportError:
    load_workbook = Workbook = None
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(__file__)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-in-production')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SQLITE_PATH = os.environ.get('SQLITE_PATH', os.path.join(BASE, 'zara_sara.db'))
USE_PG = bool(DATABASE_URL)
BOOL_TRUE = 'TRUE' if USE_PG else '1'
MAX_QUESTIONS_PER_CLASS = 1000
QUIZ_DEFAULT_QUESTION_COUNT = 20
QUIZ_DEFAULT_MAX_QUESTION_COUNT = 50


class DB:
    def __init__(self):
        self.pg = USE_PG
        if self.pg:
            if psycopg2 is None:
                raise RuntimeError('DATABASE_URL is set but psycopg2-binary is not installed.')
            self.c = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            self.cur = self.c.cursor()
        else:
            self.c = sqlite3.connect(SQLITE_PATH)
            self.c.row_factory = sqlite3.Row
            self.c.execute('PRAGMA foreign_keys=ON')
            self.cur = self.c.cursor()

    def execute(self, sql, params=()):
        if self.pg:
            sql = sql.replace('?', '%s')
        self.cur.execute(sql, params)
        return self.cur

    def fetchone(self, sql, params=()):
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.execute(sql, params).fetchall()

    def commit(self):
        self.c.commit()

    def rollback(self):
        self.c.rollback()

    def close(self):
        try:
            self.cur.close()
        finally:
            self.c.close()

    def insert_id(self, sql, params=()):
        if self.pg:
            sql = sql.replace('?', '%s') + ' RETURNING id'
            self.cur.execute(sql, params)
            row = self.cur.fetchone()
            return row['id']
        self.cur.execute(sql, params)
        return self.cur.lastrowid


def db():
    return DB()


def _column_exists(d, table, column):
    if d.pg:
        row = d.fetchone(
            '''SELECT 1 AS ok
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name=? AND column_name=?''',
            (table, column),
        )
        return bool(row)
    rows = d.fetchall(f'PRAGMA table_info({table})')
    return any(r['name'] == column for r in rows)


def _add_column_if_missing(d, table, column, definition):
    if not _column_exists(d, table, column):
        d.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def ensure_schema_upgrades(d):
    """Safely upgrade an existing v4.x database without dropping user data."""
    if d.pg:
        d.execute('ALTER TABLE chapters ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE questions ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS phone TEXT')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS recovery_pin_hash TEXT')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS practice_class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS chapter_id BIGINT REFERENCES chapters(id)')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS question_count INTEGER DEFAULT 0')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS max_question_count INTEGER DEFAULT 50')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS student_can_choose_count BOOLEAN DEFAULT FALSE')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS randomize_questions BOOLEAN DEFAULT TRUE')
        d.execute('ALTER TABLE badges ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE')
        d.execute('ALTER TABLE badges ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0')
        d.execute('ALTER TABLE games ADD COLUMN IF NOT EXISTS launch_url TEXT')
        d.execute('ALTER TABLE games ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0')
    else:
        _add_column_if_missing(d, 'chapters', 'class_id', 'INTEGER REFERENCES classes(id)')
        _add_column_if_missing(d, 'questions', 'class_id', 'INTEGER REFERENCES classes(id)')
        _add_column_if_missing(d, 'students', 'email', 'TEXT')
        _add_column_if_missing(d, 'students', 'phone', 'TEXT')
        _add_column_if_missing(d, 'students', 'recovery_pin_hash', 'TEXT')
        _add_column_if_missing(d, 'students', 'practice_class_id', 'INTEGER REFERENCES classes(id)')
        _add_column_if_missing(d, 'students', 'updated_at', 'TEXT')
        _add_column_if_missing(d, 'quizzes', 'chapter_id', 'INTEGER REFERENCES chapters(id)')
        _add_column_if_missing(d, 'quizzes', 'question_count', 'INTEGER DEFAULT 0')
        _add_column_if_missing(d, 'quizzes', 'max_question_count', 'INTEGER DEFAULT 50')
        _add_column_if_missing(d, 'quizzes', 'student_can_choose_count', 'INTEGER DEFAULT 0')
        _add_column_if_missing(d, 'quizzes', 'randomize_questions', 'INTEGER DEFAULT 1')
        _add_column_if_missing(d, 'badges', 'active', 'INTEGER DEFAULT 1')
        _add_column_if_missing(d, 'badges', 'display_order', 'INTEGER DEFAULT 0')
        _add_column_if_missing(d, 'games', 'launch_url', 'TEXT')
        _add_column_if_missing(d, 'games', 'display_order', 'INTEGER DEFAULT 0')
    d.execute('CREATE INDEX IF NOT EXISTS idx_questions_class_subject ON questions(class_id, subject_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_chapters_class_subject ON chapters(class_id, subject_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_quizzes_class_subject_chapter ON quizzes(class_id, subject_id, chapter_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_quiz_questions_question ON quiz_questions(question_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_students_practice_class ON students(practice_class_id)')
    if d.pg:
        d.execute('CREATE TABLE IF NOT EXISTS quiz_attempt_questions(attempt_id BIGINT NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,display_order INTEGER NOT NULL,PRIMARY KEY(attempt_id,display_order))')
    else:
        d.execute('CREATE TABLE IF NOT EXISTS quiz_attempt_questions(attempt_id INTEGER NOT NULL,question_id INTEGER NOT NULL,display_order INTEGER NOT NULL,PRIMARY KEY(attempt_id,display_order),FOREIGN KEY(attempt_id) REFERENCES quiz_attempts(id) ON DELETE CASCADE,FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_attempt ON quiz_attempt_questions(attempt_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_question ON quiz_attempt_questions(question_id)')


def init_db():
    d = db()
    try:
        if USE_PG:
            with open(os.path.join(BASE, 'database', 'schema_postgres.sql'), encoding='utf-8') as f:
                schema = f.read()
            for stmt in [x.strip() for x in schema.split(';') if x.strip()]:
                d.execute(stmt)
        else:
            with open(os.path.join(BASE, 'database', 'schema_sqlite.sql'), encoding='utf-8') as f:
                schema = f.read()
            d.c.executescript(schema)

        ensure_schema_upgrades(d)

        if not d.fetchone('SELECT COUNT(*) AS n FROM site_settings')['n']:
            d.execute(
                '''INSERT INTO site_settings
                   (site_name,tagline,purpose,about,hero_title,hero_subtitle)
                   VALUES(?,?,?,?,?,?)''',
                (
                    'প্র্যাকটিস উইথ জারা-সারা',
                    'শিখি • অনুশীলন করি • এগিয়ে যাই',
                    'ষষ্ঠ থেকে দশম শ্রেণির শিক্ষার্থীদের নিয়মিত অনুশীলন, আত্মমূল্যায়ন ও শেখার আগ্রহ বাড়াতে তৈরি একটি অনুশীলনভিত্তিক শিক্ষামূলক প্ল্যাটফর্ম।',
                    'এখানে একাডেমিক বিষয়, ইংরেজি, সাধারণ জ্ঞান, কুইজ ও শিক্ষামূলক গেম এক জায়গায় পাওয়া যাবে।',
                    'শেখা হোক আনন্দের, অনুশীলন হোক নিয়মিত!',
                    'জারা ও সারা তোমার শেখার সঙ্গী—প্রতিদিন একটু অনুশীলন, প্রতিদিন একটু এগিয়ে যাওয়া।',
                ),
            )

        if not d.fetchone('SELECT COUNT(*) AS n FROM admin_users')['n']:
            d.execute(
                'INSERT INTO admin_users(username,password_hash) VALUES(?,?)',
                ('admin', generate_password_hash('admin123')),
            )

        # Ensure every required Class/Subject exists without replacing existing records.
        for i in range(6, 11):
            if not d.fetchone('SELECT id FROM classes WHERE name=? LIMIT 1', (f'শ্রেণি {i}',)):
                d.execute(
                    'INSERT INTO classes(name,display_order) VALUES(?,?)',
                    (f'শ্রেণি {i}', i - 5),
                )

        subjects = [
            ('বাংলা', '📚', 1),
            ('ইংরেজি', '🔤', 2),
            ('গণিত', '➗', 3),
            ('বিজ্ঞান', '🔬', 4),
            ('বাংলাদেশ ও বিশ্বপরিচয়', '🌍', 5),
            ('সাধারণ জ্ঞান', '🧠', 6),
        ]
        for name, icon, order_no in subjects:
            if not d.fetchone('SELECT id FROM subjects WHERE name=? LIMIT 1', (name,)):
                d.execute(
                    'INSERT INTO subjects(name,icon,display_order) VALUES(?,?,?)',
                    (name, icon, order_no),
                )

        # Keep the existing working demo content for a fresh database.
        if not d.fetchone('SELECT COUNT(*) AS n FROM questions')['n']:
            samples = [
                ('বিজ্ঞান', 'অধ্যায় ১: মানবদেহ', 'মানবদেহের বৃহত্তম অঙ্গ কোনটি?', ['ত্বক', 'যকৃত', 'মস্তিষ্ক', 'ফুসফুস'], 0),
                ('বিজ্ঞান', 'অধ্যায় ১: মানবদেহ', 'রক্তে অক্সিজেন বহনকারী উপাদান কোনটি?', ['হিমোগ্লোবিন', 'প্লাজমা', 'শ্বেতকণিকা', 'অণুচক্রিকা'], 0),
                ('গণিত', 'অধ্যায় ১: মৌলিক গণিত', '১২ × ৪ = কত?', ['৪৮', '৪২', '৫৬', '৬৪'], 0),
                ('ইংরেজি', 'Grammar', 'Choose the correct plural of “child”.', ['childs', 'children', 'childes', 'childrens'], 1),
                ('সাধারণ জ্ঞান', 'বাংলাদেশ', 'বাংলাদেশের জাতীয় ফুল কোনটি?', ['শাপলা', 'গোলাপ', 'জবা', 'বেলি'], 0),
            ]
            default_class = d.fetchone('SELECT id FROM classes WHERE name=?', ('শ্রেণি ৬',))
            default_class_id = default_class['id'] if default_class else None
            for subj, chap, q_text, opts, ans in samples:
                sid = d.fetchone('SELECT id FROM subjects WHERE name=?', (subj,))['id']
                ch = d.fetchone(
                    'SELECT id FROM chapters WHERE subject_id=? AND title=? AND (class_id=? OR class_id IS NULL)',
                    (sid, chap, default_class_id),
                )
                cid = ch['id'] if ch else d.insert_id(
                    'INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',
                    (sid, default_class_id, chap),
                )
                qid = d.insert_id(
                    '''INSERT INTO questions
                       (subject_id,chapter_id,class_id,question_text,question_type,explanation,difficulty,marks)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (sid, cid, default_class_id, q_text, 'mcq', 'সঠিক উত্তরটি মিলিয়ে নাও।', 'medium', 1),
                )
                for i, option_text in enumerate(opts):
                    d.execute(
                        '''INSERT INTO question_options
                           (question_id,option_text,is_correct,display_order)
                           VALUES(?,?,?,?)''',
                        (qid, option_text, i == ans, i),
                    )

        if not d.fetchone('SELECT COUNT(*) AS n FROM badges')['n']:
            default_badges = [
                ('Starter', '🌱', 'প্রথম ১০০ XP অর্জন করলে পাওয়া যাবে।', 100, 1),
                ('Rising Star', '⭐', '২৫০ XP অর্জন করলে পাওয়া যাবে।', 250, 2),
                ('Quiz Champion', '🏆', '৫০০ XP অর্জন করলে পাওয়া যাবে।', 500, 3),
                ('Learning Legend', '👑', '১০০০ XP অর্জন করলে পাওয়া যাবে।', 1000, 4),
            ]
            for name, icon, description, threshold, order_no in default_badges:
                d.execute(
                    'INSERT INTO badges(name,icon,description,xp_threshold,active,display_order) VALUES(?,?,?,?,?,?)',
                    (name, icon, description, threshold, True, order_no),
                )

        d.execute('UPDATE students SET practice_class_id=class_id WHERE practice_class_id IS NULL AND class_id IS NOT NULL')
        d.execute('UPDATE quizzes SET max_question_count=? WHERE max_question_count IS NULL OR max_question_count<=0', (QUIZ_DEFAULT_MAX_QUESTION_COUNT,))
        d.execute('UPDATE quizzes SET randomize_questions=? WHERE randomize_questions IS NULL', (True,))
        d.execute('UPDATE quizzes SET student_can_choose_count=? WHERE student_can_choose_count IS NULL', (False,))
        d.commit()
    except Exception:
        d.rollback()
        raise
    finally:
        d.close()


init_db()


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('admin_id'):
            return redirect(url_for('admin_login'))
        return f(*a, **kw)
    return w


def student_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('student_id'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return w


def level_for_xp(xp):
    return max(1, int(xp // 100) + 1)


def award_badges(d, student_id, xp):
    badges = d.fetchall(
        f'SELECT * FROM badges WHERE active={BOOL_TRUE} AND xp_threshold<=? ORDER BY xp_threshold, display_order, id',
        (int(xp),),
    )
    for badge in badges:
        exists = d.fetchone('SELECT 1 AS ok FROM student_badges WHERE student_id=? AND badge_id=?', (student_id, badge['id']))
        if not exists:
            d.execute('INSERT INTO student_badges(student_id,badge_id) VALUES(?,?)', (student_id, badge['id']))


def update_student_progress(d, student_id, xp_gain):
    student = d.fetchone('SELECT * FROM students WHERE id=?', (student_id,))
    if not student:
        return
    today = date.today()
    last = None
    try:
        if student['last_active']:
            last = date.fromisoformat(str(student['last_active'])[:10])
    except (TypeError, ValueError):
        last = None
    if last == today:
        streak = int(student['streak'] or 0)
    elif last == today - timedelta(days=1):
        streak = int(student['streak'] or 0) + 1
    else:
        streak = 1
    new_xp = int(student['xp'] or 0) + int(xp_gain)
    d.execute(
        'UPDATE students SET xp=?, level=?, streak=?, last_active=?, updated_at=? WHERE id=?',
        (new_xp, level_for_xp(new_xp), streak, today.isoformat(), datetime.utcnow().isoformat(), student_id),
    )
    award_badges(d, student_id, new_xp)


def safe_external_url(value):
    value = (value or '').strip()
    if not value:
        return ''
    return value if value.startswith(('http://', 'https://')) else ''


def normalize_phone(value):
    return re.sub(r'[^0-9+]', '', (value or '').strip())


def generate_student_id(d):
    for _ in range(30):
        candidate = f"ZS-{datetime.now().year}-{secrets.token_hex(3).upper()}"
        if not d.fetchone('SELECT 1 AS ok FROM students WHERE username=? LIMIT 1', (candidate,)):
            return candidate
    raise RuntimeError('Student ID generate করা যায়নি। আবার চেষ্টা করুন।')


def storage_upload(file_storage):
    supabase_url = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    bucket = os.environ.get('SUPABASE_STORAGE_BUCKET', 'zara-sara-media').strip()
    if not supabase_url or not service_key:
        raise RuntimeError('Supabase Storage upload-এর জন্য SUPABASE_URL এবং SUPABASE_SERVICE_ROLE_KEY সেট করতে হবে।')
    original = secure_filename(file_storage.filename or '')
    ext = os.path.splitext(original)[1].lower()
    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    if ext not in allowed:
        raise RuntimeError('শুধু JPG, PNG, GIF বা WEBP image upload করা যাবে।')
    data = file_storage.stream.read()
    if not data:
        raise RuntimeError('Image file খালি।')
    if len(data) > 5 * 1024 * 1024:
        raise RuntimeError('Image সর্বোচ্চ 5 MB হতে পারবে।')
    path = f"website/{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex}{ext}"
    url = f"{supabase_url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(
        url,
        data=data,
        method='POST',
        headers={
            'Authorization': f'Bearer {service_key}',
            'apikey': service_key,
            'Content-Type': file_storage.mimetype or 'application/octet-stream',
            'x-upsert': 'false',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f'Storage upload failed: HTTP {response.status}')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')[:300]
        raise RuntimeError(f'Storage upload failed: HTTP {exc.code} {detail}') from exc
    return f"{supabase_url}/storage/v1/object/public/{bucket}/{path}"


@app.route('/')
def home():
    d = db()
    try:
        settings = d.fetchone('SELECT * FROM site_settings LIMIT 1')
        classes = d.fetchall(f'SELECT * FROM classes WHERE active={BOOL_TRUE} ORDER BY display_order')
        subjects = d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order')
        notices = d.fetchall(
            f'''SELECT * FROM notices
                WHERE published={BOOL_TRUE}
                AND (audience='public' OR audience='all')
                ORDER BY id DESC LIMIT 5'''
        )
        gallery = d.fetchall(
            f'''SELECT * FROM media_assets WHERE active={BOOL_TRUE} AND slot='gallery'
                ORDER BY id DESC LIMIT 8'''
        )
        return render_template(
            'index.html', settings=settings, classes=classes, subjects=subjects,
            notices=notices, gallery=gallery,
        )
    finally:
        d.close()


@app.route('/register', methods=['GET', 'POST'])
def register():
    d = db()
    try:
        classes = d.fetchall(f'SELECT * FROM classes WHERE active={BOOL_TRUE} ORDER BY display_order')
        if request.method == 'POST':
            display_name = request.form.get('display_name', '').strip()
            class_id = request.form.get('class_id') or ''
            phone = normalize_phone(request.form.get('phone', ''))
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            recovery_pin = request.form.get('recovery_pin', '').strip()
            if not display_name or not class_id.isdigit() or not phone:
                flash('নাম, Class এবং মোবাইল নম্বর অবশ্যই দিতে হবে।', 'error')
            elif not d.fetchone(f'SELECT 1 AS ok FROM classes WHERE id=? AND active={BOOL_TRUE}', (int(class_id),)):
                flash('সঠিক Class নির্বাচন করুন।', 'error')
            elif len(password) < 6:
                flash('Password কমপক্ষে ৬ অক্ষরের হতে হবে।', 'error')
            elif password != confirm:
                flash('Password দুবার একইভাবে লিখুন।', 'error')
            elif not re.fullmatch(r'\d{6}', recovery_pin):
                flash('Recovery PIN অবশ্যই ৬ সংখ্যার হতে হবে।', 'error')
            else:
                username = generate_student_id(d)
                d.execute(
                    '''INSERT INTO students(username,password_hash,display_name,class_id,practice_class_id,email,phone,recovery_pin_hash,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (username, generate_password_hash(password), display_name, int(class_id), int(class_id), email or None, phone, generate_password_hash(recovery_pin), datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
                )
                d.commit()
                return render_template('registration_success.html', student_id=username, display_name=display_name)
        return render_template('register.html', classes=classes)
    finally:
        d.close()


@app.route('/forgot-id', methods=['GET', 'POST'])
def forgot_id():
    student_id = None
    if request.method == 'POST':
        d = db()
        try:
            name = request.form.get('display_name', '').strip()
            phone = normalize_phone(request.form.get('phone', ''))
            pin = request.form.get('recovery_pin', '').strip()
            s = d.fetchone('SELECT * FROM students WHERE display_name=? AND phone=? AND active=? ORDER BY id LIMIT 1', (name, phone, True if USE_PG else 1))
            if s and s['recovery_pin_hash'] and check_password_hash(s['recovery_pin_hash'], pin):
                student_id = s['username']
            else:
                flash('তথ্যগুলো মেলেনি। নাম, মোবাইল ও Recovery PIN ঠিকভাবে দিন।', 'error')
        finally:
            d.close()
    return render_template('forgot_id.html', student_id=student_id)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    reset_done = False
    if request.method == 'POST':
        d = db()
        try:
            username = request.form.get('username', '').strip()
            phone = normalize_phone(request.form.get('phone', ''))
            pin = request.form.get('recovery_pin', '').strip()
            new_password = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')
            s = d.fetchone('SELECT * FROM students WHERE username=? AND phone=? AND active=?', (username, phone, True if USE_PG else 1))
            if not s or not s['recovery_pin_hash'] or not check_password_hash(s['recovery_pin_hash'], pin):
                flash('Student ID, মোবাইল বা Recovery PIN সঠিক নয়।', 'error')
            elif len(new_password) < 6:
                flash('নতুন password কমপক্ষে ৬ অক্ষরের হতে হবে।', 'error')
            elif new_password != confirm:
                flash('নতুন password দুবার একইভাবে লিখুন।', 'error')
            else:
                d.execute('UPDATE students SET password_hash=?, updated_at=? WHERE id=?', (generate_password_hash(new_password), datetime.utcnow().isoformat(), s['id']))
                d.commit()
                reset_done = True
                flash('Password reset হয়েছে। এখন নতুন password দিয়ে লগইন করুন।', 'ok')
        finally:
            d.close()
    return render_template('forgot_password.html', reset_done=reset_done)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        d = db()
        try:
            s = d.fetchone(
                f'SELECT * FROM students WHERE username=? AND active={BOOL_TRUE}',
                (request.form.get('username', '').strip(),),
            )
        finally:
            d.close()
        if s and check_password_hash(s['password_hash'], request.form.get('password', '')):
            session.clear()
            session['student_id'] = s['id']
            return redirect(url_for('student'))
        flash('ইউজারনেম বা পাসওয়ার্ড সঠিক নয়।', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/student', methods=['GET'])
@student_required
def student():
    d = db()
    try:
        s = d.fetchone(
            '''SELECT s.*, c.name class_name, pc.name practice_class_name
               FROM students s
               LEFT JOIN classes c ON c.id=s.class_id
               LEFT JOIN classes pc ON pc.id=s.practice_class_id
               WHERE s.id=?''',
            (session['student_id'],),
        )
        if not s or not s['active']:
            session.clear()
            return redirect(url_for('login'))

        practice_class_id = s['practice_class_id'] or s['class_id']
        subject_id = request.args.get('subject_id') or ''
        chapter_id = request.args.get('chapter_id') or ''
        badges = d.fetchall(
            '''SELECT b.* FROM badges b JOIN student_badges sb ON sb.badge_id=b.id
               WHERE sb.student_id=? ORDER BY sb.earned_at DESC''',
            (s['id'],),
        )
        subjects = d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name')
        chapters = []
        if practice_class_id:
            if subject_id and subject_id.isdigit():
                chapters = d.fetchall(
                    f'''SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=?
                       AND (class_id=? OR class_id IS NULL) ORDER BY display_order,title''',
                    (int(subject_id), practice_class_id),
                )
            else:
                chapters = d.fetchall(
                    f'''SELECT * FROM chapters WHERE active={BOOL_TRUE} AND (class_id=? OR class_id IS NULL)
                       ORDER BY subject_id,display_order,title''',
                    (practice_class_id,),
                )
        q_where = [f'q.published={BOOL_TRUE} AND (q.class_id IS NULL OR q.class_id=?)']
        q_params = [practice_class_id]
        if subject_id and subject_id.isdigit():
            q_where.append('q.subject_id=?'); q_params.append(int(subject_id))
        if chapter_id and chapter_id.isdigit():
            q_where.append('q.chapter_id=?'); q_params.append(int(chapter_id))
        quizzes = d.fetchall(
            f'''SELECT q.*, c.name class_name, sub.name subject_name, ch.title chapter_name,
                       COUNT(qq.question_id) AS question_pool_count
                FROM quizzes q LEFT JOIN classes c ON c.id=q.class_id LEFT JOIN subjects sub ON sub.id=q.subject_id
                LEFT JOIN chapters ch ON ch.id=q.chapter_id LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id
                WHERE {' AND '.join(q_where)} GROUP BY q.id,c.name,sub.name,ch.title ORDER BY q.id DESC''',
            tuple(q_params),
        )
        attempts = d.fetchall(
            '''SELECT qa.*, q.title, q.total_marks FROM quiz_attempts qa JOIN quizzes q ON q.id=qa.quiz_id
               WHERE qa.student_id=? AND qa.completed_at IS NOT NULL ORDER BY qa.id DESC LIMIT 5''',
            (s['id'],),
        )
        notices = d.fetchall(
            f'''SELECT * FROM notices WHERE published={BOOL_TRUE} AND audience IN ('students','all') ORDER BY id DESC LIMIT 5''',
        )
        return render_template(
            'student.html', student=s, badges=badges, quizzes=quizzes, attempts=attempts, subjects=subjects,
            chapters=chapters, selected_subject=subject_id, selected_chapter=chapter_id,
            practice_class_id=practice_class_id,
            practice_classes=d.fetchall(f'SELECT * FROM classes WHERE active={BOOL_TRUE} ORDER BY display_order'),
            notices=notices,
        )
    finally:
        d.close()


@app.route('/student/practice-class', methods=['POST'])
@student_required
def student_practice_class():
    class_id = request.form.get('practice_class_id') or None
    d = db()
    try:
        if not class_id or not str(class_id).isdigit():
            flash('Practice Class নির্বাচন করুন।', 'error')
        else:
            c = d.fetchone(f'SELECT id,name FROM classes WHERE id=? AND active={BOOL_TRUE}', (int(class_id),))
            if not c:
                flash('নির্বাচিত Practice Class পাওয়া যায়নি।', 'error')
            else:
                d.execute('UPDATE students SET practice_class_id=?,updated_at=? WHERE id=?', (c['id'],datetime.utcnow().isoformat(),session['student_id']))
                d.commit(); flash(f"Practice Class এখন {c['name']}।", 'ok')
    finally:
        d.close()
    return redirect(url_for('student'))


@app.route('/student/password', methods=['GET', 'POST'])
@student_required
def student_password():
    d = db()
    try:
        s = d.fetchone('SELECT * FROM students WHERE id=?', (session['student_id'],))
        if request.method == 'POST':
            current = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')
            if not s or not check_password_hash(s['password_hash'], current):
                flash('বর্তমান password সঠিক নয়।', 'error')
            elif len(new_password) < 6:
                flash('নতুন password কমপক্ষে ৬ অক্ষরের হতে হবে।', 'error')
            elif new_password != confirm:
                flash('নতুন password দুবার একইভাবে লিখুন।', 'error')
            else:
                d.execute('UPDATE students SET password_hash=?,updated_at=? WHERE id=?', (generate_password_hash(new_password),datetime.utcnow().isoformat(),s['id']))
                d.commit(); flash('Password পরিবর্তন হয়েছে।', 'ok'); return redirect(url_for('student'))
        return render_template('student_password.html')
    finally:
        d.close()


def _quiz_pool(d, quiz_id):
    return d.fetchall(f'''SELECT q.* FROM questions q JOIN quiz_questions qq ON qq.question_id=q.id WHERE qq.quiz_id=? AND q.active={BOOL_TRUE} ORDER BY qq.display_order,q.id''',(quiz_id,))


def _normalize_quiz_count(qz,pool_count):
    configured=int(qz['question_count'] or 0)
    default_count=configured if configured>0 else pool_count
    max_configured=int(qz['max_question_count'] or 0)
    max_count=max_configured if max_configured>0 else max(pool_count,QUIZ_DEFAULT_MAX_QUESTION_COUNT)
    max_count=min(max_count,MAX_QUESTIONS_PER_CLASS)
    default_count=max(1,min(default_count,max_count)) if pool_count else 0
    return default_count,max_count


def _choose_quiz_questions(d,student_id,quiz_id,pool,count,randomize=True):
    import random
    if not pool or count<1: return []
    prev=d.fetchall('''SELECT DISTINCT qaq.question_id FROM quiz_attempt_questions qaq JOIN quiz_attempts qa ON qa.id=qaq.attempt_id WHERE qa.student_id=? AND qa.quiz_id=? AND qa.completed_at IS NOT NULL''',(student_id,quiz_id))
    previous={int(r['question_id']) for r in prev}
    fresh=[q for q in pool if int(q['id']) not in previous]
    old=[q for q in pool if int(q['id']) in previous]
    if randomize:
        random.shuffle(fresh); random.shuffle(old)
    chosen=fresh[:min(count,len(fresh))]
    remaining=count-len(chosen)
    if remaining>0:
        source=old if old else list(pool)
        if randomize: random.shuffle(source)
        idx=0
        while remaining>0 and source:
            if idx>=len(source):
                idx=0
                if randomize: random.shuffle(source)
            chosen.append(source[idx]); idx+=1; remaining-=1
    return chosen


def _create_quiz_attempt(d,student_id,quiz_id,pool,count,randomize=True):
    chosen=_choose_quiz_questions(d,student_id,quiz_id,pool,count,randomize)
    if not chosen: raise ValueError('এই Quiz-এর Question Pool-এ Active প্রশ্ন নেই।')
    started_at=datetime.utcnow().isoformat()
    attempt_id=d.insert_id('INSERT INTO quiz_attempts(student_id,quiz_id,started_at) VALUES(?,?,?)',(student_id,quiz_id,started_at))
    for order_no,q in enumerate(chosen,1):
        d.execute('INSERT INTO quiz_attempt_questions(attempt_id,question_id,display_order) VALUES(?,?,?)',(attempt_id,int(q['id']),order_no))
    d.commit()
    return attempt_id,chosen,time.time()


@app.route('/quiz/<int:qid>', methods=['GET', 'POST'])
@student_required
def quiz(qid):
    d=db()
    try:
        student_row=d.fetchone('SELECT * FROM students WHERE id=?',(session['student_id'],))
        qz=d.fetchone(f'''SELECT q.*,c.name class_name,sub.name subject_name,ch.title chapter_name FROM quizzes q LEFT JOIN classes c ON c.id=q.class_id LEFT JOIN subjects sub ON sub.id=q.subject_id LEFT JOIN chapters ch ON ch.id=q.chapter_id WHERE q.id=? AND q.published={BOOL_TRUE}''',(qid,))
        if not qz or not student_row: return redirect(url_for('student'))
        practice_class_id=student_row['practice_class_id'] or student_row['class_id']
        if qz['class_id'] is not None and qz['class_id'] != practice_class_id:
            flash('এই Quizটি বর্তমানে নির্বাচিত Practice Class-এর জন্য নয়।','error'); return redirect(url_for('student'))
        pool=_quiz_pool(d,qid)
        if not pool:
            flash('এই কুইজে এখনো কোনো Active প্রশ্ন নেই।','error'); return redirect(url_for('student'))
        default_count,max_count=_normalize_quiz_count(qz,len(pool))
        session_key=f'quiz_started_{qid}'; attempt_key=f'quiz_attempt_{qid}'
        if request.method=='POST' and request.form.get('action')=='start':
            requested=default_count
            if bool(qz['student_can_choose_count']):
                try: requested=int(request.form.get('question_count',''))
                except ValueError: requested=0
                if requested<1 or requested>max_count:
                    flash(f'প্রশ্নসংখ্যা ১ থেকে {max_count}-এর মধ্যে দিন।','error')
                    return render_template('quiz.html',quiz=qz,questions=[],options={},setup=True,default_question_count=default_count,max_question_count=max_count,pool_count=len(pool))
            session.pop(attempt_key,None); session.pop(session_key,None)
            attempt_id,chosen,started_ts=_create_quiz_attempt(d,session['student_id'],qid,pool,requested,bool(qz['randomize_questions']))
            session[attempt_key]=attempt_id; session[session_key]=started_ts
            return redirect(url_for('quiz',qid=qid))
        attempt_id=session.get(attempt_key)
        if bool(qz['student_can_choose_count']) and not attempt_id:
            return render_template('quiz.html',quiz=qz,questions=[],options={},setup=True,default_question_count=default_count,max_question_count=max_count,pool_count=len(pool))
        if not attempt_id:
            requested=default_count if int(qz['question_count'] or 0)>0 else len(pool)
            attempt_id,chosen,started_ts=_create_quiz_attempt(d,session['student_id'],qid,pool,requested,bool(qz['randomize_questions']))
            session[attempt_key]=attempt_id; session[session_key]=started_ts
        else:
            started_ts=float(session.get(session_key,time.time()))
        attempt_rows=d.fetchall('SELECT question_id,display_order FROM quiz_attempt_questions WHERE attempt_id=? ORDER BY display_order',(attempt_id,))
        if not attempt_rows:
            session.pop(attempt_key,None); session.pop(session_key,None); flash('Quiz session পাওয়া যায়নি। আবার শুরু করুন।','error'); return redirect(url_for('quiz',qid=qid))
        unique_ids=list(dict.fromkeys(int(r['question_id']) for r in attempt_rows)); ph=','.join(['?']*len(unique_ids))
        rows=d.fetchall(f'SELECT * FROM questions WHERE id IN ({ph}) AND active={BOOL_TRUE}',tuple(unique_ids)); by_id={int(q['id']):q for q in rows}
        qs=[]
        for r in attempt_rows:
            q=by_id.get(int(r['question_id']))
            if q:
                item=dict(q); item['_attempt_position']=int(r['display_order']); qs.append(item)
        if not qs:
            flash('এই কুইজের প্রশ্নগুলো আর Active নেই।','error'); return redirect(url_for('student'))
        total_marks=sum(int(q['marks'] or 1) for q in qs)
        if request.method=='POST' and request.form.get('action','submit')!='start':
            started_ts=float(session.get(session_key,time.time())); elapsed=time.time()-started_ts
            timed_out=bool(qz['time_limit'] and elapsed>(int(qz['time_limit'])*60+15))
            score_marks=0; correct_count=0; review=[]
            for q in qs:
                opts=d.fetchall('SELECT * FROM question_options WHERE question_id=? ORDER BY display_order',(q['id'],))
                correct_row=next((dict(o) for o in opts if o['is_correct']), None)
                selected_answer=request.form.get(f"q{q['_attempt_position']}")
                correct_answer=correct_row['option_text'] if correct_row else ''
                is_correct=bool(correct_answer and selected_answer==correct_answer)
                if is_correct:
                    correct_count+=1; score_marks+=int(q['marks'] or 1)
                review_options=[]
                for o in opts:
                    od=dict(o)
                    od['is_selected']=bool(selected_answer is not None and selected_answer==o['option_text'])
                    od['is_correct']=bool(o['is_correct'])
                    review_options.append(od)
                review.append({
                    'number': int(q['_attempt_position']),
                    'question_text': q['question_text'],
                    'options': review_options,
                    'selected_answer': selected_answer,
                    'correct_answer': correct_answer,
                    'is_correct': is_correct,
                    'marks': int(q['marks'] or 1),
                })
            review.sort(key=lambda item: item['number'])
            xp=correct_count*10; started_at=datetime.utcfromtimestamp(started_ts).isoformat(); completed_at=datetime.utcnow().isoformat()
            d.execute('UPDATE quiz_attempts SET score=?,total=?,xp_earned=?,started_at=?,completed_at=? WHERE id=? AND student_id=? AND quiz_id=?',(score_marks,total_marks,xp,started_at,completed_at,attempt_id,session['student_id'],qid))
            update_student_progress(d,session['student_id'],xp); d.commit(); session.pop(session_key,None); session.pop(attempt_key,None)
            return render_template('quiz_result.html',score=score_marks,total=total_marks,correct=correct_count,question_total=len(qs),xp=xp,timed_out=timed_out,quiz=qz,review=review)
        options={q['id']:d.fetchall('SELECT * FROM question_options WHERE question_id=? ORDER BY display_order',(q['id'],)) for q in qs}
        return render_template('quiz.html',quiz=qz,questions=qs,options=options,setup=False,default_question_count=default_count,max_question_count=max_count,pool_count=len(pool))
    finally:
        d.close()


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        d = db()
        try:
            a = d.fetchone(
                f'''SELECT * FROM admin_users
                    WHERE username=? AND active={BOOL_TRUE}''',
                (request.form.get('username', '').strip(),),
            )
        finally:
            d.close()
        if a and check_password_hash(a['password_hash'], request.form.get('password', '')):
            session.clear()
            session['admin_id'] = a['id']
            return redirect(url_for('admin'))
        flash('Admin তথ্য সঠিক নয়।', 'error')
    return render_template('admin/login.html')


@app.route('/admin')
@admin_required
def admin():
    d = db()
    try:
        tables = ['students','questions','quizzes','notices','chapters','badges','games','media_assets']
        counts = {t: d.fetchone(f'SELECT COUNT(*) AS n FROM {t}')['n'] for t in tables}
        settings = d.fetchone('SELECT * FROM site_settings LIMIT 1')
        recent_quizzes = d.fetchall(
            '''SELECT q.id,q.title,q.published,q.time_limit,c.name class_name,s.name subject_name,ch.title chapter_name,
                      COUNT(qq.question_id) AS question_pool_count
               FROM quizzes q LEFT JOIN classes c ON c.id=q.class_id LEFT JOIN subjects s ON s.id=q.subject_id
               LEFT JOIN chapters ch ON ch.id=q.chapter_id LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id
               GROUP BY q.id,c.name,s.name,ch.title ORDER BY q.id DESC LIMIT 8'''
        )
        return render_template('admin/dashboard.html', counts=counts, settings=settings, recent_quizzes=recent_quizzes)
    finally:
        d.close()


@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    d = db()
    try:
        s = d.fetchone('SELECT * FROM site_settings LIMIT 1')
        if request.method == 'POST':
            fields = ['site_name','tagline','purpose','about','hero_title','hero_subtitle','logo_url','hero_image_url','background_url','facebook_url']
            vals = [request.form.get(x, '').strip() for x in fields]
            d.execute(
                '''UPDATE site_settings
                   SET site_name=?,tagline=?,purpose=?,about=?,hero_title=?,hero_subtitle=?,logo_url=?,hero_image_url=?,background_url=?,facebook_url=?
                   WHERE id=?''',
                (*vals, s['id']),
            )
            d.commit()
            flash('সাইটের তথ্য সংরক্ষণ হয়েছে।', 'ok')
            s = d.fetchone('SELECT * FROM site_settings LIMIT 1')
        return render_template('admin/settings.html', settings=s)
    finally:
        d.close()


@app.route('/admin/students', methods=['GET', 'POST'])
@admin_required
def admin_students():
    d = db()
    try:
        if request.method == 'POST':
            try:
                username = request.form.get('username', '').strip() or generate_student_id(d)
                password = request.form.get('password', '')
                display_name = request.form.get('display_name', '').strip()
                class_raw = request.form.get('class_id') or ''
                class_id = int(class_raw) if str(class_raw).isdigit() else None
                phone = normalize_phone(request.form.get('phone', '')) or None
                email = request.form.get('email', '').strip().lower() or None
                if len(password) < 6 or not display_name:
                    raise ValueError('Display name এবং কমপক্ষে ৬ অক্ষরের password প্রয়োজন।')
                if class_id is not None and not d.fetchone(f'SELECT 1 AS ok FROM classes WHERE id=? AND active={BOOL_TRUE}', (class_id,)):
                    raise ValueError('সঠিক Class নির্বাচন করুন।')
                d.execute(
                    '''INSERT INTO students(username,password_hash,display_name,class_id,practice_class_id,phone,email,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (username,generate_password_hash(password),display_name,class_id,class_id,phone,email,datetime.utcnow().isoformat()),
                )
                d.commit(); flash(f'শিক্ষার্থী যোগ হয়েছে। Student ID: {username}', 'ok')
            except ValueError as exc:
                d.rollback(); flash(str(exc), 'error')
            except Exception:
                d.rollback(); flash('Student তৈরি করা যায়নি—Student ID/username আগে আছে কি না পরীক্ষা করুন।', 'error')
        search=request.args.get('q','').strip(); filter_class=request.args.get('class_id') or ''; filter_status=request.args.get('status','').strip()
        where=[]; params=[]
        if search:
            like=f'%{search}%'
            where.append('(s.username LIKE ? OR s.display_name LIKE ? OR s.phone LIKE ? OR s.email LIKE ?)'); params.extend([like,like,like,like])
        if filter_class.isdigit(): where.append('s.class_id=?'); params.append(int(filter_class))
        if filter_status=='active': where.append(f's.active={BOOL_TRUE}')
        elif filter_status=='inactive': where.append(f's.active<>{BOOL_TRUE}')
        where_sql=('WHERE '+' AND '.join(where)) if where else ''
        students=d.fetchall(f'SELECT s.*,c.name class_name,pc.name practice_class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN classes pc ON pc.id=s.practice_class_id {where_sql} ORDER BY s.id DESC LIMIT 500',tuple(params))
        classes=d.fetchall('SELECT * FROM classes ORDER BY display_order')
        return render_template('admin/students.html',students=students,classes=classes,search=search,filter_class=filter_class,filter_status=filter_status)
    finally:
        d.close()


@app.route('/admin/students/<int:sid>/edit', methods=['GET','POST'])
@admin_required
def admin_student_edit(sid):
    d=db()
    try:
        s=d.fetchone('SELECT * FROM students WHERE id=?',(sid,))
        if not s:
            flash('শিক্ষার্থী পাওয়া যায়নি।','error'); return redirect(url_for('admin_students'))
        if request.method=='POST':
            display_name=request.form.get('display_name','').strip(); phone=normalize_phone(request.form.get('phone','')) or None
            email=request.form.get('email','').strip().lower() or None
            class_raw=request.form.get('class_id') or ''; class_id=int(class_raw) if str(class_raw).isdigit() else None
            practice_raw=request.form.get('practice_class_id') or ''; practice_class_id=int(practice_raw) if str(practice_raw).isdigit() else class_id or None
            active=request.form.get('active')=='1'; recovery_pin=request.form.get('recovery_pin','').strip()
            if not display_name:
                flash('নাম প্রয়োজন।','error')
            elif class_id is not None and not d.fetchone(f'SELECT 1 AS ok FROM classes WHERE id=?', (class_id,)):
                flash('সঠিক Registered Class নির্বাচন করুন।','error')
            elif practice_class_id is not None and not d.fetchone(f'SELECT 1 AS ok FROM classes WHERE id=? AND active={BOOL_TRUE}', (practice_class_id,)):
                flash('সঠিক Practice Class নির্বাচন করুন।','error')
            elif recovery_pin and not re.fullmatch(r'\d{6}',recovery_pin):
                flash('Recovery PIN ৬ সংখ্যার হতে হবে।','error')
            else:
                d.execute(
                    "UPDATE students SET display_name=?,phone=?,email=?,class_id=?,practice_class_id=?,active=?,updated_at=? {pin_clause} WHERE id=?".format(pin_clause=',recovery_pin_hash=?' if recovery_pin else ''),
                    (display_name,phone,email,class_id,practice_class_id,active,datetime.utcnow().isoformat(),generate_password_hash(recovery_pin),sid) if recovery_pin else (display_name,phone,email,class_id,practice_class_id,active,datetime.utcnow().isoformat(),sid),
                )
                d.commit(); flash('শিক্ষার্থীর তথ্য আপডেট হয়েছে।','ok'); return redirect(url_for('admin_students'))
        classes=d.fetchall('SELECT * FROM classes ORDER BY display_order')
        return render_template('admin/student_edit.html',student=s,classes=classes)
    finally: d.close()


@app.route('/admin/students/<int:sid>/reset-password', methods=['POST'])
@admin_required
def admin_student_reset_password(sid):
    d=db()
    try:
        new_password=request.form.get('new_password','')
        if len(new_password)<6: flash('Password কমপক্ষে ৬ অক্ষরের হতে হবে।','error')
        else:
            d.execute('UPDATE students SET password_hash=?,updated_at=? WHERE id=?',(generate_password_hash(new_password),datetime.utcnow().isoformat(),sid)); d.commit(); flash('Student password reset হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_students'))


@app.route('/api/chapters')
def api_chapters():
    class_id=request.args.get('class_id') or ''
    subject_id=request.args.get('subject_id') or ''
    d=db()
    try:
        where=[f'active={BOOL_TRUE}']; params=[]
        if subject_id.isdigit(): where.append('subject_id=?'); params.append(int(subject_id))
        if class_id.isdigit(): where.append('(class_id=? OR class_id IS NULL)'); params.append(int(class_id))
        rows=d.fetchall(f"SELECT id,title,class_id,display_order FROM chapters WHERE {' AND '.join(where)} ORDER BY display_order,title",tuple(params))
        return jsonify(chapters=[dict(r) for r in rows])
    finally: d.close()


@app.route('/admin/chapters', methods=['GET','POST'])
@admin_required
def admin_chapters():
    d=db()
    try:
        edit_id=request.args.get('edit')
        if request.method=='POST':
            title=request.form.get('title','').strip(); subject_id=request.form.get('subject_id') or None; class_id=request.form.get('class_id') or None
            description=request.form.get('description','').strip()
            try: display_order=max(0,int(request.form.get('display_order','0') or 0))
            except ValueError: display_order=0
            if not title or not subject_id:
                flash('Subject ও Chapter নাম দিতে হবে।','error')
            else:
                duplicate = d.fetchone(
                    'SELECT id FROM chapters WHERE subject_id=? AND title=? AND class_id IS NOT DISTINCT FROM ? AND (? IS NULL OR id<>?) LIMIT 1' if USE_PG else
                    'SELECT id FROM chapters WHERE subject_id=? AND title=? AND ((class_id=? ) OR (class_id IS NULL AND ? IS NULL)) AND (? IS NULL OR id<>?) LIMIT 1',
                    (subject_id,title,class_id,edit_id if edit_id and str(edit_id).isdigit() else None,edit_id if edit_id and str(edit_id).isdigit() else 0) if USE_PG else
                    (subject_id,title,class_id,class_id,edit_id if edit_id and str(edit_id).isdigit() else None,edit_id if edit_id and str(edit_id).isdigit() else 0),
                )
                if duplicate:
                    flash('এই Subject/Class-এর একই Chapter আগে থেকেই আছে।','error')
                elif edit_id and str(edit_id).isdigit():
                    d.execute('UPDATE chapters SET subject_id=?,class_id=?,title=?,description=?,display_order=? WHERE id=?',(subject_id,class_id,title,description,display_order,int(edit_id))); d.commit(); flash('Chapter আপডেট হয়েছে।','ok'); return redirect(url_for('admin_chapters'))
                else:
                    d.execute('INSERT INTO chapters(subject_id,class_id,title,description,display_order) VALUES(?,?,?,?,?)',(subject_id,class_id,title,description,display_order)); d.commit(); flash('নতুন Chapter যোগ হয়েছে।','ok')
        classes=d.fetchall('SELECT * FROM classes ORDER BY display_order'); subjects=d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name')
        filter_class=request.args.get('class_id') or ''; filter_subject=request.args.get('subject_id') or ''; search=request.args.get('q','').strip()
        where=[]; params=[]
        if filter_class.isdigit(): where.append('(ch.class_id=? OR ch.class_id IS NULL)'); params.append(int(filter_class))
        if filter_subject.isdigit(): where.append('ch.subject_id=?'); params.append(int(filter_subject))
        if search: where.append('(ch.title LIKE ? OR ch.description LIKE ?)'); params.extend([f'%{search}%',f'%{search}%'])
        where_sql=('WHERE '+' AND '.join(where)) if where else ''
        chapters=d.fetchall(f'''SELECT ch.*,c.name class_name,s.name subject_name FROM chapters ch JOIN subjects s ON s.id=ch.subject_id LEFT JOIN classes c ON c.id=ch.class_id {where_sql} ORDER BY COALESCE(ch.class_id,0),s.display_order,ch.display_order,ch.title LIMIT 500''',tuple(params))
        edit_chapter=d.fetchone('SELECT * FROM chapters WHERE id=?',(int(edit_id),)) if edit_id and str(edit_id).isdigit() else None
        return render_template('admin/chapters.html',classes=classes,subjects=subjects,chapters=chapters,edit_chapter=edit_chapter,filter_class=filter_class,filter_subject=filter_subject,search=search)
    finally: d.close()


@app.route('/admin/chapters/<int:cid>/toggle',methods=['POST'])
@admin_required
def admin_chapter_toggle(cid):
    d=db()
    try: d.execute('UPDATE chapters SET active=NOT active WHERE id=?',(cid,)); d.commit(); flash('Chapter Active/Inactive করা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_chapters'))


@app.route('/admin/chapters/<int:cid>/delete',methods=['POST'])
@admin_required
def admin_chapter_delete(cid):
    d=db()
    try:
        refs=d.fetchone('SELECT COUNT(*) AS n FROM questions WHERE chapter_id=?',(cid,))['n']; quiz_refs=d.fetchone('SELECT COUNT(*) AS n FROM quizzes WHERE chapter_id=?',(cid,))['n']
        if refs or quiz_refs: flash('এই Chapter-এর সঙ্গে প্রশ্ন/Quiz যুক্ত আছে। Delete না করে Inactive করুন।','error')
        else: d.execute('DELETE FROM chapters WHERE id=?',(cid,)); d.commit(); flash('Chapter মুছে ফেলা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_chapters'))


# ---------------------------------------------------------------------------
# Bulk Question/Quiz Import (Excel XLSX / CSV)
# ---------------------------------------------------------------------------
BULK_IMPORT_DIR = os.path.join(BASE, 'instance', 'bulk_imports')
os.makedirs(BULK_IMPORT_DIR, exist_ok=True)

BULK_HEADERS = ['Class','Subject','Chapter','Quiz Title','Quiz Description','Quiz Published','Time Limit','Question','Option A','Option B','Option C','Option D','Correct Answer','Explanation','Difficulty','Marks']
HEADER_ALIASES = {
    'class':'Class','class name':'Class','শ্রেণি':'Class','শ্রেণী':'Class',
    'subject':'Subject','বিষয়':'Subject','বিষয়':'Subject','chapter':'Chapter','অধ্যায়':'Chapter','অধ্যায়':'Chapter',
    'quiz title':'Quiz Title','quiz':'Quiz Title','কুইজ':'Quiz Title','কুইজের নাম':'Quiz Title','quiz description':'Quiz Description','কুইজ বিবরণ':'Quiz Description',
    'quiz published':'Quiz Published','published':'Quiz Published','প্রকাশিত':'Quiz Published','time limit':'Time Limit','সময়':'Time Limit','সময়':'Time Limit',
    'question':'Question','question text':'Question','প্রশ্ন':'Question','option a':'Option A','a':'Option A','অপশন a':'Option A','অপশন ১':'Option A',
    'option b':'Option B','b':'Option B','অপশন b':'Option B','অপশন ২':'Option B','option c':'Option C','c':'Option C','অপশন c':'Option C','অপশন ৩':'Option C',
    'option d':'Option D','d':'Option D','অপশন d':'Option D','অপশন ৪':'Option D','correct answer':'Correct Answer','answer':'Correct Answer','correct':'Correct Answer','উত্তর':'Correct Answer','সঠিক উত্তর':'Correct Answer',
    'explanation':'Explanation','ব্যাখ্যা':'Explanation','difficulty':'Difficulty','level':'Difficulty','কঠিনতা':'Difficulty','marks':'Marks','mark':'Marks','নম্বর':'Marks'
}

def _norm_header(value):
    text=unicodedata.normalize('NFKC',str(value or '')).strip().lower(); text=re.sub(r'\s+',' ',text)
    return HEADER_ALIASES.get(text,str(value or '').strip())

def _cell_text(value):
    if value is None: return ''
    if isinstance(value,float) and value.is_integer(): return str(int(value))
    return str(value).strip()

def _truthy(value): return _cell_text(value).lower() in {'1','true','yes','y','on','published','হ্যাঁ','হ্যা','প্রকাশিত'}

def _parse_class_name(raw):
    text=_cell_text(raw)
    if not text: return ''
    m=re.search(r'(?:class|শ্রেণি|শ্রেণী)?\s*([6-9]|10)\s*$',text,re.I)
    return f'শ্রেণি {m.group(1)}' if m else text

def _parse_correct(raw, options):
    value=_cell_text(raw); norm=value.lower()
    mapping={'a':0,'b':1,'c':2,'d':3,'1':0,'2':1,'3':2,'4':3,'option a':0,'option b':1,'option c':2,'option d':3,'option 1':0,'option 2':1,'option 3':2,'option 4':3,'অপশন ১':0,'অপশন ২':1,'অপশন ৩':2,'অপশন ৪':3}
    if norm in mapping: return mapping[norm]
    for i,opt in enumerate(options):
        if opt and norm==opt.strip().lower(): return i
    return None

def _read_bulk_file(path):
    ext=os.path.splitext(path)[1].lower()
    if ext=='.xlsx':
        if load_workbook is None: raise ValueError('Excel import-এর জন্য openpyxl package প্রয়োজন।')
        wb=load_workbook(path,read_only=True,data_only=True); ws=wb['Questions'] if 'Questions' in wb.sheetnames else wb[wb.sheetnames[0]]; rows=list(ws.iter_rows(values_only=True)); wb.close()
    elif ext=='.csv':
        with open(path,'r',encoding='utf-8-sig',newline='') as f: rows=list(csv.reader(f))
    else: raise ValueError('শুধু .xlsx অথবা .csv ফাইল গ্রহণ করা হচ্ছে।')
    if not rows: raise ValueError('ফাইলটি খালি।')
    headers=[_norm_header(x) for x in rows[0]]; indexes={h:i for i,h in enumerate(headers) if h}
    required=['Class','Subject','Chapter','Question','Option A','Option B','Option C','Option D','Correct Answer']; missing=[h for h in required if h not in indexes]
    if missing: raise ValueError('প্রয়োজনীয় column নেই: '+', '.join(missing))
    parsed=[]
    for line_no,raw in enumerate(rows[1:],2):
        if not any(_cell_text(x) for x in raw): continue
        def val(h):
            i=indexes.get(h); return _cell_text(raw[i]) if i is not None and i<len(raw) else ''
        options=[val('Option A'),val('Option B'),val('Option C'),val('Option D')]; correct=_parse_correct(val('Correct Answer'),options)
        try: marks=max(1,int(float(val('Marks') or '1')))
        except ValueError: marks=None
        try: time_limit=max(0,int(float(val('Time Limit') or '0')))
        except ValueError: time_limit=None
        difficulty=(val('Difficulty') or 'medium').lower(); difficulty=difficulty if difficulty in {'easy','medium','hard'} else 'medium'
        parsed.append({'line':line_no,'class_name':_parse_class_name(val('Class')),'subject_name':val('Subject'),'chapter_title':val('Chapter'),'quiz_title':val('Quiz Title'),'quiz_description':val('Quiz Description'),'quiz_published':_truthy(val('Quiz Published')),'time_limit':time_limit,'question':val('Question'),'options':options,'correct':correct,'explanation':val('Explanation'),'difficulty':difficulty,'marks':marks})
    return parsed

def _validate_bulk_rows(rows):
    errors=[]; seen=set()
    for row in rows:
        prefix=f"Row {row['line']}: "
        if not row['class_name'] or not row['subject_name'] or not row['chapter_title']: errors.append(prefix+'Class, Subject এবং Chapter আবশ্যক।')
        if not row['question']: errors.append(prefix+'Question খালি।')
        if not all(row['options']): errors.append(prefix+'চারটি Option-ই দিতে হবে।')
        if row['correct'] is None: errors.append(prefix+'Correct Answer A/B/C/D, 1/2/3/4 অথবা option-এর exact text হতে হবে।')
        if row['marks'] is None: errors.append(prefix+'Marks একটি সংখ্যা হতে হবে।')
        if row['time_limit'] is None: errors.append(prefix+'Time Limit একটি সংখ্যা হতে হবে।')
        key=(row['class_name'].lower(),row['subject_name'].lower(),row['chapter_title'].lower(),row['question'].strip().lower())
        if key in seen: errors.append(prefix+'একই file-এ duplicate question আছে।')
        seen.add(key)
        if len(set(x.strip().lower() for x in row['options']))<4: errors.append(prefix+'চারটি option আলাদা হতে হবে।')
    return errors

def _get_or_create_class(d,name):
    row=d.fetchone('SELECT id,name FROM classes WHERE lower(name)=lower(?) LIMIT 1',(name,))
    if row: return row['id']
    m=re.search(r'(6|7|8|9|10)$',name)
    if not m: raise ValueError(f'অজানা Class: {name}')
    return d.insert_id('INSERT INTO classes(name,display_order,active) VALUES(?,?,?)',(name,int(m.group(1))-5,True))

def _get_or_create_subject(d,name):
    row=d.fetchone('SELECT id FROM subjects WHERE lower(name)=lower(?) LIMIT 1',(name,))
    return row['id'] if row else d.insert_id('INSERT INTO subjects(name,icon,display_order,active) VALUES(?,?,?,?)',(name,'📘',99,True))

def _get_or_create_chapter(d,subject_id,class_id,title):
    row=d.fetchone('SELECT id FROM chapters WHERE subject_id=? AND title=? AND (class_id=? OR class_id IS NULL) ORDER BY CASE WHEN class_id=? THEN 0 ELSE 1 END,id LIMIT 1',(subject_id,title,class_id,class_id))
    return row['id'] if row else d.insert_id('INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',(subject_id,class_id,title))

def _find_existing_question(d,class_id,chapter_id,text):
    return d.fetchone('SELECT id FROM questions WHERE class_id=? AND chapter_id=? AND lower(trim(question_text))=lower(trim(?)) LIMIT 1',(class_id,chapter_id,text))

def _ensure_question_capacity(d, class_id, extra=1, exclude_qid=None):
    if class_id is None:
        return
    sql='SELECT COUNT(*) AS n FROM questions WHERE class_id=?'
    params=[int(class_id)]
    if exclude_qid is not None:
        sql+=' AND id<>?'; params.append(int(exclude_qid))
    current=int(d.fetchone(sql,tuple(params))['n'])
    if current + int(extra or 0) > MAX_QUESTIONS_PER_CLASS:
        raise ValueError(f'এই Class-এ সর্বোচ্চ {MAX_QUESTIONS_PER_CLASS}টি প্রশ্ন রাখা যাবে। বর্তমানে {current}টি আছে।')


def _import_bulk_rows(d,rows):
    created_questions=reused_questions=created_quizzes=linked_quiz_questions=0; quiz_ids={}
    for row in rows:
        class_id=_get_or_create_class(d,row['class_name']); subject_id=_get_or_create_subject(d,row['subject_name']); chapter_id=_get_or_create_chapter(d,subject_id,class_id,row['chapter_title'])
        existing=_find_existing_question(d,class_id,chapter_id,row['question'])
        if existing: qid=existing['id']; reused_questions+=1
        else:
            _ensure_question_capacity(d,class_id,1)
            qid=d.insert_id('INSERT INTO questions(subject_id,chapter_id,class_id,question_text,question_type,explanation,difficulty,marks,active) VALUES(?,?,?,?,?,?,?,?,?)',(subject_id,chapter_id,class_id,row['question'],'mcq',row['explanation'],row['difficulty'],row['marks'],True))
            for i,opt in enumerate(row['options']): d.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,opt,i==row['correct'],i+1))
            created_questions+=1
        if row['quiz_title']:
            key=(class_id,subject_id,chapter_id,row['quiz_title'].strip().lower())
            if key not in quiz_ids:
                existing_quiz=d.fetchone('SELECT id FROM quizzes WHERE title=? AND class_id=? AND subject_id=? AND chapter_id=? LIMIT 1',(row['quiz_title'].strip(),class_id,subject_id,chapter_id))
                if existing_quiz: quiz_id=existing_quiz['id']
                else:
                    quiz_id=d.insert_id('INSERT INTO quizzes(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published,question_count,max_question_count,student_can_choose_count,randomize_questions) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(row['quiz_title'].strip(),row['quiz_description'],class_id,subject_id,chapter_id,row['time_limit'],0,row['quiz_published'],0,QUIZ_DEFAULT_MAX_QUESTION_COUNT,False,True)); created_quizzes+=1
                quiz_ids[key]=quiz_id
            quiz_id=quiz_ids[key]
            if not d.fetchone('SELECT 1 AS ok FROM quiz_questions WHERE quiz_id=? AND question_id=?',(quiz_id,qid)):
                order_row=d.fetchone('SELECT COALESCE(MAX(display_order),0)+1 AS n FROM quiz_questions WHERE quiz_id=?',(quiz_id,)); d.execute('INSERT INTO quiz_questions(quiz_id,question_id,display_order) VALUES(?,?,?)',(quiz_id,qid,order_row['n'])); linked_quiz_questions+=1
    for quiz_id in set(quiz_ids.values()):
        total=d.fetchone('SELECT COALESCE(SUM(q.marks),0) AS total FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id WHERE qq.quiz_id=?',(quiz_id,))['total']; d.execute('UPDATE quizzes SET total_marks=? WHERE id=?',(total,quiz_id))
    return created_questions,reused_questions,created_quizzes,linked_quiz_questions

@app.route('/admin/questions/import',methods=['GET','POST'])
@admin_required
def admin_question_import():
    if request.method=='GET': return render_template('admin/question_import.html')
    upload=request.files.get('file')
    if not upload or not upload.filename: flash('Excel (.xlsx) অথবা CSV ফাইল নির্বাচন করুন।','error'); return redirect(url_for('admin_question_import'))
    filename=secure_filename(upload.filename); ext=os.path.splitext(filename)[1].lower()
    if ext not in {'.xlsx','.csv'}: flash('শুধু .xlsx অথবা .csv ফাইল গ্রহণ করা হচ্ছে।','error'); return redirect(url_for('admin_question_import'))
    token=secrets.token_urlsafe(18); path=os.path.join(BULK_IMPORT_DIR,token+ext); upload.save(path)
    try:
        rows=_read_bulk_file(path); errors=_validate_bulk_rows(rows)
        if errors:
            os.remove(path); return render_template('admin/question_import.html',errors=errors[:100],error_count=len(errors),row_count=len(rows))
        with open(os.path.join(BULK_IMPORT_DIR,token+'.json'),'w',encoding='utf-8') as f: json.dump({'filename':filename,'path':path,'row_count':len(rows)},f,ensure_ascii=False)
        return render_template('admin/question_import.html',token=token,preview=rows[:30],row_count=len(rows),filename=filename)
    except Exception as exc:
        try: os.remove(path)
        except OSError: pass
        flash(f'ফাইল পড়তে সমস্যা হয়েছে: {exc}','error'); return redirect(url_for('admin_question_import'))

@app.route('/admin/questions/import/confirm/<token>',methods=['POST'])
@admin_required
def admin_question_import_confirm(token):
    meta_path=os.path.join(BULK_IMPORT_DIR,token+'.json')
    if not os.path.exists(meta_path): flash('Import preview-এর মেয়াদ শেষ হয়েছে। ফাইলটি আবার upload করুন।','error'); return redirect(url_for('admin_question_import'))
    try:
        with open(meta_path,encoding='utf-8') as f: meta=json.load(f)
        rows=_read_bulk_file(meta['path']); errors=_validate_bulk_rows(rows)
        if errors: raise ValueError('Import validation ব্যর্থ হয়েছে: '+' | '.join(errors[:5]))
        d=db()
        try:
            result=_import_bulk_rows(d,rows); d.commit()
        except Exception: d.rollback(); raise
        finally: d.close()
        for p in (meta['path'],meta_path):
            try: os.remove(p)
            except OSError: pass
        flash(f'Bulk import সফল: নতুন প্রশ্ন {result[0]}, আগে থাকা প্রশ্ন {result[1]}, নতুন Quiz {result[2]}, Quiz-এ যুক্ত প্রশ্ন {result[3]}।','ok')
        return redirect(url_for('admin_questions'))
    except Exception as exc: flash(f'Import ব্যর্থ হয়েছে: {exc}','error'); return redirect(url_for('admin_question_import'))

@app.route('/admin/questions/import-template')
@admin_required
def admin_question_import_template():
    if Workbook is None: flash('Excel template তৈরি করতে openpyxl প্রয়োজন।','error'); return redirect(url_for('admin_question_import'))
    wb=Workbook(); ws=wb.active; ws.title='Questions'; ws.append(BULK_HEADERS); ws.append(['9','বিজ্ঞান','অধ্যায় ৫','অধ্যায় ৫ অনুশীলনী','অধ্যায় ৫-এর MCQ Quiz','No','15','উদাহরণ প্রশ্ন লিখুন','Option A','Option B','Option C','Option D','B','সঠিক উত্তরটি কেন সঠিক—ব্যাখ্যা','medium','1'])
    for cell in ws[1]: cell.font=cell.font.copy(bold=True)
    widths=[12,18,24,28,32,16,14,45,25,25,25,25,18,40,14,10]
    for i,width in enumerate(widths,1): ws.column_dimensions[chr(64+i)].width=width
    info=wb.create_sheet('Instructions')
    for row in [
        ['Bulk Question Import — নির্দেশনা'],
        ['আবশ্যক কলাম','Class, Subject, Chapter, Question, Option A, Option B, Option C, Option D, Correct Answer'],
        ['Correct Answer','A/B/C/D, 1/2/3/4 অথবা option-এর exact text লিখুন।'],
        ['Difficulty','easy / medium / hard; খালি রাখলে medium হবে।'],
        ['Marks','পূর্ণসংখ্যা; খালি রাখলে 1।'],
        ['Quiz Title','দিলে import-এর সময় ওই Chapter-এর জন্য Quiz তৈরি/আপডেট হবে। খালি রাখলে শুধু Question Bank-এ প্রশ্ন যাবে।'],
        ['Quiz Published','Yes/No, True/False বা 1/0।'],
        ['Time Limit','মিনিটে; 0 মানে no limit।'],
        ['Duplicate','একই Class + Chapter + Question আগে থাকলে duplicate question তৈরি না করে existing question reuse করা হবে।'],
        ['Encoding','CSV হলে UTF-8 with BOM ব্যবহার করুন। Excel (.xlsx) বেশি সুবিধাজনক।']]: info.append(row)
    info.column_dimensions['A'].width=28; info.column_dimensions['B'].width=110
    out=os.path.join(BULK_IMPORT_DIR,'bulk_question_import_template.xlsx'); wb.save(out)
    from flask import send_file
    return send_file(out,as_attachment=True,download_name='bulk_question_import_template.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/admin/questions', methods=['GET', 'POST'])
@admin_required
def admin_questions():
    d=db()
    try:
        if request.method=='POST':
            class_id=request.form.get('class_id') or None; sid=request.form.get('subject_id'); chapter_id=request.form.get('chapter_id') or None; new_chapter=request.form.get('new_chapter','').strip()
            textq=request.form.get('question_text','').strip(); explanation=request.form.get('explanation','').strip(); difficulty=request.form.get('difficulty','medium').strip() or 'medium'
            try: marks=max(1,int(request.form.get('marks','1') or 1))
            except ValueError: marks=1
            try: ans=max(0,min(3,int(request.form.get('correct',0))))
            except ValueError: ans=0
            opts=[request.form.get(f'opt{i}','').strip() for i in range(4)]
            if not sid or not textq or not all(opts):
                flash('Subject, Chapter, Question এবং চারটি Option পূরণ করুন।','error')
            else:
                cid=None
                if new_chapter:
                    ch=d.fetchone('SELECT id FROM chapters WHERE subject_id=? AND title=? AND (class_id=? OR class_id IS NULL) ORDER BY id LIMIT 1',(sid,new_chapter,class_id))
                    cid=ch['id'] if ch else d.insert_id('INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',(sid,class_id,new_chapter))
                elif chapter_id and str(chapter_id).isdigit():
                    ch=d.fetchone('SELECT id FROM chapters WHERE id=? AND subject_id=? AND (class_id=? OR class_id IS NULL)',(int(chapter_id),sid,class_id)); cid=ch['id'] if ch else None
                if not cid:
                    flash('সঠিক Chapter নির্বাচন বা নতুন Chapter-এর নাম দিন।','error')
                elif class_id and int(d.fetchone('SELECT COUNT(*) AS n FROM questions WHERE class_id=?',(int(class_id),))['n']) >= MAX_QUESTIONS_PER_CLASS:
                    flash(f'এই Class-এ সর্বোচ্চ {MAX_QUESTIONS_PER_CLASS}টি প্রশ্ন রাখা যাবে।','error')
                else:
                    qid=d.insert_id('INSERT INTO questions(subject_id,chapter_id,class_id,question_text,question_type,explanation,difficulty,marks) VALUES(?,?,?,?,?,?,?,?)',(sid,cid,class_id,textq,'mcq',explanation,difficulty,marks))
                    for i,o in enumerate(opts): d.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,o,i==ans,i))
                    d.commit(); flash('প্রশ্ন যোগ হয়েছে।','ok')
        class_id=request.args.get('class_id') or ''; subject_id=request.args.get('subject_id') or ''; chapter_id=request.args.get('chapter_id') or ''; difficulty=request.args.get('difficulty') or ''
        try: page=max(1,int(request.args.get('page','1') or 1))
        except ValueError: page=1
        per_page=100
        where=[]; params=[]
        if class_id: where.append('(q.class_id=? OR q.class_id IS NULL)'); params.append(class_id)
        if subject_id: where.append('q.subject_id=?'); params.append(subject_id)
        if chapter_id: where.append('q.chapter_id=?'); params.append(chapter_id)
        if difficulty: where.append('q.difficulty=?'); params.append(difficulty)
        where_sql=('WHERE '+' AND '.join(where)) if where else ''
        question_total=int(d.fetchone(f'SELECT COUNT(*) AS n FROM questions q {where_sql}',tuple(params))['n'])
        total_pages=max(1,(question_total+per_page-1)//per_page)
        page=min(page,total_pages); offset=(page-1)*per_page
        subjects=d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name'); classes=d.fetchall('SELECT * FROM classes ORDER BY display_order')
        questions=d.fetchall(f'SELECT q.*,s.name subject_name,c.title chapter_name,cl.name class_name FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters c ON c.id=q.chapter_id LEFT JOIN classes cl ON cl.id=q.class_id {where_sql} ORDER BY q.id DESC LIMIT {per_page} OFFSET {offset}',tuple(params))
        class_question_counts=d.fetchall('SELECT c.id,c.name,COUNT(q.id) AS question_count FROM classes c LEFT JOIN questions q ON q.class_id=c.id GROUP BY c.id,c.name ORDER BY c.display_order,c.id')
        chapters=[]
        if subject_id and subject_id.isdigit():
            if class_id and class_id.isdigit(): chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? AND (class_id=? OR class_id IS NULL) ORDER BY display_order,title',(int(subject_id),int(class_id)))
            else: chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? ORDER BY class_id,display_order,title',(int(subject_id),))
        return render_template('admin/questions.html',subjects=subjects,classes=classes,chapters=chapters,questions=questions,selected_class=class_id,selected_subject=subject_id,selected_chapter=chapter_id,selected_difficulty=difficulty,question_total=question_total,page=page,total_pages=total_pages,per_page=per_page,class_question_counts=class_question_counts,max_questions_per_class=MAX_QUESTIONS_PER_CLASS)
    finally: d.close()


@app.route('/admin/questions/<int:qid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_question_edit(qid):
    d=db()
    try:
        q=d.fetchone('SELECT * FROM questions WHERE id=?',(qid,))
        if not q: return redirect(url_for('admin_questions'))
        if request.method=='POST':
            class_id=request.form.get('class_id') or None; sid=request.form.get('subject_id'); chapter_id=request.form.get('chapter_id') or None; new_chapter=request.form.get('new_chapter','').strip(); textq=request.form.get('question_text','').strip(); explanation=request.form.get('explanation','').strip(); difficulty=request.form.get('difficulty','medium').strip() or 'medium'
            try: marks=max(1,int(request.form.get('marks','1') or 1))
            except ValueError: marks=1
            opts=[request.form.get(f'opt{i}','').strip() for i in range(4)]; ans=int(request.form.get('correct',0)); cid=None
            if new_chapter:
                ch=d.fetchone('SELECT id FROM chapters WHERE subject_id=? AND title=? AND (class_id=? OR class_id IS NULL) LIMIT 1',(sid,new_chapter,class_id)); cid=ch['id'] if ch else d.insert_id('INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',(sid,class_id,new_chapter))
            elif chapter_id and str(chapter_id).isdigit():
                ch=d.fetchone('SELECT id FROM chapters WHERE id=? AND subject_id=? AND (class_id=? OR class_id IS NULL)',(int(chapter_id),sid,class_id)); cid=ch['id'] if ch else None
            if not sid or not textq or not all(opts) or not cid:
                flash('Subject, Chapter, Question এবং চারটি Option সঠিকভাবে পূরণ করুন।','error')
            else:
                if class_id and (q['class_id'] is None or int(q['class_id']) != int(class_id)) and int(d.fetchone('SELECT COUNT(*) AS n FROM questions WHERE class_id=? AND id<>?',(int(class_id),qid))['n']) >= MAX_QUESTIONS_PER_CLASS:
                    flash(f'এই Class-এ সর্বোচ্চ {MAX_QUESTIONS_PER_CLASS}টি প্রশ্ন রাখা যাবে।','error')
                    return redirect(url_for('admin_question_edit',qid=qid))
                d.execute('''UPDATE questions SET subject_id=?,chapter_id=?,class_id=?,question_text=?,explanation=?,difficulty=?,marks=? WHERE id=?''',(sid,cid,class_id,textq,explanation,difficulty,marks,qid)); d.execute('DELETE FROM question_options WHERE question_id=?',(qid,))
                for i,o in enumerate(opts): d.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,o,i==ans,i))
                d.commit(); flash('প্রশ্নের তথ্য আপডেট হয়েছে।','ok'); return redirect(url_for('admin_questions'))
        subjects=d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name'); classes=d.fetchall('SELECT * FROM classes ORDER BY display_order'); options=d.fetchall('SELECT * FROM question_options WHERE question_id=? ORDER BY display_order',(qid,))
        if q['subject_id']:
            if q['class_id']:
                chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? AND (class_id=? OR class_id IS NULL) ORDER BY display_order,title',(q['subject_id'],q['class_id']))
            else:
                chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? ORDER BY class_id,display_order,title',(q['subject_id'],))
        else: chapters=[]
        chapter=d.fetchone('SELECT title FROM chapters WHERE id=?',(q['chapter_id'],)) if q['chapter_id'] else None; q['chapter_title']=chapter['title'] if chapter else ''
        return render_template('admin/question_edit.html',question=q,options=options,subjects=subjects,classes=classes,chapters=chapters)
    finally: d.close()


@app.route('/admin/questions/<int:qid>/toggle', methods=['POST'])
@admin_required
def admin_question_toggle(qid):
    d = db()
    try:
        q = d.fetchone('SELECT active FROM questions WHERE id=?', (qid,))
        if not q:
            return redirect(url_for('admin_questions'))
        d.execute(f'UPDATE questions SET active=NOT active WHERE id=?', (qid,))
        d.commit()
        flash('প্রশ্নের Active/Inactive অবস্থা বদলানো হয়েছে।', 'ok')
        return redirect(url_for('admin_questions'))
    finally:
        d.close()


@app.route('/admin/questions/<int:qid>/delete', methods=['POST'])
@admin_required
def admin_question_delete(qid):
    d = db()
    try:
        d.execute('DELETE FROM questions WHERE id=?', (qid,))
        d.commit()
        flash('প্রশ্ন মুছে ফেলা হয়েছে।', 'ok')
        return redirect(url_for('admin_questions'))
    finally:
        d.close()


@app.route('/admin/quizzes', methods=['GET', 'POST'])
@admin_required
def admin_quizzes():
    d=db()
    try:
        edit_id=request.args.get('edit'); edit_quiz=None; selected_question_ids=set()
        if request.method=='POST':
            title=request.form.get('title','').strip(); description=request.form.get('description','').strip(); class_id=request.form.get('class_id') or None; subject_id=request.form.get('subject_id') or None; chapter_id=request.form.get('chapter_id') or None
            try: time_limit=max(0,int(request.form.get('time_limit','0') or 0))
            except ValueError: time_limit=0
            try: requested_total_marks=max(0,int(request.form.get('total_marks','0') or 0))
            except ValueError: requested_total_marks=0
            try: question_count=max(0,int(request.form.get('question_count','0') or 0))
            except ValueError: question_count=0
            try: max_question_count=max(1,min(MAX_QUESTIONS_PER_CLASS,int(request.form.get('max_question_count',QUIZ_DEFAULT_MAX_QUESTION_COUNT) or QUIZ_DEFAULT_MAX_QUESTION_COUNT)))
            except ValueError: max_question_count=QUIZ_DEFAULT_MAX_QUESTION_COUNT
            student_can_choose=request.form.get('student_can_choose_count')=='1'; randomize_questions=request.form.get('randomize_questions')=='1'
            published=request.form.get('published')=='1'
            if question_count>max_question_count: flash('Default Question Count, Maximum Question Count-এর চেয়ে বেশি হতে পারে না।','error')
            elif not title: flash('Quiz Title দিন।','error')
            elif question_count < 1: flash('Question Count কমপক্ষে ১ হতে হবে।','error')
            else:
                # Automatic Question Pool: the Admin only chooses Class/Subject/Chapter.
                # Every active question matching those filters becomes part of the pool.
                q_where=[f'q.active={BOOL_TRUE}']; q_params=[]
                if class_id:
                    q_where.append('(q.class_id=? OR q.class_id IS NULL)'); q_params.append(int(class_id))
                if subject_id:
                    q_where.append('q.subject_id=?'); q_params.append(int(subject_id))
                if chapter_id:
                    q_where.append('q.chapter_id=?'); q_params.append(int(chapter_id))
                pool_rows=d.fetchall(
                    f'''SELECT q.id,q.marks,q.class_id,q.subject_id,q.chapter_id
                        FROM questions q
                        WHERE {' AND '.join(q_where)}
                        ORDER BY q.id''', tuple(q_params)
                )
                selected=[int(r['id']) for r in pool_rows]
                valid={int(r['id']):r for r in pool_rows}
                if not selected:
                    flash('এই Class/Subject/Chapter অনুযায়ী কোনো Active প্রশ্ন পাওয়া যায়নি। আগে Question Bank-এ প্রশ্ন যোগ করুন।','error')
                else:
                    total_marks=requested_total_marks or sum(int(valid[qid]['marks'] or 1) for qid in selected)
                    if edit_id and str(edit_id).isdigit():
                        quiz_id=int(edit_id)
                        d.execute('''UPDATE quizzes SET title=?,description=?,class_id=?,subject_id=?,chapter_id=?,time_limit=?,total_marks=?,published=?,question_count=?,max_question_count=?,student_can_choose_count=?,randomize_questions=? WHERE id=?''',(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published,question_count,max_question_count,student_can_choose,randomize_questions,quiz_id))
                        d.execute('DELETE FROM quiz_questions WHERE quiz_id=?',(quiz_id,))
                        flash(f'Quiz আপডেট হয়েছে। Question Pool-এ {len(selected)}টি Active প্রশ্ন যুক্ত হয়েছে।','ok')
                    else:
                        quiz_id=d.insert_id('''INSERT INTO quizzes(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published,question_count,max_question_count,student_can_choose_count,randomize_questions) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published,question_count,max_question_count,student_can_choose,randomize_questions))
                        flash(f'নতুন Quiz তৈরি হয়েছে। Question Bank থেকে {len(selected)}টি Active প্রশ্নের automatic pool তৈরি হয়েছে।','ok')
                    for order_no,question_id in enumerate(selected,1):
                        d.execute('INSERT INTO quiz_questions(quiz_id,question_id,display_order) VALUES(?,?,?)',(quiz_id,question_id,order_no))
                    d.commit(); return redirect(url_for('admin_quizzes',edit=quiz_id))
        if edit_id and str(edit_id).isdigit():
            edit_quiz=d.fetchone('SELECT * FROM quizzes WHERE id=?',(int(edit_id),))
            if edit_quiz: selected_question_ids={int(r['question_id']) for r in d.fetchall('SELECT question_id FROM quiz_questions WHERE quiz_id=?',(int(edit_id),))}
        classes=d.fetchall('SELECT * FROM classes ORDER BY display_order'); subjects=d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name')
        filter_class=request.args.get('class_id') or (str(edit_quiz['class_id']) if edit_quiz and edit_quiz['class_id'] else ''); filter_subject=request.args.get('subject_id') or (str(edit_quiz['subject_id']) if edit_quiz and edit_quiz['subject_id'] else ''); filter_chapter=request.args.get('chapter_id') or (str(edit_quiz['chapter_id']) if edit_quiz and edit_quiz['chapter_id'] else '')
        q_where=[f'q.active={BOOL_TRUE}']; q_params=[]
        if filter_class: q_where.append('(q.class_id=? OR q.class_id IS NULL)'); q_params.append(filter_class)
        if filter_subject: q_where.append('q.subject_id=?'); q_params.append(filter_subject)
        if filter_chapter: q_where.append('q.chapter_id=?'); q_params.append(filter_chapter)
        order_sql='ORDER BY q.class_id,q.subject_id,q.chapter_id,q.id' if not USE_PG else 'ORDER BY q.class_id NULLS FIRST,q.subject_id,q.chapter_id,q.id'
        questions=d.fetchall(f'''SELECT q.*,s.name subject_name,c.title chapter_name,cl.name class_name FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters c ON c.id=q.chapter_id LEFT JOIN classes cl ON cl.id=q.class_id WHERE {' AND '.join(q_where)} {order_sql} LIMIT 5000''',tuple(q_params))
        chapters=d.fetchall(f'''SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? {'AND (class_id=? OR class_id IS NULL)' if filter_class else ''} ORDER BY display_order,title''',(filter_subject,filter_class) if filter_subject and filter_class else (filter_subject,)) if filter_subject else []
        quizzes=d.fetchall('''SELECT q.*,c.name class_name,s.name subject_name,ch.title chapter_name,COUNT(qq.question_id) AS question_pool_count FROM quizzes q LEFT JOIN classes c ON c.id=q.class_id LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters ch ON ch.id=q.chapter_id LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id GROUP BY q.id,c.name,s.name,ch.title ORDER BY q.id DESC''')
        return render_template('admin/quizzes.html',classes=classes,subjects=subjects,chapters=chapters,questions=questions,quizzes=quizzes,edit_quiz=edit_quiz,selected_question_ids=selected_question_ids,filter_class=filter_class,filter_subject=filter_subject,filter_chapter=filter_chapter)
    finally: d.close()


@app.route('/admin/quizzes/<int:quiz_id>/toggle', methods=['POST'])
@admin_required
def admin_quiz_toggle(quiz_id):
    d = db()
    try:
        q = d.fetchone('SELECT published FROM quizzes WHERE id=?', (quiz_id,))
        if not q:
            return redirect(url_for('admin_quizzes'))
        d.execute('UPDATE quizzes SET published=NOT published WHERE id=?', (quiz_id,))
        d.commit()
        flash('Quiz Publish/Unpublish করা হয়েছে।', 'ok')
        return redirect(url_for('admin_quizzes'))
    finally:
        d.close()


@app.route('/admin/quizzes/<int:quiz_id>/delete', methods=['POST'])
@admin_required
def admin_quiz_delete(quiz_id):
    d = db()
    try:
        d.execute('DELETE FROM quizzes WHERE id=?', (quiz_id,))
        d.commit()
        flash('Quiz মুছে ফেলা হয়েছে।', 'ok')
        return redirect(url_for('admin_quizzes'))
    finally:
        d.close()


@app.route('/admin/password', methods=['GET','POST'])
@admin_required
def admin_password():
    d=db()
    try:
        admin=d.fetchone('SELECT * FROM admin_users WHERE id=?',(session['admin_id'],))
        if request.method=='POST':
            current=request.form.get('current_password',''); new_password=request.form.get('new_password',''); confirm=request.form.get('confirm_password','')
            if not admin or not check_password_hash(admin['password_hash'],current): flash('বর্তমান Admin password সঠিক নয়।','error')
            elif len(new_password)<8: flash('নতুন Admin password কমপক্ষে ৮ অক্ষরের হতে হবে।','error')
            elif new_password!=confirm: flash('নতুন password দুবার একইভাবে লিখুন।','error')
            else: d.execute('UPDATE admin_users SET password_hash=? WHERE id=?',(generate_password_hash(new_password),admin['id'])); d.commit(); flash('Admin password পরিবর্তন হয়েছে।','ok'); return redirect(url_for('admin'))
        return render_template('admin/password.html')
    finally: d.close()


@app.route('/admin/badges', methods=['GET','POST'])
@admin_required
def admin_badges():
    d=db()
    try:
        edit_id=request.args.get('edit')
        if request.method=='POST':
            name=request.form.get('name','').strip(); icon=request.form.get('icon','🏅').strip() or '🏅'; description=request.form.get('description','').strip()
            try: threshold=max(0,int(request.form.get('xp_threshold','0') or 0)); order_no=max(0,int(request.form.get('display_order','0') or 0))
            except ValueError: threshold=0; order_no=0
            if not name: flash('Badge name দিন।','error')
            elif edit_id and str(edit_id).isdigit(): d.execute('UPDATE badges SET name=?,icon=?,description=?,xp_threshold=?,display_order=? WHERE id=?',(name,icon,description,threshold,order_no,int(edit_id))); d.commit(); flash('Badge আপডেট হয়েছে।','ok'); return redirect(url_for('admin_badges'))
            else: d.execute('INSERT INTO badges(name,icon,description,xp_threshold,display_order,active) VALUES(?,?,?,?,?,?)',(name,icon,description,threshold,order_no,True)); d.commit(); flash('নতুন Badge যোগ হয়েছে।','ok')
        badges=d.fetchall('SELECT * FROM badges ORDER BY xp_threshold,display_order,id'); edit_badge=d.fetchone('SELECT * FROM badges WHERE id=?',(int(edit_id),)) if edit_id and str(edit_id).isdigit() else None
        leaderboard=d.fetchall(f'''SELECT s.id,s.username,s.display_name,s.xp,s.level,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active={BOOL_TRUE} ORDER BY s.xp DESC,s.id LIMIT 20''')
        return render_template('admin/badges.html',badges=badges,edit_badge=edit_badge,leaderboard=leaderboard)
    finally: d.close()


@app.route('/admin/badges/<int:bid>/toggle',methods=['POST'])
@admin_required
def admin_badge_toggle(bid):
    d=db()
    try: d.execute('UPDATE badges SET active=NOT active WHERE id=?',(bid,)); d.commit(); flash('Badge Active/Inactive করা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_badges'))


@app.route('/admin/badges/<int:bid>/delete',methods=['POST'])
@admin_required
def admin_badge_delete(bid):
    d=db()
    try: d.execute('DELETE FROM badges WHERE id=?',(bid,)); d.commit(); flash('Badge মুছে ফেলা হয়েছে।','ok')
    except Exception: d.rollback(); flash('এই Badge-এর অর্জন record আছে। Delete না করে Inactive করুন।','error')
    finally: d.close()
    return redirect(url_for('admin_badges'))


@app.route('/games')
def games():
    d=db()
    try: return render_template('games.html',games=d.fetchall(f'SELECT * FROM games WHERE active={BOOL_TRUE} ORDER BY display_order,title'))
    finally: d.close()


@app.route('/admin/games',methods=['GET','POST'])
@admin_required
def admin_games():
    d=db()
    try:
        edit_id=request.args.get('edit')
        if request.method=='POST':
            title=request.form.get('title','').strip(); slug=request.form.get('slug','').strip().lower(); description=request.form.get('description','').strip(); game_type=request.form.get('type','').strip(); launch_url=safe_external_url(request.form.get('launch_url','')); active=request.form.get('active')=='1'
            try: order_no=max(0,int(request.form.get('display_order','0') or 0))
            except ValueError: order_no=0
            form_edit=request.form.get('edit_id') or edit_id
            if not title: flash('Game title দিন।','error')
            elif form_edit and str(form_edit).isdigit():
                try:
                    d.execute('UPDATE games SET title=?,slug=?,description=?,type=?,launch_url=?,active=?,display_order=? WHERE id=?',(title,slug or None,description,game_type,launch_url or None,active,order_no,int(form_edit))); d.commit(); flash('Game আপডেট হয়েছে।','ok'); return redirect(url_for('admin_games'))
                except Exception:
                    d.rollback(); flash('Game আপডেট করা যায়নি। Slugটি হয়তো আগে থেকেই ব্যবহৃত হয়েছে।','error')
            else:
                try:
                    d.execute('INSERT INTO games(title,slug,description,type,launch_url,active,display_order) VALUES(?,?,?,?,?,?,?)',(title,slug or None,description,game_type,launch_url or None,active,order_no)); d.commit(); flash('Game যোগ হয়েছে।','ok')
                except Exception as exc:
                    d.rollback(); flash('Game সংরক্ষণ করা যায়নি। Slugটি হয়তো আগে থেকেই ব্যবহৃত হয়েছে।','error')
        games_rows=d.fetchall('SELECT * FROM games ORDER BY display_order,title'); edit_game=d.fetchone('SELECT * FROM games WHERE id=?',(int(edit_id),)) if edit_id and str(edit_id).isdigit() else None
        return render_template('admin/games.html',games=games_rows,edit_game=edit_game)
    finally: d.close()


@app.route('/admin/games/<int:gid>/toggle',methods=['POST'])
@admin_required
def admin_game_toggle(gid):
    d=db()
    try: d.execute('UPDATE games SET active=NOT active WHERE id=?',(gid,)); d.commit(); flash('Game Active/Inactive করা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_games'))


@app.route('/admin/games/<int:gid>/delete',methods=['POST'])
@admin_required
def admin_game_delete(gid):
    d=db()
    try: d.execute('DELETE FROM games WHERE id=?',(gid,)); d.commit(); flash('Game মুছে ফেলা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_games'))


@app.route('/admin/images',methods=['GET','POST'])
@admin_required
def admin_images():
    d=db()
    try:
        if request.method=='POST':
            title=request.form.get('title','').strip(); slot=request.form.get('slot','gallery').strip(); alt_text=request.form.get('alt_text','').strip(); image_url=safe_external_url(request.form.get('image_url','')); file=request.files.get('image_file'); active=request.form.get('active')=='1'
            try:
                if file and file.filename: image_url=storage_upload(file)
                if not title or not image_url: raise RuntimeError('Title এবং Image URL/Upload দিতে হবে।')
                d.execute('INSERT INTO media_assets(title,slot,url,alt_text,active,created_at) VALUES(?,?,?,?,?,?)',(title,slot,image_url,alt_text,active,datetime.utcnow().isoformat()))
                if active:
                    if slot=='logo': d.execute('UPDATE site_settings SET logo_url=? WHERE id=(SELECT id FROM site_settings LIMIT 1)',(image_url,))
                    elif slot=='hero': d.execute('UPDATE site_settings SET hero_image_url=? WHERE id=(SELECT id FROM site_settings LIMIT 1)',(image_url,))
                    elif slot=='background': d.execute('UPDATE site_settings SET background_url=? WHERE id=(SELECT id FROM site_settings LIMIT 1)',(image_url,))
                d.commit(); flash('Image asset সংরক্ষণ হয়েছে।','ok')
            except Exception as exc: d.rollback(); flash(str(exc),'error')
        assets=d.fetchall('SELECT * FROM media_assets ORDER BY id DESC'); storage_ready=bool(os.environ.get('SUPABASE_URL') and os.environ.get('SUPABASE_SERVICE_ROLE_KEY'))
        return render_template('admin/images.html',assets=assets,storage_ready=storage_ready)
    finally: d.close()


@app.route('/admin/images/<int:mid>/delete',methods=['POST'])
@admin_required
def admin_image_delete(mid):
    d=db()
    try: d.execute('DELETE FROM media_assets WHERE id=?',(mid,)); d.commit(); flash('Image asset manager থেকে সরানো হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_images'))


@app.route('/admin/notices',methods=['GET','POST'])
@admin_required
def admin_notices():
    d=db()
    try:
        edit_id=request.args.get('edit')
        if request.method=='POST':
            title=request.form.get('title','').strip(); body=request.form.get('body','').strip(); audience=request.form.get('audience','public').strip(); published=request.form.get('published')=='1'
            if not title or not body: flash('Notice title ও body দিন।','error')
            elif edit_id and str(edit_id).isdigit(): d.execute('UPDATE notices SET title=?,body=?,audience=?,published=? WHERE id=?',(title,body,audience,published,int(edit_id))); d.commit(); flash('Notice আপডেট হয়েছে।','ok'); return redirect(url_for('admin_notices'))
            else: d.execute('INSERT INTO notices(title,body,audience,published) VALUES(?,?,?,?)',(title,body,audience,published)); d.commit(); flash('Notice যোগ হয়েছে।','ok')
        notices=d.fetchall('SELECT * FROM notices ORDER BY id DESC'); edit_notice=d.fetchone('SELECT * FROM notices WHERE id=?',(int(edit_id),)) if edit_id and str(edit_id).isdigit() else None
        return render_template('admin/notices.html',notices=notices,edit_notice=edit_notice)
    finally: d.close()


@app.route('/admin/notices/<int:nid>/toggle',methods=['POST'])
@admin_required
def admin_notice_toggle(nid):
    d=db()
    try: d.execute('UPDATE notices SET published=NOT published WHERE id=?',(nid,)); d.commit(); flash('Notice Publish/Unpublish করা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_notices'))


@app.route('/admin/notices/<int:nid>/delete',methods=['POST'])
@admin_required
def admin_notice_delete(nid):
    d=db()
    try: d.execute('DELETE FROM notices WHERE id=?',(nid,)); d.commit(); flash('Notice মুছে ফেলা হয়েছে।','ok')
    finally: d.close()
    return redirect(url_for('admin_notices'))


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    return redirect(url_for('home'))


@app.route('/api/health')
def health():
    return jsonify(
        status='ok',
        app='zara-sara',
        database='supabase-postgres' if USE_PG else 'sqlite-local',
        time=datetime.utcnow().isoformat(),
    )


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=True)
