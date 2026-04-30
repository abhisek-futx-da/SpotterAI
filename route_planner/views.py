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
