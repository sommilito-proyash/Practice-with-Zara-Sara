# Practice with Zara–Sara — v5.2 আপডেট ও ডিপ্লয় নির্দেশিকা

## এই ZIP-এ কী পরিবর্তন হয়েছে

- **শ্রেণি ১–৪:** হোম পেজ থেকে সরাসরি নিবন্ধন ছাড়াই প্রশ্ন অনুশীলন ও কুইজ দেওয়া যাবে। কোনো class-specific bank একেবারে খালি থাকলে প্রথম startup-এ প্রতি শ্রেণিতে ১৫টি প্রাথমিক প্রশ্ন ও একটি practice quiz যুক্ত হবে। আগে থেকে প্রশ্ন থাকলে সেই শ্রেণির ব্যাংক বদলানো হবে না।
- **শ্রেণি ৫–১২:** নিবন্ধনের পর Admin অনুমোদন না হওয়া পর্যন্ত শিক্ষার্থী লগইন করতে পারবে না। Dashboard-এ Pending Approval গণনা এবং Student Management-এ Approve/Reject ব্যবস্থা রয়েছে।
- **আগের অ্যাকাউন্ট:** Migration-এ পুরোনো শিক্ষার্থীদের status `approved` ডিফল্ট হয়; database drop/reset করা যাবে না এবং করার প্রয়োজনও নেই।
- **Game Zone:** ১১টি built-in game; প্রতিটিতে ১–৫০ লেভেল এবং উচ্চ লেভেলে ধীরে ধীরে কঠিন চ্যালেঞ্জ।
- **Question Bank:** প্রতি শ্রেণিতে সর্বোচ্চ ১০,০০০ প্রশ্ন; মোট ১২ শ্রেণিতে ১,২০,০০০। এটি ধারণক্ষমতা, প্রতিটি শ্রেণিতে স্বয়ংক্রিয়ভাবে ১০,০০০ প্রশ্ন তৈরি হবে না। Admin Question Bank বা Excel/CSV import দিয়ে ব্যাংক পূরণ করতে হবে।

## নিরাপদ ডিপ্লয়

1. আগে GitHub repository এবং Supabase/PostgreSQL database-এর backup নিন।
2. ZIP extract করে project source-কে আপনার GitHub repository-তে আপডেট করুন; `zara_sara.db` বা Supabase database মুছবেন/রিসেট করবেন না।
3. Commit ও push করুন, তারপর Render-এ **Deploy latest commit** চালান।
4. App চালু হলে incremental schema migration নিজে চলবে। পুরোনো শিক্ষার্থীদের status `approved` থাকবে; নতুন registration `pending` হবে।
5. Admin panel → **Student Management** → `Pending` filter দিয়ে আবেদন যাচাই করে **Approve** চাপুন।
6. Live সাইটে পরীক্ষা করুন: (ক) Class 1–4-এ login ছাড়াই practice, (খ) Class 5–12 registration pending ও login blocked, (গ) Admin approval-এর পরে login, (ঘ) Game Zone-এর বিভিন্ন level, (ঙ) Question Bank import.

## গুরুত্বপূর্ণ

এই ZIP-এর কোড সরাসরি আপনার লাইভ হোস্টে পরিবর্তন করে না। GitHub/Render-এ ডিপ্লয় করার পরেই লাইভ সাইটে পরিবর্তনগুলো আসবে। ডিপ্লয়ের আগে backup রাখা জরুরি।
