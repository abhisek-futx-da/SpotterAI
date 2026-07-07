from __future__ import annotations

from typing import Any

from django.conf import settings

from .exceptions import ValidationError
from .fuel_data import FuelStationRepository
from .geocoding import NominatimGeocoder, is_coordinate_payload
from .maps import openstreetmap_directions_url, route_geojson
from .optimizer import FuelOptimizer
from .routing import RouteClient


class RoutePlanService:
    def __init__(self) -> None:
        self.geocoder = NominatimGeocoder()
        self.route_client = RouteClient()
        self.station_repository = FuelStationRepository()

    def plan(self, payload: dict[str, Any]) -> dict:
        start_payload = payload.get("start")
        finish_payload = payload.get("finish")
        if start_payload is None or finish_payload is None:
            raise ValidationError("Both 'start' and 'finish' are required.")

        config = settings.ROUTE_PLANNER
        try:
            max_range_miles = float(payload.get("max_range_miles", config["MAX_RANGE_MILES"]))
            mpg = float(payload.get("mpg", config["MPG"]))
            corridor_miles = float(payload.get("corridor_miles", config["CORRIDOR_MILES"]))
            starting_range_miles = float(
                payload.get("starting_range_miles", config["STARTING_RANGE_MILES"])
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "max_range_miles, mpg, corridor_miles, and starting_range_miles must be numeric."
            ) from exc

        if corridor_miles <= 0:
            raise ValidationError("corridor_miles must be greater than zero.")
        # Server-side bound — the UI caps at 100; the API must too, or one request
        # can pull the entire station dataset into the corridor search.
        if corridor_miles > 100:
            corridor_miles = 100.0
        if max_range_miles <= 0 or mpg <= 0:
            raise ValidationError("max_range_miles and mpg must be greater than zero.")
        # A tank cannot currently hold more range than its capacity.
        if starting_range_miles > max_range_miles:
            raise ValidationError(
                f"starting_range_miles ({starting_range_miles:g}) cannot exceed "
                f"max_range_miles ({max_range_miles:g}) — the tank can't hold more than its capacity."
            )
        if starting_range_miles < 0:
            raise ValidationError("starting_range_miles cannot be negative.")

        start = self.geocoder.resolve(start_payload)
        finish = self.geocoder.resolve(finish_payload)
        route = self.route_client.get_route(start, finish)
        # Same-point "routes" are not a trip.
        if route.distance_miles < 1.0:
            raise ValidationError(
                "Origin and destination are the same place (route under 1 mile). "
                "Enter two different locations."
            )
        candidates = self.station_repository.stations_along_route(route.points, corridor_miles)
        fuel_plan = FuelOptimizer(
            max_range_miles=max_range_miles,
            mpg=mpg,
            starting_range_miles=starting_range_miles,
        ).optimize(route.distance_miles, candidates)

        selected_stations = [stop.station for stop in fuel_plan.stops]
        return {
            "start": start.as_dict(),
            "finish": finish.as_dict(),
            "route": {
                "distance_miles": round(route.distance_miles, 2),
                "duration_minutes": round(route.duration_minutes, 2),
                "geometry_points": len(route.points),
            },
            "fuel_plan": {
                "max_range_miles": round(max_range_miles, 2),
                "mpg": round(mpg, 2),
                "starting_range_miles": round(min(starting_range_miles, max_range_miles), 2),
                "candidate_station_count": len(candidates),
                "total_cost_usd": round(fuel_plan.total_cost, 2),
                "total_gallons_purchased": round(fuel_plan.total_gallons_purchased, 2),
                "stops": [
                    stop.station.as_stop_dict(
                        gallons=stop.gallons,
                        leg_miles=stop.leg_miles,
                        cost=stop.cost,
                    )
                    for stop in fuel_plan.stops
                ],
            },
            "map": {
                "geojson": route_geojson(route.points, selected_stations, start, finish),
                "openstreetmap_url": openstreetmap_directions_url(start, finish),
                "attribution": "Route data from OSRM/OpenStreetMap contributors.",
            },
            "meta": {
                "external_calls": {
                    "geocoding": int(not is_coordinate_payload(start_payload))
                    + int(not is_coordinate_payload(finish_payload)),
                    "routing": 1,
                },
                "assumptions": [
                    "The vehicle starts with starting_range_miles of usable range.",
                    "Fuel stop selection minimizes total fuel spend using the loaded fuel prices.",
                    "Fuel purchases are sized to reach the next selected stop or destination.",
                    "Only stations within corridor_miles of the route are considered.",
                ],
            },
        }
