"""Shared aggregation for the cross-broker lane-rate network.

Both the /api/lane-rates/ endpoint and the rate-intelligence engine use this so
there is exactly one definition of "what the network says this lane pays."
Anonymous: aggregates only origin/dest state, equipment, rate, timestamp.
"""
import statistics
from datetime import timedelta

from django.utils import timezone


def aggregate_lane(origin_state: str, dest_state: str, equipment_type: str) -> dict:
    """Network aggregate for a lane — count, avg, median, range, recency windows.
    Returns data_source 'real' when at least one rate is logged, else 'unavailable'."""
    from route_planner.models import LaneRate

    qs = LaneRate.objects.filter(
        origin_state=origin_state,
        dest_state=dest_state,
        equipment_type=equipment_type,
    )
    total = qs.count()
    if total == 0:
        return {
            "count": 0,
            "data_source": "unavailable",
            "note": "No broker-logged rates on this lane yet. Log a load to start "
                    "the network's real-rate picture — it's the one number no free "
                    "government feed can give you.",
        }

    rows = list(qs.values_list("rate_per_mile", "created_at", "origin_city", "dest_city"))
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

    return {
        "count": total,
        "avg": round(statistics.mean(rates), 2),
        "low": round(min(rates), 2),
        "high": round(max(rates), 2),
        "median": round(statistics.median(rates), 2),
        "last_30d": _stats(d30),
        "last_90d": _stats(d90),
        "recent": recent,
        "data_source": "real",
        "source": "Broker-logged network rates (SpotterAI users)",
    }
