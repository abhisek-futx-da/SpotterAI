from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("route_planner", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fuelstation",
            name="retail_price",
            field=models.DecimalField(decimal_places=8, max_digits=12),
        ),
    ]
