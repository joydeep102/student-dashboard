"""Populate the portal with batch + plan demo data so you can click around.

    python manage.py seed_demo

Creates the 4 plans, an admin/instructor, students on different plans, a course
with Batch 01, and tiered live classes + recorded lessons. Re-runnable.
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.models import LiveClass
from courses.models import Batch, BatchEnrollment, BatchScheduleSlot, Course, Lesson, Plan

User = get_user_model()

PLANS = [
    {
        "name": "Basic", "level": 1, "duration_months": 3, "price": 3999, "accent": "green",
        "features": "Crypto Trading Basics\nTechnical Analysis\nChart Reading\nRisk Management\nLive Market Sessions",
    },
    {
        "name": "Advance", "level": 2, "duration_months": 4, "price": 4999, "accent": "green",
        "features": "Crypto + Forex Trading\nAdvanced Strategies\nMarket Psychology\nLive Trading Practice\nDaily Guidance",
    },
    {
        "name": "Pro Trader", "level": 3, "duration_months": 5, "price": 6999, "accent": "dark",
        "badge": "🔥 MOST POPULAR", "is_highlighted": True,
        "features": "Crypto + Forex + Indian Options\nAdvanced Technical Analysis\nSmart Money Concepts\nScalping & Swing Trading\nStrategy Building",
    },
    {
        "name": "Elite Mentorship", "level": 4, "duration_months": 6, "price": 9999, "accent": "gold",
        "badge": "👑 ELITE",
        "features": "All-in-One Course\n1-on-1 Personal Guidance\nFunding Account Support\nTrading Psychology\nPortfolio Management\nPremium Community",
    },
]


class Command(BaseCommand):
    help = "Create demo plans, a batch, tiered content and students."

    def handle(self, *args, **options):
        # --- Plans ---
        plans = {}
        for p in PLANS:
            obj, _ = Plan.objects.update_or_create(level=p["level"], defaults=p)
            plans[p["level"]] = obj
        self.stdout.write(self.style.SUCCESS("Plans ready: Basic, Advance, Pro Trader, Elite"))

        # --- Admin (logs in with EMAIL) ---
        admin, _ = User.objects.get_or_create(
            email="admin@example.com",
            defaults={"username": "admin", "role": User.Role.ADMIN, "is_staff": True,
                      "is_superuser": True, "first_name": "Portal", "last_name": "Admin"},
        )
        admin.set_password("admin12345")
        admin.save()
        self.stdout.write(self.style.SUCCESS("Admin: admin@example.com / admin12345"))

        instructor, _ = User.objects.get_or_create(
            email="instructor1@example.com",
            defaults={"username": "instructor1", "role": User.Role.INSTRUCTOR,
                      "first_name": "Anita", "last_name": "Rao", "is_staff": True},
        )
        instructor.set_password("trainer12345")
        instructor.save()
        self.stdout.write(self.style.SUCCESS(
            "Trainer: instructor1@example.com / trainer12345  (Trainer Studio at /trainer/)"))

        # --- Students on different plans (to demo tier gating) ---
        roster = [
            ("student1@example.com", "Rahul", "Sharma", 1),   # Basic
            ("student2@example.com", "Priya", "Das", 3),       # Pro Trader
            ("student3@example.com", "Imran", "Khan", 2),      # Advance
            ("student4@example.com", "Neha", "Gupta", 4),      # Elite
        ]

        # --- Course + Batch 01 ---
        course, _ = Course.objects.get_or_create(
            title="Fighter Bull's Trading Mastery",
            defaults={"summary": "Crypto, Forex & Indian Options — from basics to breakouts.",
                      "description": "Live mentorship and pro strategy classes, delivered batch by batch.",
                      "instructor": instructor},
        )
        batch, _ = Batch.objects.get_or_create(
            course=course, name="Batch 01",
            defaults={"start_date": timezone.now().date(), "description": "Our flagship cohort."},
        )

        for email, fn, ln, lvl in roster:
            s, _ = User.objects.get_or_create(
                email=email,
                defaults={"username": email.split("@")[0], "role": User.Role.STUDENT,
                          "first_name": fn, "last_name": ln})
            s.set_password("student12345")
            s.save()
            BatchEnrollment.objects.update_or_create(
                student=s, batch=batch, defaults={"plan": plans[lvl]})
        self.stdout.write(self.style.SUCCESS(
            "Students (pw: student12345): student1@example.com=Basic, student2@…=Pro, "
            "student3@…=Advance, student4@…=Elite"))

        # --- Recorded lessons (tiered by required plan) ---
        lessons = [
            ("Welcome & How Markets Work", "aqz-KE-bpKQ", 120, None),
            ("Reading Candlestick Charts", "kUMe1FH4CHE", 600, 1),     # Basic+
            ("Forex Pairs Explained", "tXIhdp5R7sc", 720, 2),          # Advance+
            ("Smart Money Concepts", "W6NZfCO5SIk", 900, 3),           # Pro+
            ("Portfolio Management Masterclass", "ScMzIvxBSi4", 800, 4),  # Elite only
        ]
        for i, (title, yid, dur, lvl) in enumerate(lessons, start=1):
            Lesson.objects.get_or_create(
                batch=batch, title=title,
                defaults={"youtube_id": yid, "order": i, "duration_seconds": dur,
                          "required_plan": plans[lvl] if lvl else None})

        # --- Live classes (tiered) ---
        now = timezone.now()
        classes = [
            ("Orientation & Crypto Basics", 5, 90, None, "https://meet.google.com/demo-orientation"),
            ("Forex Fundamentals (Live)", 60 * 24, 60, 2, ""),       # Advance+
            ("Indian Options & Smart Money", 60 * 24 * 2, 75, 3, ""),  # Pro+
            ("1-on-1 Strategy Review", 60 * 24 * 3, 45, 4, ""),       # Elite only
        ]
        for title, mins, dur, lvl, link in classes:
            LiveClass.objects.get_or_create(
                batch=batch, title=title,
                defaults={"start_time": now + timezone.timedelta(minutes=mins), "duration_minutes": dur,
                          "required_plan": plans[lvl] if lvl else None, "meet_link": link})

        # --- Weekly schedule (admin decides which weekdays the batch runs) ---
        for wd, hour in [(0, 19), (2, 19), (4, 19)]:  # Mon, Wed, Fri at 7:00 PM
            BatchScheduleSlot.objects.get_or_create(
                batch=batch, weekday=wd, start_time=datetime.time(hour, 0),
                defaults={"duration_minutes": 75})
        # Ensure there's also a class scheduled *today* so the trainer flow is testable now.
        today_wd = timezone.localdate().weekday()
        BatchScheduleSlot.objects.get_or_create(
            batch=batch, weekday=today_wd, start_time=datetime.time(20, 0),
            defaults={"duration_minutes": 60})
        self.stdout.write(self.style.SUCCESS("Batch 01 weekly schedule: Mon/Wed/Fri 7:00 PM (+ a class today)"))

        self.stdout.write(self.style.SUCCESS("Demo data ready. Log in at /accounts/login/  (Plans page at /pricing/)"))
