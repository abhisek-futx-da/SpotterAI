from __future__ import annotations

from dataclasses import dataclass

from .exceptions import FuelPlanError, ValidationError
from .fuel_data import StationCandidate


@dataclass(frozen=True)
class FuelStop:
    station: StationCandidate
    gallons: float
    leg_miles: float
    cost: float


@dataclass(frozen=True)
class FuelPlan:
    stops: list[FuelStop]
    total_cost: float
    total_gallons_purchased: float


class FuelOptimizer:
    def __init__(self, max_range_miles: float, mpg: float, starting_range_miles: float) -> None:
        if max_range_miles <= 0:
            raise ValidationError("max_range_miles must be greater than zero.")
        if mpg <= 0:
            raise ValidationError("mpg must be greater than zero.")
        if starting_range_miles < 0:
            raise ValidationError("starting_range_miles cannot be negative.")

        self.max_range_miles = max_range_miles
        self.mpg = mpg
        self.starting_range_miles = min(starting_range_miles, max_range_miles)

    def optimize(self, total_distance_miles: float, candidates: list[StationCandidate]) -> FuelPlan:
        if total_distance_miles <= self.starting_range_miles:
            return FuelPlan(stops=[], total_cost=0.0, total_gallons_purchased=0.0)

        usable_candidates = [
            candidate
            for candidate in candidates
            if 0 < candidate.mile_marker < total_distance_miles
        ]
        usable_candidates.sort(key=lambda item: (item.mile_marker, item.price))

        distances = [0.0] + [item.mile_marker for item in usable_candidates] + [total_distance_miles]
        prices = [None] + [item.price for item in usable_candidates] + [None]
        node_count = len(distances)

        dp = [(float("inf"), 10**9)] * node_count
        previous: list[int | None] = [None] * node_count
        dp[0] = (0.0, 0)

        for start_index in range(node_count - 1):
            if dp[start_index][0] == float("inf"):
                continue

            max_leg = self.starting_range_miles if start_index == 0 else self.max_range_miles
            for end_index in range(start_index + 1, node_count):
                leg_miles = distances[end_index] - distances[start_index]
                if leg_miles > max_leg:
                    break

                if start_index == 0:
                    additional_stops = 0
                    leg_cost = 0.0
                else:
                    additional_stops = 1
                    leg_cost = (leg_miles / self.mpg) * float(prices[start_index])

                candidate_value = (
                    dp[start_index][0] + leg_cost,
                    dp[start_index][1] + additional_stops,
                )
                if candidate_value < dp[end_index]:
                    dp[end_index] = candidate_value
                    previous[end_index] = start_index

        if dp[-1][0] == float("inf"):
            raise FuelPlanError(
                "No feasible fuel plan found. Increase corridor_miles, load more stations, "
                "or check that the fuel data covers this route."
            )

        path = self._reconstruct_path(previous)
        stops: list[FuelStop] = []
        for path_index in range(1, len(path) - 1):
            station_node_index = path[path_index]
            next_node_index = path[path_index + 1]
            station = usable_candidates[station_node_index - 1]
            leg_miles = distances[next_node_index] - distances[station_node_index]
            gallons = leg_miles / self.mpg
            cost = gallons * station.price
            stops.append(FuelStop(station=station, gallons=gallons, leg_miles=leg_miles, cost=cost))

        return FuelPlan(
            stops=stops,
            total_cost=sum(stop.cost for stop in stops),
            total_gallons_purchased=sum(stop.gallons for stop in stops),
        )

    @staticmethod
    def _reconstruct_path(previous: list[int | None]) -> list[int]:
        path = [len(previous) - 1]
        current = previous[-1]
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()
        return path
