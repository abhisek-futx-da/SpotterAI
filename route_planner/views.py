import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .services.exceptions import PlannerError
from .services.planner import RoutePlanService


@method_decorator(csrf_exempt, name="dispatch")
class OptimizeRouteView(View):
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Request body must be valid JSON."}, status=400)

        try:
            plan = RoutePlanService().plan(payload)
        except PlannerError as exc:
            return JsonResponse({"error": str(exc), "code": exc.code}, status=exc.status_code)

        return JsonResponse(plan, status=200)


US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WV", "WI",
    "WY", "DC",
}


def rates_page(request):
    """Homepage — renders with REAL dataset stats queried from the DB, so the
    page never claims a station count or coverage the data doesn't back up."""
    from django.shortcuts import render
    from .models import FuelStation

    station_count = FuelStation.objects.count()
    states = set(
        FuelStation.objects.exclude(state="").values_list("state", flat=True).distinct()
    )
    us_states = {s for s in states if s.upper().strip() in US_STATE_CODES}
    has_canada = len(states) > len(us_states)

    return render(request, "route_planner/solutions/rates.html", {
        "station_count": f"{station_count:,}",
        "us_state_count": len(us_states),
        "has_canada": has_canada,
    })
