import os, json, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY','change-this-secret-in-production')
DB_PATH = os.environ.get('SQLITE_PATH', os.path.join(os.path.dirname(__file__),'zara_sara.db'))

SCHEMA = open(os.path.join(os.path.dirname(__file__),'database','schema.sql'),encoding='utf-8').read()

def db():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init_db():
    c=db(); c.executescript(SCHEMA); c.commit()
    if c.execute('SELECT COUNT(*) n FROM site_settings').fetchone()['n']==0:
        c.execute('INSERT INTO site_settings(site_name,tagline,purpose,about,hero_title,hero_subtitle) VALUES(?,?,?,?,?,?)',(
            'প্র্যাকটিস উইথ জারা-সারা','শিখি • অনুশীলন করি • এগিয়ে যাই',
            'ষষ্ঠ থেকে দশম শ্রেণির শিক্ষার্থীদের নিয়মিত অনুশীলন, আত্মমূল্যায়ন ও শেখার আগ্রহ বাড়াতে তৈরি একটি অনুশীলনভিত্তিক শিক্ষামূলক প্ল্যাটফর্ম।',
            'এখানে একাডেমিক বিষয়, ইংরেজি, সাধারণ জ্ঞান, কুইজ ও শিক্ষামূলক গেম এক জায়গায় পাওয়া যাবে।',
            'শেখা হোক আনন্দের, অনুশীলন হোক নিয়মিত!','জারা ও সারা তোমার শেখার সঙ্গী—প্রতিদিন একটু অনুশীলন, প্রতিদিন একটু এগিয়ে যাওয়া।'))
    if c.execute('SELECT COUNT(*) n FROM admin_users').fetchone()['n']==0:
        c.execute('INSERT INTO admin_users(username,password_hash) VALUES(?,?)',('admin',generate_password_hash('admin123')))
    if c.execute('SELECT COUNT(*) n FROM classes').fetchone()['n']==0:
        for i in range(6,11): c.execute('INSERT INTO classes(name,display_order) VALUES(?,?)',(f'শ্রেণি {i}',i-5))
        for s in [('বাংলা','📚'),('ইংরেজি','🔤'),('গণিত','➗'),('বিজ্ঞান','🔬'),('বাংলাদেশ ও বিশ্বপরিচয়','🌍'),('সাধারণ জ্ঞান','🧠')]:
            c.execute('INSERT INTO subjects(name,icon) VALUES(?,?)',s)
        # A small verified-style seed set from the prototype; all content is editable in Admin.
        samples=[
          ('বিজ্ঞান','অধ্যায় ১: মানবদেহ','মানবদেহের বৃহত্তম অঙ্গ কোনটি?','ত্বক|যকৃত|মস্তিষ্ক|ফুসফুস',0),
          ('বিজ্ঞান','অধ্যায় ১: মানবদেহ','রক্তে অক্সিজেন বহনকারী উপাদান কোনটি?','হিমোগ্লোবিন|প্লাজমা|শ্বেতকণিকা|অণুচক্রিকা',0),
          ('বিজ্ঞান','অধ্যায় ২: বিদ্যুৎ ও পদার্থ','বিদ্যুৎ প্রবাহের একক কী?','অ্যাম্পিয়ার|ভোল্ট|ওহম|ওয়াট',0),
          ('গণিত','অধ্যায় ১: মৌলিক গণিত','১২ × ৪ = কত?','৪৮|৪২|৫৬|৬৪',0),
          ('ইংরেজি','Grammar','Choose the correct plural of “child”.','childs|children|childes|childrens',1),
          ('সাধারণ জ্ঞান','বাংলাদেশ','বাংলাদেশের জাতীয় ফুল কোনটি?','শাপলা|গোলাপ|জবা|বেলি',0)
        ]
        for subj,chap,q,opts,ans in samples:
            sid=c.execute('SELECT id FROM subjects WHERE name=?',(subj,)).fetchone()['id']
            ch=c.execute('SELECT id FROM chapters WHERE subject_id=? AND title=?',(sid,chap)).fetchone()
            if not ch:
                c.execute('INSERT INTO chapters(subject_id,title) VALUES(?,?)',(sid,chap)); ch=c.execute('SELECT last_insert_rowid() id').fetchone()
            cid=ch['id']; c.execute('INSERT INTO questions(subject_id,chapter_id,question_text,question_type,explanation) VALUES(?,?,?,?,?)',(sid,cid,q,'mcq','প্রয়োজনে Admin থেকে ব্যাখ্যা যোগ বা পরিবর্তন করুন।'))
            qid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
            for i,o in enumerate(opts.split('|')): c.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,o,1 if i==ans else 0,i))
    c.commit(); c.close()

init_db()

def admin_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('admin_id'): return redirect(url_for('admin_login'))
        return f(*a,**kw)
    return w

def student_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('student_id'): return redirect(url_for('login'))
        return f(*a,**kw)
    return w

@app.route('/')
def home():
    c=db(); settings=c.execute('SELECT * FROM site_settings LIMIT 1').fetchone(); classes=c.execute('SELECT * FROM classes WHERE active=1 ORDER BY display_order').fetchall(); subjects=c.execute('SELECT * FROM subjects WHERE active=1 ORDER BY display_order').fetchall(); notices=c.execute("SELECT * FROM notices WHERE published=1 AND (audience='public' OR audience='all') ORDER BY id DESC LIMIT 5").fetchall(); c.close()
    return render_template('index.html',settings=settings,classes=classes,subjects=subjects,notices=notices)

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','')
        c=db(); s=c.execute('SELECT * FROM students WHERE username=? AND active=1',(u,)).fetchone(); c.close()
        if s and check_password_hash(s['password_hash'],p): session['student_id']=s['id']; return redirect(url_for('student'))
        flash('ইউজারনেম বা পাসওয়ার্ড সঠিক নয়।','error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/student')
@student_required
def student():
    c=db(); s=c.execute('SELECT s.*, c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(session['student_id'],)).fetchone(); badges=c.execute('SELECT b.* FROM badges b JOIN student_badges sb ON sb.badge_id=b.id WHERE sb.student_id=?',(s['id'],)).fetchall(); quizzes=c.execute('SELECT * FROM quizzes WHERE published=1 ORDER BY id DESC').fetchall(); c.close(); return render_template('student.html',student=s,badges=badges,quizzes=quizzes)

@app.route('/quiz/<int:qid>',methods=['GET','POST'])
@student_required
def quiz(qid):
    c=db(); qz=c.execute('SELECT * FROM quizzes WHERE id=? AND published=1',(qid,)).fetchone();
    if not qz: c.close(); return redirect(url_for('student'))
    qs=c.execute('''SELECT q.* FROM questions q JOIN quiz_questions qq ON qq.question_id=q.id WHERE qq.quiz_id=? ORDER BY qq.display_order''',(qid,)).fetchall()
    if request.method=='POST':
        score=0
        for q in qs:
            correct=c.execute('SELECT option_text FROM question_options WHERE question_id=? AND is_correct=1',(q['id'],)).fetchone()
            if correct and request.form.get(f'q{q["id"]}')==correct['option_text']: score+=1
        xp=score*10; c.execute('INSERT INTO quiz_attempts(student_id,quiz_id,score,total,xp_earned,completed_at) VALUES(?,?,?,?,?,?)',(session['student_id'],qid,score,len(qs),xp,datetime.utcnow().isoformat())); c.execute('UPDATE students SET xp=xp+?,last_active=? WHERE id=?',(xp,datetime.utcnow().date().isoformat(),session['student_id'])); c.commit(); c.close(); return render_template('quiz_result.html',score=score,total=len(qs),xp=xp)
    options={}
    for q in qs: options[q['id']]=c.execute('SELECT * FROM question_options WHERE question_id=? ORDER BY display_order',(q['id'],)).fetchall()
    c.close(); return render_template('quiz.html',quiz=qz,questions=qs,options=options)

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=request.form.get('username',''); p=request.form.get('password',''); c=db(); a=c.execute('SELECT * FROM admin_users WHERE username=? AND active=1',(u,)).fetchone(); c.close()
        if a and check_password_hash(a['password_hash'],p): session['admin_id']=a['id']; return redirect(url_for('admin'))
        flash('Admin তথ্য সঠিক নয়।','error')
    return render_template('admin/login.html')

@app.route('/admin')
@admin_required
def admin():
    c=db(); counts={t:c.execute(f'SELECT COUNT(*) n FROM {t}').fetchone()['n'] for t in ['students','questions','quizzes','notices']}; settings=c.execute('SELECT * FROM site_settings LIMIT 1').fetchone(); c.close(); return render_template('admin/dashboard.html',counts=counts,settings=settings)

@app.route('/admin/settings',methods=['GET','POST'])
@admin_required
def admin_settings():
    c=db(); s=c.execute('SELECT * FROM site_settings LIMIT 1').fetchone()
    if request.method=='POST':
        fields=['site_name','tagline','purpose','about','hero_title','hero_subtitle','facebook_url']
        vals=[request.form.get(x,'').strip() for x in fields]
        c.execute('UPDATE site_settings SET site_name=?,tagline=?,purpose=?,about=?,hero_title=?,hero_subtitle=?,facebook_url=? WHERE id=?',(*vals,s['id'])); c.commit(); flash('সাইটের তথ্য সংরক্ষিত হয়েছে।','ok'); s=c.execute('SELECT * FROM site_settings LIMIT 1').fetchone()
    c.close(); return render_template('admin/settings.html',settings=s)

@app.route('/admin/students',methods=['GET','POST'])
@admin_required
def admin_students():
    c=db();
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password',''); name=request.form.get('display_name','').strip(); cls=request.form.get('class_id') or None
        try: c.execute('INSERT INTO students(username,password_hash,display_name,class_id) VALUES(?,?,?,?)',(u,generate_password_hash(p),name,cls)); c.commit(); flash('শিক্ষার্থী যোগ হয়েছে।','ok')
        except sqlite3.IntegrityError: flash('এই username আগে থেকেই আছে।','error')
    students=c.execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id ORDER BY s.id DESC').fetchall(); classes=c.execute('SELECT * FROM classes ORDER BY display_order').fetchall(); c.close(); return render_template('admin/students.html',students=students,classes=classes)

@app.route('/admin/questions',methods=['GET','POST'])
@admin_required
def admin_questions():
    c=db();
    if request.method=='POST':
        sid=request.form.get('subject_id'); chap=request.form.get('chapter','').strip(); textq=request.form.get('question_text','').strip(); opts=[request.form.get(f'opt{i}','').strip() for i in range(4)]; ans=int(request.form.get('correct',0))
        ch=c.execute('SELECT id FROM chapters WHERE subject_id=? AND title=?',(sid,chap)).fetchone()
        if not ch: c.execute('INSERT INTO chapters(subject_id,title) VALUES(?,?)',(sid,chap)); ch=c.execute('SELECT last_insert_rowid() id').fetchone()
        c.execute('INSERT INTO questions(subject_id,chapter_id,question_text,question_type) VALUES(?,?,?,?)',(sid,ch['id'],textq,'mcq')); qid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
        for i,o in enumerate(opts): c.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,o,1 if i==ans else 0,i))
        c.commit(); flash('প্রশ্ন যোগ হয়েছে।','ok')
    subjects=c.execute('SELECT * FROM subjects WHERE active=1 ORDER BY name').fetchall(); questions=c.execute('SELECT q.*,s.name subject_name FROM questions q JOIN subjects s ON s.id=q.subject_id ORDER BY q.id DESC LIMIT 100').fetchall(); c.close(); return render_template('admin/questions.html',subjects=subjects,questions=questions)

@app.route('/admin/logout')
def admin_logout(): session.pop('admin_id',None); return redirect(url_for('home'))

@app.route('/api/health')
def health(): return jsonify(status='ok',app='zara-sara',time=datetime.utcnow().isoformat())

if __name__=='__main__': app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=True)
