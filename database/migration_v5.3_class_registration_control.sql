-- v5.3: Admin-controlled registration per class.
-- app.py applies this automatically at startup (one time). Run manually only if you prefer.
-- PostgreSQL / Supabase:
ALTER TABLE classes ADD COLUMN IF NOT EXISTS registration_required BOOLEAN NOT NULL DEFAULT TRUE;
-- ONE-TIME ONLY (keeps old behaviour: Classes 1-4 open). Running it again overwrites the admin's choices.
UPDATE classes SET registration_required=FALSE WHERE name IN ('শ্রেণি 1','শ্রেণি 2','শ্রেণি 3','শ্রেণি 4');
-- SQLite equivalent:
--   ALTER TABLE classes ADD COLUMN registration_required INTEGER NOT NULL DEFAULT 1;
--   UPDATE classes SET registration_required=0 WHERE name IN ('শ্রেণি 1','শ্রেণি 2','শ্রেণি 3','শ্রেণি 4');
