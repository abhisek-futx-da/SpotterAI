"""Cross-user lane-rate flywheel — the only source of *real, lane-level* rates
in the product. Brokers log what they actually paid; the network aggregate on
that lane becomes real market data no free government feed can provide.

POST   /api/lane-rates/  — log a rate (anonymous)
GET    /api/lane-rates/?origin_state=NY&dest_state=IL&equipment_type=dry_van
                         — network aggregate for the lane
DELETE /api/lane-rates/  — moderation: remove bad entries on a lane. Requires
                           X-Admin-Token header matching the ADMIN_TOKEN env var;
                           disabled entirely (403) when ADMIN_TOKEN is unset.
"""
import hmac
import json
import os

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import LaneRate
from .services.lane_rate_stats import aggregate_lane as _aggregate

VALID_EQUIPMENT = {"dry_van", "reefer", "flatbed"}

# Per-equipment sanity ceilings ($/mi). A fat-fingered "20" instead of "2.0"
# passing validation would poison the lane's network average for everyone.
RATE_CEILING = {"dry_van": 7.0, "reefer": 9.0, "flatbed": 9.0}
RATE_FLOOR = 0.50   # below this nobody hauls a full truckload


@method_decorator(csrf_exempt, name="dispatch")
class LaneRateView(View):
    http_method_names = ["get", "post", "delete", "options"]

    def delete(self, request, *args, **kwargs):
        admin_token = os.environ.get("ADMIN_TOKEN", "")
        supplied = request.headers.get("X-Admin-Token", "")
        if not admin_token or not hmac.compare_digest(supplied, admin_token):
            return JsonResponse({"error": "Forbidden"}, status=403)

        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        o = (body.get("origin_state", "") or "").strip().upper()[:2]
        d = (body.get("dest_state", "") or "").strip().upper()[:2]
        eq = (body.get("equipment_type", "") or "").strip()
        if not o or not d or eq not in VALID_EQUIPMENT:
            return JsonResponse({"error": "origin_state, dest_state, equipment_type required"}, status=400)

        qs = LaneRate.objects.filter(origin_state=o, dest_state=d, equipment_type=eq)
        # Optional narrowing to a specific bad entry by its exact rate
        rate = body.get("rate_per_mile")
        if rate is not None:
            try:
                qs = qs.filter(rate_per_mile=round(float(rate), 2))
            except (TypeError, ValueError):
                return JsonResponse({"error": "rate_per_mile must be a number"}, status=400)

        deleted, _ = qs.delete()
        return JsonResponse({"ok": True, "deleted": deleted, "aggregate": _aggregate(o, d, eq)})

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
        ceiling = RATE_CEILING.get(eq, 9.0)
        if not (RATE_FLOOR <= rate <= ceiling):
            return JsonResponse({
                "error": f"Rate ${rate:.2f}/mi is outside the realistic range for "
                         f"{eq.replace('_', ' ')} (${RATE_FLOOR:.2f}–${ceiling:.2f}/mi). "
                         "Check for a typo (e.g. 20 instead of 2.0) and try again."
            }, status=400)

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
