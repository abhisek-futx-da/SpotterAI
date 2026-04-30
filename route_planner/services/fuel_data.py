from __future__ import annotations

from dataclasses import dataclass

from route_planner.models import FuelStation

from .geometry import cumulative_route_miles, nearest_route_position, route_bounds, simplify_route_points


@dataclass(frozen=True)
class StationCandidate:
    id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lon: float
    price: float
    mile_marker: float
    distance_from_route_miles: float

    def as_stop_dict(self, gallons: float, leg_miles: float, cost: float) -> dict:
        return {
            "station_id": self.id,
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "price_per_gallon": round(self.price, 3),
            "route_mile": round(self.mile_marker, 2),
            "distance_from_route_miles": round(self.distance_from_route_miles, 2),
            "gallons": round(gallons, 2),
            "leg_miles": round(leg_miles, 2),
            "cost_usd": round(cost, 2),
        }


class FuelStationRepository:
    def stations_along_route(
        self,
        route_points: list[tuple[float, float]],
        corridor_miles: float,
    ) -> list[StationCandidate]:
        matching_points = simplify_route_points(route_points)
        cumulative = cumulative_route_miles(matching_points)
        min_lat, max_lat, min_lon, max_lon = route_bounds(matching_points, corridor_miles)

        stations = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=min_lat,
            latitude__lte=max_lat,
            longitude__gte=min_lon,
            longitude__lte=max_lon,
        ).only(
            "id",
            "name",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "retail_price",
        )

        candidates: list[StationCandidate] = []
        for station in stations.iterator(chunk_size=1000):
            lat = float(station.latitude)
            lon = float(station.longitude)
            mile_marker, distance = nearest_route_position((lat, lon), matching_points, cumulative)
            if distance <= corridor_miles:
                candidates.append(
                    StationCandidate(
                        id=station.id,
                        name=station.name,
                        address=station.address,
                        city=station.city,
                        state=station.state,
                        lat=lat,
                        lon=lon,
                        price=float(station.retail_price),
                        mile_marker=mile_marker,
                        distance_from_route_miles=distance,
                    )
                )

        return sorted(candidates, key=lambda item: (item.mile_marker, item.price))
