# SpotterAI — Product, Engineering & QA Audit

**Date:** July 9, 2026
**Scope:** Full application — Django backend (`route_planner`), all six API endpoints, client-side broker rate calculator, deployment/config, and the test suite.
**Method:** Read-only review. No code, data, or config was changed. The existing test suite was run in an isolated sandbox copy purely to verify pass/fail status and measure coverage; the working `db.sqlite3` was untouched (verified via checksum before/after).

This is a working audit meant to be acted on, not a final grade. Findings are ordered by what would most change how you prioritize next.

---

## 1. Product Assessment

SpotterAI is materially bigger than its own README describes. The README documents two things — the fuel-route optimizer and a broker rate calculator — but the codebase actually ships six live API endpoints: route optimization, lane-rate intelligence, a cross-broker lane-rate network, FMCSA carrier verification, NWS weather alerts, and a BLS market index. The rate-intelligence engine alone (`services/rate_intelligence.py`) pulls from six external government/market data sources (BLS, EIA, FRED, NWS, FMCSA, USDA) plus an optional Claude-powered negotiation coach. None of this is mentioned in the README, which still describes the rate calculator as "user-input estimates" — that description is now stale.

**What's real vs. estimated**, by feature:

| Feature | Data source | Status |
|---|---|---|
| Fuel route + DP optimizer | OSRM, Nominatim, SQLite fuel prices (EIA-calibrated weekly) | Real |
| Broker buy-rate suggestion | ATRI cost floor + BLS PPI/employment signals | Real, calibrated |
| Cross-broker lane rates | Broker-submitted, anonymous | Real once seeded; needs 5 logs on a lane to reach "exact" confidence tier |
| Market index (PPI, employment) | BLS API | Real, degrades to "unavailable" without a key |
| Freight volume / Cass Index | FRED API | Real, degrades gracefully without a key |
| Carrier verification | FMCSA API | Real, degrades to "unavailable" without a key |
| Weather alerts | NWS API | Real, no key required |
| Negotiation coach | Claude Haiku via Anthropic API | Real AI text when key present; rule-based fallback otherwise |
| Tolls | N/A | Flat hardcoded estimate (3.8¢/mi), as documented |

The degrade-gracefully pattern is consistent everywhere: every external service returns an explicit `data_source: "real" | "unavailable" | "estimated"` field rather than silently faking data, and the system stays fully functional with zero API keys configured. That's a good, honest product design choice and it's enforced by tests (`test_degrades_gracefully_with_no_network_and_no_keys`).

**Three product-level things worth deciding on:**

The README undersells the product by omission — a prospective user or reviewer reading it would not know rate intelligence, carrier verification, weather, or the lane-rate network exist. Worth refreshing before it's shown to anyone external.

The lane-rate network has a cold-start problem: a brand-new lane has no data until five brokers log a rate on it, and there's currently no seeding strategy in the code. Until then every lane falls back to the cost-model estimate — fine, but it means the network's flywheel value is invisible until organic volume builds up. Worth deciding whether to pre-seed a few high-traffic lanes.

Five marketing templates exist in the repo (`carriers.html`, `fleet.html`, `shippers.html`, `about.html`, `login.html`) but none are wired into `config/urls.py` and nothing in the nav links to them — they're currently dead code, unreachable from the live site. Either route them or remove them; right now they're a maintenance trap (someone will edit one and wonder why nothing changes).

---

## 2. Engineering / Architecture Review

**Architecture:** a Django monolith with a clean service-layer split — `views*.py` stay thin (parse request, call a service, map exceptions to status codes), and business logic lives in `services/`, each concern in its own module (routing, geocoding, optimization, fuel data, rate intelligence, weather, etc.), using frozen dataclasses for domain objects and a small custom exception hierarchy (`PlannerError` → `ValidationError`/`ExternalServiceError`/`RouteNotFoundError`/`FuelPlanError`) that maps cleanly to HTTP status codes and machine-readable error codes. This is a genuinely good pattern and it's only fully used by the original `optimize-route` endpoint — the four newer endpoints hand-roll their JSON error responses inline instead of raising typed exceptions. Extending the same exception pattern to them would remove a fair amount of repeated validation boilerplate.

**Security posture is better than average for a project this size.** `DEBUG` defaults off and requires an explicit env var to enable; `SECRET_KEY` is required (not defaulted) outside debug mode; HSTS, secure cookies, and SSL redirect auto-enable outside debug; the reverse-proxy header is configured correctly for Railway-style TLS termination; the admin-only `DELETE` endpoint on lane rates uses `hmac.compare_digest` (not `==`) and is hard-disabled (403) whenever `ADMIN_TOKEN` is unset rather than falling back to an open state. The git history shows this wasn't accidental — there's a commit explicitly titled "Fix all 6 findings from live black-box pentest," and a more recent one fixing a real bug where the in-memory duplicate-submission guard silently failed once gunicorn ran multiple worker processes (each worker had its own copy of the guard's memory, so duplicates slipped through on whichever worker didn't see the first submission — now fixed by moving the check to the database, which is shared). That's the kind of bug that only shows up under real multi-worker load, and it's good that it was caught and fixed rather than left.

**Issues found**, ranked by what would bite first:

| Severity | Finding |
|---|---|
| Medium | `requirements.txt` pins `Django==6.0.4`, which requires Python ≥3.12 — but nothing in the repo (`runtime.txt`, `.python-version`, buildpack config) pins the interpreter version for the deploy platform. If Railway's default Python is below 3.12, the build fails outright at deploy time rather than at development time. This is exactly why I couldn't run the suite against 6.0.4 in this sandbox (only Python 3.10 was available) and had to substitute Django 5.2 to verify the tests — worth confirming the actual deploy target has 3.12 available. |
| Medium | Both abuse-prevention guards — the API rate limiter (`middleware.py`) and the per-IP daily lane-rate cap (`views_lane_rates.py`) — are in-process, per-gunicorn-worker state. This is called out honestly in code comments as an accepted tradeoff, but it means the *effective* limit is `workers × configured_limit` (currently 2×). Worth a product sign-off that a 2x-looser cap than configured is acceptable, since it's easy to lose track of that multiplier as worker count changes. |
| Low | `origin_city`/`dest_city` — user-controlled strings — are interpolated directly into the negotiation-coach LLM prompt with no delimiting or sanitization. Blast radius is small (the output is advisory text shown back to the same user, not used for anything privileged), but it is a textbook prompt-injection surface and would be trivial to harden with basic input sanitization or delimiters. |
| Low | `services/rate_intelligence.py` is a single 1,106-line file with 20+ private methods on one class. It's organized coherently (buy-rate → sell-rate → confidence → coach, in that order), but it's grown well past the size of every other file in `services/` and is a natural candidate to split into sub-modules mirroring the pattern already used elsewhere in the package. |
| Info | `db.sqlite3` is correctly excluded from git (`*.sqlite3` in `.gitignore`), so this isn't a real risk — noting it only because the source fuel-price CSV is checked into git twice (root `fuel-prices-for-be-assessment.csv` and `data/fuel-prices-for-be-assessment.csv`), which is harmless but worth deduplicating for clarity. |

**Code quality, generally:** consistent use of `from __future__ import annotations` and dataclasses for typed domain objects, docstrings that explain *why* (not just what) for every non-obvious tradeoff — the rate-limit worker-multiplier math, the DB-backed-vs-in-memory dedup rationale, the corridor-miles server-side clamp reasoning are all documented inline. That's a strong signal for whoever picks this up next.

---

## 3. Testing / QA Assessment

**Current state:** `route_planner/tests.py` — 468 lines, 25 tests, all passing. I ran the full suite in a sandboxed copy (Django 5.2 substituted for the pinned 6.0.4, since only Python 3.10 was available here — recommend re-running once on the actual 3.12 deploy target to confirm) and measured coverage with `coverage.py`, which isn't currently wired into the repo or `requirements.txt`.

**Overall: 64% statement coverage** (2,217 statements, 795 uncovered). That number hides a wide spread — the original core (fuel optimizer, geometry, fuel-data repository) is excellently tested; everything added since then is progressively less covered the newer it is.

| Area | Coverage | Note |
|---|---|---|
| `optimizer.py`, `geometry.py`, `fuel_data.py`, `maps.py`, `exceptions.py` | 95–100% | Core DP algorithm and geo-math — well tested, including edge cases like infeasible routes. |
| `models.py`, `middleware.py`, `lane_rate_stats.py`, `carrier_verification.py`, `fred.py`, `weather.py`, `bls_ppi.py` | 80–95% | Solid. |
| `planner.py` | 80% | Orchestration logic tested end-to-end via the API test, but individual validation branches (corridor clamp, negative starting range) aren't hit directly. |
| `geocoding.py` | 47% | `routing.py` | 59% | The actual HTTP-calling code paths and error branches (`HTTPError`, `URLError`, malformed payload) are untested — every existing test mocks these classes out at the planner level rather than exercising them directly. |
| `views.py`, `views_carrier_verification.py`, `views_lane_rates.py`, `views_market_index.py`, `views_rate_intelligence.py`, `views_weather.py` | 29–65% | Four of six endpoints (carrier-verification, market-index, rate-intelligence, weather-alerts) have no direct `Client().post(...)`-style endpoint test — existing tests call the underlying service class directly, so a bug in request parsing, field validation, or status-code mapping in the view itself could ship with the suite fully green. |
| `rate_intelligence.py` | 63% | The single most business-critical file — it produces the numbers brokers act on — and it's the least tested relative to its size. Covered: `_compute_buy_rate`, `_blend_with_network`, the overall degrade-gracefully path. Uncovered: `_compute_consensus`, `_compute_equipment_demand`, `_compute_market`, `_compute_capacity`, `_compute_fuel_surcharge`, `_compute_history`, `_compute_confidence`, `_get_negotiation_coach`/`_fallback_coach`, and the EIA diesel-price/caching helpers. |
| `city_lookup.py`, `usda_rates.py`, all three management commands (`load_fuel_prices`, `refresh_fuel_prices`, `generate_city_lookup`) | 0% | Completely untested. The three management commands run unattended on every single deploy boot (`deploy_start.sh`) and directly determine what data the optimizer and price calibration operate on — a silent regression here degrades every downstream feature with no test to catch it before production. |
| Client-side JS in `rates.html` (~1,200 lines, 30+ functions, including `computeRateCard` at ~240 lines — the function that actually produces the rate-card numbers shown to users) | 0% | No JS test runner exists in the repo at all. |

**Risk-prioritized test plan** — what I'd write next, in order:

*P0 — currently blind on business-critical logic:*
Table-driven unit tests for the uncovered `rate_intelligence.py` compute methods (`_compute_market`, `_compute_capacity`, `_compute_fuel_surcharge`, `_compute_confidence`, `_compute_consensus`, `_compute_equipment_demand`), each with known inputs and hand-checked expected outputs, the same style already used for `FuelOptimizer`. Tests for the three management commands, since they run unattended on every deploy and a regression there is invisible until stations or prices look wrong in production. And a way to verify `computeRateCard` in `rates.html` — either a small Node/jsdom smoke test, or an integration test asserting its output stays numerically consistent with the server-side `_compute_buy_rate`/`_compute_sell_rate`, since right now nothing enforces the two stay in sync.

*P1 — endpoint-level correctness:*
Direct `Client().post/get(...)` tests for the four under-tested view endpoints, covering missing fields, malformed JSON, and actual returned status codes rather than just the service layer underneath them. Error-branch tests for `RouteClient.get_route` and `NominatimGeocoder` (`HTTPError`, `URLError`, timeout, empty/malformed response, "no route found") — right now only the happy path is exercised, always through a mock.

*P2 — hardening / regression prevention:*
`RoutePlanService.plan` validation branches specifically (corridor > 100 clamp, non-positive mpg, starting-range exceeding max-range, same-origin/destination rejection). A concurrency-style regression test for the DB-backed dedup guard in `views_lane_rates.py` — this is the exact class of bug the July 8 commit fixed, and a regression test would stop it from silently reappearing if the guard logic changes again. Tests for the admin `DELETE` moderation endpoint: token comparison, disabled-when-unset behavior, and the "narrow by exact rate" filter.

*P3 — nice to have:*
`city_lookup.py`'s `normalize_city` edge cases ("St." vs "Saint", ampersands), and `usda_rates.py`, currently the only fully-untested external-data service.

**Process recommendation:** add `coverage` to `requirements.txt` (or a dev-only requirements file) and wire `coverage report --fail-under=X` into whatever runs before deploy — right now coverage isn't measured anywhere in the repo, and I had to install the tool ad hoc to produce the numbers above.

---

## Summary — top 5 things to act on first

1. Write tests for the `rate_intelligence.py` compute methods and the three unattended management commands — this is where a real bug would currently ship completely undetected, and it's the code that sets prices brokers act on.
2. Confirm the actual deploy target has Python ≥3.12 available for Django 6.0.4, and pin the interpreter version explicitly (`runtime.txt` or equivalent) so a platform mismatch fails at review time, not deploy time.
3. Add direct endpoint tests (`Client().post/get`) for the four newer API views — carrier-verification, market-index, rate-intelligence, weather-alerts — currently only their service layer is tested.
4. Refresh the README to reflect what the product actually does now (six live endpoints, cross-broker lane-rate network, AI negotiation coach) — it currently describes a much smaller product.
5. Either wire up or delete the five orphaned marketing templates (`carriers.html`, `fleet.html`, `shippers.html`, `about.html`, `login.html`) — decide intentionally rather than leaving them as unreachable dead code.
