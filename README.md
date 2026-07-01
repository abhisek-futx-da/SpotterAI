# SpotterAI — Fuel Route Optimizer & Broker Rate Intelligence

A Django-based platform combining a **real fuel cost optimizer** (backend, data-driven) with a **broker lane rate intelligence tool** (frontend, pre-booking pricing). Built on top of a multi-page marketing site for Spotter.ai — a freight tech platform serving carriers, fleet operators, and shippers.

---

## What This System Actually Does

### ✅ Backend (Real Intelligence)

The Django API at `POST /api/routes/optimize/` does three genuine things:

| Step | What Happens | Data Source |
|---|---|---|
| **1. Geocoding** | Converts city/state strings to lat/lon | Nominatim (OpenStreetMap) — 1 call max |
| **2. Routing** | Fetches real road distance & geometry | OSRM (OpenStreetMap Routing Machine) — 1 call |
| **3. Fuel Optimization** | Finds cheapest stop sequence using DP | SQLite DB seeded from `fuel-prices-for-be-assessment.csv` |

The fuel optimizer uses a **Dynamic Programming algorithm** ($O(N^2)$) that finds the mathematically cheapest sequence of fuel stops given tank capacity, starting fuel level, MPG, and a corridor search radius.

### ⚠️ Frontend (Broker Rate Calculator — User-Input Estimates)

The `/solutions/rates/` page adds a **broker pricing layer** on top of the fuel plan. Everything beyond fuel cost is calculated client-side using user-entered defaults — not live market data:

| Field | Source |
|---|---|
| Fuel cost | ✅ Real — from backend optimizer |
| Route distance | ✅ Real — from OSRM |
| Driver pay, insurance, equipment, overhead | ⚠️ User input (defaults provided) |
| Shipper rate, carrier pay | ⚠️ User input |
| Tolls | ⚠️ Flat estimate (3.8¢/mi hardcoded) |
| Market benchmark rates | ❌ Not connected (no DAT/Truckstop integration) |

---

## Architecture

```
SpotterAI/
├── config/                          # Django project settings
│   ├── settings.py
│   └── urls.py                      # All page + API routes
│
├── route_planner/                   # Core Django app
│   ├── models.py                    # FuelStation model (SQLite)
│   ├── views.py                     # OptimizeRouteView (POST /api/routes/optimize/)
│   ├── urls.py                      # API URL routing
│   │
│   ├── services/                    # Business logic
│   │   ├── planner.py               # RoutePlanService — orchestrates full pipeline
│   │   ├── optimizer.py             # FuelOptimizer — DP algorithm
│   │   ├── fuel_data.py             # FuelStationRepository — DB queries
│   │   ├── routing.py               # RouteClient — OSRM integration
│   │   ├── geocoding.py             # NominatimGeocoder
│   │   ├── geometry.py              # Corridor math, bounding box, mile markers
│   │   ├── maps.py                  # GeoJSON builder, OSM directions URL
│   │   ├── city_lookup.py           # City → coordinate pre-computation
│   │   └── exceptions.py            # PlannerError, ValidationError, FuelPlanError
│   │
│   ├── management/commands/
│   │   ├── load_fuel_prices.py      # Import CSV → FuelStation table
│   │   └── generate_city_lookup.py  # Pre-compute city coordinates
│   │
│   └── templates/route_planner/
│       ├── base.html                # Shared layout, nav, CSS vars
│       ├── index.html               # Homepage
│       ├── carriers.html            # Carrier-facing page
│       ├── fleet.html               # Fleet operator page
│       ├── shippers.html            # Shipper-facing page
│       ├── about.html               # Company page
│       ├── login.html               # Login page
│       └── solutions/
│           ├── rates.html           # ⭐ Fuel optimizer + broker rate tool
│           ├── capacity.html
│           ├── payments.html
│           ├── factoring.html
│           ├── banking.html
│           └── insurance.html
│
├── data/
│   ├── fuel-prices-for-be-assessment.csv   # Source fuel price data (~2,400 stations)
│   └── fuel_city_coordinates.csv           # Pre-computed city coordinates
│
├── db.sqlite3                       # Pre-seeded database (3.5MB)
├── requirements.txt                 # Django==6.0.4 only
├── manage.py
└── run.sh                           # One-command setup & launch
```

---

## Pages & Routes

| URL | Page | Description |
|---|---|---|
| `/` | Homepage | Marketing landing page |
| `/carriers/` | Carriers | Owner-operator & carrier solutions |
| `/fleet/` | Fleet Operators | Fleet management solutions |
| `/shippers/` | Shippers | Shipper-facing solutions |
| `/about/` | About | Company page |
| `/login/` | Login | Auth page |
| `/solutions/rates/` | **Fuel Rate Intelligence** | ⭐ Live optimizer + broker rate tool |
| `/solutions/capacity/` | Route Capacity | Capacity intelligence |
| `/solutions/payments/` | SpotterPay | Payments solution |
| `/solutions/factoring/` | Early Pay Factoring | Factoring solution |
| `/solutions/banking/` | Fleet Banking | Banking solution |
| `/solutions/insurance/` | Insurance | Insurance solution |
| `POST /api/routes/optimize/` | Optimizer API | Core fuel optimization endpoint |
| `/admin/` | Django Admin | Database management |

---

## The Broker Rate Tool — `/solutions/rates/`

The main product page combines the fuel optimizer with a **three-column broker pricing interface**:

### Column 1 — 💼 Broker Spread
Shows the broker's profit on a load:
```
Shipper Rate       $1,590   ($2.00/mi)   ← what you charge shipper
FSC (pass-through)   $14.93              ← fuel surcharge, pass-through
Carrier Pay       −$1,240   ($1.56/mi)   ← what you pay carrier
─────────────────────────────────────────
Gross Profit         $350   ($0.44/mi)
Factoring (2.5%)    −$40                 ← Triumph/factoring fee
Net Profit           $310                ← take-home after fees
```

### Column 2 — 🧾 Shipper Invoice
Generates a line-item invoice preview:
```
Base Freight Rate   $1,590
Fuel Surcharge        $14.93
Detention (2h×$55)   $110     ← only shown if hours entered
TONU                 $150     ← only shown if entered
─────────────────────────────
Invoice Total       $1,865
Rate per mile        $2.35/mi
```

### Column 3 — 📊 Shipper Quote Tiers
Pre-booking rate guidance based on carrier all-in cost + margin:
```
Conservative   $1,339   $1.69/mi   ← 85% of target margin
Suggested      $1,428   $1.80/mi   ← 100% of target margin
Premium        $1,513   $1.91/mi   ← 120% of target margin
```

### Sidebar Inputs

**Broker Pricing (primary):**
- Shipper Rate ($/mi) — what you charge the shipper
- Carrier Pay ($/mi) — what you pay the carrier
- Deadhead %, Factoring %, FSC ($/gal), Margin %

**Accessorials:**
- Detention ($/hr + hours), TONU ($), Layover ($)

**Carrier Cost Detail** *(collapsible reference):*
- Driver ($/mi), Per Diem ($/day), Insurance ($/mi), Equipment ($/mi), Overhead ($/mi), Maintenance ($/mi), Permits ($/mi)

---

## Quick Start

### One-Command Setup (macOS/Linux)
```bash
./run.sh
```
Opens at **http://127.0.0.1:8000/**

> If port 8000 is in use, run manually on another port:
> ```bash
> source .venv/bin/activate
> python manage.py runserver 8080
> ```

### Manual Setup
```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .\.venv\Scripts\Activate.ps1  # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations (skip if db.sqlite3 already exists)
python manage.py migrate

# 4. Generate city coordinate lookup (skip if data/fuel_city_coordinates.csv exists)
python manage.py generate_city_lookup \
    data/fuel-prices-for-be-assessment.csv \
    data/fuel_city_coordinates.csv

# 5. Load fuel station data (skip if db.sqlite3 already seeded)
python manage.py load_fuel_prices \
    data/fuel-prices-for-be-assessment.csv \
    --city-lookup data/fuel_city_coordinates.csv \
    --clear

# 6. Run tests
python manage.py test

# 7. Start server
python manage.py runserver
```

---

## Running Tests

```bash
python manage.py test
```

4 unit tests covering core optimizer and service logic. All pass on a clean setup.

---

## API Reference

### `POST /api/routes/optimize/`

#### Request — Text Input
```json
{
  "start": "New York, NY",
  "finish": "Chicago, IL",
  "max_range_miles": 500,
  "starting_range_miles": 500,
  "mpg": 10,
  "corridor_miles": 25
}
```

#### Request — Coordinate Input (skips geocoding)
```json
{
  "start":  { "lat": 40.7128, "lon": -74.0060, "label": "New York, NY" },
  "finish": { "lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL" },
  "max_range_miles": 500,
  "starting_range_miles": 250,
  "mpg": 8,
  "corridor_miles": 30
}
```

#### Request Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `start` | `string` or `object` | Required | Origin — city/state string or `{lat, lon, label}` |
| `finish` | `string` or `object` | Required | Destination |
| `max_range_miles` | `number` | `500` | Full tank range in miles |
| `starting_range_miles` | `number` | `500` | Fuel on board at departure (miles of range) |
| `mpg` | `number` | `10` | Vehicle fuel efficiency (miles per gallon) |
| `corridor_miles` | `number` | `25` | Search radius off-route for stations (miles) |

#### Response Shape
```json
{
  "start":  { "label": "New York, NY", "lat": 40.7128, "lon": -74.0060 },
  "finish": { "label": "Chicago, IL",  "lat": 41.8781, "lon": -87.6298 },
  "route": {
    "distance_miles": 790.12,
    "duration_minutes": 742.5,
    "geometry_points": 240
  },
  "fuel_plan": {
    "max_range_miles": 500.0,
    "mpg": 10.0,
    "starting_range_miles": 500.0,
    "candidate_station_count": 84,
    "total_cost_usd": 91.19,
    "total_gallons_purchased": 29.8,
    "stops": [
      {
        "station_id": 1024,
        "name": "PILOT TRAVEL CENTER #280",
        "address": "4000 RED ROAD",
        "city": "Stonycreek",
        "state": "PA",
        "lat": 40.0125,
        "lon": -78.9211,
        "price_per_gallon": 3.059,
        "route_mile": 290.12,
        "distance_from_route_miles": 1.3,
        "gallons": 29.8,
        "leg_miles": 290.0,
        "cost_usd": 91.19
      }
    ]
  },
  "map": {
    "geojson": { "type": "FeatureCollection", "features": [ "..." ] },
    "openstreetmap_url": "https://www.openstreetmap.org/directions?...",
    "attribution": "Route data from OSRM/OpenStreetMap contributors."
  },
  "meta": {
    "external_calls": { "geocoding": 2, "routing": 1 },
    "assumptions": [
      "The vehicle starts with starting_range_miles of usable range.",
      "Fuel stop selection minimizes total fuel spend using the loaded fuel prices.",
      "Fuel purchases are sized to reach the next selected stop or destination.",
      "Only stations within corridor_miles of the route are considered."
    ]
  }
}
```

#### Error Responses

| HTTP | `code` | Cause |
|---|---|---|
| `400` | `VALIDATION_ERROR` | Missing required fields or invalid numeric values |
| `422` | `GEOCODING_ERROR` | Location string could not be resolved |
| `422` | `ROUTING_ERROR` | OSRM could not find a route |
| `422` | `FUEL_PLAN_ERROR` | No feasible fuel plan (try wider corridor or more stations) |

---

## Optimization Algorithm

### 1. Station Filtering
Stations are pre-filtered using a **geographic bounding box** derived from the route geometry + `corridor_miles`. Each passing station is then checked for exact perpendicular distance to the route polyline.

### 2. Dynamic Programming Formulation

The route is modeled as an ordered list of nodes:

```
[S=mile 0] → [station 1] → [station 2] → ... → [station N] → [F=mile D]
```

**State:** `dp[i] = (min_total_cost, min_stops)` to reach node `i`

**Transition:** from node `i` to node `j` if `dist(i, j) ≤ vehicle_range`

$$\text{leg\_cost}(i \to j) = \frac{\text{dist}(i, j)}{\text{mpg}} \times \text{price}(i)$$

**Complexity:** $O(N^2)$ where $N$ = candidate stations in corridor

**Key constraint:** The first leg uses `starting_range_miles` (current tank), all subsequent legs use `max_range_miles` (full tank).

### 3. Why DP and not greedy?
A greedy "always stop at the cheapest nearby station" fails because:
- It may stop unnecessarily when the next cheap station is reachable
- It misses cases where a slightly pricier stop now avoids an expensive stop later

The DP considers all feasible paths and finds the globally optimal solution.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0.4 |
| Database | SQLite (pre-seeded, 3.5MB) |
| Routing | OSRM (OpenStreetMap Routing Machine) |
| Geocoding | Nominatim (OpenStreetMap) |
| Map rendering | Leaflet.js + CartoDB dark tiles |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Dependency | `Django==6.0.4` only |

---

## What's Not (Yet) In This System

| Feature | Status | Notes |
|---|---|---|
| Live fuel prices | ❌ Static CSV | Prices are from assessment dataset, not a live feed |
| Market lane rates (DAT/Truckstop) | ❌ Not connected | Would require DAT RateView API |
| UltraShip load history integration | ❌ Not connected | `carrier_lane_rates`, `load_extended` data not wired |
| Carrier Confidence Score | ❌ Not connected | Ultraship-ml service exists but not integrated here |
| Real toll calculation | ❌ Estimated | Flat 3.8¢/mi — needs PCMiler or SMC3 |
| Multi-drop route optimization | ❌ Roadmap | Currently point-to-point only |
| Authentication | ❌ None | API is open (`csrf_exempt`) |
