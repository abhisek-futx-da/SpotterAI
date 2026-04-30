# Generated manually for the take-home project.
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("city", models.CharField(blank=True, max_length=128)),
                ("state", models.CharField(blank=True, db_index=True, max_length=32)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("retail_price", models.DecimalField(decimal_places=8, max_digits=12)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["state", "city", "name"],
            },
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(fields=["latitude", "longitude"], name="route_plann_latitud_4f068b_idx"),
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(fields=["retail_price"], name="route_plann_retail__6625fa_idx"),
        ),
    ]
