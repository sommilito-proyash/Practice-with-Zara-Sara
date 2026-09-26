-- Practice with Zara-Sara v4.5 migration for existing Supabase/PostgreSQL
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS question_count INTEGER DEFAULT 0;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS max_question_count INTEGER DEFAULT 50;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS student_can_choose_count BOOLEAN DEFAULT FALSE;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS randomize_questions BOOLEAN DEFAULT TRUE;
CREATE TABLE IF NOT EXISTS quiz_attempt_questions(attempt_id BIGINT NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,display_order INTEGER NOT NULL,PRIMARY KEY(attempt_id,display_order));
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_attempt ON quiz_attempt_questions(attempt_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_question ON quiz_attempt_questions(question_id);
UPDATE quizzes SET max_question_count=50 WHERE max_question_count IS NULL OR max_question_count<=0;
UPDATE quizzes SET randomize_questions=TRUE WHERE randomize_questions IS NULL;
UPDATE quizzes SET student_can_choose_count=FALSE WHERE student_can_choose_count IS NULL;
