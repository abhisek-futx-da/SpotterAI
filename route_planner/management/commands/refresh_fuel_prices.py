"""Management command: refresh fuel station prices from EIA state-level diesel data.

The fuel optimizer uses FuelStation.retail_price for all route calculations.
This command pulls the latest EIA weekly diesel price for each state in the
database and updates all stations in that state proportionally:

  new_price = old_price * (eia_state_avg / baseline_state_avg)

This preserves the relative price differences between stations within a state
(some stations are always cheaper than others) while anchoring the absolute
prices to the current market. It is far more accurate than using a static CSV
snapshot — and it uses an API that is already integrated and free.

Usage:
    python manage.py refresh_fuel_prices
    python manage.py refresh_fuel_prices --dry-run
    python manage.py refresh_fuel_prices --states TX,CA,IL

Schedule weekly via cron or your PaaS scheduler (Railway, Heroku Scheduler).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Avg

from route_planner.models import FuelStation
from route_planner.services.rate_intelligence import LaneRateIntelligenceService


class Command(BaseCommand):
    help = "Refresh FuelStation retail prices from EIA weekly state-level diesel averages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing to the database.",
        )
        parser.add_argument(
            "--states",
            type=str,
            default="",
            help="Comma-separated list of state abbreviations to refresh (default: all states).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        states_arg: str = options["states"]

        # Determine which states to refresh
        if states_arg:
            target_states = [s.strip().upper() for s in states_arg.split(",") if s.strip()]
        else:
            target_states = list(
                FuelStation.objects.values_list("state", flat=True)
                .distinct()
                .order_by("state")
            )

        if not target_states:
            self.stdout.write(self.style.WARNING("No fuel stations in the database."))
            return

        service = LaneRateIntelligenceService()
        updated_count = 0
        skipped_count = 0
        failed_states: list[str] = []

        # Compute current baseline (average price per state in DB)
        baseline_avgs: dict[str, float] = defaultdict(lambda: 3.85)
        for row in (
            FuelStation.objects.values("state")
            .annotate(avg_price=Avg("retail_price"))
            .filter(state__in=target_states)
        ):
            if row["avg_price"]:
                baseline_avgs[row["state"]] = float(row["avg_price"])

        for state in target_states:
            try:
                eia_price, source = service._get_diesel_price_state(state)
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"  {state}: EIA fetch failed — {exc}")
                )
                failed_states.append(state)
                continue

            if source != "real":
                self.stdout.write(
                    self.style.WARNING(
                        f"  {state}: EIA returned estimated price ${eia_price:.3f} "
                        f"(no live data) — skipping."
                    )
                )
                skipped_count += 1
                continue

            baseline = baseline_avgs[state]
            if baseline == 0:
                self.stdout.write(
                    self.style.WARNING(f"  {state}: baseline avg is zero — skipping.")
                )
                skipped_count += 1
                continue

            # Scale factor: preserves intra-state price spread while anchoring to EIA
            scale = eia_price / baseline
            stations_qs = FuelStation.objects.filter(state=state)
            count = stations_qs.count()

            self.stdout.write(
                f"  {state}: EIA ${eia_price:.3f}/gal (src=real) | "
                f"DB avg ${baseline:.3f} | scale {scale:.4f} | {count} stations"
            )

            if not dry_run:
                from django.utils import timezone as _tz
                stations = list(stations_qs)
                now = _tz.now()
                for station in stations:
                    new_price = Decimal(str(round(float(station.retail_price) * scale, 4)))
                    # Clamp to a sane range (EIA data anomalies do occur)
                    station.retail_price = max(Decimal("2.00"), min(Decimal("8.00"), new_price))
                    station.updated_at = now
                # One bulk UPDATE per batch instead of N individual saves.
                with transaction.atomic():
                    FuelStation.objects.bulk_update(
                        stations, ["retail_price", "updated_at"], batch_size=500
                    )
                updated_count += count
            else:
                updated_count += count

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix}Done. Updated {updated_count} stations across "
                f"{len(target_states) - len(failed_states) - skipped_count} states. "
                f"Skipped: {skipped_count}. Failed: {len(failed_states)}."
                + (f" Failed states: {', '.join(failed_states)}" if failed_states else "")
            )
        )
