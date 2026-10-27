# সার্ভারে আপলোডের নির্দেশনা (Zara-Sara + Earth Explorer)

## ১) VPS / যেকোনো Linux সার্ভার
    unzip Zara-Sara-Merged-Deploy.zip -d zara && cd zara
    python3 -m venv venv && . venv/bin/activate
    pip install -r requirements.txt
    export SECRET_KEY="লম্বা-র‍্যান্ডম-স্ট্রিং"
    gunicorn app:app --bind 0.0.0.0:8000 --workers 2
(Nginx দিয়ে ৮০০০ পোর্টে proxy করুন।) ডাটাবেস প্রথম রানে নিজে তৈরি হয় (SQLite)।

## ২) Render / Railway / Heroku
ZIP খুলে GitHub-এ পুশ করে কানেক্ট করুন। `Procfile` ও `render.yaml` দেওয়া আছে।
Environment: SECRET_KEY (বাধ্যতামূলক), SESSION_COOKIE_SECURE=1।
স্থায়ী ডাটার জন্য DATABASE_URL (Supabase/PostgreSQL) দিন — কারণ এসব হোস্টে SQLite মুছে যেতে পারে।

## ৩) cPanel
Setup Python App → Application root = এই ফোল্ডার, startup file = passenger_wsgi.py, entry = application।
requirements.txt ইনস্টল করুন।

## পাতাসমূহ
/ হোম · /explore ৩D পৃথিবী · /games · /login · /register · /admin/login
ডিফল্ট Admin: ইউজারনেম `admin`, পাসওয়ার্ড `admin123` — প্রথম লগইনের পরই বদলান।

## v5.2 আপডেট নোট
- `app.py`-এ incremental schema migration থাকায় বিদ্যমান Supabase database drop/recreate করতে হবে না।
- আগের শিক্ষার্থীরা Approved থাকবে; নতুন self-registration Pending হবে এবং Admin → Student Management থেকে Approve করতে হবে।
- Class 1–4 Home Page থেকে সরাসরি ব্যবহার করা যাবে; Class 5–12-এর জন্য অনুমোদিত Student login প্রয়োজন।
- Question Bank capacity প্রতি Class 10,000 (Classes 1–12 মিলিয়ে 120,000); এটি ধারণক্ষমতার সীমা, স্বয়ংক্রিয়ভাবে ১০,০০০ প্রশ্ন পূরণ নয়।
- Class 1–4-এর নির্দিষ্ট question bank একেবারে খালি থাকলে প্রথম startup-এ ১৫টি করে starter question ও practice quiz তৈরি হবে। আগে থেকেই প্রশ্ন থাকলে সেগুলো স্পর্শ করা হবে না।
- Game Zone-এর built-in গেমগুলোতে ৫০টি লেভেল আছে।
