"""Purge the fake lane rates a black-box tester injected into the live network
(cities "Spam"/"Testville"/"Faketown", 2026-07-07, IL→TX). Data migration so it
runs exactly once on deploy — including against the persistent volume DB.
"""
from django.db import migrations

JUNK_CITIES = ["spam", "testville", "faketown", "test", "junk", "fake"]


def purge_junk(apps, schema_editor):
    LaneRate = apps.get_model("route_planner", "LaneRate")
    qs = LaneRate.objects.none()
    for city in JUNK_CITIES:
        qs = qs | LaneRate.objects.filter(origin_city__iexact=city)
        qs = qs | LaneRate.objects.filter(dest_city__iexact=city)
    deleted, _ = qs.distinct().delete()
    if deleted:
        print(f"  purged {deleted} junk lane-rate rows")


class Migration(migrations.Migration):
    dependencies = [
        ("route_planner", "0003_lanerate"),
    ]
    operations = [
        migrations.RunPython(purge_junk, migrations.RunPython.noop),
    ]
