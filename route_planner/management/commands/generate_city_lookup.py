from __future__ import annotations

import csv
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
import zipfile

from django.core.management.base import BaseCommand, CommandError


GEONAMES_US_URL = "https://download.geonames.org/export/dump/US.zip"

ALIASES = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "mount": "mt",
    "fort": "ft",
    "saint": "st",
}


def normalize_city(value: str) -> str:
    text = (value or "").casefold().replace("&", " and ")
    text = re.sub(r"\bsaint\b", "st", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def city_variants(name: str) -> set[str]:
    base = normalize_city(name)
    values = {base, base.replace(" ", "")}
    parts = base.split()
    if parts:
        first = parts[0]
        if first in ALIASES:
            values.add(" ".join([ALIASES[first], *parts[1:]]))

        inverse_aliases = {value: key for key, value in ALIASES.items()}
        if first in inverse_aliases:
            values.add(" ".join([inverse_aliases[first], *parts[1:]]))

    return {value for value in values if value}


class Command(BaseCommand):
    help = "Generate city/state coordinate lookup data from the fuel-price CSV and GeoNames."

    def add_arguments(self, parser):
        parser.add_argument("fuel_csv", type=Path)
        parser.add_argument("output_csv", type=Path)
        parser.add_argument(
            "--geonames-zip",
            type=Path,
            help="Optional local GeoNames US.zip file. If omitted, the command downloads it.",
        )
        parser.add_argument(
            "--geonames-url",
            default=GEONAMES_US_URL,
            help="GeoNames US.zip URL used when --geonames-zip is omitted.",
        )

    def handle(self, *args, **options):
        fuel_csv: Path = options["fuel_csv"]
        output_csv: Path = options["output_csv"]
        geonames_zip: Path | None = options["geonames_zip"]

        if not fuel_csv.exists():
            raise CommandError(f"Fuel CSV file not found: {fuel_csv}")

        originals, wanted_aliases, fuel_row_count = self._fuel_city_keys(fuel_csv)
        if geonames_zip is not None:
            if not geonames_zip.exists():
                raise CommandError(f"GeoNames zip file not found: {geonames_zip}")
            matches = self._match_geonames(geonames_zip, wanted_aliases)
        else:
            with TemporaryDirectory() as tmpdir:
                downloaded_zip = Path(tmpdir) / "US.zip"
                self.stdout.write(f"Downloading GeoNames US data from {options['geonames_url']}...")
                urlretrieve(options["geonames_url"], downloaded_zip)
                matches = self._match_geonames(downloaded_zip, wanted_aliases)

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._write_lookup(output_csv, originals, matches)

        matched_rows = self._matched_fuel_rows(fuel_csv, matches)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {output_csv}. Matched {len(matches)} of {len(originals)} "
                f"city/state pairs and {matched_rows} of {fuel_row_count} fuel rows."
            )
        )

    def _fuel_city_keys(
        self,
        fuel_csv: Path,
    ) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[tuple[str, str], tuple[str, str]], int]:
        originals: dict[tuple[str, str], tuple[str, str]] = {}
        wanted_aliases: dict[tuple[str, str], tuple[str, str]] = {}
        row_count = 0

        with fuel_csv.open(newline="", encoding="utf-8-sig") as file_obj:
            reader = csv.DictReader(file_obj)
            if not reader.fieldnames or "City" not in reader.fieldnames or "State" not in reader.fieldnames:
                raise CommandError("Fuel CSV must include City and State columns.")

            for row in reader:
                row_count += 1
                city = row["City"].strip()
                state = row["State"].strip().upper()
                original_key = (normalize_city(city), state)
                originals.setdefault(original_key, (city, state))
                for alias in city_variants(city):
                    wanted_aliases.setdefault((alias, state), original_key)

        return originals, wanted_aliases, row_count

    def _match_geonames(
        self,
        geonames_zip: Path,
        wanted_aliases: dict[tuple[str, str], tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, str | int]]:
        matches: dict[tuple[str, str], dict[str, str | int]] = {}

        with zipfile.ZipFile(geonames_zip) as zip_file:
            if "US.txt" not in zip_file.namelist():
                raise CommandError("GeoNames zip must contain US.txt.")

            with zip_file.open("US.txt") as file_obj:
                for raw in file_obj:
                    parts = raw.decode("utf-8").rstrip("\n").split("\t")
                    if len(parts) < 19 or parts[6] != "P":
                        continue

                    state = parts[10].upper()
                    population = int(parts[14] or 0)
                    names = [parts[1], parts[2], *parts[3].split(",")]
                    for name in names:
                        for city_key in city_variants(name):
                            original_key = wanted_aliases.get((city_key, state))
                            if original_key is None:
                                continue

                            current = matches.get(original_key)
                            if current is None or population > int(current["population"]):
                                matches[original_key] = {
                                    "latitude": parts[4],
                                    "longitude": parts[5],
                                    "source_name": parts[1],
                                    "population": population,
                                }

        return matches

    def _write_lookup(
        self,
        output_csv: Path,
        originals: dict[tuple[str, str], tuple[str, str]],
        matches: dict[tuple[str, str], dict[str, str | int]],
    ) -> None:
        with output_csv.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=["city", "state", "latitude", "longitude", "source_name", "population"],
            )
            writer.writeheader()
            for key in sorted(matches, key=lambda item: (item[1], originals[item][0].casefold())):
                city, state = originals[key]
                writer.writerow({"city": city, "state": state, **matches[key]})

    def _matched_fuel_rows(self, fuel_csv: Path, matches: dict[tuple[str, str], dict]) -> int:
        with fuel_csv.open(newline="", encoding="utf-8-sig") as file_obj:
            reader = csv.DictReader(file_obj)
            return sum(
                1
                for row in reader
                if (normalize_city(row["City"]), row["State"].strip().upper()) in matches
            )
