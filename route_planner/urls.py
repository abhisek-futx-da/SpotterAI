from django.urls import path

from .views import OptimizeRouteView


urlpatterns = [
    path("routes/optimize/", OptimizeRouteView.as_view(), name="optimize-route"),
]
