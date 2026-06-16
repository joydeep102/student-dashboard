from django.db import migrations


def forward(apps, schema_editor):
    """Convert each weekly slot's old required_plan (minimum level) into the
    explicit set of plans whose level is >= that minimum."""
    Slot = apps.get_model("courses", "BatchScheduleSlot")
    Plan = apps.get_model("courses", "Plan")
    for s in Slot.objects.exclude(required_plan__isnull=True):
        level = s.required_plan.level
        ids = list(Plan.objects.filter(level__gte=level).values_list("id", flat=True))
        if ids:
            s.allowed_plans.set(ids)


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0004_batchscheduleslot_allowed_plans_and_more"),
    ]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]