"""FRED (Federal Reserve Economic Data) — St. Louis Fed public API.
Free API key from fred.stlouisfed.org (5 min registration).
Set env var: FRED_API_KEY

Signals used for freight market context:
  NAPM              — ISM Manufacturing PMI (above 50 = expansion = more freight)
  TRFVOLUSM227NFWA  — US truck freight volume, ton-miles SA (actual freight moving)
  FRGSHPUSM649NCIS  — Cass Freight Index: Shipments (industry-standard demand benchmark)
  TRUCKD11          — ATA Truck Tonnage Index
  HOUST             — Housing starts (flatbed demand: construction)
  INDPRO            — Industrial production (flatbed demand: manufacturing)
  ISRATIO           — Inventories-to-sales ratio (dry van demand: restocking cycles)
"""
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT = 6


def _fetch(series_id: str, limit: int = 13) -> list[dict]:
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        return []
    url = (
        f"{FRED_BASE}?series_id={series_id}&api_key={api_key}"
        f"&sort_order=desc&limit={limit}&file_type=json"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "SpotterAI/1.0 (freight analytics)"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        obs = data.get("observations", [])
        # Filter out missing values (".")
        return [o for o in obs if o.get("value", ".") != "."]
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, KeyError):
        return []


class FREDService:
    """FRED economic signals for freight market context."""

    def get_market_signals(self) -> dict:
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        has_key = bool(os.environ.get("FRED_API_KEY", ""))

        if not has_key:
            return {
                "pmi": None,
                "freight_volume": None,
                "data_source": "unavailable",
                "reason": "FRED_API_KEY not set — free key at fred.stlouisfed.org",
                "fetched_at": fetched_at,
            }

        # Fetch all series in parallel — 7 sequential calls would be too slow
        with ThreadPoolExecutor(max_workers=7) as pool:
            f_pmi = pool.submit(self._get_pmi)
            f_freight = pool.submit(self._get_freight_volume)
            f_cass = pool.submit(self._get_trend_series, "FRGSHPUSM649NCIS", "Cass Freight Index (shipments)")
            f_tonnage = pool.submit(self._get_trend_series, "TRUCKD11", "ATA Truck Tonnage Index")
            f_housing = pool.submit(self._get_trend_series, "HOUST", "Housing starts (thousands)")
            f_indpro = pool.submit(self._get_trend_series, "INDPRO", "Industrial production index")
            f_isratio = pool.submit(self._get_trend_series, "ISRATIO", "Inventories-to-sales ratio")

            def safe(fut):
                try:
                    return fut.result(timeout=8)
                except Exception:
                    return None

            pmi = safe(f_pmi)
            freight = safe(f_freight)
            cass = safe(f_cass)
            tonnage = safe(f_tonnage)
            housing = safe(f_housing)
            indpro = safe(f_indpro)
            isratio = safe(f_isratio)

        return {
            "pmi": pmi,
            "freight_volume": freight,
            "cass_index": cass,
            "truck_tonnage": tonnage,
            "housing_starts": housing,
            "industrial_production": indpro,
            "inventories_ratio": isratio,
            "data_source": "real" if (pmi or freight or cass) else "unavailable",
            "source": "FRED — St. Louis Federal Reserve (fred.stlouisfed.org)",
            "fetched_at": fetched_at,
        }

    def _get_trend_series(self, series_id: str, label: str) -> dict | None:
        """Generic monthly series: latest value, YoY %, 3-month trend."""
        obs = _fetch(series_id, limit=13)
        if not obs:
            return None
        latest = obs[0]
        value = float(latest["value"])

        yoy_delta_pct = None
        if len(obs) >= 12:
            yoy_val = float(obs[11]["value"])
            if yoy_val:
                yoy_delta_pct = round((value - yoy_val) / yoy_val * 100, 2)

        trend = "FLAT"
        if len(obs) >= 3:
            three_ago = float(obs[2]["value"])
            delta = value - three_ago
            if delta > abs(value) * 0.01:
                trend = "UP"
            elif delta < -abs(value) * 0.01:
                trend = "DOWN"

        return {
            "value": value,
            "period": latest["date"][:7],
            "yoy_delta_pct": yoy_delta_pct,
            "trend_3m": trend,
            "label": label,
            "series": series_id,
        }

    def _get_pmi(self) -> dict | None:
        obs = _fetch("NAPM", limit=13)
        if not obs:
            return None
        latest = obs[0]
        value = float(latest["value"])
        # Build 12-month history (newest first → reverse for chart)
        history = [
            {"period": o["date"][:7], "value": float(o["value"])}
            for o in reversed(obs)
        ]
        # Signal
        if value >= 55:
            signal = "STRONG_EXPANSION"
            label = "Strong expansion — freight demand rising"
        elif value >= 50:
            signal = "EXPANSION"
            label = "Expanding — freight demand positive"
        elif value >= 48:
            signal = "CONTRACTION"
            label = "Contracting — freight demand softening"
        else:
            signal = "RECESSION"
            label = "Significant contraction — freight demand weak"

        yoy_delta = None
        if len(obs) >= 12:
            yoy_val = float(obs[11]["value"])
            yoy_delta = round(value - yoy_val, 1)

        return {
            "value": value,
            "period": latest["date"][:7],
            "signal": signal,
            "label": label,
            "yoy_delta_pts": yoy_delta,
            "history_12m": history,
            "series": "NAPM",
            "note": "ISM Manufacturing PMI — above 50 = expansion = more freight moving",
        }

    def _get_freight_volume(self) -> dict | None:
        obs = _fetch("TRFVOLUSM227NFWA", limit=13)
        if not obs:
            return None
        latest = obs[0]
        value = float(latest["value"])
        history = [
            {"period": o["date"][:7], "value": float(o["value"])}
            for o in reversed(obs)
        ]
        yoy_delta_pct = None
        if len(obs) >= 12:
            yoy_val = float(obs[11]["value"])
            if yoy_val:
                yoy_delta_pct = round((value - yoy_val) / yoy_val * 100, 2)

        trend = "FLAT"
        if len(obs) >= 3:
            three_ago = float(obs[2]["value"])
            delta = value - three_ago
            if delta > value * 0.01:
                trend = "UP"
            elif delta < -value * 0.01:
                trend = "DOWN"

        return {
            "value_million_ton_miles": value,
            "period": latest["date"][:7],
            "yoy_delta_pct": yoy_delta_pct,
            "trend_3m": trend,
            "history_12m": history,
            "series": "TRFVOLUSM227NFWA",
            "note": "US truck freight volume (ton-miles) — actual freight moving in the economy",
        }
