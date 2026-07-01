import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .services.bls_ppi import BLSEmploymentService, BLSPPIService


@method_decorator(csrf_exempt, name="dispatch")
class MarketIndexView(View):
    """Real BLS Trucking PPI and employment data for rate benchmarking."""
    http_method_names = ["get", "post", "options"]

    def get(self, request, *args, **kwargs):
        equipment_type = request.GET.get("equipment_type", "")
        include_employment = request.GET.get("employment", "false").lower() == "true"
        return self._respond(equipment_type, include_employment)

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        equipment_type = body.get("equipment_type", "")
        include_employment = body.get("employment", False)
        return self._respond(equipment_type, include_employment)

    def _respond(self, equipment_type: str, include_employment: bool = False):
        ppi_service = BLSPPIService()
        valid = ("dry_van", "reefer", "flatbed")
        if equipment_type and equipment_type in valid:
            ppi_result = ppi_service.get_rate_index(equipment_type)
        else:
            ppi_result = ppi_service.get_all_equipment_indices()

        if include_employment:
            emp_service = BLSEmploymentService()
            employment = emp_service.get_capacity_signal()
            return JsonResponse({"ppi": ppi_result, "employment": employment})

        return JsonResponse(ppi_result)
