import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(
        "SELECT COUNT(*) FROM django_migrations WHERE app=%s AND name=%s",
        ['courses', '0012_qa_and_lecture_qa_enabled']
    )
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())",
            ['courses', '0012_qa_and_lecture_qa_enabled']
        )
        print("Migration record inserted successfully.")
    else:
        print("Migration record already exists.")

# Now add the qa_enabled column if it doesn't exist
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='courses_lecture' AND column_name='qa_enabled'"
    )
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE courses_lecture ADD COLUMN qa_enabled boolean NOT NULL DEFAULT true"
        )
        print("qa_enabled column added to courses_lecture.")
    else:
        print("qa_enabled column already exists.")
