import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0011_payout_paid_at_payout_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add qa_enabled to the Lecture model
        migrations.AddField(
            model_name="lecture",
            name="qa_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Allow students to post questions and discussion under this lecture.",
            ),
        ),
        # Create LectureQuestion table
        migrations.CreateModel(
            name="LectureQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField(blank=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="qa_attachments/")),
                ("voice_message", models.FileField(blank=True, null=True, upload_to="qa_voices/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "lecture",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="questions",
                        to="courses.lecture",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lecture_questions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        # Create LectureReply table
        migrations.CreateModel(
            name="LectureReply",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField(blank=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="qa_attachments/")),
                ("voice_message", models.FileField(blank=True, null=True, upload_to="qa_voices/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "question",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replies",
                        to="courses.lecturequestion",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lecture_replies",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
