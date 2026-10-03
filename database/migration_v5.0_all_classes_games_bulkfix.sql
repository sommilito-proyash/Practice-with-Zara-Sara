-- v5.0 incremental migration for existing Supabase/PostgreSQL database
ALTER TABLE classes ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id);
ALTER TABLE questions ADD COLUMN IF NOT EXISTS class_id BIGINT REFERENCES classes(id);
ALTER TABLE students ADD COLUMN IF NOT EXISTS practice_class_id BIGINT REFERENCES classes(id);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS chapter_id BIGINT REFERENCES chapters(id);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS question_count INTEGER DEFAULT 0;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS max_question_count INTEGER DEFAULT 50;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS student_can_choose_count BOOLEAN DEFAULT FALSE;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS randomize_questions BOOLEAN DEFAULT TRUE;
ALTER TABLE games ADD COLUMN IF NOT EXISTS launch_url TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS bulk_import_batches(
  id BIGSERIAL PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  payload JSONB NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  expires_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bulk_import_batches_expires ON bulk_import_batches(expires_at);
CREATE INDEX IF NOT EXISTS idx_classes_order ON classes(display_order,active);
CREATE INDEX IF NOT EXISTS idx_questions_class_subject ON questions(class_id,subject_id);
CREATE INDEX IF NOT EXISTS idx_chapters_class_subject ON chapters(class_id,subject_id);

INSERT INTO classes(name,display_order,active,stage)
SELECT v.name,v.ord,TRUE,v.stage
FROM (VALUES
  ('শ্রেণি 1',1,'প্রাথমিক'),('শ্রেণি 2',2,'প্রাথমিক'),('শ্রেণি 3',3,'প্রাথমিক'),('শ্রেণি 4',4,'প্রাথমিক'),('শ্রেণি 5',5,'প্রাথমিক'),
  ('শ্রেণি 6',6,'নিম্ন মাধ্যমিক'),('শ্রেণি 7',7,'নিম্ন মাধ্যমিক'),('শ্রেণি 8',8,'নিম্ন মাধ্যমিক'),
  ('শ্রেণি 9',9,'মাধ্যমিক'),('শ্রেণি 10',10,'মাধ্যমিক'),('শ্রেণি 11',11,'উচ্চ মাধ্যমিক'),('শ্রেণি 12',12,'উচ্চ মাধ্যমিক')
) AS v(name,ord,stage)
WHERE NOT EXISTS (SELECT 1 FROM classes c WHERE lower(c.name)=lower(v.name));

UPDATE classes c SET stage=CASE
  WHEN c.name='শ্রেণি 1' OR c.name='শ্রেণি 2' OR c.name='শ্রেণি 3' OR c.name='শ্রেণি 4' OR c.name='শ্রেণি 5' THEN 'প্রাথমিক'
  WHEN c.name='শ্রেণি 6' OR c.name='শ্রেণি 7' OR c.name='শ্রেণি 8' THEN 'নিম্ন মাধ্যমিক'
  WHEN c.name='শ্রেণি 9' OR c.name='শ্রেণি 10' THEN 'মাধ্যমিক'
  WHEN c.name='শ্রেণি 11' OR c.name='শ্রেণি 12' THEN 'উচ্চ মাধ্যমিক'
  ELSE c.stage END
WHERE c.stage IS NULL;

INSERT INTO games(title,slug,description,type,launch_url,active,display_order,config)
VALUES
('দ্রুত গণিত','quick-math','সময় ধরে দ্রুত অঙ্ক সমাধান করো।','builtin',NULL,TRUE,1,'{"icon":"➗","kind":"quick_math"}'::jsonb),
('সংখ্যা রহস্য','number-pattern','ধারার পরের সংখ্যা বের করো—সহজ থেকে কঠিন।','builtin',NULL,TRUE,2,'{"icon":"🔢","kind":"number_pattern"}'::jsonb),
('স্মৃতি মিল','memory-match','মনোযোগ ও স্মৃতিশক্তির মজার অনুশীলন।','builtin',NULL,TRUE,3,'{"icon":"🧠","kind":"memory_match"}'::jsonb),
('শব্দ সাজাও','word-scramble','ইংরেজি শব্দের অক্ষর ঠিকভাবে সাজাও।','builtin',NULL,TRUE,4,'{"icon":"🔤","kind":"word_scramble"}'::jsonb),
('দ্রুত সাধারণ জ্ঞান','quick-gk','স্কুল শিক্ষার্থীদের জন্য দ্রুত GK challenge।','builtin',NULL,TRUE,5,'{"icon":"🌍","kind":"quick_gk"}'::jsonb)
ON CONFLICT (slug) DO NOTHING;
