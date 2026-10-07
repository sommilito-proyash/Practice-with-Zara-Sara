CREATE TABLE IF NOT EXISTS site_settings(id BIGSERIAL PRIMARY KEY,site_name TEXT,tagline TEXT,purpose TEXT,about TEXT,hero_title TEXT,hero_subtitle TEXT,logo_url TEXT,hero_image_url TEXT,background_url TEXT,facebook_url TEXT);
CREATE TABLE IF NOT EXISTS classes(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,display_order INTEGER DEFAULT 0,active BOOLEAN DEFAULT TRUE,stage TEXT);
CREATE TABLE IF NOT EXISTS subjects(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,icon TEXT DEFAULT '📘',display_order INTEGER DEFAULT 0,active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS chapters(id BIGSERIAL PRIMARY KEY,subject_id BIGINT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,class_id BIGINT REFERENCES classes(id),title TEXT NOT NULL,description TEXT,display_order INTEGER DEFAULT 0,active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS questions(id BIGSERIAL PRIMARY KEY,subject_id BIGINT REFERENCES subjects(id),chapter_id BIGINT REFERENCES chapters(id),class_id BIGINT REFERENCES classes(id),question_text TEXT NOT NULL,question_type TEXT DEFAULT 'mcq',explanation TEXT,difficulty TEXT DEFAULT 'medium',marks INTEGER DEFAULT 1,active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS question_options(id BIGSERIAL PRIMARY KEY,question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,option_text TEXT NOT NULL,is_correct BOOLEAN DEFAULT FALSE,display_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS students(id BIGSERIAL PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,display_name TEXT,class_id BIGINT REFERENCES classes(id),practice_class_id BIGINT REFERENCES classes(id),email TEXT,phone TEXT,recovery_pin_hash TEXT,avatar_url TEXT,xp INTEGER DEFAULT 0,level INTEGER DEFAULT 1,streak INTEGER DEFAULT 0,last_active TEXT,active BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW(),updated_at TIMESTAMPTZ DEFAULT NOW(),active_device_token TEXT,active_session_token TEXT,active_device_seen_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS quizzes(id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,description TEXT,class_id BIGINT REFERENCES classes(id),subject_id BIGINT REFERENCES subjects(id),chapter_id BIGINT REFERENCES chapters(id),time_limit INTEGER DEFAULT 0,total_marks INTEGER DEFAULT 0,published BOOLEAN DEFAULT FALSE,question_count INTEGER DEFAULT 0,max_question_count INTEGER DEFAULT 50,student_can_choose_count BOOLEAN DEFAULT FALSE,randomize_questions BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS quiz_questions(quiz_id BIGINT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,display_order INTEGER DEFAULT 0,PRIMARY KEY(quiz_id,question_id));
CREATE TABLE IF NOT EXISTS quiz_attempts(id BIGSERIAL PRIMARY KEY,student_id BIGINT NOT NULL REFERENCES students(id),quiz_id BIGINT NOT NULL REFERENCES quizzes(id),score INTEGER,total INTEGER,xp_earned INTEGER DEFAULT 0,started_at TIMESTAMPTZ,completed_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS badges(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,icon TEXT,description TEXT,xp_threshold INTEGER DEFAULT 0,active BOOLEAN DEFAULT TRUE,display_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS student_badges(student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,badge_id BIGINT NOT NULL REFERENCES badges(id) ON DELETE CASCADE,earned_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(student_id,badge_id));
CREATE TABLE IF NOT EXISTS notices(id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,audience TEXT DEFAULT 'public',published BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS games(id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,slug TEXT UNIQUE,description TEXT,type TEXT,launch_url TEXT,active BOOLEAN DEFAULT TRUE,display_order INTEGER DEFAULT 0,config JSONB DEFAULT '{}'::jsonb);
CREATE TABLE IF NOT EXISTS admin_users(id BIGSERIAL PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,active BOOLEAN DEFAULT TRUE);


CREATE TABLE IF NOT EXISTS media_assets(id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,slot TEXT DEFAULT 'gallery',url TEXT NOT NULL,alt_text TEXT,active BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_media_assets_slot_active ON media_assets(slot,active);

CREATE TABLE IF NOT EXISTS quiz_attempt_questions(attempt_id BIGINT NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,display_order INTEGER NOT NULL,PRIMARY KEY(attempt_id,display_order));
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_attempt ON quiz_attempt_questions(attempt_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_questions_question ON quiz_attempt_questions(question_id);

CREATE TABLE IF NOT EXISTS bulk_import_batches(id BIGSERIAL PRIMARY KEY,token TEXT UNIQUE NOT NULL,filename TEXT NOT NULL,row_count INTEGER NOT NULL,payload JSONB NOT NULL,created_at DOUBLE PRECISION NOT NULL,expires_at DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS idx_bulk_import_batches_expires ON bulk_import_batches(expires_at);

