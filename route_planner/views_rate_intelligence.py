import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .services.rate_intelligence import LaneRateIntelligenceService


@method_decorator(csrf_exempt, name="dispatch")
class LaneRateIntelligenceView(View):
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        required = [
            "origin_city", "origin_state", "dest_city", "dest_state",
            "equipment_type", "distance_miles",
        ]
        missing = [f for f in required if not body.get(f)]
        if missing:
            return JsonResponse({"error": f"Missing fields: {missing}"}, status=400)

        try:
            distance = float(body["distance_miles"])
            carrier_pay = float(body.get("carrier_pay_per_mile", 0) or 0)
            margin_pct = float(body.get("margin_pct", 15) or 15)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid numeric values"}, status=400)

        # Optional: route_points [[lat, lon], ...] for real weather alerts
        raw_points = body.get("route_points")
        route_points = None
        if raw_points:
            try:
                route_points = [(float(p[0]), float(p[1])) for p in raw_points]
            except (TypeError, ValueError, IndexError):
                route_points = None

        service = LaneRateIntelligenceService()
        result = service.get_lane_intelligence(
            origin_city=body["origin_city"].strip().title(),
            origin_state=body["origin_state"].strip().upper(),
            dest_city=body["dest_city"].strip().title(),
            dest_state=body["dest_state"].strip().upper(),
            equipment_type=body["equipment_type"],
            distance_miles=distance,
            carrier_pay_per_mile=carrier_pay,
            margin_pct=margin_pct,
            route_points=route_points,
        )
        return JsonResponse(result)
