
# Practice with Zara Sara — v4.5 Automatic Quiz + Answer Review

## v4.5 updates

### v4.5 automatic quiz + answer review
- Admin Quiz Management no longer requires manual question-by-question selection. Class/Subject/Chapter filters automatically build the Quiz Question Pool from all matching Active questions in the Question Bank.
- Default Question Count and Maximum Question Count control the number of questions per attempt; Student may choose within the Admin limit when enabled.
- Every attempt can receive a fresh randomized set, preferring questions the student has not previously seen in that Quiz; repeats are used only when the pool is exhausted.
- Quiz Result now includes a full answer-sheet review: correct questions/options are green, incorrectly selected options are red, and the correct answer is shown for mistakes.

- Question Bank: প্রতি Class-এ সর্বোচ্চ 1000টি প্রশ্ন; 5টি Class-এর জন্য মোট 5000 প্রশ্নের capacity.
- Quiz: Default Question Count, Maximum Question Count, Student choice এবং Random Question Set.
- Student attempt history অনুযায়ী আগে না-আসা প্রশ্ন অগ্রাধিকার পায়; প্রয়োজন হলে পুরোনো প্রশ্ন আবার আসে।
- Quiz attempt-এর প্রশ্ন snapshot `quiz_attempt_questions` table-এ সংরক্ষিত হয়।
- Existing v4.x data-এর জন্য auto schema upgrade রাখা হয়েছে; Supabase-এর জন্য `database/migration_v4.5_quiz_random_count.sql` দেওয়া আছে।


Flask + PostgreSQL/Supabase educational quiz platform for Classes 6–10.

## What changed in v4.3 (Bulk Import base)

- Added Admin **Bulk Question Import** from Excel `.xlsx` and CSV.
- Added official `bulk_question_import_template.xlsx` with `Questions` and `Instructions` sheets.
- Added validation + preview before database import.
- Supports Class, Subject and Chapter creation/reuse during import.
- Supports duplicate-question detection/reuse.
- Supports optional Quiz creation/linking from the same spreadsheet using `Quiz Title`.
- Quiz total marks are recalculated automatically after import.
- Existing manual Question Bank and Quiz Management remain available.
- Games remain catalogue/launch based for future game-package integration.


## What changed in v4.2

### Student accounts
- Student self-registration at `/register`.
- Student ID is generated automatically in the form `ZS-YYYY-XXXXXX`.
- Registration stores Class, phone, optional email, password and a 6-digit Recovery PIN.
- Forgot Student ID using name + phone + Recovery PIN.
- Forgot Password using Student ID + phone + Recovery PIN.
- Student can change their own password.
- Admin can edit student information and reset a student's password.

### Practice Class
- Registered Class remains the student's original class.
- Student can select any active Class 6–10 as `Practice Class`.
- Dashboard, chapters and published quizzes follow the selected Practice Class.
- Existing students are automatically assigned their current Registered Class as the initial Practice Class.

### Question Bank / Curriculum
- Questions are now explicitly linked to Class + Subject + Chapter.
- Admin can create a new Chapter while adding a question.
- Chapter selector loads dynamically after Class/Subject selection.
- Curriculum / Chapters has CRUD, ordering, Active/Inactive and safe-delete protection.
- Existing chapter name query mismatch was corrected to use `chapters.title`.

### Quiz Management
- Quiz can be assigned to Class + Subject + Chapter.
- Question selection is filtered to match the selected scope.
- Existing general/mixed quizzes remain supported when Class/Subject/Chapter is left blank.
- Publish/Unpublish, Edit and Delete remain available.

### Badges / Leaderboard
- XP-based starter badges are created automatically on a fresh app initialization.
- Admin can add, edit, activate/deactivate and delete badges.
- Admin can view a Top-20 Student XP leaderboard.
- Completing quizzes continues to update XP, level and streak; eligible badges are awarded automatically.

### Games
- `/games` is now a public game catalogue.
- Admin can create/edit/delete games, set type, launch URL, ordering and Active/Inactive.
- External launch URLs accept only `http://` and `https://`.

### Images / Storage
- Admin can save external image URLs or upload images to Supabase Storage.
- Supported image types: JPG, JPEG, PNG, GIF, WEBP.
- Server-side upload limit: 5 MB per image.
- Asset slots: Gallery, Hero, Logo, Background.
- Active Hero/Logo/Background assets automatically update the matching Home Page setting.
- Removing an asset from the manager removes its database record; it does not delete a remote Storage object.

### Notice Board
- Admin can manage Public, Students-only and All-audience notices.
- Public Home shows public/all notices.
- Student Dashboard shows students/all notices.

### Existing working features preserved
- Student login and Admin login.
- Question explanations, difficulty and marks.
- Timed quizzes and server-side elapsed-time check.
- Quiz attempt history and XP progression.
- Supabase/PostgreSQL support plus local SQLite support.
- Existing prepared 150-question seed and 35 starter quizzes.

## Local test workflow

1. Activate the same Python virtual environment that already works on your computer.
2. Copy `.env.example` to `.env` if needed.
3. For local SQLite testing, leave `DATABASE_URL=` empty.
4. Run:

   `python app.py`

5. Open:

   `http://127.0.0.1:5000`

6. Seed the prepared Question Bank and starter Quizzes:

   `python database/seed_question_bank.py`

The seed script is now safe to run as the first database command on a fresh local database: it initializes the prerequisite schema before seeding when the `questions` table does not exist.

The seed is idempotent for the prepared Question Bank and starter Quiz titles, so running it again does not intentionally duplicate the same prepared content.

## Supabase / PostgreSQL workflow

1. Set `DATABASE_URL` to the connection string for the Zara Sara Supabase project.
2. Run `python app.py` once so the application creates or incrementally upgrades the required schema.
3. Run `python database/seed_question_bank.py` to load the prepared Question Bank and starter quizzes.
4. For Images / Storage uploads, set:

   `SUPABASE_URL=`

   `SUPABASE_SERVICE_ROLE_KEY=`

   `SUPABASE_STORAGE_BUCKET=zara-sara-media`

5. Run `database/supabase_storage_setup.sql` once in Supabase SQL Editor.

The service-role key must remain server-side only.

## First login

On a fresh database the default Admin is:

`admin / admin123`

Change the Admin password immediately after first login.

## Important deployment note

This build is designed as a non-destructive incremental upgrade. Do not drop or recreate an existing Supabase database just to install this v4.5 upgrade. Run the application against the existing database so its upgrade checks can add missing columns/indexes.

For production, run Flask behind a proper WSGI server such as Gunicorn rather than using Flask's built-in development server.

## v4.3 Bulk Question Import

Admin → Question Bank → **Bulk Import** থেকে `.xlsx` বা `.csv` ফাইল আপলোড করুন। ZIP-এর `bulk_question_import_template.xlsx` হলো official template।

Required columns: `Class, Subject, Chapter, Question, Option A, Option B, Option C, Option D, Correct Answer`.

Optional columns: `Quiz Title, Quiz Description, Quiz Published, Time Limit, Explanation, Difficulty, Marks`.

একটি row = একটি MCQ। `Quiz Title` দিলে import-এর সময় সংশ্লিষ্ট Class/Subject/Chapter-এর Quiz তৈরি/পুনঃব্যবহার করে প্রশ্নগুলো যুক্ত করা হবে এবং total marks স্বয়ংক্রিয়ভাবে হিসাব হবে। Duplicate question হলে নতুন duplicate তৈরি না করে existing question reuse করা হবে। Import-এর আগে validation ও preview দেখানো হয়।

Excel import-এর জন্য `openpyxl` dependency যোগ করা হয়েছে।
