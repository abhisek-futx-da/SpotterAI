"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView


def tv(template):
    return TemplateView.as_view(template_name=f"route_planner/{template}")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("route_planner.urls")),

    # Homepage — Fuel Route Optimizer + Lane Rate Intelligence + Carrier Verification
    path("", tv("solutions/rates.html"), name="home"),
]
