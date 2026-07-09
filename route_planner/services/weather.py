"""Real weather alerts along a route via the NWS (weather.gov) API.
No API key required. Queries NWS /alerts/active for a bounding box covering
the route, returns active alerts that overlap the corridor."""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class WeatherAlert:
    event: str
    severity: str          # Extreme / Severe / Moderate / Minor / Unknown
    urgency: str           # Immediate / Expected / Future / Past / Unknown
    headline: str
    area_desc: str
    onset: str
    expires: str
    certainty: str


class WeatherService:
    BASE_URL = "https://api.weather.gov"
    TIMEOUT = 6
    # Severity ranks for sorting (higher = worse)
    SEVERITY_RANK = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1, "Unknown": 0}

    # Approximate lat/lon bounds for each US state (for route-to-state mapping)
    STATE_BOUNDS = {
        "AL": (30.1, 35.0, -88.5, -84.9), "AK": (51.0, 71.5, -180.0, -129.0),
        "AZ": (31.3, 37.0, -114.8, -109.0), "AR": (33.0, 36.5, -94.6, -89.6),
        "CA": (32.5, 42.0, -124.5, -114.1), "CO": (36.9, 41.1, -109.1, -102.0),
        "CT": (40.9, 42.1, -73.7, -71.8), "DE": (38.4, 39.8, -75.8, -75.0),
        "FL": (24.5, 31.0, -87.6, -80.0), "GA": (30.4, 35.0, -85.6, -80.8),
        "HI": (18.9, 22.2, -160.2, -154.8), "ID": (42.0, 49.0, -117.2, -111.0),
        "IL": (36.9, 42.5, -91.5, -87.5), "IN": (37.8, 41.8, -88.1, -84.8),
        "IA": (40.4, 43.5, -96.6, -90.1), "KS": (36.9, 40.0, -102.1, -94.6),
        "KY": (36.5, 39.1, -89.6, -81.9), "LA": (28.9, 33.0, -94.1, -88.8),
        "ME": (43.1, 47.5, -71.1, -66.9), "MD": (37.9, 39.7, -79.5, -75.0),
        "MA": (41.2, 42.9, -73.5, -69.9), "MI": (41.7, 48.3, -90.4, -82.4),
        "MN": (43.5, 49.4, -97.2, -89.5), "MS": (30.2, 35.0, -91.7, -88.1),
        "MO": (36.0, 40.6, -95.8, -89.1), "MT": (44.4, 49.0, -116.0, -104.0),
        "NE": (40.0, 43.0, -104.1, -95.3), "NV": (35.0, 42.0, -120.0, -114.0),
        "NH": (42.7, 45.3, -72.6, -70.6), "NJ": (38.9, 41.4, -75.6, -73.9),
        "NM": (31.3, 37.0, -109.1, -103.0), "NY": (40.5, 45.0, -79.8, -71.9),
        "NC": (33.8, 36.6, -84.3, -75.5), "ND": (45.9, 49.0, -104.1, -96.6),
        "OH": (38.4, 42.3, -84.8, -80.5), "OK": (33.6, 37.0, -103.0, -94.4),
        "OR": (41.9, 46.3, -124.6, -116.5), "PA": (39.7, 42.3, -80.5, -74.7),
        "RI": (41.1, 42.0, -71.9, -71.1), "SC": (32.0, 35.2, -83.4, -78.5),
        "SD": (42.5, 45.9, -104.1, -96.4), "TN": (34.9, 36.7, -90.3, -81.6),
        "TX": (25.8, 36.5, -106.6, -93.5), "UT": (36.9, 42.0, -114.1, -109.0),
        "VT": (42.7, 45.0, -73.4, -71.5), "VA": (36.5, 39.5, -83.7, -75.2),
        "WA": (45.5, 49.0, -124.7, -116.9), "WV": (37.2, 40.6, -82.6, -77.7),
        "WI": (42.5, 47.1, -92.9, -86.2), "WY": (41.0, 45.0, -111.1, -104.1),
    }

    def _states_from_points(self, route_points: list[tuple[float, float]]) -> list[str]:
        """Map route lat/lon points to US state abbreviations."""
        matched = set()
        # Sample every Nth point to avoid checking hundreds
        step = max(1, len(route_points) // 20)
        sampled = route_points[::step]
        for lat, lon in sampled:
            for state, (min_lat, max_lat, min_lon, max_lon) in self.STATE_BOUNDS.items():
                if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                    matched.add(state)
        return sorted(matched)

    def alerts_along_route(
        self,
        route_points: list[tuple[float, float]],
        max_alerts: int = 10,
    ) -> dict:
        """Return active NWS weather alerts for US states the route passes through.

        Args:
            route_points: list of (lat, lon) tuples from the routing service
            max_alerts: cap on returned alerts to keep response size small
        """
        if not route_points:
            return self._empty("no route points provided")

        states = self._states_from_points(route_points)
        if not states:
            return self._empty("could not determine US states from route points")

        all_alerts = []
        for state in states:
            all_alerts.extend(self._alerts_for_state(state))

        alerts = []
        seen = set()
        for feature in all_alerts:
            props = feature.get("properties") or {}
            uid = props.get("id", "") or props.get("headline", "")
            if uid in seen:
                continue
            seen.add(uid)

            severity = props.get("severity", "Unknown")
            # Skip Minor marine/lake alerts (not relevant to trucking)
            event = props.get("event", "")
            if "Marine" in event or "Lake" in event or "Coastal" in event:
                continue

            alerts.append({
                "event": event,
                "severity": severity,
                "urgency": props.get("urgency", "Unknown"),
                "headline": (props.get("headline") or "")[:200],
                "area_desc": props.get("areaDesc", ""),
                "onset": props.get("onset") or props.get("effective", ""),
                "expires": props.get("expires", ""),
                "certainty": props.get("certainty", "Unknown"),
            })

        alerts.sort(key=lambda a: self.SEVERITY_RANK.get(a["severity"], 0), reverse=True)
        alerts = alerts[:max_alerts]

        highest = "None"
        if alerts:
            highest = max(alerts, key=lambda a: self.SEVERITY_RANK.get(a["severity"], 0))["severity"]

        return {
            "alerts": alerts,
            "alert_count": len(alerts),
            "highest_severity": highest,
            "delay_risk": self._delay_risk(highest, len(alerts)),
            "states_checked": states,
            "data_source": "real",
            "source": "NWS (weather.gov)",
        }

    # NWS alerts change on an hourly timescale — cache per state 20 min so a
    # 10-state route stops making 10 live calls on every rate-intel request.
    ALERTS_TTL = 1200

    def _alerts_for_state(self, state: str) -> list:
        from . import ttl_cache

        def _fetch():
            url = (
                f"{self.BASE_URL}/alerts/active"
                f"?status=actual&message_type=alert&area={state}"
            )
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "SpotterAI/1.0 (freight route weather)",
                        "Accept": "application/geo+json",
                    },
                )
                with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("features") or []
            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
                return []

        return ttl_cache.cached_call(f"nws_alerts:{state}", self.ALERTS_TTL, _fetch)

    def point_forecast(self, lat: float, lon: float) -> dict:
        """Get short-term forecast for a single point (e.g. pickup/delivery location).
        Cached 30 min — a 2-day forecast doesn't move between requests."""
        from . import ttl_cache
        key = f"nws_forecast:{lat:.2f},{lon:.2f}"
        return ttl_cache.cached_call(key, 1800, lambda: self._point_forecast_live(lat, lon))

    def _point_forecast_live(self, lat: float, lon: float) -> dict:
        try:
            point_url = f"{self.BASE_URL}/points/{lat:.4f},{lon:.4f}"
            req = urllib.request.Request(
                point_url,
                headers={"User-Agent": "SpotterAI/1.0", "Accept": "application/geo+json"},
            )
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                point_data = json.loads(resp.read().decode("utf-8"))

            forecast_url = point_data["properties"]["forecast"]
            req2 = urllib.request.Request(
                forecast_url,
                headers={"User-Agent": "SpotterAI/1.0", "Accept": "application/geo+json"},
            )
            with urllib.request.urlopen(req2, timeout=self.TIMEOUT) as resp2:
                forecast_data = json.loads(resp2.read().decode("utf-8"))

            periods = forecast_data["properties"]["periods"][:4]  # next 2 days
            return {
                "periods": [
                    {
                        "name": p["name"],
                        "temperature": p["temperature"],
                        "temperature_unit": p["temperatureUnit"],
                        "wind_speed": p["windSpeed"],
                        "short_forecast": p["shortForecast"],
                        "detailed_forecast": p["detailedForecast"],
                        "is_daytime": p["isDaytime"],
                    }
                    for p in periods
                ],
                "data_source": "real",
                "source": "NWS (weather.gov)",
            }
        except Exception:
            return {"periods": [], "data_source": "unavailable"}

    @staticmethod
    def _delay_risk(highest_severity: str, alert_count: int) -> str:
        if highest_severity in ("Extreme",):
            return "HIGH"
        if highest_severity in ("Severe",) or alert_count >= 3:
            return "MODERATE"
        if highest_severity in ("Moderate", "Minor") or alert_count >= 1:
            return "LOW"
        return "NONE"

    @staticmethod
    def _empty(reason: str) -> dict:
        return {
            "alerts": [],
            "alert_count": 0,
            "highest_severity": "None",
            "delay_risk": "NONE",
            "data_source": "unavailable",
            "reason": reason,
        }
