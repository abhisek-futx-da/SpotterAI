from __future__ import annotations

import json
from unittest.mock import patch

from django.test import Client, TestCase

from route_planner.models import FuelStation
from route_planner.services.fuel_data import StationCandidate
from route_planner.services.geocoding import Location
from route_planner.services.optimizer import FuelOptimizer
from route_planner.services.routing import Route


class FuelOptimizerTests(TestCase):
    def test_chooses_cheaper_feasible_stop_sequence(self):
        candidates = [
            StationCandidate(1, "A", "", "", "PA", 40.0, -79.0, 5.00, 300.0, 1.0),
            StationCandidate(2, "B", "", "", "OH", 40.0, -83.0, 3.00, 480.0, 1.0),
            StationCandidate(3, "C", "", "", "IN", 40.0, -88.0, 4.50, 780.0, 1.0),
        ]

        plan = FuelOptimizer(max_range_miles=500, mpg=10, starting_range_miles=500).optimize(
            total_distance_miles=950,
            candidates=candidates,
        )

        self.assertEqual([stop.station.name for stop in plan.stops], ["B"])
        self.assertAlmostEqual(plan.total_gallons_purchased, 47.0)
        self.assertAlmostEqual(plan.total_cost, 141.0)

    def test_raises_when_gap_exceeds_vehicle_range(self):
        candidates = [
            StationCandidate(1, "A", "", "", "PA", 40.0, -79.0, 4.00, 550.0, 1.0),
        ]

        with self.assertRaisesMessage(Exception, "No feasible fuel plan"):
            FuelOptimizer(max_range_miles=500, mpg=10, starting_range_miles=500).optimize(
                total_distance_miles=900,
                candidates=candidates,
            )

    def test_prefers_lower_cost_before_fewer_stops(self):
        candidates = [
            StationCandidate(1, "One stop", "", "", "OH", 40.0, -82.0, 4.00, 490.0, 1.0),
            StationCandidate(2, "Cheap hop", "", "", "OH", 40.0, -83.0, 2.00, 520.0, 1.0),
        ]

        plan = FuelOptimizer(max_range_miles=500, mpg=10, starting_range_miles=500).optimize(
            total_distance_miles=800,
            candidates=candidates,
        )

        self.assertEqual([stop.station.name for stop in plan.stops], ["One stop", "Cheap hop"])
        self.assertLess(plan.total_cost, 124)


class OptimizeRouteApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        FuelStation.objects.create(
            name="Youngstown Fuel",
            city="Youngstown",
            state="OH",
            latitude="40.000000",
            longitude="-82.000000",
            retail_price="3.100",
        )
        FuelStation.objects.create(
            name="Indiana Fuel",
            city="Gary",
            state="IN",
            latitude="40.000000",
            longitude="-89.000000",
            retail_price="3.600",
        )

    @patch("route_planner.services.planner.RouteClient.get_route")
    @patch("route_planner.services.planner.NominatimGeocoder.resolve")
    def test_returns_route_fuel_plan_and_map_data(self, geocode_mock, route_mock):
        geocode_mock.side_effect = [
            Location(label="New York, NY", lat=40.0, lon=-75.0),
            Location(label="Chicago, IL", lat=40.0, lon=-96.0),
        ]
        route_mock.return_value = Route(
            points=[(40.0, -75.0), (40.0, -82.0), (40.0, -89.0), (40.0, -96.0)],
            distance_miles=1070.0,
            duration_seconds=54000.0,
        )

        response = self.client.post(
            "/api/routes/optimize/",
            data=json.dumps({"start": "New York, NY", "finish": "Chicago, IL"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["external_calls"], {"geocoding": 2, "routing": 1})
        self.assertEqual(payload["fuel_plan"]["candidate_station_count"], 2)
        self.assertGreaterEqual(len(payload["fuel_plan"]["stops"]), 1)
        self.assertEqual(payload["map"]["geojson"]["type"], "FeatureCollection")
