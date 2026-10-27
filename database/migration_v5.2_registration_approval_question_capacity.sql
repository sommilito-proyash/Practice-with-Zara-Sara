-- v5.2: Registration approval + indexes. Existing students remain approved.
ALTER TABLE students ADD COLUMN IF NOT EXISTS registration_status TEXT NOT NULL DEFAULT 'approved';
UPDATE students SET registration_status='approved' WHERE registration_status IS NULL OR registration_status='';
CREATE INDEX IF NOT EXISTS idx_students_registration_status ON students(registration_status);
CREATE INDEX IF NOT EXISTS idx_questions_class_capacity ON questions(class_id);
