# Practice with Zara Sara — v5.2

## মূল আপডেট
- Class 1–12 support, stage label সহ।
- Student Registration ও Practice Class Class 1–12।
- প্রতি Class 10000 প্রশ্ন capacity; ১২টি Class মিলিয়ে configured total capacity 120000।
- ১১টি built-in Educational Game; প্রতিটি গেমে ৫০টি ক্রমবর্ধমান চ্যালেঞ্জ লেভেল।
- Future external game যোগের জন্য Admin → Games workflow রাখা হয়েছে।
- Home, Student Dashboard ও Game Zone-এ games access।
- Bulk Import Preview data database-এ store হয়; Render/local temporary filesystem-এর উপর Confirm নির্ভর করে না। Preview 60 মিনিট valid।
- Bulk Import Class 1–12, Bengali digits, Grade/Class labels ও extra header aliases নেয়।
- 25 MB upload limit এবং সর্বোচ্চ 120000 data rows per batch; বড় ফাইল ভাগ করে upload করলে বেশি স্থিতিশীল।
- Excel template-এ Questions, Examples, Instructions sheet; freeze panes, filters এবং dropdown validation।
- Import পুরো transaction-এর মধ্যে হয়; error হলে rollback।

## Existing features
Student self-registration, recovery, Practice Class, Question Bank, automatic Quiz pool/randomization, answer review, XP/Level/Streak/Badge, Notice, Image/Storage এবং Supabase/PostgreSQL + SQLite support অক্ষুণ্ণ আছে।

## Test
Python 3.13 ব্যবহার করে `python app.py` চালান। Local SQLite-এর জন্য `DATABASE_URL=` খালি রাখুন। `python database/seed_question_bank.py` prepared content load করবে; প্রথমবার চালানোর সময় Class 1–4-এর কোনো Class-specific question bank একেবারে খালি থাকলে ১৫টি starter question ও একটি practice quiz স্বয়ংক্রিয়ভাবে যোগ হবে। Classes 6–10-এর prepared bank-ও আলাদাভাবে আছে।

## Supabase
Existing database drop/recreate করার দরকার নেই। App run করলে incremental schema upgrade হবে।

## নতুন পরিবর্তন (v5.2)
- শ্রেণি ১–৪: Home Page থেকে নিবন্ধন ছাড়াই Practice ও কুইজ।
- শ্রেণি ৫–১২: Student self-registration-এর পর Admin approval না হওয়া পর্যন্ত login বন্ধ।
- পুরোনো Student account migration-এ স্বয়ংক্রিয়ভাবে Approved থাকবে।
- Admin Dashboard-এ Pending Approval counter এবং Student Management-এ Approve/Reject ব্যবস্থা।
- প্রতি শ্রেণিতে প্রশ্ন ব্যাংকের ধারণক্ষমতা ১০,০০০; ১২ শ্রেণিতে মোট ১,২০,০০০। মনে রাখুন: capacity মানে এই সংখ্যক প্রশ্ন রাখার সুযোগ, প্রতিটি শ্রেণিতে স্বয়ংক্রিয়ভাবে ১০,০০০ প্রশ্ন তৈরি হয় না।
- Game Zone-এ ১১টি built-in game; প্রতিটিতে Level 1–50, এবং উচ্চ লেভেলে কঠিনতা বৃদ্ধি।
