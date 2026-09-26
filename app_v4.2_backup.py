import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
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
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(__file__)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-in-production')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SQLITE_PATH = os.environ.get('SQLITE_PATH', os.path.join(BASE, 'zara_sara.db'))
USE_PG = bool(DATABASE_URL)
BOOL_TRUE = 'TRUE' if USE_PG else '1'


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
        _add_column_if_missing(d, 'badges', 'active', 'INTEGER DEFAULT 1')
        _add_column_if_missing(d, 'badges', 'display_order', 'INTEGER DEFAULT 0')
        _add_column_if_missing(d, 'games', 'launch_url', 'TEXT')
        _add_column_if_missing(d, 'games', 'display_order', 'INTEGER DEFAULT 0')
    d.execute('CREATE INDEX IF NOT EXISTS idx_questions_class_subject ON questions(class_id, subject_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_chapters_class_subject ON chapters(class_id, subject_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_quizzes_class_subject_chapter ON quizzes(class_id, subject_id, chapter_id)')
    d.execute('CREATE INDEX IF NOT EXISTS idx_students_practice_class ON students(practice_class_id)')


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
                       COUNT(qq.question_id) AS question_count
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


@app.route('/quiz/<int:qid>', methods=['GET', 'POST'])
@student_required
def quiz(qid):
    d = db()
    try:
        student_row = d.fetchone('SELECT * FROM students WHERE id=?', (session['student_id'],))
        qz = d.fetchone(
            f'''SELECT q.*, c.name class_name, sub.name subject_name, ch.title chapter_name
                FROM quizzes q
                LEFT JOIN classes c ON c.id=q.class_id
                LEFT JOIN subjects sub ON sub.id=q.subject_id
                LEFT JOIN chapters ch ON ch.id=q.chapter_id
                WHERE q.id=? AND q.published={BOOL_TRUE}''',
            (qid,),
        )
        if not qz or not student_row:
            return redirect(url_for('student'))
        practice_class_id = student_row['practice_class_id'] or student_row['class_id']
        if qz['class_id'] is not None and qz['class_id'] != practice_class_id:
            flash('এই Quizটি বর্তমানে নির্বাচিত Practice Class-এর জন্য নয়।', 'error')
            return redirect(url_for('student'))

        qs = d.fetchall(
            f'''SELECT q.*
                FROM questions q
                JOIN quiz_questions qq ON qq.question_id=q.id
                WHERE qq.quiz_id=? AND q.active={BOOL_TRUE}
                ORDER BY qq.display_order, q.id''',
            (qid,),
        )
        if not qs:
            flash('এই কুইজে এখনো কোনো প্রশ্ন নেই।', 'error')
            return redirect(url_for('student'))

        total_marks = int(qz['total_marks'] or 0) or sum(int(q['marks'] or 1) for q in qs)
        session_key = f'quiz_started_{qid}'
        attempt_key = f'quiz_attempt_{qid}'

        if request.method == 'POST':
            started_ts = float(session.get(session_key, time.time()))
            elapsed = time.time() - started_ts
            timed_out = bool(qz['time_limit'] and elapsed > (int(qz['time_limit']) * 60 + 15))

            score_marks = 0
            correct_count = 0
            for q in qs:
                correct = d.fetchone(
                    f'''SELECT option_text
                        FROM question_options
                        WHERE question_id=? AND is_correct={BOOL_TRUE}
                        ORDER BY display_order LIMIT 1''',
                    (q['id'],),
                )
                if correct and request.form.get(f'q{q["id"]}') == correct['option_text']:
                    correct_count += 1
                    score_marks += int(q['marks'] or 1)

            xp = correct_count * 10
            started_at = datetime.utcfromtimestamp(started_ts).isoformat()
            completed_at = datetime.utcnow().isoformat()
            attempt_id = session.pop(attempt_key, None)
            if attempt_id:
                d.execute(
                    '''UPDATE quiz_attempts
                       SET score=?, total=?, xp_earned=?, started_at=?, completed_at=?
                       WHERE id=? AND student_id=? AND quiz_id=?''',
                    (score_marks, total_marks, xp, started_at, completed_at, attempt_id, session['student_id'], qid),
                )
            else:
                d.execute(
                    '''INSERT INTO quiz_attempts
                       (student_id,quiz_id,score,total,xp_earned,started_at,completed_at)
                       VALUES(?,?,?,?,?,?,?)''',
                    (session['student_id'], qid, score_marks, total_marks, xp, started_at, completed_at),
                )
            update_student_progress(d, session['student_id'], xp)
            d.commit()
            session.pop(session_key, None)
            return render_template(
                'quiz_result.html',
                score=score_marks,
                total=total_marks,
                correct=correct_count,
                question_total=len(qs),
                xp=xp,
                timed_out=timed_out,
                quiz=qz,
            )

        if not session.get(session_key):
            session[session_key] = time.time()
            attempt_id = d.insert_id(
                '''INSERT INTO quiz_attempts(student_id,quiz_id,started_at)
                   VALUES(?,?,?)''',
                (session['student_id'], qid, datetime.utcnow().isoformat()),
            )
            session[attempt_key] = attempt_id

        options = {
            q['id']: d.fetchall(
                'SELECT * FROM question_options WHERE question_id=? ORDER BY display_order',
                (q['id'],),
            )
            for q in qs
        }
        return render_template(
            'quiz.html',
            quiz=qz,
            questions=qs,
            options=options,
        )
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
                      COUNT(qq.question_id) AS question_count
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
            opts=[request.form.get(f'opt{i}','').strip() for i in range(4)]
            if not sid or not textq or not all(opts):
                flash('Subject, Chapter, Question এবং চারটি Option পূরণ করুন।','error')
            else:
                ans=int(request.form.get('correct',0)); cid=None
                if new_chapter:
                    ch=d.fetchone('SELECT id FROM chapters WHERE subject_id=? AND title=? AND (class_id=? OR class_id IS NULL) ORDER BY id LIMIT 1',(sid,new_chapter,class_id))
                    cid=ch['id'] if ch else d.insert_id('INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',(sid,class_id,new_chapter))
                elif chapter_id and str(chapter_id).isdigit():
                    ch=d.fetchone('SELECT id FROM chapters WHERE id=? AND subject_id=? AND (class_id=? OR class_id IS NULL)',(int(chapter_id),sid,class_id)); cid=ch['id'] if ch else None
                if not cid:
                    flash('সঠিক Chapter নির্বাচন বা নতুন Chapter-এর নাম দিন।','error')
                else:
                    qid=d.insert_id('''INSERT INTO questions(subject_id,chapter_id,class_id,question_text,question_type,explanation,difficulty,marks) VALUES(?,?,?,?,?,?,?,?)''',(sid,cid,class_id,textq,'mcq',explanation,difficulty,marks))
                    for i,o in enumerate(opts): d.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,o,i==ans,i))
                    d.commit(); flash('প্রশ্ন যোগ হয়েছে।','ok')
        class_id=request.args.get('class_id') or ''; subject_id=request.args.get('subject_id') or ''; chapter_id=request.args.get('chapter_id') or ''; difficulty=request.args.get('difficulty') or ''
        where=[]; params=[]
        if class_id: where.append('(q.class_id=? OR q.class_id IS NULL)'); params.append(class_id)
        if subject_id: where.append('q.subject_id=?'); params.append(subject_id)
        if chapter_id: where.append('q.chapter_id=?'); params.append(chapter_id)
        if difficulty: where.append('q.difficulty=?'); params.append(difficulty)
        where_sql=('WHERE '+' AND '.join(where)) if where else ''
        subjects=d.fetchall(f'SELECT * FROM subjects WHERE active={BOOL_TRUE} ORDER BY display_order,name'); classes=d.fetchall('SELECT * FROM classes ORDER BY display_order')
        questions=d.fetchall(f'''SELECT q.*,s.name subject_name,c.title chapter_name,cl.name class_name FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters c ON c.id=q.chapter_id LEFT JOIN classes cl ON cl.id=q.class_id {where_sql} ORDER BY q.id DESC LIMIT 250''',tuple(params))
        chapters=[]
        if subject_id and subject_id.isdigit():
            if class_id and class_id.isdigit(): chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? AND (class_id=? OR class_id IS NULL) ORDER BY display_order,title',(int(subject_id),int(class_id)))
            else: chapters=d.fetchall(f'SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? ORDER BY class_id,display_order,title',(int(subject_id),))
        return render_template('admin/questions.html',subjects=subjects,classes=classes,chapters=chapters,questions=questions,selected_class=class_id,selected_subject=subject_id,selected_chapter=chapter_id,selected_difficulty=difficulty)
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
            selected=[int(x) for x in request.form.getlist('question_ids') if str(x).isdigit()]; published=request.form.get('published')=='1'
            if not title: flash('Quiz Title দিন।','error')
            elif not selected: flash('কমপক্ষে ১টি প্রশ্ন নির্বাচন করুন।','error')
            else:
                ph=','.join(['?']*len(selected)); rows=d.fetchall(f'SELECT id,marks,class_id,subject_id,chapter_id FROM questions WHERE id IN ({ph}) AND active={BOOL_TRUE}',tuple(selected)); valid={int(r['id']):r for r in rows}; selected=[qid for qid in selected if qid in valid]
                if class_id: selected=[qid for qid in selected if valid[qid]['class_id'] in (None,int(class_id))]
                if subject_id: selected=[qid for qid in selected if valid[qid]['subject_id'] in (None,int(subject_id))]
                if chapter_id: selected=[qid for qid in selected if valid[qid]['chapter_id'] in (None,int(chapter_id))]
                if not selected: flash('নির্বাচিত প্রশ্নগুলো Quiz-এর Class/Subject/Chapter-এর সঙ্গে মিলছে না।','error')
                else:
                    total_marks=requested_total_marks or sum(int(valid[qid]['marks'] or 1) for qid in selected)
                    if edit_id and str(edit_id).isdigit():
                        quiz_id=int(edit_id); d.execute('''UPDATE quizzes SET title=?,description=?,class_id=?,subject_id=?,chapter_id=?,time_limit=?,total_marks=?,published=? WHERE id=?''',(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published,quiz_id)); d.execute('DELETE FROM quiz_questions WHERE quiz_id=?',(quiz_id,)); flash('Quiz আপডেট হয়েছে।','ok')
                    else:
                        quiz_id=d.insert_id('''INSERT INTO quizzes(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published) VALUES(?,?,?,?,?,?,?,?)''',(title,description,class_id,subject_id,chapter_id,time_limit,total_marks,published)); flash('নতুন Quiz তৈরি হয়েছে।','ok')
                    for order_no,question_id in enumerate(selected,1): d.execute('INSERT INTO quiz_questions(quiz_id,question_id,display_order) VALUES(?,?,?)',(quiz_id,question_id,order_no))
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
        questions=d.fetchall((f'''SELECT q.*,s.name subject_name,c.title chapter_name,cl.name class_name FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters c ON c.id=q.chapter_id LEFT JOIN classes cl ON cl.id=q.class_id WHERE {' AND '.join(q_where)} ORDER BY q.class_id NULLS FIRST,q.subject_id,q.chapter_id,q.id''' if USE_PG else f'''SELECT q.*,s.name subject_name,c.title chapter_name,cl.name class_name FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters c ON c.id=q.chapter_id LEFT JOIN classes cl ON cl.id=q.class_id WHERE {' AND '.join(q_where)} ORDER BY CASE WHEN q.class_id IS NULL THEN 0 ELSE 1 END,q.subject_id,q.chapter_id,q.id'''),tuple(q_params))
        if filter_subject:
            chapters=d.fetchall(f'''SELECT * FROM chapters WHERE active={BOOL_TRUE} AND subject_id=? {'AND (class_id=? OR class_id IS NULL)' if filter_class else ''} ORDER BY display_order,title''',(filter_subject,filter_class) if filter_class else (filter_subject,))
        else: chapters=[]
        quizzes=d.fetchall('''SELECT q.*,c.name class_name,s.name subject_name,ch.title chapter_name,COUNT(qq.question_id) AS question_count FROM quizzes q LEFT JOIN classes c ON c.id=q.class_id LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN chapters ch ON ch.id=q.chapter_id LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id GROUP BY q.id,c.name,s.name,ch.title ORDER BY q.id DESC''')
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
