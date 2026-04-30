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
