from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from route_planner.models import FuelStation
from route_planner.services.city_lookup import CityCoordinateLookup
from route_planner.services.geocoding import NominatimGeocoder


COLUMN_ALIASES = {
    "source_id": ["source_id", "id", "opis_truckstop_id", "truckstop_id", "station_id"],
    "name": ["name", "station_name", "truckstop_name", "truck_stop_name"],
    "address": ["address", "street", "street_address"],
    "city": ["city"],
    "state": ["state", "st"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "lng", "long"],
    "retail_price": ["retail_price", "price", "fuel_price", "diesel_price", "retail"],
}


def normalize_header(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def value_for(row: dict[str, str], field: str) -> str:
    for alias in COLUMN_ALIASES[field]:
        if alias in row and row[alias] not in {None, ""}:
            return row[alias].strip()
    return ""


def parse_decimal(value: str, field_name: str) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.\-]+", "", value)
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise CommandError(f"Could not parse {field_name}: {value!r}") from exc


class Command(BaseCommand):
    help = "Load fuel prices from the exercise CSV into the FuelStation table."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=Path)
        parser.add_argument("--clear", action="store_true", help="Delete existing stations first.")
        parser.add_argument(
            "--city-lookup",
            type=Path,
            help="CSV with city,state,latitude,longitude columns used for rows missing coordinates.",
        )
        parser.add_argument(
            "--geocode-missing",
            action="store_true",
            help="Use Nominatim to geocode rows that do not include latitude/longitude.",
        )
        parser.add_argument(
            "--geocode-delay",
            type=float,
            default=1.1,
            help="Seconds to sleep between public Nominatim calls.",
        )
        parser.add_argument(
            "--allow-empty-coordinates",
            action="store_true",
            help="Allow importing a file where no rows have latitude/longitude.",
        )

    def handle(self, *args, **options):
        csv_path: Path = options["csv_path"]
        if not csv_path.exists():
            raise CommandError(f"CSV file not found: {csv_path}")

        geocoder = NominatimGeocoder() if options["geocode_missing"] else None
        city_lookup_path: Path | None = options["city_lookup"]
        city_lookup = None
        if city_lookup_path is not None:
            if not city_lookup_path.exists():
                raise CommandError(f"City lookup file not found: {city_lookup_path}")
            city_lookup = CityCoordinateLookup(city_lookup_path)

        rows = self._read_rows(csv_path)
        if not rows:
            raise CommandError("CSV did not contain any fuel station rows.")

        stations = []
        city_lookup_count = 0
        geocoded_count = 0
        missing_coordinate_count = 0
        for index, row in enumerate(rows, start=2):
            price = parse_decimal(value_for(row, "retail_price"), "retail_price")
            if price is None:
                raise CommandError(f"Row {index} is missing a retail price.")

            lat = parse_decimal(value_for(row, "latitude"), "latitude")
            lon = parse_decimal(value_for(row, "longitude"), "longitude")
            address = value_for(row, "address")
            city = value_for(row, "city")
            state = value_for(row, "state")

            if (lat is None or lon is None) and city_lookup is not None:
                coordinate = city_lookup.get(city, state)
                if coordinate is not None:
                    lat = coordinate.latitude
                    lon = coordinate.longitude
                    city_lookup_count += 1

            if (lat is None or lon is None) and geocoder is not None:
                query = ", ".join(part for part in [address, city, state, "USA"] if part)
                if query:
                    location = geocoder.resolve(query)
                    lat = Decimal(str(location.lat))
                    lon = Decimal(str(location.lon))
                    geocoded_count += 1
                    time.sleep(options["geocode_delay"])

            if lat is None or lon is None:
                missing_coordinate_count += 1

            stations.append(
                FuelStation(
                    source_id=value_for(row, "source_id"),
                    name=value_for(row, "name") or "Unnamed fuel station",
                    address=address,
                    city=city,
                    state=state,
                    latitude=lat,
                    longitude=lon,
                    retail_price=price,
                    raw_data=row,
                )
            )

        coordinate_count = len(stations) - missing_coordinate_count
        if coordinate_count == 0 and not options["allow_empty_coordinates"]:
            raise CommandError(
                "No coordinate-backed fuel stations were loaded. The optimizer needs station "
                "coordinates to find stops along a route. Generate a city lookup first and rerun: "
                "python manage.py generate_city_lookup data/fuel-prices-for-be-assessment.csv "
                "data/fuel_city_coordinates.csv"
            )

        with transaction.atomic():
            if options["clear"]:
                FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} fuel stations"
                + (f" ({city_lookup_count} city lookup matches)" if city_lookup_count else "")
                + (f" ({geocoded_count} geocoded)" if geocoded_count else "")
                + (
                    f" ({missing_coordinate_count} without coordinates)"
                    if missing_coordinate_count
                    else ""
                )
                + "."
            )
        )

    def _read_rows(self, csv_path: Path) -> list[dict[str, str]]:
        with csv_path.open(newline="", encoding="utf-8-sig") as file_obj:
            reader = csv.DictReader(file_obj)
            if reader.fieldnames is None:
                return []

            rows = []
            for row in reader:
                rows.append({normalize_header(key): (value or "") for key, value in row.items()})
            return rows