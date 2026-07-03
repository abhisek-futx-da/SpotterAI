from django.db import models


class FuelStation(models.Model):
    source_id = models.CharField(max_length=128, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=32, blank=True, db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=8)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["latitude", "longitude"],
                name="route_plann_latitud_4f068b_idx",
            ),
            models.Index(fields=["retail_price"], name="route_plann_retail__6625fa_idx"),
        ]
        ordering = ["state", "city", "name"]

    def __str__(self) -> str:
        location = ", ".join(part for part in [self.city, self.state] if part)
        return f"{self.name} ({location})" if location else self.name


class LaneRate(models.Model):
    """Anonymous broker-logged rate for a lane. This is the real-lane-rate flywheel:
    every broker who logs what they actually paid makes the network's rate picture
    on that lane more accurate for everyone — the one thing free government data can't
    provide. No PII, no user identity: just origin/dest, equipment, rate, timestamp."""

    EQUIPMENT_CHOICES = [
        ("dry_van", "Dry Van"),
        ("reefer", "Reefer"),
        ("flatbed", "Flatbed"),
    ]

    origin_city = models.CharField(max_length=128, blank=True)
    origin_state = models.CharField(max_length=2, db_index=True)
    dest_city = models.CharField(max_length=128, blank=True)
    dest_state = models.CharField(max_length=2, db_index=True)
    equipment_type = models.CharField(max_length=16, choices=EQUIPMENT_CHOICES, db_index=True)
    rate_per_mile = models.DecimalField(max_digits=6, decimal_places=2)
    distance_miles = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["origin_state", "dest_state", "equipment_type"],
                name="lane_rate_lane_idx",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.origin_state}->{self.dest_state} {self.equipment_type} ${self.rate_per_mile}/mi"
