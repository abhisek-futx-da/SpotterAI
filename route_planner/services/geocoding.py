from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from .exceptions import ExternalServiceError, ValidationError


@dataclass(frozen=True)
class Location:
    label: str
    lat: float
    lon: float

    def as_dict(self) -> dict[str, float | str]:
        return {"label": self.label, "lat": round(self.lat, 6), "lon": round(self.lon, 6)}


def is_coordinate_payload(value: Any) -> bool:
    return isinstance(value, dict) and (
        {"lat", "lon"}.issubset(value.keys())
        or {"latitude", "longitude"}.issubset(value.keys())
    )


class NominatimGeocoder:
    def __init__(self) -> None:
        config = settings.ROUTE_PLANNER
        self.base_url = config["NOMINATIM_BASE_URL"].rstrip("/")
        self.user_agent = config["NOMINATIM_USER_AGENT"]
        self.email = config.get("NOMINATIM_EMAIL", "")
        self.timeout = config["REQUEST_TIMEOUT_SECONDS"]

    def resolve(self, value: Any) -> Location:
        if is_coordinate_payload(value):
            return self._from_coordinates(value)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Location must be a non-empty string or a lat/lon object.")

        query = value.strip()
        params_dict = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
            "countrycodes": "us",
        }
        if self.email:
            params_dict["email"] = self.email

        params = urlencode(params_dict)
        url = f"{self.base_url}/search?{params}"
        request = Request(url, headers={"User-Agent": self.user_agent})

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(f"Could not geocode location '{query}'.") from exc

        if not payload:
            raise ValidationError(f"Could not find a USA location for '{query}'.")

        result = payload[0]
        return Location(
            label=result.get("display_name", query),
            lat=float(result["lat"]),
            lon=float(result["lon"]),
        )

    def _from_coordinates(self, value: dict[str, Any]) -> Location:
        lat = value.get("lat", value.get("latitude"))
        lon = value.get("lon", value.get("longitude"))
        try:
            lat_float = float(lat)
            lon_float = float(lon)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Latitude and longitude must be numeric.") from exc

        if not (18 <= lat_float <= 72 and -170 <= lon_float <= -65):
            raise ValidationError("Coordinates must be within the United States.")

        label = str(value.get("label") or f"{lat_float:.6f},{lon_float:.6f}")
        return Location(label=label, lat=lat_float, lon=lon_float)
