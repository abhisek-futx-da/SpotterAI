"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from route_planner.views import rates_page


def coming_soon(title, icon, description):
    return TemplateView.as_view(
        template_name="route_planner/solutions/coming_soon.html",
        extra_context={"sol_title": title, "sol_icon": icon, "sol_description": description},
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("route_planner.urls")),

    # Homepage — stats rendered from the real dataset, never hardcoded
    path("", rates_page, name="home"),
    path("solutions/rates/", rates_page, name="solution-rates"),

    # Upcoming solutions — real pages so nav links never dead-end
    path("solutions/capacity/", coming_soon(
        "Capacity Solutions", "🚛",
        "Find and secure trucks on the lanes you need, when you need them.",
    ), name="solution-capacity"),
    path("solutions/payments/", coming_soon(
        "Payments", "💳",
        "Fast, transparent freight payments between brokers and carriers.",
    ), name="solution-payments"),
    path("solutions/factoring/", coming_soon(
        "Factoring", "📄",
        "Same-day funding on your invoices with clear, simple terms.",
    ), name="solution-factoring"),
    path("solutions/banking/", coming_soon(
        "Banking", "🏦",
        "Banking built for trucking businesses — accounts, cards, and fuel spend controls.",
    ), name="solution-banking"),
    path("solutions/insurance/", coming_soon(
        "Insurance", "🛡️",
        "Coverage tailored to carriers, from liability to cargo protection.",
    ), name="solution-insurance"),
]
