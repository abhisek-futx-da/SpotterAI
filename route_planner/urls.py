from django.urls import path

from .views import OptimizeRouteView
from .views_carrier_verification import CarrierVerificationView
from .views_market_index import MarketIndexView
from .views_rate_intelligence import LaneRateIntelligenceView
from .views_weather import WeatherAlertsView


urlpatterns = [
    path("routes/optimize/", OptimizeRouteView.as_view(), name="optimize-route"),
    path("rate-intelligence/", LaneRateIntelligenceView.as_view(), name="rate-intelligence"),
    path("carrier-verification/", CarrierVerificationView.as_view(), name="carrier-verification"),
    path("weather-alerts/", WeatherAlertsView.as_view(), name="weather-alerts"),
    path("market-index/", MarketIndexView.as_view(), name="market-index"),
]
