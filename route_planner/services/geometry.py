from __future__ import annotations

import math


EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))


def cumulative_route_miles(points: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    for index in range(1, len(points)):
        cumulative.append(cumulative[-1] + haversine_miles(points[index - 1], points[index]))
    return cumulative


def simplify_route_points(
    points: list[tuple[float, float]],
    min_spacing_miles: float = 5.0,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points

    simplified = [points[0]]
    miles_since_kept = 0.0
    previous = points[0]
    for point in points[1:-1]:
        miles_since_kept += haversine_miles(previous, point)
        previous = point
        if miles_since_kept >= min_spacing_miles:
            simplified.append(point)
            miles_since_kept = 0.0

    if simplified[-1] != points[-1]:
        simplified.append(points[-1])
    return simplified


def route_bounds(
    points: list[tuple[float, float]],
    buffer_miles: float,
) -> tuple[float, float, float, float]:
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    lat_buffer = buffer_miles / 69.0
    avg_lat = sum(lats) / len(lats)
    lon_buffer = buffer_miles / max(1.0, 69.0 * math.cos(math.radians(avg_lat)))
    return (
        min(lats) - lat_buffer,
        max(lats) + lat_buffer,
        min(lons) - lon_buffer,
        max(lons) + lon_buffer,
    )


def nearest_route_position(
    point: tuple[float, float],
    route_points: list[tuple[float, float]],
    cumulative_miles: list[float],
) -> tuple[float, float]:
    """Return (mile marker, distance from route) for a point.

    Uses a local equirectangular projection per segment. That is accurate enough
    for station-to-route corridor checks and much cheaper than geodesic segment
    projection across every row.
    """
    point_lat, point_lon = point
    origin_lat_radians = math.radians(point_lat)

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        return (
            math.radians(lon) * math.cos(origin_lat_radians) * EARTH_RADIUS_MILES,
            math.radians(lat) * EARTH_RADIUS_MILES,
        )

    px, py = to_xy(point_lat, point_lon)
    best_distance = float("inf")
    best_marker = 0.0

    for index in range(len(route_points) - 1):
        ax, ay = to_xy(*route_points[index])
        bx, by = to_xy(*route_points[index + 1])
        dx = bx - ax
        dy = by - ay
        segment_length_squared = dx * dx + dy * dy
        if segment_length_squared == 0:
            projection = 0.0
        else:
            projection = ((px - ax) * dx + (py - ay) * dy) / segment_length_squared
            projection = max(0.0, min(1.0, projection))

        nearest_x = ax + projection * dx
        nearest_y = ay + projection * dy
        distance = math.hypot(px - nearest_x, py - nearest_y)
        if distance < best_distance:
            segment_miles = cumulative_miles[index + 1] - cumulative_miles[index]
            best_distance = distance
            best_marker = cumulative_miles[index] + projection * segment_miles

    return best_marker, best_distance
