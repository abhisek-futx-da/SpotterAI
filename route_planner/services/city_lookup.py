from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re


def normalize_city(value: str) -> str:
    normalized = (value or "").casefold().replace("&", " and ")
    normalized = re.sub(r"\bsaint\b", "st", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()


@dataclass(frozen=True)
class CityCoordinate:
    latitude: Decimal
    longitude: Decimal


class CityCoordinateLookup:
    def __init__(self, csv_path: Path) -> None:
        self._coordinates: dict[tuple[str, str], CityCoordinate] = {}
        with csv_path.open(newline="", encoding="utf-8-sig") as file_obj:
            reader = csv.DictReader(file_obj)
            for row in reader:
                city = normalize_city(row.get("city", ""))
                state = (row.get("state") or "").strip().upper()
                latitude = row.get("latitude")
                longitude = row.get("longitude")
                if not city or not state or not latitude or not longitude:
                    continue
                self._coordinates[(city, state)] = CityCoordinate(
                    latitude=Decimal(str(latitude)),
                    longitude=Decimal(str(longitude)),
                )

    def get(self, city: str, state: str) -> CityCoordinate | None:
        return self._coordinates.get((normalize_city(city), state.strip().upper()))
