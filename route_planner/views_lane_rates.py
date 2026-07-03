"""Cross-user lane-rate flywheel — the only source of *real, lane-level* rates
in the product. Brokers log what they actually paid; the network aggregate on
that lane becomes real market data no free government feed can provide.

POST /api/lane-rates/  — log a rate (anonymous)
GET  /api/lane-rates/?origin_state=NY&dest_state=IL&equipment_type=dry_van
                       — network aggregate for the lane
"""
import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import LaneRate
from .services.lane_rate_stats import aggregate_lane as _aggregate

VALID_EQUIPMENT = {"dry_van", "reefer", "flatbed"}


@method_decorator(csrf_exempt, name="dispatch")
class LaneRateView(View):
    http_method_names = ["get", "post", "options"]

    def get(self, request, *args, **kwargs):
        o = (request.GET.get("origin_state", "") or "").strip().upper()[:2]
        d = (request.GET.get("dest_state", "") or "").strip().upper()[:2]
        eq = (request.GET.get("equipment_type", "") or "").strip()
        if not o or not d or eq not in VALID_EQUIPMENT:
            return JsonResponse({"error": "origin_state, dest_state, equipment_type required"}, status=400)
        return JsonResponse(_aggregate(o, d, eq))

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        o = (body.get("origin_state", "") or "").strip().upper()[:2]
        d = (body.get("dest_state", "") or "").strip().upper()[:2]
        eq = (body.get("equipment_type", "") or "").strip()
        if not o or not d or eq not in VALID_EQUIPMENT:
            return JsonResponse({"error": "origin_state, dest_state, equipment_type required"}, status=400)

        try:
            rate = round(float(body.get("rate_per_mile")), 2)
        except (TypeError, ValueError):
            return JsonResponse({"error": "rate_per_mile must be a number"}, status=400)
        if not (0.1 <= rate <= 20):
            return JsonResponse({"error": "rate_per_mile out of range (0.1–20)"}, status=400)

        distance = body.get("distance_miles")
        try:
            distance = round(float(distance), 1) if distance else None
        except (TypeError, ValueError):
            distance = None

        LaneRate.objects.create(
            origin_city=(body.get("origin_city", "") or "").strip()[:128],
            origin_state=o,
            dest_city=(body.get("dest_city", "") or "").strip()[:128],
            dest_state=d,
            equipment_type=eq,
            rate_per_mile=rate,
            distance_miles=distance,
        )
        return JsonResponse({"ok": True, "aggregate": _aggregate(o, d, eq)})
