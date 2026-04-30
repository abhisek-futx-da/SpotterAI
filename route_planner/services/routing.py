from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from .exceptions import ExternalServiceError, RouteNotFoundError
from .geocoding import Location


METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Route:
    points: list[tuple[float, float]]
    distance_miles: float
    duration_seconds: float

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60


class RouteClient:
    def __init__(self) -> None:
        config = settings.ROUTE_PLANNER
        self.base_url = config["OSRM_BASE_URL"].rstrip("/")
        self.timeout = config["REQUEST_TIMEOUT_SECONDS"]

    def get_route(self, start: Location, finish: Location) -> Route:
        coordinates = f"{start.lon},{start.lat};{finish.lon},{finish.lat}"
        params = urlencode(
            {
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "false",
            }
        )
        url = f"{self.base_url}/route/v1/driving/{coordinates}?{params}"
        request = Request(url, headers={"User-Agent": "route-fuel-optimizer/1.0"})

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceError("Could not retrieve a route from OSRM.") from exc

        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RouteNotFoundError("No drivable route was found between the two locations.")

        route_payload = payload["routes"][0]
        coordinates = route_payload.get("geometry", {}).get("coordinates") or []
        points = [(float(lat), float(lon)) for lon, lat in coordinates]
        if len(points) < 2:
            raise RouteNotFoundError("The routing service returned an empty route geometry.")

        return Route(
            points=points,
            distance_miles=float(route_payload["distance"]) / METERS_PER_MILE,
            duration_seconds=float(route_payload["duration"]),
        )
