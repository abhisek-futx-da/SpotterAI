"""USDA AMS Specialty Crops National Truck Rate Report (report 2375 / FVWTRK).

The one FREE source of real, surveyed, per-lane truck rates. USDA Market News
publishes weekly reefer freight rates from major produce shipping areas to ten
destination cities (Atlanta, Baltimore, Boston, Chicago, Dallas, Los Angeles,
Miami, New York, Philadelphia, Seattle). Rates are for 48-53' refrigerated
trailers — so this is real reefer lane data, verifiable by anyone.

Free API key: register at mymarketnews.ams.usda.gov, key is in your profile.
Auth: HTTP Basic, key as username, blank password.
Set env var: USDA_API_KEY

Only covers reefer/produce lanes into the 10 destination cities — narrow, but
100% real surveyed rates where it applies. Degrades to unavailable otherwise.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
TRUCK_REPORT_SLUG = os.getenv("USDA_TRUCK_REPORT_SLUG", "2375")  # FVWTRK
TIMEOUT = 8

# The report's ten fixed destination cities → state.
DEST_CITY_STATE = {
    "atlanta": "GA", "baltimore": "MD", "boston": "MA", "chicago": "IL",
    "dallas": "TX", "los angeles": "CA", "miami": "FL", "new york": "NY",
    "philadelphia": "PA", "seattle": "WA",
}

# Produce shipping areas in the report roughly map to these origin states.
# Kept broad; matching is best-effort on the origin district text.
ORIGIN_HINTS = {
    "CA": ["california", "salinas", "san joaquin", "oxnard", "santa maria", "imperial", "coachella", "fresno"],
    "AZ": ["arizona", "nogales", "yuma"],
    "FL": ["florida", "plant city", "immokalee"],
    "TX": ["texas", "rio grande", "mcallen"],
    "GA": ["georgia", "vidalia"],
    "WA": ["washington", "yakima", "wenatchee"],
    "OR": ["oregon"],
    "ID": ["idaho"],
    "MI": ["michigan"],
    "NC": ["north carolina"],
    "NJ": ["new jersey"],
    "NY": ["new york"],
}


def _fetch_report() -> list[dict]:
    # USDA truck-rate report is WEEKLY — cache 6h so every reefer request isn't
    # a fresh HTTP round-trip for data that changes once a week.
    from . import ttl_cache
    return ttl_cache.cached_call("usda_truck_report", 6 * 3600, _fetch_report_live)


def _fetch_report_live() -> list[dict]:
    api_key = os.environ.get("USDA_API_KEY", "")
    if not api_key:
        return []
    url = f"{MARS_BASE}/{TRUCK_REPORT_SLUG}"
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "SpotterAI/1.0 (freight analytics)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return []
    # MARS returns {"results": [...]} or a report envelope; handle both.
    if isinstance(payload, dict):
        for key in ("results", "report", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    if isinstance(payload, list):
        return payload
    return []


def _num(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _field(rec: dict, *names):
    """Grab the first present field by any of several possible USDA field names."""
    for n in names:
        for k in rec.keys():
            if k.lower() == n.lower():
                return rec[k]
    return None


def get_produce_lane_rate(origin_state: str, dest_state: str, distance_miles: float) -> dict:
    """Real USDA surveyed reefer rate for a produce lane, as $/mi.
    Returns data_source 'real' only when a matching origin→destination is found."""
    o, d = (origin_state or "").upper(), (dest_state or "").upper()
    # Destination must be one of the report's ten cities' states.
    dest_states = set(DEST_CITY_STATE.values())
    if d not in dest_states:
        return {"data_source": "unavailable", "reason": "destination not a USDA report city"}

    records = _fetch_report()
    if not records:
        return {"data_source": "unavailable", "reason": "USDA_API_KEY not set or report unreachable"}

    origin_hints = ORIGIN_HINTS.get(o, [o.lower()])
    dest_cities = [c for c, s in DEST_CITY_STATE.items() if s == d]

    matches = []
    for rec in records:
        origin_txt = str(_field(rec, "origin", "origin_district", "shipping_point", "location") or "").lower()
        dest_txt = str(_field(rec, "destination", "dest", "market", "city") or "").lower()
        if not any(city in dest_txt for city in dest_cities):
            continue
        if not any(h in origin_txt for h in origin_hints):
            continue
        low = _num(_field(rec, "low_price", "price_low", "low", "min_price"))
        high = _num(_field(rec, "high_price", "price_high", "high", "max_price"))
        if low is None and high is None:
            continue
        vals = [x for x in (low, high) if x is not None]
        matches.append(sum(vals) / len(vals))

    if not matches or not distance_miles:
        return {"data_source": "unavailable", "reason": "no matching produce lane in current report"}

    avg_load = sum(matches) / len(matches)
    per_mile = round(avg_load / distance_miles, 2)
    return {
        "data_source": "real",
        "per_mile": per_mile,
        "avg_load_usd": round(avg_load, 0),
        "sample": len(matches),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "USDA AMS Specialty Crops National Truck Rate Report (report 2375, weekly, reefer)",
        "note": "Real USDA-surveyed reefer rate for this produce lane — verifiable at mymarketnews.ams.usda.gov.",
    }
