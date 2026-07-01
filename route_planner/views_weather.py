import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .services.weather import WeatherService


@method_decorator(csrf_exempt, name="dispatch")
class WeatherAlertsView(View):
    """Real NWS weather alerts along a route or for a single point."""
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        service = WeatherService()

        # Route-based alerts: expects {"route_points": [[lat, lon], ...]}
        route_points = body.get("route_points")
        if route_points:
            try:
                points = [(float(p[0]), float(p[1])) for p in route_points]
            except (TypeError, ValueError, IndexError):
                return JsonResponse({"error": "route_points must be [[lat, lon], ...] pairs"}, status=400)
            result = service.alerts_along_route(points)
            return JsonResponse(result)

        # Single-point forecast: expects {"lat": 41.85, "lon": -87.65}
        lat = body.get("lat")
        lon = body.get("lon")
        if lat is not None and lon is not None:
            try:
                result = service.point_forecast(float(lat), float(lon))
            except (TypeError, ValueError):
                return JsonResponse({"error": "lat and lon must be numbers"}, status=400)
            return JsonResponse(result)

        return JsonResponse(
            {"error": "Provide either 'route_points' (array of [lat,lon]) or 'lat'+'lon' for a point forecast"},
            status=400,
        )
