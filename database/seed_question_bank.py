import json
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA_FILE = ROOT / 'database' / 'question_bank_seed.json'
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SQLITE_PATH = os.environ.get('SQLITE_PATH', str(ROOT / 'zara_sara.db'))
USE_PG = bool(DATABASE_URL)

class DB:
    def __init__(self):
        if USE_PG:
            if psycopg2 is None:
                raise RuntimeError('DATABASE_URL is set but psycopg2-binary is not installed.')
            self.pg = True
            self.c = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            self.cur = self.c.cursor()
        else:
            self.pg = False
            self.c = sqlite3.connect(SQLITE_PATH)
            self.c.row_factory = sqlite3.Row
            self.c.execute('PRAGMA foreign_keys=ON')
            self.cur = self.c.cursor()
    def execute(self, sql, params=()):
        if self.pg:
            sql = sql.replace('?', '%s')
        self.cur.execute(sql, params)
        return self.cur
    def fetchone(self, sql, params=()): return self.execute(sql, params).fetchone()
    def fetchall(self, sql, params=()): return self.execute(sql, params).fetchall()
    def commit(self): self.c.commit()
    def rollback(self): self.c.rollback()
    def close(self): self.cur.close(); self.c.close()
    def insert_id(self, sql, params=()):
        if self.pg:
            sql = sql.replace('?', '%s') + ' RETURNING id'
            self.cur.execute(sql, params)
            return self.cur.fetchone()['id']
        self.cur.execute(sql, params)
        return self.cur.lastrowid

BOOL_TRUE = 'TRUE' if USE_PG else '1'

def ensure_schema(d):
    if USE_PG:
        schema = (ROOT / 'database' / 'schema_postgres.sql').read_text(encoding='utf-8')
        for stmt in [x.strip() for x in schema.split(';') if x.strip()]:
            d.execute(stmt)
    else:
        d.c.executescript((ROOT / 'database' / 'schema_sqlite.sql').read_text(encoding='utf-8'))


def _column_exists(d, table, column):
    if USE_PG:
        return bool(d.fetchone(
            '''SELECT 1 AS ok FROM information_schema.columns
               WHERE table_schema='public' AND table_name=? AND column_name=?''',
            (table, column),
        ))
    return any(r['name'] == column for r in d.fetchall(f'PRAGMA table_info({table})'))


def ensure_prerequisites(d):
    # Make this script safe even when it is the first database command run locally.
    if USE_PG:
        row = d.fetchone("SELECT to_regclass('public.questions') AS t")
        if not row or not row['t']:
            ensure_schema(d)
    else:
        tables = {r[0] for r in d.c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if 'questions' not in tables:
            ensure_schema(d)

    if USE_PG:
        d.execute('ALTER TABLE classes ADD COLUMN IF NOT EXISTS stage TEXT')
        d.execute('ALTER TABLE chapters ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE questions ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS practice_class_id BIGINT REFERENCES classes(id)')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS phone TEXT')
        d.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS recovery_pin_hash TEXT')
        d.execute('ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS chapter_id BIGINT REFERENCES chapters(id)')
        d.execute('CREATE INDEX IF NOT EXISTS idx_questions_class_subject ON questions(class_id,subject_id)')
        d.execute('CREATE INDEX IF NOT EXISTS idx_chapters_class_subject ON chapters(class_id,subject_id)')
    else:
        for table, column, definition in [
            ('classes','stage','TEXT'), ('questions','class_id','INTEGER'), ('chapters','class_id','INTEGER'),
            ('students','practice_class_id','INTEGER'), ('students','email','TEXT'),
            ('students','phone','TEXT'), ('students','recovery_pin_hash','TEXT'),
            ('quizzes','chapter_id','INTEGER'), ('badges','active','INTEGER DEFAULT 1'),
            ('badges','display_order','INTEGER DEFAULT 0'), ('games','launch_url','TEXT'),
            ('games','display_order','INTEGER DEFAULT 0'),
        ]:
            if not _column_exists(d, table, column):
                d.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        d.execute('CREATE INDEX IF NOT EXISTS idx_questions_class_subject ON questions(class_id,subject_id)')
        d.execute('CREATE INDEX IF NOT EXISTS idx_chapters_class_subject ON chapters(class_id,subject_id)')

    def stage(n):
        if n <= 5: return 'প্রাথমিক'
        if n <= 8: return 'নিম্ন মাধ্যমিক'
        if n <= 10: return 'মাধ্যমিক'
        return 'উচ্চ মাধ্যমিক'
    for i in range(1,13):
        row=d.fetchone('SELECT id,stage FROM classes WHERE name=? LIMIT 1',(f'শ্রেণি {i}',))
        if not row: d.execute('INSERT INTO classes(name,display_order,stage) VALUES(?,?,?)',(f'শ্রেণি {i}',i,stage(i)))
        elif not row['stage']: d.execute('UPDATE classes SET stage=? WHERE id=?',(stage(i),row['id']))
    subjects = [
        ('বাংলা','📚',1),('ইংরেজি','🔤',2),('গণিত','➗',3),
        ('বিজ্ঞান','🔬',4),('বাংলাদেশ ও বিশ্বপরিচয়','🌍',5),('সাধারণ জ্ঞান','🧠',6)
    ]
    for name, icon, order_no in subjects:
        if not d.fetchone('SELECT id FROM subjects WHERE name=? LIMIT 1', (name,)):
            d.execute('INSERT INTO subjects(name,icon,display_order) VALUES(?,?,?)', (name,icon,order_no))


def main():
    data = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    d = DB()
    try:
        ensure_prerequisites(d)
        question_ids = {}
        for item in data:
            cls = d.fetchone('SELECT id FROM classes WHERE name=? LIMIT 1', (f"শ্রেণি {item['class']}",))
            sub = d.fetchone('SELECT id FROM subjects WHERE name=? LIMIT 1', (item['subject'],))
            if not cls or not sub:
                raise RuntimeError(f"Class/Subject missing: {item['class']} / {item['subject']}")
            class_id, subject_id = cls['id'], sub['id']
            ch = d.fetchone('SELECT id FROM chapters WHERE class_id=? AND subject_id=? AND title=? LIMIT 1', (class_id,subject_id,item['chapter']))
            chapter_id = ch['id'] if ch else d.insert_id('INSERT INTO chapters(subject_id,class_id,title) VALUES(?,?,?)',(subject_id,class_id,item['chapter']))
            q = d.fetchone('SELECT id FROM questions WHERE class_id=? AND subject_id=? AND question_text=? LIMIT 1',(class_id,subject_id,item['question']))
            if q:
                qid=q['id']
            else:
                qid=d.insert_id('''INSERT INTO questions(subject_id,chapter_id,class_id,question_text,question_type,explanation,difficulty,marks) VALUES(?,?,?,?,?,?,?,?)''',
                    (subject_id,chapter_id,class_id,item['question'],'mcq',item.get('explanation',''),item.get('difficulty','medium'),int(item.get('marks',1))))
                for i,opt in enumerate(item['options']):
                    d.execute('INSERT INTO question_options(question_id,option_text,is_correct,display_order) VALUES(?,?,?,?)',(qid,opt,i==int(item['answer']),i))
            question_ids[(item['class'],item['subject'],item['question'])]=qid

        subjects=['বাংলা','ইংরেজি','গণিত','বিজ্ঞান','বাংলাদেশ ও বিশ্বপরিচয়','সাধারণ জ্ঞান']
        for class_no in range(1,13):
            cid=d.fetchone('SELECT id FROM classes WHERE name=? LIMIT 1',(f'শ্রেণি {class_no}',))['id']
            for subject in subjects:
                sid=d.fetchone('SELECT id FROM subjects WHERE name=? LIMIT 1',(subject,))['id']
                title=f'শ্রেণি {class_no} • {subject} • অনুশীলনী কুইজ ১'
                if d.fetchone('SELECT id FROM quizzes WHERE title=? AND class_id=? AND subject_id=? LIMIT 1',(title,cid,sid)):
                    continue
                selected=[qid for (c,s,_),qid in question_ids.items() if c==class_no and s==subject]
                if not selected:
                    selected=[r['id'] for r in d.fetchall(f'SELECT id FROM questions WHERE class_id=? AND subject_id=? AND active={BOOL_TRUE} ORDER BY id LIMIT 5',(cid,sid))]
                if not selected: continue
                ph=','.join(['?']*len(selected))
                total=sum(int(r['marks'] or 1) for r in d.fetchall(f'SELECT marks FROM questions WHERE id IN ({ph})',tuple(selected)))
                qzid=d.insert_id('''INSERT INTO quizzes(title,description,class_id,subject_id,time_limit,total_marks,published) VALUES(?,?,?,?,?,?,?)''',
                    (title,f'{subject} বিষয়ের class {class_no} অনুশীলনের জন্য প্রস্তুত Quiz।',cid,sid,10,total or len(selected),True))
                for order_no,qid in enumerate(selected,1): d.execute('INSERT INTO quiz_questions(quiz_id,question_id,display_order) VALUES(?,?,?)',(qzid,qid,order_no))

            mix_title=f'শ্রেণি {class_no} • Mixed Challenge • অনুশীলনী কুইজ'
            if not d.fetchone('SELECT id FROM quizzes WHERE title=? AND class_id=? LIMIT 1',(mix_title,cid)):
                mixed=[]
                for subject in subjects:
                    sid=d.fetchone('SELECT id FROM subjects WHERE name=? LIMIT 1',(subject,))['id']
                    rows=d.fetchall(f'SELECT id FROM questions WHERE class_id=? AND subject_id=? AND active={BOOL_TRUE} ORDER BY id LIMIT 2',(cid,sid))
                    mixed.extend(r['id'] for r in rows)
                if mixed:
                    ph=','.join(['?']*len(mixed))
                    total=sum(int(r['marks'] or 1) for r in d.fetchall(f'SELECT marks FROM questions WHERE id IN ({ph})',tuple(mixed)))
                    qzid=d.insert_id('''INSERT INTO quizzes(title,description,class_id,subject_id,time_limit,total_marks,published) VALUES(?,?,?,?,?,?,?)''',
                        (mix_title,f'শ্রেণি {class_no}-এর ৬টি বিষয়ের মিশ্র অনুশীলন।',cid,None,15,total or len(mixed),True))
                    for order_no,qid in enumerate(mixed,1): d.execute('INSERT INTO quiz_questions(quiz_id,question_id,display_order) VALUES(?,?,?)',(qzid,qid,order_no))
        d.commit()
        print(f'SEED COMPLETE: {len(data)} questions processed; 35 starter quizzes targeted.')
    except Exception:
        d.rollback(); raise
    finally:
        d.close()

if __name__=='__main__': main()
