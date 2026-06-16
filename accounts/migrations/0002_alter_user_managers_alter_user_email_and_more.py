# Switch the login identifier from username to email.

import accounts.models
from django.db import migrations, models


def backfill_emails(apps, schema_editor):
    """Give every existing user a unique, non-empty email before email becomes
    the unique login field. Users without one get <username>@example.com."""
    User = apps.get_model("accounts", "User")
    assigned = set()
    for u in User.objects.all().order_by("id"):
        cand = (u.email or "").strip().lower()
        if not cand or cand in assigned:
            local = (u.username or "user%d" % u.pk).strip().lower() or "user%d" % u.pk
            cand = "%s@example.com" % local
            n = 2
            while cand in assigned:
                cand = "%s%d@example.com" % (local, n)
                n += 1
        changed = False
        if u.email != cand:
            u.email = cand
            changed = True
        if not u.username:
            u.username = cand
            changed = True
        if changed:
            u.save(update_fields=["email", "username"])
        assigned.add(cand)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="user",
            managers=[
                ("objects", accounts.models.UserManager()),
            ],
        ),
        # Backfill must run BEFORE the unique constraint is enforced.
        migrations.RunPython(backfill_emails, noop),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254, unique=True, verbose_name="email address"),
        ),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
