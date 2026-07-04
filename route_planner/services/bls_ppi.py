"""Real trucking market data via the BLS Public Data API.
No API key required. Two data sets:

PPI series — price index per equipment type:
  PCU484121484121  General freight trucking, long-distance TL (dry van proxy)
  PCU484122484122  Refrigerated goods trucking (reefer)
  PCU484210484210  Specialized freight trucking (flatbed proxy)

Employment series — real capacity proxy:
  CES4348400001  All employees, truck transportation (thousands, SA)
  CES4348400008  Average hourly earnings, truck transportation ($/hr)

Employment is the best free real-time capacity signal: rising headcount = more
trucks available = loose market. Falling headcount = tight market = rates up.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# File-based cache — survives server restarts, prevents hitting BLS daily limit
# (25 req/day unregistered, 500/day with a key). When SQLITE_PATH points at a
# persistent volume (Railway /data), the cache lives there too so it survives
# redeploys; otherwise it sits in the repo dir (fine locally).
import os as _os

if _os.environ.get("SQLITE_PATH"):
    _CACHE_DIR = Path(_os.environ["SQLITE_PATH"]).resolve().parent / ".bls_cache"
else:
    _CACHE_DIR = Path(__file__).resolve().parents[2] / ".bls_cache"
_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


def _cache_path(series_id: str) -> Path:
    _CACHE_DIR.mkdir(exist_ok=True)
    return _CACHE_DIR / f"{series_id}.json"


def _read_cache(series_id: str) -> list[dict] | None:
    p = _cache_path(series_id)
    if not p.exists():
        return None
    try:
        cached = json.loads(p.read_text())
        age = datetime.now(timezone.utc).timestamp() - cached.get("ts", 0)
        if age < _CACHE_TTL_SECONDS:
            return cached["data"]
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def _write_cache(series_id: str, data: list[dict]) -> None:
    try:
        _cache_path(series_id).write_text(json.dumps({
            "ts": datetime.now(timezone.utc).timestamp(),
            "data": data,
        }))
    except OSError:
        pass


# BLS series IDs (no key needed for public API)
SERIES = {
    "dry_van": "PCU484121484121",    # General freight trucking, long-distance TL
    "reefer":  "PCU484122484122",    # Refrigerated goods trucking
    "flatbed": "PCU484210484210",    # Specialized freight trucking (flatbed proxy)
}

EMPLOYMENT_SERIES = {
    "headcount": "CES4348400001",   # Total employees in truck transportation (thousands)
    "wages":     "CES4348400008",   # Average hourly earnings, truck drivers ($/hr)
}

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
TIMEOUT = 8


def _fetch_series(series_id: str, years: int = 2) -> list[dict]:
    """Fetch BLS monthly data — cache-first to stay within 25 req/day free limit."""
    cached = _read_cache(series_id)
    if cached is not None:
        return cached

    api_key = os.environ.get("BLS_API_KEY", "")
    current_year = datetime.now().year
    body: dict = {
        "seriesid": [series_id],
        "startyear": str(current_year - years),
        "endyear": str(current_year),
        "catalog": False,
        "calculations": False,
        "annualaverage": False,
    }
    if api_key:
        body["registrationkey"] = api_key   # 500 req/day with free key

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BLS_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SpotterAI/1.0 (freight analytics)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return []

    if data.get("status") != "REQUEST_SUCCEEDED":
        return []

    results = data.get("Results", {}).get("series", [])
    if not results:
        return []

    series_data = results[0].get("data", [])
    if series_data:
        _write_cache(series_id, series_data)
    return series_data


class BLSPPIService:
    """Trucking Producer Price Index — real market rate trend data."""

    # Baseline index values (approx 2023 averages) for normalizing % change
    BASELINE_INDEX = {
        "dry_van": 155.0,
        "reefer": 160.0,
        "flatbed": 148.0,
    }

    def get_rate_index(self, equipment_type: str) -> dict:
        """Return the latest PPI value, 12-month trend, and a rate adjustment
        multiplier that rate_intelligence can apply to its base rate."""
        series_id = SERIES.get(equipment_type, SERIES["dry_van"])
        raw = _fetch_series(series_id, years=2)

        if not raw:
            return self._unavailable(equipment_type)

        # BLS returns newest first; sort chronologically
        records = sorted(raw, key=lambda r: (r["year"], r["period"]))
        if not records:
            return self._unavailable(equipment_type)

        latest = records[-1]
        latest_value = float(latest["value"])
        latest_period = f"{latest['year']}-{latest['period'].replace('M', '')}"

        # 12-month comparison
        yoy_delta_pct = None
        yoy_record = None
        if len(records) >= 12:
            yoy_record = records[-12]
            yoy_value = float(yoy_record["value"])
            if yoy_value:
                yoy_delta_pct = round((latest_value - yoy_value) / yoy_value * 100, 2)

        # 3-month trend direction — records sorted ASC: [-1] latest, [-4] = 3 months ago
        trend = "FLAT"
        if len(records) >= 4:
            three_months_ago = float(records[-4]["value"])
            delta = latest_value - three_months_ago
            if delta > 1.0:
                trend = "UP"
            elif delta < -1.0:
                trend = "DOWN"

        # Adjustment multiplier: how far current index is from baseline
        baseline = self.BASELINE_INDEX.get(equipment_type, 155.0)
        rate_adjustment_multiplier = round(latest_value / baseline, 4) if baseline else 1.0

        # Build 12-month history for charting
        history = [
            {
                "period": f"{r['year']}-{r['period'].replace('M', '')}",
                "index": float(r["value"]),
            }
            for r in records[-12:]
        ]

        return {
            "series_id": series_id,
            "equipment_type": equipment_type,
            "latest_index": latest_value,
            "latest_period": latest_period,
            "yoy_delta_pct": yoy_delta_pct,
            "trend_3m": trend,
            "rate_adjustment_multiplier": rate_adjustment_multiplier,
            "history_12m": history,
            "data_source": "real",
            "source": "BLS Producer Price Index (bls.gov)",
        }

    def get_all_equipment_indices(self) -> dict:
        """Fetch PPI for all three equipment types in one call."""
        return {eq: self.get_rate_index(eq) for eq in SERIES}

    @staticmethod
    def _unavailable(equipment_type: str) -> dict:
        return {
            "equipment_type": equipment_type,
            "latest_index": None,
            "latest_period": None,
            "yoy_delta_pct": None,
            "trend_3m": "UNKNOWN",
            "rate_adjustment_multiplier": 1.0,
            "history_12m": [],
            "data_source": "unavailable",
            "source": "BLS PPI (unavailable)",
        }


class BLSEmploymentService:
    """Real trucking employment data — capacity signal.

    Rising headcount → more trucks available → loose market (lower rates).
    Falling headcount → driver shortage → tight market (higher rates).

    Series used:
      CES4348400001 — Total employees, truck transportation (thousands, SA)
      CES4348400008 — Average hourly earnings, truck transportation ($/hr)
    """

    # Approximate 2023 average baselines for YoY comparison
    HEADCOUNT_BASELINE = 1490.0   # thousands of employees (2023 avg)
    WAGES_BASELINE = 29.50        # $/hr (2023 avg)

    def get_capacity_signal(self) -> dict:
        """Return current employment level, trend, and a market tightness signal."""
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        headcount_raw = _fetch_series(EMPLOYMENT_SERIES["headcount"], years=2)
        wages_raw = _fetch_series(EMPLOYMENT_SERIES["wages"], years=1)

        if not headcount_raw:
            return self._unavailable(fetched_at)

        # BLS returns newest first; sort chronologically
        hc_records = sorted(headcount_raw, key=lambda r: (r["year"], r["period"]))
        latest_hc = hc_records[-1]
        headcount = float(latest_hc["value"])
        hc_period = f"{latest_hc['year']}-{latest_hc['period'].replace('M', '')}"

        # YoY headcount change
        hc_yoy_pct = None
        if len(hc_records) >= 12:
            yoy_hc = float(hc_records[-12]["value"])
            if yoy_hc:
                hc_yoy_pct = round((headcount - yoy_hc) / yoy_hc * 100, 2)

        # 3-month trend — records sorted ASC: [-1] latest, [-4] = 3 months ago
        hc_trend = "FLAT"
        if len(hc_records) >= 4:
            three_ago = float(hc_records[-4]["value"])
            delta = headcount - three_ago
            if delta > 5:
                hc_trend = "GROWING"
            elif delta < -5:
                hc_trend = "SHRINKING"

        # Latest wages
        wages = None
        wages_period = None
        if wages_raw:
            w_records = sorted(wages_raw, key=lambda r: (r["year"], r["period"]))
            latest_w = w_records[-1]
            wages = float(latest_w["value"])
            wages_period = f"{latest_w['year']}-{latest_w['period'].replace('M', '')}"

        # Market tightness signal:
        #   headcount vs baseline + trend → TIGHT / NEUTRAL / LOOSE
        tightness = "NEUTRAL"
        pct_vs_baseline = (headcount - self.HEADCOUNT_BASELINE) / self.HEADCOUNT_BASELINE * 100
        if pct_vs_baseline < -2 or hc_trend == "SHRINKING":
            tightness = "TIGHT"
        elif pct_vs_baseline > 2 and hc_trend == "GROWING":
            tightness = "LOOSE"

        # Capacity ratio multiplier (tight = higher rates, loose = lower)
        # Maps: TIGHT → 1.10, NEUTRAL → 1.0, LOOSE → 0.92
        capacity_multiplier = {"TIGHT": 1.10, "NEUTRAL": 1.0, "LOOSE": 0.92}.get(tightness, 1.0)

        return {
            "headcount_thousands": headcount,
            "headcount_period": hc_period,
            "headcount_yoy_pct": hc_yoy_pct,
            "headcount_trend": hc_trend,
            "avg_hourly_wages": wages,
            "wages_period": wages_period,
            "market_tightness": tightness,
            "capacity_multiplier": capacity_multiplier,
            "pct_vs_baseline": round(pct_vs_baseline, 2),
            "fetched_at": fetched_at,
            "data_source": "real",
            "source": "BLS Current Employment Statistics (bls.gov)",
        }

    @staticmethod
    def _unavailable(fetched_at: str) -> dict:
        return {
            "headcount_thousands": None,
            "market_tightness": "UNKNOWN",
            "capacity_multiplier": 1.0,
            "fetched_at": fetched_at,
            "data_source": "unavailable",
            "source": "BLS CES (unavailable)",
        }
