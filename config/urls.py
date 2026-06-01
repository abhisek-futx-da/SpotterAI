"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("route_planner.urls")),
    path("", TemplateView.as_view(template_name="route_planner/index.html"), name="home"),
]

