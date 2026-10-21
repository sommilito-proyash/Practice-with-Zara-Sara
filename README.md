# Practice with Zara Sara — v5.0

## মূল আপডেট
- Class 1–12 support, stage label সহ।
- Student Registration ও Practice Class Class 1–12।
- প্রতি Class 1000 প্রশ্ন capacity; configured total 12000।
- 5টি starter built-in Educational Game: দ্রুত গণিত, সংখ্যা রহস্য, স্মৃতি মিল, শব্দ সাজাও, দ্রুত সাধারণ জ্ঞান।
- Future external game যোগের জন্য Admin → Games workflow রাখা হয়েছে।
- Home, Student Dashboard ও Game Zone-এ games access।
- Bulk Import Preview data database-এ store হয়; Render/local temporary filesystem-এর উপর Confirm নির্ভর করে না। Preview 60 মিনিট valid।
- Bulk Import Class 1–12, Bengali digits, Grade/Class labels ও extra header aliases নেয়।
- 25 MB upload limit এবং সর্বোচ্চ 12000 data rows per batch।
- Excel template-এ Questions, Examples, Instructions sheet; freeze panes, filters এবং dropdown validation।
- Import পুরো transaction-এর মধ্যে হয়; error হলে rollback।

## Existing features
Student self-registration, recovery, Practice Class, Question Bank, automatic Quiz pool/randomization, answer review, XP/Level/Streak/Badge, Notice, Image/Storage এবং Supabase/PostgreSQL + SQLite support অক্ষুণ্ণ আছে।

## Test
Python 3.13 ব্যবহার করে `python app.py` চালান। Local SQLite-এর জন্য `DATABASE_URL=` খালি রাখুন। `python database/seed_question_bank.py` prepared content load করবে; included starter questions বর্তমানে Classes 6–10-এর; Class 1–12 catalog ও bulk import সম্পূর্ণভাবে প্রস্তুত।

## Supabase
Existing database drop/recreate করার দরকার নেই। App run করলে incremental schema upgrade হবে।
