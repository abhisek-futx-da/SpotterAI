"""Shared aggregation for the cross-broker lane-rate network.

Both the /api/lane-rates/ endpoint and the rate-intelligence engine use this so
there is exactly one definition of "what the network says this lane pays."
Anonymous: aggregates only origin/dest state, equipment, rate, timestamp.

Two tiers of real data:
  1. Exact lane  — logged rates on this exact origin_state->dest_state lane.
  2. Regional inference — when the exact lane is thin (<3 loads), borrow from the
     same freight-region pair (e.g. Newark->Milwaukee inherits from
     Northeast->Midwest). Lower confidence, but real transactions on similar lanes,
     which beats a pure cost estimate. Clearly tagged so it's never mistaken for
     exact-lane data.
"""
import statistics
from datetime import timedelta

from django.utils import timezone

# Freight regions for cross-lane inference — coarser than states, finer than national.
STATE_TO_REGION = {
    # Northeast
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "RI": "Northeast", "VT": "Northeast", "NJ": "Northeast", "NY": "Northeast",
    "PA": "Northeast",
    # Mid-Atlantic / Southeast
    "DE": "Southeast", "DC": "Southeast", "MD": "Southeast", "VA": "Southeast",
    "WV": "Southeast", "NC": "Southeast", "SC": "Southeast", "GA": "Southeast",
    "FL": "Southeast",
    # Midwest
    "OH": "Midwest", "IN": "Midwest", "IL": "Midwest", "MI": "Midwest",
    "WI": "Midwest", "MN": "Midwest", "IA": "Midwest", "MO": "Midwest",
    "KS": "Midwest", "NE": "Midwest", "ND": "Midwest", "SD": "Midwest",
    "KY": "Midwest", "TN": "Midwest",
    # South Central
    "TX": "SouthCentral", "OK": "SouthCentral", "AR": "SouthCentral",
    "LA": "SouthCentral", "MS": "SouthCentral", "AL": "SouthCentral",
    "NM": "SouthCentral",
    # West
    "CA": "West", "OR": "West", "WA": "West", "NV": "West", "AZ": "West",
    "UT": "West", "ID": "West", "CO": "West", "MT": "West", "WY": "West",
    "AK": "West", "HI": "West",
}

MIN_EXACT = 3   # below this many exact-lane loads, fall back to regional inference


def _region(state: str) -> str:
    return STATE_TO_REGION.get((state or "").upper(), "")


def _stats(vals):
    if not vals:
        return None
    return {
        "count": len(vals),
        "avg": round(statistics.mean(vals), 2),
        "low": round(min(vals), 2),
        "high": round(max(vals), 2),
        "median": round(statistics.median(vals), 2),
    }


def _shape(rows, tier, o_region="", d_region=""):
    """Build the aggregate payload from a list of (rate, created_at, o_city, d_city)."""
    rates = [float(r[0]) for r in rows]
    now = timezone.now()
    d30 = [float(r[0]) for r in rows if r[1] >= now - timedelta(days=30)]
    d90 = [float(r[0]) for r in rows if r[1] >= now - timedelta(days=90)]
    recent = [
        {
            "rate": float(r[0]),
            "date": r[1].strftime("%Y-%m-%d"),
            "origin_city": r[2] or None,
            "dest_city": r[3] or None,
        }
        for r in rows[:8]
    ]
    out = {
        "count": len(rows),
        "avg": round(statistics.mean(rates), 2),
        "low": round(min(rates), 2),
        "high": round(max(rates), 2),
        "median": round(statistics.median(rates), 2),
        "last_30d": _stats(d30),
        "last_90d": _stats(d90),
        "recent": recent,
        "data_source": "real",
        "tier": tier,
    }
    if tier == "exact":
        out["source"] = "Broker-logged network rates — this exact lane"
    else:
        out["source"] = f"Broker-logged network rates — regional pattern ({o_region}→{d_region})"
        out["region_pair"] = f"{o_region}→{d_region}"
    return out


def aggregate_lane(origin_state: str, dest_state: str, equipment_type: str) -> dict:
    """Real network rate for a lane. Exact-lane data first; if thin, regional inference.
    Returns data_source 'real' with tier 'exact' or 'regional', else 'unavailable'."""
    from route_planner.models import LaneRate

    o, d = (origin_state or "").upper(), (dest_state or "").upper()

    exact = list(
        LaneRate.objects.filter(
            origin_state=o, dest_state=d, equipment_type=equipment_type
        ).values_list("rate_per_mile", "created_at", "origin_city", "dest_city")
    )
    if len(exact) >= MIN_EXACT:
        return _shape(exact, "exact")

    # Thin exact lane — try regional inference from the same freight-region pair.
    o_region, d_region = _region(o), _region(d)
    if o_region and d_region:
        region_states_o = [s for s, r in STATE_TO_REGION.items() if r == o_region]
        region_states_d = [s for s, r in STATE_TO_REGION.items() if r == d_region]
        regional = list(
            LaneRate.objects.filter(
                origin_state__in=region_states_o,
                dest_state__in=region_states_d,
                equipment_type=equipment_type,
            ).values_list("rate_per_mile", "created_at", "origin_city", "dest_city")
        )
        # Only use regional if it adds signal beyond the thin exact set.
        if len(regional) >= MIN_EXACT:
            payload = _shape(regional, "regional", o_region, d_region)
            payload["exact_count"] = len(exact)
            return payload

    # Have 1-2 exact loads but no regional backup — still return the exact (honest, thin).
    if exact:
        return _shape(exact, "exact")

    return {
        "count": 0,
        "data_source": "unavailable",
        "note": "No broker-logged rates on this lane or region yet. Log a load to start "
                "the network's real-rate picture — the one number no free feed can give you.",
    }
