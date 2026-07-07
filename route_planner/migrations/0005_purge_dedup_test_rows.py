"""Purge the two duplicate UT->CO verification rows created while testing the
dedup guard on production (the in-memory version failed across gunicorn
workers; the guard is now DB-backed)."""
from django.db import migrations


def purge(apps, schema_editor):
    LaneRate = apps.get_model("route_planner", "LaneRate")
    deleted, _ = LaneRate.objects.filter(
        origin_state="UT", dest_state="CO", equipment_type="dry_van",
        rate_per_mile=2.44, origin_city="", dest_city="",
    ).delete()
    if deleted:
        print(f"  purged {deleted} dedup-test rows")


class Migration(migrations.Migration):
    dependencies = [("route_planner", "0004_purge_test_junk_rates")]
    operations = [migrations.RunPython(purge, migrations.RunPython.noop)]
