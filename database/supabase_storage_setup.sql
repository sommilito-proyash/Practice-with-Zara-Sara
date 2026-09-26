-- Practice with Zara Sara — optional Supabase Storage setup
-- Run once in the Supabase SQL Editor for Admin > Images / Storage uploads.
-- The application uploads files server-side using SUPABASE_SERVICE_ROLE_KEY.
-- Keep that key server-side only; never put it in HTML/JavaScript.

INSERT INTO storage.buckets (id, name, public)
VALUES ('zara-sara-media', 'zara-sara-media', true)
ON CONFLICT (id) DO UPDATE SET public = EXCLUDED.public;
