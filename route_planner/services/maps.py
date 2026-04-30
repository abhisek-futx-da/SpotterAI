from __future__ import annotations

from .fuel_data import StationCandidate
from .geocoding import Location


def openstreetmap_directions_url(start: Location, finish: Location) -> str:
    return (
        "https://www.openstreetmap.org/directions?"
        f"engine=fossgis_osrm_car&route={start.lat}%2C{start.lon}%3B{finish.lat}%2C{finish.lon}"
    )


def route_geojson(
    route_points: list[tuple[float, float]],
    stops: list[StationCandidate],
    start: Location,
    finish: Location,
) -> dict:
    features = [
        {
            "type": "Feature",
            "properties": {"kind": "route"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in route_points],
            },
        },
        {
            "type": "Feature",
            "properties": {"kind": "start", "label": start.label},
            "geometry": {"type": "Point", "coordinates": [start.lon, start.lat]},
        },
        {
            "type": "Feature",
            "properties": {"kind": "finish", "label": finish.label},
            "geometry": {"type": "Point", "coordinates": [finish.lon, finish.lat]},
        },
    ]

    for stop in stops:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "fuel_stop",
                    "station_id": stop.id,
                    "name": stop.name,
                    "price_per_gallon": round(stop.price, 3),
                    "route_mile": round(stop.mile_marker, 2),
                },
                "geometry": {"type": "Point", "coordinates": [stop.lon, stop.lat]},
            }
        )

    return {"type": "FeatureCollection", "features": features}
