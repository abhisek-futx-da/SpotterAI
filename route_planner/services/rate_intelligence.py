"""Stateless lane rate intelligence: buy/sell rate guidance, market and capacity
signals, lane history, and an AI negotiation coach for a given lane.

Real data sources:
- Diesel price: EIA weekly retail price (national + state-level, EIA_API_KEY)
- Market rate index: BLS Trucking PPI (PCU484121484121 series, no key needed)
- Capacity signal: BLS Trucking Employment (CES4348400001, no key needed)
- Driver wages: BLS CES (CES4348400008, no key needed)
- Natural gas (reefer fuel cost signal): EIA Henry Hub (EIA_API_KEY)
- Weather alerts: NWS weather.gov alerts along route (no key needed)

Estimated (formula-based, tagged data_source="estimated"):
- Lane history load counts / cover time
- Sell-rate margin math
"""
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .bls_ppi import BLSEmploymentService, BLSPPIService
from .fred import FREDService
from .weather import WeatherService


class LaneRateIntelligenceService:

    DEFAULT_DIESEL_PRICE = 3.85

    # ATRI 2025 Update — "An Analysis of the Operational Costs of Trucking: 2025 Update"
    # Published July 2025 by American Transportation Research Institute (truckingresearch.org)
    # Covers 2024 operating data. Total: $2.260/mi. Non-fuel: $1.779/mi (record high).
    # Fuel implied: $0.481/mi (total minus non-fuel). Driver wages rose 2.4% YoY.
    # Truck & trailer payments: $0.390/mi. Driver benefits: $0.197/mi.
    # Source: https://truckingresearch.org/2025/07/an-analysis-of-the-operational-costs-of-trucking-2025-update/
    ATRI_FLOOR_PER_MILE = {
        "dry_van": 2.260,
        "reefer":  2.510,   # +$0.25 for refrigeration unit fuel/maintenance
        "flatbed": 2.410,   # +$0.15 for tarps, straps, specialized equipment
    }
    ATRI_BREAKDOWN = {
        "fuel":              0.481,   # implied: total $2.260 minus non-fuel $1.779
        "truck_trailer":     0.390,   # truck & trailer payments (record high)
        "driver_benefits":   0.197,   # driver benefits
        "non_fuel_total":    1.779,   # non-fuel costs (record high per ATRI 2025)
        "total":             2.260,
        "data_year":         2024,
        "report_year":       2025,
        "source":            "ATRI Operational Costs of Trucking: 2025 Update (truckingresearch.org)",
        "note":              "Driver wages +2.4% YoY. Non-fuel costs at record high. Fuel and maintenance declined.",
    }

    # Market premium above ATRI floor by tightness and distance
    # These ranges reflect 2025-2026 soft market reality (post-freight-recession)
    CAPACITY_PREMIUM = {
        "TIGHT":    0.55,   # carrier market — rates well above floor
        "BALANCED": 0.22,   # normal — modest margin above floor
        "LOOSE":    0.07,   # broker market — carriers near floor, competing
    }

    SEASONALITY_ADJUSTMENT = {
        1: -0.04, 2: -0.04,
        3:  0.03, 4:  0.03, 5: 0.02,
        6:  0.01, 7:  0.00, 8: 0.01,
        9:  0.04, 10: 0.04,
        11: 0.07, 12: 0.07,
    }

    PEAK_MONTHS = {
        "dry_van": {11, 12, 3},
        "reefer":  {11, 12, 3},
        "flatbed": {3, 4, 5},
    }

    BACKHAUL_STATES = {"TX", "IL", "CA", "OH", "GA", "FL"}

    def get_lane_intelligence(
        self,
        origin_city: str,
        origin_state: str,
        dest_city: str,
        dest_state: str,
        equipment_type: str,
        distance_miles: float,
        carrier_pay_per_mile: float,
        margin_pct: float,
        route_points: list | None = None,
    ) -> dict:
        if not distance_miles:
            distance_miles = 500.0

        month = datetime.now().month

        # --- Fetch all external data in parallel to avoid sequential timeout ---
        ppi_service = BLSPPIService()
        employment_service = BLSEmploymentService()
        fred_service = FREDService()
        weather_service = WeatherService()

        no_weather = {"alerts": [], "alert_count": 0, "highest_severity": "None",
                      "delay_risk": "NONE", "data_source": "unavailable",
                      "reason": "no route points provided"}

        def _fetch_ppi():
            return ppi_service.get_rate_index(equipment_type)

        def _fetch_employment():
            return employment_service.get_capacity_signal()

        def _fetch_fred():
            return fred_service.get_market_signals()

        def _fetch_nat_gas():
            return self._get_nat_gas_price() if equipment_type == "reefer" else None

        def _fetch_weather():
            return weather_service.alerts_along_route(route_points) if route_points else no_weather

        def _fetch_diesel_trend():
            return self._get_diesel_trend()

        def _fetch_fsc():
            return self._compute_fuel_surcharge(distance_miles, origin_state, dest_state)

        tasks = {
            "ppi": _fetch_ppi,
            "employment": _fetch_employment,
            "fred": _fetch_fred,
            "nat_gas": _fetch_nat_gas,
            "weather": _fetch_weather,
            "diesel_trend": _fetch_diesel_trend,
            "fsc": _fetch_fsc,
        }

        results = {}
        executor = ThreadPoolExecutor(max_workers=7)
        future_map = {executor.submit(fn): name for name, fn in tasks.items()}
        try:
            for future in as_completed(future_map, timeout=12):
                name = future_map[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = None
        except TimeoutError:
            pass
        finally:
            # Don't block on slow/hung threads — take whatever finished, move on.
            executor.shutdown(wait=False)
        for name in tasks:
            results.setdefault(name, None)

        ppi = results.get("ppi") or BLSPPIService._unavailable(equipment_type)
        employment = results.get("employment") or employment_service._unavailable(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        fred = results.get("fred") or {"pmi": None, "freight_volume": None, "data_source": "unavailable"}
        nat_gas = results.get("nat_gas")
        weather = results.get("weather") or no_weather
        diesel_trend_data = results.get("diesel_trend") or []
        fuel_surcharge = results.get("fsc") or self._fsc_fallback(distance_miles)

        capacity = self._compute_capacity(employment, dest_state)
        tightness = capacity.get("market_tightness", "NEUTRAL")

        buy_rate = self._compute_buy_rate(equipment_type, distance_miles, month, tightness, ppi)
        sell_rate = self._compute_sell_rate(buy_rate["suggested"], margin_pct)
        market = self._compute_market(buy_rate["suggested"], carrier_pay_per_mile, month, ppi, fred)
        history = self._compute_history()
        seasonality = self._compute_seasonality(equipment_type, month)
        confidence = self._compute_confidence(0, capacity["signal"], employment, ppi, fuel_surcharge)

        for section in (sell_rate, seasonality, confidence):
            section["data_source"] = "estimated"
        for window in history.values():
            window["data_source"] = "estimated"
        # buy_rate floor is real (ATRI); range is ATRI+BLS estimate
        buy_rate["data_source"] = "real"
        market["data_source"] = "real" if ppi["data_source"] == "real" else "estimated"
        capacity["data_source"] = employment.get("data_source", "estimated")

        signals = {
            "origin_city": origin_city,
            "origin_state": origin_state,
            "dest_city": dest_city,
            "dest_state": dest_state,
            "equipment_type": equipment_type,
            "distance_miles": round(distance_miles, 2),
            "carrier_pay_per_mile": carrier_pay_per_mile,
            "buy_rate": buy_rate,
            "market": market,
            "capacity": capacity,
            "fuel_surcharge": fuel_surcharge,
            "history": history,
            "seasonality": seasonality,
            "confidence": confidence,
            "weather": weather,
        }
        negotiation_coach, coach_source = self._get_negotiation_coach(signals)

        return {
            "lane": {
                "origin_city": origin_city,
                "origin_state": origin_state,
                "dest_city": dest_city,
                "dest_state": dest_state,
                "equipment_type": equipment_type,
                "distance_miles": round(distance_miles, 2),
            },
            "buy_rate": buy_rate,
            "sell_rate": sell_rate,
            "market": market,
            "capacity": capacity,
            "fuel_surcharge": fuel_surcharge,
            "history": history,
            "seasonality": seasonality,
            "weather_alerts": weather,
            "market_index": ppi,
            "employment": employment,
            "fred": fred,
            "nat_gas": nat_gas,
            "atri": self.ATRI_BREAKDOWN,
            "negotiation_coach": negotiation_coach,
            "negotiation_coach_source": coach_source,
            "confidence": confidence,
            "diesel_trend": diesel_trend_data,
        }

    def _compute_buy_rate(
        self,
        equipment_type: str,
        distance_miles: float,
        month: int,
        tightness: str = "NEUTRAL",
        ppi: dict | None = None,
    ) -> dict:
        # Anchor to ATRI 2024 published carrier operating cost — real floor
        floor = self.ATRI_FLOOR_PER_MILE.get(equipment_type, 2.270)

        # Distance adjustment: short haul costs more per mile (deadhead, hours)
        if distance_miles < 300:
            distance_adj = 0.18
        elif distance_miles < 500:
            distance_adj = 0.08
        elif distance_miles > 1200:
            distance_adj = -0.06
        else:
            distance_adj = 0.0

        # Market premium above ATRI floor based on real BLS employment tightness
        premium = self.CAPACITY_PREMIUM.get(tightness, 0.22)

        # Seasonal adjustment on premium only (not floor — floor is fixed cost)
        seasonal = self.SEASONALITY_ADJUSTMENT.get(month, 0.0)

        # PPI trend nudge — use direction only, not raw multiplier (avoids inflation)
        ppi_trend = ppi.get("trend_3m", "FLAT") if ppi else "FLAT"
        ppi_nudge = 0.05 if ppi_trend == "UP" else (-0.04 if ppi_trend == "DOWN" else 0.0)

        suggested = floor + premium + distance_adj + (premium * seasonal) + ppi_nudge
        suggested = round(suggested, 2)

        return {
            "atri_floor": floor,
            "atri_year": 2024,
            "atri_breakdown": self.ATRI_BREAKDOWN,
            "low": round(floor + 0.04, 2),          # just above carrier break-even
            "suggested": suggested,
            "high": round(suggested + 0.30, 2),      # tight market ceiling
            "tightness_used": tightness,
            "ppi_trend_used": ppi_trend,
            "note": "Floor = ATRI 2024 published carrier cost. Range = BLS employment-adjusted market estimate. Verify with DAT for live spot.",
        }

    def _compute_sell_rate(self, buy_rate_suggested: float, margin_pct: float) -> dict:
        margin_frac = margin_pct / 100

        def safe_divide(factor):
            denom = max(0.01, 1 - factor * margin_frac)
            return buy_rate_suggested / denom

        return {
            "conservative": round(safe_divide(0.85), 2),
            "suggested": round(safe_divide(1.0), 2),
            "premium": round(safe_divide(1.20), 2),
        }

    def _compute_market(
        self,
        buy_rate_suggested: float,
        carrier_pay_per_mile: float,
        month: int,
        ppi: dict | None = None,
        fred: dict | None = None,
    ) -> dict:
        market_avg = buy_rate_suggested

        if not carrier_pay_per_mile:
            your_rate = market_avg
            delta_pct = 0.0
            delta_signal = "AT"
        else:
            your_rate = carrier_pay_per_mile
            delta_pct = (your_rate - market_avg) / market_avg * 100
            if delta_pct > 10:
                delta_signal = "ABOVE"
            elif delta_pct > -5:
                delta_signal = "AT"
            elif delta_pct > -15:
                delta_signal = "BELOW"
            else:
                delta_signal = "WELL_BELOW"

        # Rate trend: BLS PPI (real) takes priority
        if ppi and ppi.get("data_source") == "real" and ppi.get("trend_3m"):
            trend = ppi["trend_3m"]
            trend_source = "BLS PPI (real)"
        else:
            trend = "UP" if month in (11, 12, 3) else ("DOWN" if month in (1, 2) else "FLAT")
            trend_source = "seasonal estimate"

        # FRED demand context
        pmi_value = None
        pmi_signal = None
        freight_yoy = None
        if fred and fred.get("data_source") == "real":
            if fred.get("pmi"):
                pmi_value = fred["pmi"]["value"]
                pmi_signal = fred["pmi"]["signal"]
            if fred.get("freight_volume"):
                freight_yoy = fred["freight_volume"]["yoy_delta_pct"]

        return {
            "market_avg_per_mile": round(market_avg, 2),
            "your_rate_per_mile": round(your_rate, 2),
            "delta_pct": round(delta_pct, 2),
            "delta_signal": delta_signal,
            "trend_30d": trend,
            "trend_source": trend_source,
            "ppi_yoy_delta_pct": ppi.get("yoy_delta_pct") if ppi else None,
            "pmi_value": pmi_value,
            "pmi_signal": pmi_signal,
            "freight_volume_yoy_pct": freight_yoy,
        }

    def _compute_capacity(self, employment: dict, dest_state: str) -> dict:
        """Real capacity signal based on BLS trucking employment headcount."""
        tightness = employment.get("market_tightness", "NEUTRAL")
        signal_map = {"TIGHT": "TIGHT", "NEUTRAL": "BALANCED", "LOOSE": "LOOSE", "UNKNOWN": "BALANCED"}
        signal = signal_map.get(tightness, "BALANCED")

        headcount = employment.get("headcount_thousands")
        hc_trend = employment.get("headcount_trend", "FLAT")
        hc_yoy = employment.get("headcount_yoy_pct")
        wages = employment.get("avg_hourly_wages")

        return {
            "signal": signal,
            "market_tightness": tightness,
            "headcount_thousands": headcount,
            "headcount_trend": hc_trend,
            "headcount_yoy_pct": hc_yoy,
            "avg_hourly_wages": wages,
            "backhaul_available": dest_state in self.BACKHAUL_STATES,
            "source": employment.get("source", ""),
        }

    def _compute_fuel_surcharge(
        self, distance_miles: float, origin_state: str = "", dest_state: str = ""
    ) -> dict:
        # Try state-level price for the origin state first, then dest, then national
        origin_price, origin_source = self._get_diesel_price_state(origin_state)
        dest_price, dest_source = self._get_diesel_price_state(dest_state)

        if origin_source == "real" and dest_source == "real":
            diesel_price = round((origin_price + dest_price) / 2, 3)
            source = "real"
            price_breakdown = {
                "origin_state_price": round(origin_price, 3),
                "dest_state_price": round(dest_price, 3),
            }
        elif origin_source == "real":
            diesel_price = origin_price
            source = "real"
            price_breakdown = {"origin_state_price": round(origin_price, 3)}
        elif dest_source == "real":
            diesel_price = dest_price
            source = "real"
            price_breakdown = {"dest_state_price": round(dest_price, 3)}
        else:
            national, national_source = self._get_diesel_price_national()
            diesel_price = national
            source = national_source
            price_breakdown = {}

        mpg = 6.5
        per_mile = round((diesel_price - 0.50) / mpg, 4)
        return {
            "per_mile": per_mile,
            "total": round(per_mile * distance_miles, 2),
            "diesel_price_per_gallon": round(diesel_price, 3),
            "data_source": source,
            **price_breakdown,
        }

    # EIA PADD region mapping (state → PADD duoarea code for state-level prices)
    STATE_TO_EIA_DUOAREA = {
        "CT": "SCT", "ME": "SME", "MA": "SMA", "NH": "SNH", "RI": "SRI", "VT": "SVT",
        "DE": "SDE", "DC": "SDC", "MD": "SMD", "NJ": "SNJ", "NY": "SNY", "PA": "SPA",
        "IL": "SIL", "IN": "SIN", "MI": "SMI", "MN": "SMN", "OH": "SOH", "WI": "SWI",
        "IA": "SIA", "KS": "SKS", "MO": "SMO", "NE": "SNE", "ND": "SND", "SD": "SSD",
        "AL": "SAL", "AR": "SAR", "FL": "SFL", "GA": "SGA", "KY": "SKY", "LA": "SLA",
        "MS": "SMS", "NC": "SNC", "SC": "SSC", "TN": "STN", "VA": "SVA", "WV": "SWV",
        "AZ": "SAZ", "CO": "SCO", "ID": "SID", "MT": "SMT", "NV": "SNV", "NM": "SNM",
        "UT": "SUT", "WY": "SWY", "AK": "SAK", "CA": "SCA", "HI": "SHI", "OR": "SOR",
        "WA": "SWA", "TX": "STX", "OK": "SOK",
    }

    def _get_diesel_price_state(self, state: str) -> tuple:
        """State-level weekly retail diesel from EIA. Returns (price, source)."""
        api_key = os.environ.get("EIA_API_KEY", "")
        duoarea = self.STATE_TO_EIA_DUOAREA.get((state or "").upper(), "")
        if not api_key or not duoarea:
            return self.DEFAULT_DIESEL_PRICE, "estimated"

        url = (
            "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
            f"?api_key={api_key}&frequency=weekly&data[0]=value"
            f"&facets[product][]=EPD2D&facets[duoarea][]={duoarea}"
            "&sort[0][column]=period&sort[0][direction]=desc&length=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            records = payload["response"]["data"]
            if not records:
                return self.DEFAULT_DIESEL_PRICE, "estimated"
            return float(records[0]["value"]), "real"
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError):
            return self.DEFAULT_DIESEL_PRICE, "estimated"

    def _get_diesel_price_national(self) -> tuple:
        """National weekly retail diesel from EIA."""
        api_key = os.environ.get("EIA_API_KEY", "")
        if not api_key:
            return self.DEFAULT_DIESEL_PRICE, "estimated"

        url = (
            "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
            f"?api_key={api_key}&frequency=weekly&data[0]=value"
            "&facets[product][]=EPD2D&facets[duoarea][]=NUS"
            "&sort[0][column]=period&sort[0][direction]=desc&length=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            value = payload["response"]["data"][0]["value"]
            return float(value), "real"
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError):
            return self.DEFAULT_DIESEL_PRICE, "estimated"

    def _compute_history(self, *args, **kwargs) -> dict:
        # No real lane transaction data available without DAT/Truckstop integration.
        # Returning honest zero rather than fabricated numbers.
        no_data = {
            "load_count": 0,
            "avg_carrier_rate": None,
            "avg_margin_pct": None,
            "cover_time_hrs": None,
            "confidence": "NO_DATA",
            "data_source": "unavailable",
            "note": "Real lane history requires DAT One or TMS integration.",
        }
        return {"30d": no_data, "90d": no_data, "365d": no_data}

    def _compute_seasonality(self, equipment_type: str, month: int) -> dict:
        peak_months = self.PEAK_MONTHS.get(equipment_type, self.PEAK_MONTHS["dry_van"])
        adjacent_months = set()
        for m in peak_months:
            adjacent_months.add(12 if m == 1 else m - 1)
            adjacent_months.add(1 if m == 12 else m + 1)

        if month in peak_months:
            return {"signal": "PEAK", "yoy_delta_pct": 12.0}
        if month in adjacent_months:
            return {"signal": "NORMAL", "yoy_delta_pct": 3.0}
        return {"signal": "TROUGH", "yoy_delta_pct": -6.0}

    def _compute_confidence(self, data_points: int, capacity_signal: str, employment: dict | None = None, ppi: dict | None = None, fsc: dict | None = None) -> dict:
        # Honest confidence: each source scores only if it returned real data
        score_breakdown = {
            "atri_floor":     25,   # always real — static published data
            "bls_employment": 20 if (employment and employment.get("data_source") == "real") else 0,
            "bls_ppi_trend":  15 if (ppi and ppi.get("data_source") == "real") else 0,
            "eia_diesel":     20 if (fsc and fsc.get("data_source") == "real") else 0,
            "nws_weather":    10,   # always attempted; NWS is free and reliable
            "lane_history":    0,   # no real data without DAT
        }
        score = sum(score_breakdown.values())
        grade = "HIGH" if score >= 70 else ("MEDIUM" if score >= 45 else "LOW")
        return {
            "score": score,
            "grade": grade,
            "breakdown": score_breakdown,
            "ceiling_note": "Score capped at 90/100 — lane-level transaction history requires DAT.",
        }

    def _get_negotiation_coach(self, signals: dict) -> tuple:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._fallback_coach(signals), "rule_based_fallback"

        weather = signals.get("weather", {})
        weather_note = ""
        if weather.get("alert_count", 0) > 0:
            weather_note = f"\nWeather alerts on route: {weather['alert_count']} active ({weather['highest_severity']} severity, delay risk: {weather['delay_risk']})"

        cap = signals["capacity"]
        hc = cap.get("headcount_thousands")
        hc_trend = cap.get("headcount_trend", "FLAT")
        hc_yoy = cap.get("headcount_yoy_pct")
        mkt = signals["market"]

        employment_note = ""
        if hc:
            yoy_str = f", YoY {hc_yoy:+.1f}%" if hc_yoy is not None else ""
            employment_note = f"\nBLS truck drivers: {hc:.1f}k employed ({hc_trend}{yoy_str})"

        pmi_note = ""
        if mkt.get("pmi_value"):
            pmi_note = f"\nISM PMI: {mkt['pmi_value']} — {mkt.get('pmi_signal','')}"

        freight_note = ""
        if mkt.get("freight_volume_yoy_pct") is not None:
            freight_note = f"\nUS truck freight volume: {mkt['freight_volume_yoy_pct']:+.1f}% YoY"

        prompt = f"""You are an expert freight broker negotiation coach with 15+ years experience.
A broker is pricing a live load. All data below is from real government sources (BLS, EIA, FRED, NWS).

Lane: {signals['origin_city']}, {signals['origin_state']} → {signals['dest_city']}, {signals['dest_state']}
Equipment: {signals['equipment_type']}   Distance: {signals['distance_miles']} miles
ATRI carrier cost floor: ${signals['buy_rate']['atri_floor']}/mi (published 2024)
Market buy rate estimate: ${signals['buy_rate']['suggested']}/mi (ATRI floor + BLS capacity premium)
Broker's carrier pay entered: ${signals['carrier_pay_per_mile']}/mi
Delta vs market estimate: {mkt['delta_pct']:+.1f}%
BLS PPI rate trend: {signals['buy_rate'].get('ppi_trend_used','FLAT')} (YoY index: {mkt.get('ppi_yoy_delta_pct') or 'N/A'}%)
Capacity: {cap['signal']} — BLS employment {hc:.1f}k drivers{employment_note}
Season: {signals['seasonality']['signal']}{pmi_note}{freight_note}
EIA diesel: ${signals['fuel_surcharge']['diesel_price_per_gallon']}/gal ({signals['fuel_surcharge']['data_source']}){weather_note}

Write 4 sentences max. Be direct and specific — name the actual numbers. Tell the broker:
1. What the market is doing RIGHT NOW based on the real data above
2. Whether their carrier pay is strong/weak vs the ATRI floor
3. One specific thing to say on the call to the carrier or shipper
4. If weather alerts exist, how to use them as a pricing lever
No bullet points. Plain spoken language a broker uses on a real call."""

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip(), "ai"
        except Exception:
            return self._fallback_coach(signals), "rule_based_fallback"

    def _get_nat_gas_price(self) -> dict | None:
        """EIA Henry Hub natural gas weekly price — reefer refrigeration fuel cost signal.
        Series: NG.RNGWHHD.W  (Henry Hub Natural Gas Spot Price, weekly)
        Same EIA_API_KEY used for diesel. Returns None if key not set or request fails."""
        api_key = os.environ.get("EIA_API_KEY", "")
        if not api_key:
            return None
        url = (
            "https://api.eia.gov/v2/natural-gas/pri/fut/data/"
            f"?api_key={api_key}&frequency=weekly&data[0]=value"
            "&facets[series][]=RNGWHHD"
            "&sort[0][column]=period&sort[0][direction]=desc&length=4"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            records = payload["response"]["data"]
            if not records:
                return None
            latest = records[0]
            price = float(latest["value"])
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Context: ~$3/MMBtu is moderate, >$5 is high, <$2 is low
            signal = "HIGH" if price > 5 else ("LOW" if price < 2 else "MODERATE")
            return {
                "price_per_mmbtu": price,
                "period": latest["period"],
                "signal": signal,
                "fetched_at": fetched_at,
                "data_source": "real",
                "source": "EIA Henry Hub natural gas spot price",
                "note": "Reefer refrigeration units burn nat gas derivative diesel; high gas → reefer fuel cost pressure",
            }
        except Exception:
            return None

    def _fsc_fallback(self, distance_miles: float) -> dict:
        mpg = 6.5
        per_mile = round((self.DEFAULT_DIESEL_PRICE - 0.50) / mpg, 4)
        return {
            "per_mile": per_mile,
            "total": round(per_mile * distance_miles, 2),
            "diesel_price_per_gallon": self.DEFAULT_DIESEL_PRICE,
            "data_source": "estimated",
        }

    def _get_diesel_trend(self) -> list:
        """Last 12 weeks of US retail diesel from EIA. Returns [] if key not set or
        request fails — treat as optional enrichment only."""
        api_key = os.environ.get("EIA_API_KEY", "")
        if not api_key:
            return []
        url = (
            "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
            f"?api_key={api_key}&frequency=weekly&data[0]=value"
            "&facets[product][]=EPD2D&facets[duoarea][]=NUS"
            "&sort[0][column]=period&sort[0][direction]=desc&length=12"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            records = payload["response"]["data"]
            return [{"period": r["period"], "value": float(r["value"])} for r in reversed(records)]
        except Exception:
            return []

    def _fallback_coach(self, signals: dict) -> str:
        cap = signals["capacity"].get("signal", "BALANCED")
        tightness = signals["capacity"].get("market_tightness", "NEUTRAL")
        trend = signals["market"]["trend_30d"]
        delta = signals["market"]["delta_pct"]
        floor = signals["buy_rate"].get("atri_floor", 2.27)
        carrier_pay = signals["carrier_pay_per_mile"] or 0

        if cap == "TIGHT":
            market_note = f"BLS employment shows a tight carrier market — driver headcount is shrinking. Carriers have leverage right now."
            action = "Quote your shipper at the High rate and hold firm — capacity is genuinely limited."
        elif cap == "LOOSE":
            market_note = f"BLS employment shows a loose market — 1,464k+ drivers available. Brokers have pricing power."
            action = "Negotiate the carrier rate toward the Low band — trucks are available and carriers need freight."
        else:
            market_note = f"BLS shows a neutral market — normal availability."
            action = "Use the Suggested rate for both sides."

        floor_note = ""
        if carrier_pay and carrier_pay < floor:
            floor_note = f" Warning: your carrier pay of ${carrier_pay:.2f}/mi is below the ATRI 2024 cost floor of ${floor:.2f}/mi — a carrier accepting this rate is losing money and may not perform."
        elif carrier_pay and delta < -10:
            floor_note = f" Your rate is {abs(delta):.0f}% below market estimate — you have negotiation room."

        trend_note = (
            "BLS PPI shows rates trending up — move quickly on capacity." if trend == "UP"
            else "BLS PPI shows rates softening — take your time shopping." if trend == "DOWN"
            else "Rate trend is flat per BLS PPI."
        )

        return f"{market_note} {action}{floor_note} {trend_note}"
