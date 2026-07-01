import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .services.carrier_verification import CarrierVerificationService


@method_decorator(csrf_exempt, name="dispatch")
class CarrierVerificationView(View):
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        dot_number = (body.get("dot_number") or "").strip()
        if not dot_number:
            return JsonResponse({"error": "Missing field: dot_number"}, status=400)

        result = CarrierVerificationService().verify_carrier(dot_number)
        return JsonResponse(result)
