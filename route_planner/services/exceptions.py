class PlannerError(Exception):
    code = "planner_error"
    status_code = 400


class ValidationError(PlannerError):
    code = "validation_error"


class ExternalServiceError(PlannerError):
    code = "external_service_error"
    status_code = 502


class RouteNotFoundError(PlannerError):
    code = "route_not_found"


class FuelPlanError(PlannerError):
    code = "fuel_plan_error"
