from django.db import migrations


def forward(apps, schema_editor):
    """Convert the old single required_plan (a minimum level) into the explicit
    set of plans whose level is >= that minimum."""
    LiveClass = apps.get_model("classroom", "LiveClass")
    Plan = apps.get_model("courses", "Plan")
    for lc in LiveClass.objects.exclude(required_plan__isnull=True):
        level = lc.required_plan.level
        ids = list(Plan.objects.filter(level__gte=level).values_list("id", flat=True))
        if ids:
            lc.allowed_plans.set(ids)


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0002_liveclass_allowed_plans_and_more"),
        ("courses", "0004_batchscheduleslot_allowed_plans_and_more"),
    ]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]