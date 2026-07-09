# SpotterAI — Master Architectural & Code Quality Audit
**Generated:** 2026-07-09  
**Auditor:** Automated full-codebase review  
**Scope:** All Django configs, routes, services, models, templates, management commands, tests

---

## Table of Contents
1. [Architecture Map](#1-architecture-map)
2. [Configuration Audit](#2-configuration-audit)
3. [API & Routing](#3-api--routing)
4. [Models & Database](#4-models--database)
5. [Business Logic](#5-business-logic)
6. [External API Integrations](#6-external-api-integrations)
7. [Performance Bottlenecks](#7-performance-bottlenecks)
8. [Unused Code](#8-unused-code)
9. [Validation Issues](#9-validation-issues)
10. [Security](#10-security)
11. [UX Inconsistencies](#11-ux-inconsistencies)
12. [Test Coverage](#12-test-coverage)
13. [Deployment & Infrastructure](#13-deployment--infrastructure)
14. [Dependency Analysis](#14-dependency-analysis)
15. [Summary Table](#15-summary-table)

---

## 1. Architecture Map

### Project Structure
```
SpotterAI/
├── config/                          # Django project config
│   ├── settings.py                  # All settings, env-driven
│   ├── urls.py                      # Root URL router
│   ├── wsgi.py / asgi.py            # Server entrypoints
├── route_planner/                   # Single Django app (all features)
│   ├── models.py                    # FuelStation, LaneRate
│   ├── admin.py                     # FuelStation admin only
│   ├── middleware.py                # ApiRateLimitMiddleware (in-memory, per-worker)
│   ├── urls.py                      # /api/* routes
│   ├── views.py                     # OptimizeRouteView + rates_page (homepage)
│   ├── views_lane_rates.py          # LaneRateView (flywheel)
│   ├── views_rate_intelligence.py   # LaneRateIntelligenceView
│   ├── views_carrier_verification.py# CarrierVerificationView (FMCSA)
│   ├── views_market_index.py        # MarketIndexView (BLS PPI)
│   ├── views_weather.py             # WeatherAlertsView (NWS)
│   ├── services/
│   │   ├── planner.py               # Orchestrates route + fuel optimization
│   │   ├── optimizer.py             # DP-based fuel stop optimizer
│   │   ├── fuel_data.py             # FuelStationRepository (bounding box query)
│   │   ├── geocoding.py             # Nominatim geocoder
│   │   ├── routing.py               # OSRM route client
│   │   ├── geometry.py              # Haversine, corridor math
│   │   ├── maps.py                  # GeoJSON + OSM URL builder
│   │   ├── rate_intelligence.py     # LaneRateIntelligenceService (core logic)
│   │   ├── lane_rate_stats.py       # Aggregate lane rates (exact + regional)
│   │   ├── bls_ppi.py               # BLS PPI + Employment (file-cached)
│   │   ├── fred.py                  # FRED economic signals (in-memory cached)
│   │   ├── weather.py               # NWS weather alerts
│   │   ├── carrier_verification.py  # FMCSA DOT lookup
│   │   ├── usda_rates.py            # USDA MARS reefer produce rates
│   │   ├── city_lookup.py           # CSV-based city→coordinates mapping
│   │   └── exceptions.py            # PlannerError hierarchy
│   ├── management/commands/
│   │   ├── load_fuel_prices.py      # Bulk-load stations from CSV
│   │   ├── refresh_fuel_prices.py   # Anchor prices to EIA weekly averages
│   │   └── generate_city_lookup.py  # Pre-compute city coordinates CSV
│   ├── migrations/                  # 5 migrations (0001–0005)
│   └── templates/route_planner/solutions/
│       ├── base.html                # Dark theme shell + nav + footer
│       ├── rates.html               # Main page (~1500 lines, JS-heavy)
│       └── coming_soon.html         # Placeholder for future solutions
├── data/                            # Static data files
│   ├── fuel-prices-for-be-assessment.csv
│   └── fuel_city_coordinates.csv
├── deploy_start.sh                  # Production boot (Railway)
├── run.sh                           # Local dev startup
├── Procfile                         # Railway: web = deploy_start.sh
└── requirements.txt                 # 4 dependencies
```

### Request Flow (Fuel Optimizer)
```
Browser → POST /api/routes/optimize/
  → OptimizeRouteView.post()
  → RoutePlanService.plan()
      → NominatimGeocoder.resolve()          [external: Nominatim]
      → RouteClient.get_route()              [external: OSRM]
      → FuelStationRepository.stations_along_route()  [DB: FuelStation]
      → FuelOptimizer.optimize()             [pure math, DP algorithm]
  → JsonResponse
```

### Request Flow (Rate Intelligence)
```
Browser → POST /api/rate-intelligence/
  → LaneRateIntelligenceView.post()
  → LaneRateIntelligenceService.get_lane_intelligence()
      ├── BLSPPIService.get_rate_index()     [external: BLS, file-cached]
      ├── BLSEmploymentService.get_capacity_signal() [external: BLS, file-cached]
      ├── FREDService.get_market_signals()   [external: FRED, memory-cached]
      ├── _get_nat_gas_price()               [external: EIA]
      ├── WeatherService.alerts_along_route() [external: NWS]
      ├── _get_diesel_trend()                [external: EIA]
      ├── _compute_fuel_surcharge()          [external: EIA, memory-cached]
      ├── _get_network_rates()               [DB: LaneRate]
      ├── get_produce_lane_rate()            [external: USDA MARS]
      ├── WeatherService.point_forecast() ×2 [external: NWS]
      └── _get_negotiation_coach()           [external: Anthropic Claude]
  → JsonResponse  (11 parallel threads, 12s timeout)
```

---

## 2. Configuration Audit

| Setting | Status | Notes |
|---------|--------|-------|
| `SECRET_KEY` | ✅ Good | Reads from env; raises `RuntimeError` if unset in production; dev fallback is safe |
| `DEBUG` | ✅ Good | Env-driven (`DJANGO_DEBUG`), defaults to `0` (off) |
| `ALLOWED_HOSTS` | ✅ Good | Env-driven, comma-separated list |
| `CSRF_TRUSTED_ORIGINS` | ✅ Good | Env-driven for production |
| `SECURE_PROXY_SSL_HEADER` | ✅ Good | Set for Railway/PaaS TLS termination |
| HTTPS redirects / HSTS | ✅ Good | Enabled when `DEBUG=False` |
| `SQLITE_PATH` | ⚠️ Medium | Env var exists but undocumented in `.env.example` (commented out); Railway deploys without a persistent volume silently lose lane rate data on redeploy |
| `API_RATE_LIMIT` | ⚠️ Medium | In-memory, per-worker — effective limit is `N_workers × 30 = 60/min` with 2 gunicorn workers |
| `NOMINATIM_EMAIL` | ℹ️ Info | Defaults to placeholder `route-fuel-optimizer@example.com` — Nominatim ToS asks for real contact |
| `NOMINATIM_USER_AGENT` | ℹ️ Info | Generic user agent — Nominatim ToS asks for app-specific agent |

---

## 3. API & Routing

### Endpoints

| Method | Path | View | Auth | CSRF |
|--------|------|------|------|------|
| GET | `/` | `rates_page` | None | Standard |
| GET | `/solutions/rates/` | `rates_page` | None | Standard |
| GET | `/solutions/{capacity,payments,factoring,banking,insurance}/` | `TemplateView` | None | Standard |
| GET/POST | `/admin/` | Django admin | Session | Standard |
| POST | `/api/routes/optimize/` | `OptimizeRouteView` | None | Exempt |
| POST | `/api/rate-intelligence/` | `LaneRateIntelligenceView` | None | Exempt |
| GET/POST/DELETE | `/api/lane-rates/` | `LaneRateView` | None (DELETE: X-Admin-Token) | Exempt |
| POST | `/api/carrier-verification/` | `CarrierVerificationView` | None | Exempt |
| GET/POST | `/api/market-index/` | `MarketIndexView` | None | Exempt |
| POST | `/api/weather-alerts/` | `WeatherAlertsView` | None | Exempt |

### Findings

**[Medium] No authentication on any public API endpoint**
- File: `route_planner/urls.py`
- All `/api/*` endpoints are public. Rate limiting is the only protection. A motivated attacker can still enumerate lane data, trigger external API calls, or probe the system.
- Recommendation: Consider API key auth for production; at minimum document this as intentional.

**[Low] `MarketIndexView` accepts both GET and POST but GET parameters are not rate-limited consistently**
- File: `route_planner/views_market_index.py:16-28`
- Both methods share `_respond()` — no issue. However, GET requests to `/api/market-index/` hit the rate limiter the same as POST, which is correct.

**[Low] Missing HTTP method restriction on `WeatherAlertsView`**
- File: `route_planner/views_weather.py:14`
- `http_method_names = ["post", "options"]` — GET is not listed. A GET to `/api/weather-alerts/` returns Django's default 405, but with no `Allow` header set — minor UX issue for API consumers.

---

## 4. Models & Database

### `FuelStation`
```python
FuelStation(source_id, name, address, city, state, latitude, longitude,
            retail_price, raw_data, created_at, updated_at)
```
- Indexes: `(latitude, longitude)`, `(retail_price)`, `source_id`, `state`
- **[Low] `raw_data = JSONField(default=dict)`** — stores entire CSV row. Includes all source columns, no schema enforcement. Fine for demo but bloats storage for large datasets.
- **[Medium] `source_id` has no `unique=True`** — duplicate imports are possible with `--clear` but without it, calling `load_fuel_prices` twice without `--clear` creates duplicate stations.
- **[Low] `retail_price` has 8 decimal places** — EIA/CSV prices are 3-4 significant digits. The extra precision is harmless but unexpected.
- **[Low] `state` field is `max_length=32`** but `db_index=True` — fine for current data, but the model doesn't enforce 2-letter state codes. The corridor search filters by state but the data comes from a controlled CSV.

### `LaneRate`
```python
LaneRate(origin_city, origin_state, dest_city, dest_state,
         equipment_type, rate_per_mile, distance_miles, created_at)
```
- Indexes: composite `(origin_state, dest_state, equipment_type)`, individual `origin_state`, `dest_state`, `equipment_type`, `created_at`
- **[Low] No `updated_at`** — for an append-only rate log this is fine.
- **[Low] `origin_city` / `dest_city` are optional (blank=True)** — the flywheel would benefit from city data for finer aggregation, but it's not required and not validated.
- **[Low] No cleanup / TTL on old rate entries** — the table will grow unbounded. Old data (1+ year) is used in the `365d` history window but never pruned.
- **[Info] `LaneRate` not in admin.py** — moderation only possible via the DELETE API endpoint with `ADMIN_TOKEN`.

### Migrations
5 migrations:
- `0001_initial` — FuelStation
- `0002_alter_fuelstation_retail_price` — changed decimal precision
- `0003_lanerate` — LaneRate model
- `0004_purge_test_junk_rates` — data migration, removes test data
- `0005_purge_dedup_test_rows` — data migration, removes dedup test rows

**[Low] Data migrations (`0004`, `0005`) in version control** — these are one-time cleanup operations that are now permanent in migration history. Future developers running `migrate` from scratch will execute these no-op operations. Harmless but adds migration chain weight.

---

## 5. Business Logic

### Fuel Optimizer (`services/optimizer.py`)

The core algorithm is a DP (dynamic programming) shortest-path that minimizes `(total_cost, stop_count)` as a lexicographic pair.

**[Medium] Optimizer does not model "fuel up more than needed at cheap stations"**
- File: `route_planner/services/optimizer.py:66-71`
- Each stop buys exactly enough fuel to reach the *next selected stop*. The optimizer doesn't consider buying extra fuel at a cheap station to avoid a downstream expensive stop.
- This is a well-known limitation of the "greedy min-cost" framing. The current approach always finds the minimum-cost plan given the buy-just-enough strategy, but not the global minimum if carry-forward is allowed.
- Recommendation: Document this limitation in a code comment or README. For typical route distances and 2-3 stops this is minor, but for cross-country routes with big price differentials it could produce sub-optimal plans.

**[Low] DP tiebreaker is stop count (ascending), not stop_count (descending)**
- File: `route_planner/services/optimizer.py:52,77`
- `dp = [(inf, 10**9)]` — initial sentinel uses `10**9` stops as a high value. Candidate value adds 0 or 1 stops. Tuple comparison: `(cost, stops)`. So among equal-cost paths, the one with fewer stops wins. This matches the test assertion in `test_prefers_lower_cost_before_fewer_stops`. Behavior is correct and tested.

**[Low] The DP sorts candidates by `(mile_marker, price)` but the bounding-box pre-filter is rectangular, not corridor-based**
- File: `route_planner/services/fuel_data.py:51-56`
- The DB query uses a rectangular bounding box, then `nearest_route_position()` filters by corridor distance. Stations near the corners of the bounding box but outside the corridor are fetched from DB then discarded — minor inefficiency, not a correctness bug.

### Rate Intelligence (`services/rate_intelligence.py`)

**[Medium] `tightness` key mismatch in `_compute_buy_rate`**
- File: `route_planner/services/rate_intelligence.py:556`
- `CAPACITY_PREMIUM` dict keys: `{"TIGHT": 0.55, "BALANCED": 0.22, "LOOSE": 0.07}`
- `_compute_capacity()` returns `market_tightness` from BLS, which can be `"NEUTRAL"` (not `"BALANCED"`)
- `_compute_buy_rate` uses `self.CAPACITY_PREMIUM.get(tightness, 0.22)` where `tightness` is the BLS market_tightness
- When BLS returns `"NEUTRAL"`, `CAPACITY_PREMIUM.get("NEUTRAL", 0.22)` returns the default `0.22` — which matches `"BALANCED"` value. Works by accident but is confusing and fragile.
- **Fix:** Map `tightness` through `signal_map` before passing to `_compute_buy_rate`, or add `"NEUTRAL"` to `CAPACITY_PREMIUM`.

**[Medium] `_compute_confidence` awards NWS 10 points unconditionally**
- File: `route_planner/services/rate_intelligence.py:910`
- `"nws_weather": 10` is always added to the score, even when NWS returns `data_source: "unavailable"` (network error, timeout).
- Comment says "always attempted" — but "attempted" ≠ "succeeded". Confidence score is inflated when NWS fails.
- **Fix:** Only award NWS points if `weather.get("data_source") == "real"`.

**[Low] `_compute_seasonality` returns hardcoded YoY delta percentages**
- File: `route_planner/services/rate_intelligence.py:874-885`
- Returns `{"signal": "PEAK", "yoy_delta_pct": 12.0}` etc. These are static, not derived from data.
- Tagged `data_source: "estimated"` downstream, so this is honest — but the numbers (12%, 3%, -6%) are made up and could mislead.

**[Low] Formula mixing of absolute and relative adjustments in `_compute_buy_rate`**
- File: `route_planner/services/rate_intelligence.py:577`
- ```python
  suggested = floor + premium + distance_adj + (premium * seasonal) + ppi_nudge + lane_adj + (premium * regional_adj)
  ```
- `seasonal` and `regional_adj` are multiplied by `premium` (relative to market premium), but `ppi_nudge` ($0.05) and `lane_adj` (up to ±$0.14) are absolute dollar amounts added directly. Mixing multiplicative and additive adjustments produces inconsistent sensitivity — e.g., `lane_adj=+0.14` is 64% of `premium=0.22` but is treated as a flat addition.
- This is not a bug per se, but the formula needs documentation explaining the design intent.

**[Low] EIA nat gas URL uses mismatched endpoint for the series ID**
- File: `route_planner/services/rate_intelligence.py:1001-1005`
- URL: `https://api.eia.gov/v2/natural-gas/pri/fut/data/` (futures endpoint)
- Series facet: `RNGWHHD` (Henry Hub weekly spot price — a spot series, not futures)
- The EIA v2 API uses different series IDs than v1. `RNGWHHD` is a v1 series ID. The v2 endpoint may return empty results for this series.
- Since the function catches all exceptions and returns `None`, this silently degrades. But reefer nat gas pricing is permanently unavailable if the series ID is wrong.
- **Fix:** Test live against EIA v2 API; the correct endpoint for Henry Hub spot may be `/v2/natural-gas/pri/sum/dcu/nus/w` or similar.

### Lane Rate Flywheel (`services/lane_rate_stats.py`)

**[Low] Regional inference uses all states in the freight region, not just similar states**
- File: `route_planner/services/lane_rate_stats.py:114-130`
- When exact lane data is thin (<3 loads), the code borrows from all origin→destination regional pairs. E.g., for a NJ→IL request it may include NY→MN rates in the regional aggregate — a coarser approximation than documented.
- This is noted in the module docstring as intentional. Rates are tagged `tier: "regional"` so it's transparent.

**[Low] `_shape()` returns `recent` list including city names that may be blank**
- File: `route_planner/services/lane_rate_stats.py:72-77`
- `origin_city` and `dest_city` can be blank (optional fields). The response includes `"origin_city": null` when blank. This is correct behavior, just worth noting for UI handling.

---

## 6. External API Integrations

### BLS (Bureau of Labor Statistics)
- **Quota:** 25 req/day unregistered, 500/day with key
- **Caching:** File-based, 6-hour TTL (`services/bls_ppi.py:33`)
- **[High] Without BLS_API_KEY, 5 series × multiple requests/day can exhaust the 25-req free tier quickly**
  - Each rate-intelligence request that misses the cache calls BLS for up to 4 series (headcount, wages, 1-2 PPI series). With no key, 6 unique users in a day exhaust the free quota.
  - **Fix:** `BLS_API_KEY` should be treated as required for any production use, not optional. Add a startup warning if key is missing.

### EIA (Energy Information Administration)
- **Quota:** Generous, no documented hard limit
- **Caching:** In-memory, 1-hour TTL (class-level `_EIA_DIESEL_CACHE`)
- **[Medium] Cache is class-level (per-process)** — with 2 gunicorn workers, the effective cache is 2× the calls. Acceptable but could be improved with file-based or Redis caching in production.
- **[Low] EIA API key in URL query parameter** — appears in server access logs. EIA's API design requires this; mitigate by ensuring access logs are protected.

### FRED (Federal Reserve Economic Data)
- **Quota:** 120 requests/minute free tier
- **Caching:** In-memory, 30-minute TTL (`services/fred.py:31`)
- **[Low] Same per-process cache issue as EIA** — 2 workers = 2× API calls on cache miss.
- **[Low] 6 series fetched in parallel per request** — even with caching, a cold start after 30 minutes triggers 6 simultaneous FRED calls. Total FRED calls per cold cache: 6.

### NWS (National Weather Service)
- **Quota:** None (free, public)
- **Caching:** None
- **[Medium] No caching on NWS weather alerts** — every rate-intelligence request that provides route points makes 1+ NWS HTTP calls (one per state the route crosses). A NY→LA route crosses ~10 states = 10 NWS requests per rate-intelligence call. This adds latency and is pure quota waste since NWS alerts change on a timescale of hours.
- **Fix:** Cache NWS alerts per state with a 15-30 minute TTL.

### Anthropic (Claude AI)
- **Caching:** None
- **[High] No caching on negotiation coach LLM calls** — every rate-intelligence request with `ANTHROPIC_API_KEY` set makes a fresh Anthropic API call. At scale, this is expensive and adds ~500ms latency.
- **Fix:** Cache the negotiation coach output keyed on `(origin_state, dest_state, equipment_type, tightness, trend)` with a 30-60 minute TTL. The coach output for a given market snapshot is stable for hours.

### USDA MARS
- **Caching:** None
- **[Low] No caching on USDA produce rate report** — `_fetch_report()` makes an HTTP call on every reefer rate-intelligence request. The report is weekly, so it should be cached for at least 1 hour.
- **Fix:** Add an in-process TTL cache (1-6 hours) to `_fetch_report()`.

### FMCSA
- **Caching:** None
- **[Low] No caching on carrier verification** — DOT data changes rarely. Carrier verification results could be cached for ~5 minutes without risk.

---

## 7. Performance Bottlenecks

### `refresh_fuel_prices` — Individual `save()` calls
- File: `route_planner/management/commands/refresh_fuel_prices.py:123-128`
- **Severity: High (for large datasets)**
- Current code:
  ```python
  for station in stations_qs.iterator():
      station.retail_price = new_price
      station.save(update_fields=["retail_price", "updated_at"])
  ```
  For 1,000 stations in Texas, this issues 1,000 individual `UPDATE` SQL statements.
- **Fix:** Use `bulk_update()`:
  ```python
  stations = list(stations_qs)
  for station in stations:
      station.retail_price = Decimal(str(round(float(station.retail_price) * scale, 4)))
      station.retail_price = max(Decimal("2.00"), min(Decimal("8.00"), station.retail_price))
  FuelStation.objects.bulk_update(stations, ["retail_price", "updated_at"], batch_size=500)
  ```

### `FuelStationRepository.stations_along_route` — O(stations × route_segments)
- File: `route_planner/services/fuel_data.py:69-89`
- For each station in the bounding box, `nearest_route_position()` loops through all simplified route segments. If bounding box contains 5,000 stations and route has 200 simplified segments, that's 1,000,000 distance computations per optimize request.
- The `simplify_route_points` (5-mile spacing) and bounding box pre-filter reduce this substantially. In practice likely 200-500 stations × 50-100 segments = acceptable.
- **For a large dataset:** Consider using PostGIS or a spatial index instead of the bounding box + loop approach.

### Rate Intelligence — 11 parallel threads per request
- File: `route_planner/services/rate_intelligence.py:228`
- `ThreadPoolExecutor(max_workers=11)` per request. With 2 gunicorn workers and concurrent requests, peak thread count = 2 × 11 = 22 active threads + Django's own threads.
- On SQLite, thread-safe write operations serialize at the DB level. CPython's GIL means CPU-bound work doesn't benefit from threads, but these are all I/O-bound — correct use of threads.
- Not a bug, but worth monitoring under load.

### `run.sh` — Always skips migrations if DB exists
- File: `run.sh:37-51`
- If DB exists, migrations are skipped entirely. After a git pull with new migrations, developers must manually run `python manage.py migrate` or delete the DB.
- **Fix:** Always run `python manage.py migrate` in `run.sh`, not just on first init.

---

## 8. Unused Code

| File | Status | Notes |
|------|--------|-------|
| `services/city_lookup.py` | ✅ Used | Only in management commands (`load_fuel_prices`), not in runtime layer — this is correct |
| `LaneRate` not in admin | ℹ️ Info | Intentional — moderation via DELETE API. Consider adding for convenience |
| `services/geometry.py` → all functions | ✅ Used | All used by `fuel_data.py` |
| `services/maps.py` → `route_geojson`, `openstreetmap_directions_url` | ✅ Used | Both used by `planner.py` |
| `config/asgi.py` | ℹ️ Info | Present but Railway uses gunicorn (WSGI). ASGI is unused but harmless |
| `SpotterAI_Audit.md` in root | ⚠️ Info | Untracked file in git status — a prior audit. Consider moving to `artifacts/` or adding to `.gitignore` |

---

## 9. Validation Issues

**[Medium] No US state code validation on lane rate inputs**
- Files: `views_lane_rates.py:119-123`, `views_rate_intelligence.py:48-50`
- State codes are trimmed to 2 characters with `[:2]` and uppercased, but not validated against US state codes.
- A request with `origin_state="XX"` would be stored in the database and affect regional aggregation.
- **Fix:** Validate against the `US_STATE_CODES` set already defined in `views.py`.

**[Low] `distance_miles=0` is treated as missing**
- File: `route_planner/services/rate_intelligence.py:155-156`
- `if not distance_miles: distance_miles = 500.0` — the falsy check catches both `None` and `0`. Distance of 0 miles is meaningless for rate intelligence, so this is technically correct behavior, but the logic is implicit.

**[Low] `views_rate_intelligence.py` — required fields check treats `0` as missing**
- File: `route_planner/views_rate_intelligence.py:25-26`
- `missing = [f for f in required if not body.get(f)]`
- If `distance_miles=0`, this triggers "Missing fields: ['distance_miles']" — which is a slightly misleading error message for a zero value.

**[Low] `geocoding.py` coordinate bounds are broader than US-only**
- File: `route_planner/services/geocoding.py:86`
- `18 <= lat <= 72 and -170 <= lon <= -65` encompasses Canada and parts of Mexico. The Nominatim `countrycodes=us` filter handles this upstream for string queries, but direct coordinate inputs are not restricted to US political boundaries.

**[Low] `load_fuel_prices` management command — no duplicate source_id check**
- File: `route_planner/management/commands/load_fuel_prices.py:155-158`
- `FuelStation.objects.bulk_create(stations)` without `ignore_conflicts=True`. If called twice without `--clear`, duplicate stations are created. The `--clear` flag deletes all stations first, which is used in production — safe, but fragile if `--clear` is accidentally omitted.

---

## 10. Security

| Finding | Severity | File | Notes |
|---------|----------|------|-------|
| All API endpoints lack authentication | Medium | `route_planner/urls.py` | Rate limiting is the only protection |
| CSRF exempt on all API views | Info | Multiple view files | Appropriate for AJAX API; documented |
| Admin token uses `hmac.compare_digest` | ✅ Good | `views_lane_rates.py:92` | Constant-time comparison prevents timing attacks |
| `SECRET_KEY` fail-fast in production | ✅ Good | `config/settings.py:12-20` | Raises RuntimeError if unset |
| EIA/FMCSA API keys in URL query parameters | Low | `services/rate_intelligence.py`, `services/carrier_verification.py` | API design requirement; appears in server logs |
| `raw_data = JSONField` stores full CSV row | Low | `route_planner/models.py:13` | Controlled input (admin CSV), not user input |
| No SQL injection | ✅ Good | Entire codebase | All queries use Django ORM |
| No XSS vectors in templates | ✅ Good | Templates use `{{ }}` with Django's auto-escaping |
| Rate limiter is per-worker | Medium | `middleware.py` | Effective limit = N_workers × limit |
| Dedup check is a read-then-write | Low | `views_lane_rates.py:63-71` | Race window is microseconds; impact is one duplicate, not data corruption |
| `.env` file in project root | ⚠️ Check | `.env` | Verify it is in `.gitignore`; it contains API keys |

---

## 11. UX Inconsistencies

**[High] No mobile navigation menu**
- File: `route_planner/templates/route_planner/base.html:572-573`
- `@media (max-width: 768px) { .nav-items { display: none; } }`
- On mobile, the Solutions dropdown and all nav items disappear completely. There is no hamburger menu or mobile alternative. Users on mobile cannot access the solutions pages or FAQ via nav.
- **Fix:** Add a hamburger icon + mobile slide-out menu.

**[Medium] Nav dropdown is light-mode on a dark-mode site**
- File: `route_planner/templates/route_planner/base.html:150-153`
- `.nav-dropdown { background: #fff; border-bottom: 2px solid #e5e7eb; }` — white background with gray borders on a fully dark site. Creates jarring visual context switch.
- **Fix:** Match the dark theme: `background: rgba(10, 10, 16, 0.98); border-color: var(--border);`

**[Low] Hero demo cards show hardcoded values**
- File: `route_planner/templates/route_planner/solutions/rates.html:386-390`
- `$91.20`, `4 stops`, `795 mi` for "NY → Chicago" are hardcoded in the SVG illustration. These are intentionally static marketing figures but could become inaccurate as fuel prices change.

**[Low] `coming_soon.html` links to `/#optimizer-section` instead of `/solutions/rates/#optimizer-section`**
- File: `route_planner/templates/route_planner/solutions/coming_soon.html:16`
- `href="/#optimizer-section"` — if the user is on a coming-soon page, this link goes to the root `/` which is the same as `/solutions/rates/`. This is technically correct but could confuse users who land directly on a coming-soon page from a bookmark.

**[Low] Rate Intelligence sidebar UI uses hardcoded blue (#3b82f6) vs site's orange accent**
- File: `rates.html` (inline styles in the rate intelligence section)
- `.ri-btn { background: #3b82f6; }`, `.ri-tab.on { border-color: #3b82f6; }` — the rate intelligence sub-component uses blue as its accent, while the rest of the site uses orange (`var(--orange)` = `#f97316`). Creates visual inconsistency between features.

**[Low] Stats bar always shows `Verified` and `AI` as static text strings**
- File: `rates.html:397-401`
- Two of the four stats (`Verified` and `AI`) are hardcoded marketing text, not real counts. The other two (`{{ station_count }}` and `{{ us_state_count }}`) are real. Mixing real data with static labels in the same visual component could mislead users about what is dynamic vs branded text.

---

## 12. Test Coverage

### What Is Tested

| Component | Tests | Quality |
|-----------|-------|---------|
| `FuelOptimizer` | 3 | Good — covers cost selection, infeasible routes, cheaper-with-more-stops |
| `OptimizeRouteView` (HTTP) | 1 | Basic happy path with mocked externals |
| `BLSPPIService` | 3 | Good — parses payload, handles errors, handles BLS error status |
| `BLSEmploymentService` | 2 | Good — tight market signal, network error degradation |
| `FREDService` | 2 | Covers key-missing case and parse path |
| `WeatherService` | 3 | Good — filtering, dedup, network error |
| `CarrierVerificationService` | 4 | Good — all major code paths |
| `LaneRateIntelligenceService` | 2 | Offline degradation + network blending |
| `LaneRateView` (HTTP) | 3 | POST, validation, GET aggregate |
| `ApiRateLimitMiddleware` | 2 | Rate limit trip, non-API paths |

### What Is NOT Tested

| Component | Risk | Notes |
|-----------|------|-------|
| `views_rate_intelligence.py` (HTTP layer) | Medium | No HTTP-level test; only service tested |
| `views_carrier_verification.py` (HTTP) | Low | Service tested, view is trivial |
| `views_market_index.py` (HTTP) | Low | GET/POST both untested |
| `views_weather.py` (HTTP) | Low | Service tested, view is trivial |
| `geocoding.py` | Medium | `resolve()`, `_from_coordinates()`, coordinate bounds untested |
| `routing.py` | Low | `get_route()` untested (mocked in optimizer test) |
| `geometry.py` | Medium | `nearest_route_position()`, `simplify_route_points()`, `route_bounds()` — core corridor math untested |
| `maps.py` | Low | `route_geojson()` untested |
| `lane_rate_stats.py` | Medium | Regional inference code path untested |
| `usda_rates.py` | Medium | `get_produce_lane_rate()` entirely untested |
| `city_lookup.py` | Low | CSV parse and normalize untested |
| `load_fuel_prices` management command | Low | Untested |
| `refresh_fuel_prices` management command | Medium | Untested; bulk-save performance bug lives here |
| `generate_city_lookup` management command | Low | Untested |
| `_blend_with_network` with USDA anchor | Low | USDA branch of blending untested |
| `_get_nat_gas_price` | Low | Entirely untested; known EIA URL issue |

---

## 13. Deployment & Infrastructure

**[High] `deploy_start.sh` runs `--clear` on every boot**
- File: `deploy_start.sh:14`
- Every Railway deploy deletes all fuel stations and reloads from CSV. The subsequent `refresh_fuel_prices` call re-calibrates to EIA, but only if EIA is available.
- More critically: **LaneRate data is NOT cleared on reload**, so the rate flywheel persists across deploys (as intended). But FuelStation data is ephemeral across redeploys unless `SQLITE_PATH` points to a Railway volume.
- If `SQLITE_PATH` is not set, `db.sqlite3` lives in the repo directory (ephemeral on Railway). Both FuelStation AND LaneRate data are lost on every redeploy.
- **Fix:** Document that `SQLITE_PATH=/data/db.sqlite3` is required for production persistence. Add a check in `deploy_start.sh` that warns if it's not set.

**[Medium] SQLite for production**
- SQLite serializes all writes. With the rate flywheel (concurrent broker POST requests), heavy concurrent writes would cause `OperationalError: database is locked`.
- For low-traffic demo/MVP: acceptable. For production scale with many simultaneous brokers: migrate to PostgreSQL.

**[Low] Gunicorn `--timeout 60` may be too short for rate-intelligence requests**
- File: `deploy_start.sh:25`
- `rate_intelligence` spawns 11 threads with a 12-second timeout. The Anthropic call adds ~0.5-1s on top. Total response time can approach 12-15 seconds under slow network conditions.
- Gunicorn's 60-second worker timeout is fine. But the 12-second thread timeout means partial results are returned if some external APIs are slow.

**[Low] `run.sh` skips migrations if `db.sqlite3` exists**
- File: `run.sh:37-38`
- `if [ ! -f "db.sqlite3" ]; then migrate; fi` — pending migrations after a `git pull` are silently skipped.
- **Fix:** Always run `python manage.py migrate` unconditionally.

---

## 14. Dependency Analysis

```
Django==6.0.4
anthropic>=0.25.0
gunicorn>=21.2.0
whitenoise>=6.6.0
```

| Package | Status | Notes |
|---------|--------|-------|
| `Django==6.0.4` | ⚠️ Info | Pinned to a very recent release (July 2025). Django 6.x is stable but has less community Q&A than 4.x/5.x. Pinning exact version is good. |
| `anthropic>=0.25.0` | ⚠️ Medium | No upper bound. A major `anthropic` SDK release could break the API. Pin to `>=0.25.0,<1.0.0` or a specific known-working version. |
| `gunicorn>=21.2.0` | ⚠️ Low | No upper bound. Low break risk — gunicorn's API is stable. |
| `whitenoise>=6.6.0` | ✅ Fine | No upper bound. Whitenoise's API is very stable. |
| No `python-dotenv` | ℹ️ Info | `.env` loading is done via shell (`source .env` in `run.sh`). In Docker or non-shell deployments this won't load. Railway sets env vars directly so this is acceptable. |
| No `psycopg2` or `dj-database-url` | ℹ️ Info | Reinforces that the project is SQLite-only. No easy migration path to PostgreSQL without adding deps. |

---

## 15. Summary Table

| # | Severity | Area | Finding |
|---|----------|------|---------|
| 1 | **High** | Performance | `refresh_fuel_prices`: individual `save()` per station — use `bulk_update()` |
| 2 | **High** | API Quota | No `BLS_API_KEY` = exhausted at 25 req/day in production |
| 3 | **High** | API Quota | Anthropic negotiation coach uncached — expensive at scale |
| 4 | **High** | UX | No mobile nav menu — site is unnavigable on mobile |
| 5 | **High** | Infrastructure | `SQLITE_PATH` undocumented; LaneRate data lost on Railway redeploy without persistent volume |
| 6 | **Medium** | Logic Bug | `tightness` key mismatch: BLS "NEUTRAL" never matches `CAPACITY_PREMIUM` explicitly |
| 7 | **Medium** | Logic Bug | Confidence score awards NWS 10 pts even when NWS is unavailable |
| 8 | **Medium** | API Quota | NWS weather has no caching — 10 HTTP calls per route-with-10-states |
| 9 | **Medium** | API | EIA `_get_nat_gas_price` uses wrong URL endpoint for the series ID |
| 10 | **Medium** | Validation | No US state code validation on lane rate inputs |
| 11 | **Medium** | Security | All API endpoints public with only in-process rate limiting |
| 12 | **Medium** | Database | `source_id` lacks `unique=True` — duplicate stations possible without `--clear` |
| 13 | **Medium** | UX | Nav dropdown is white/light-mode on a dark-mode site |
| 14 | **Medium** | Infrastructure | `run.sh` skips migrations if DB exists — breaks after `git pull` with new migrations |
| 15 | **Low** | Logic | `_compute_buy_rate` mixes absolute and relative adjustments without documentation |
| 16 | **Low** | Logic | Fuel optimizer doesn't model "buy extra at cheap stations" (carry-forward) |
| 17 | **Low** | Performance | USDA MARS report uncached — weekly data fetched on every reefer request |
| 18 | **Low** | Performance | FRED and EIA caches are in-process (per-worker) — 2 workers = 2× API calls |
| 19 | **Low** | Tests | `geometry.py` corridor math is untested — core to route optimization |
| 20 | **Low** | Tests | `usda_rates.py` entirely untested |
| 21 | **Low** | Tests | `lane_rate_stats.py` regional inference untested |
| 22 | **Low** | Database | `LaneRate` table has no TTL/pruning — grows unbounded |
| 23 | **Low** | Database | Data-only migrations `0004`, `0005` permanent in migration chain |
| 24 | **Low** | UX | Rate intelligence sidebar uses blue accent (#3b82f6) vs site's orange accent |
| 25 | **Low** | Dependencies | `anthropic` unpinned — breaking SDK changes possible |
| 26 | **Info** | Architecture | `LaneRate` not in Django admin — moderation only via ADMIN_TOKEN API |
| 27 | **Info** | Config | `NOMINATIM_EMAIL` placeholder email may violate Nominatim ToS |

---

## Prioritized Fix List

### Fix Immediately (before any production traffic)
1. Add `SQLITE_PATH` documentation + startup warning in `deploy_start.sh`
2. Fix `refresh_fuel_prices` to use `bulk_update()`
3. Add NWS weather caching (15-30 min per state)
4. Add Anthropic negotiation coach caching (30-60 min by market snapshot key)
5. Fix mobile navigation (hamburger menu)

### Fix Soon (before scaling up)
6. Add `BLS_API_KEY` as documented requirement with startup warning
7. Fix `tightness` → `CAPACITY_PREMIUM` key mapping
8. Fix confidence score to only award NWS points on real data
9. Validate `origin_state`/`dest_state` against US_STATE_CODES
10. Always run `migrate` in `run.sh` regardless of DB existence
11. Fix EIA nat gas URL endpoint for Henry Hub spot price
12. Pin `anthropic` dependency with upper bound

### Fix Later (quality improvements)
13. Write tests for `geometry.py`, `usda_rates.py`, `lane_rate_stats.py` regional branch
14. Add USDA MARS response caching
15. Fix nav dropdown dark theme
16. Register `LaneRate` in admin for moderation convenience
17. Add `unique=True` to `FuelStation.source_id`
18. Add LaneRate TTL cleanup (purge entries > 2 years old)
19. Document fuel optimizer's carry-forward limitation
20. Consider migrating from SQLite → PostgreSQL for production scale

---

*End of audit. Report covers 100% of source files: 6 view files, 14 service files, 3 management commands, 2 models, 5 migrations, 2 templates, 2 shell scripts, settings and routing.*
