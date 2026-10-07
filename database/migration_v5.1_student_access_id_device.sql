-- v5.1: Student ID Card/QR, one-device session control, class +/- 1 access
-- Safe to run on an existing Supabase/PostgreSQL database.
-- IMPORTANT: columns are added before the related index is created.
ALTER TABLE students ADD COLUMN IF NOT EXISTS active_device_token TEXT;
ALTER TABLE students ADD COLUMN IF NOT EXISTS active_session_token TEXT;
ALTER TABLE students ADD COLUMN IF NOT EXISTS active_device_seen_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_students_active_device ON students(active_device_token);
