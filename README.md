# Route Fuel Optimizer API & Dashboard

A professional Django application built for the Remote Backend Django Engineer (AI & Algorithmic Systems) assessment.

It accepts a USA start and finish location, calls the public Open Source Routing Machine (OSRM) service exactly once per route request, finds the cheapest fuel stations along the route corridor from the provided fuel-price CSV, selects the cost-effective refueling stops under a 500-mile vehicle range constraint using a Dynamic Programming optimization algorithm, and displays the route and statistics.

This repository includes both a **REST API** and a **responsive, modern map dashboard UI** to visualize the optimal route and stops.

---

## Features

- **Latest Django Release:** Built on Django 6.0.4.
- **Single-Call Routing:** Queries OSRM exactly once per route calculation, minimizing external API calls.
- **Dynamic Programming Optimization:** Uses an $O(N \log N + N^2)$ DP algorithm to find the absolute lowest-cost sequence of fuel stops along the route.
- **Interactive Visual Dashboard:** A beautiful, responsive frontend built with glassmorphism styling, Leaflet.js, and OpenStreetMap tiles. Includes presets for instant testing.
- **Flexible Inputs:** Accepts address/city queries (e.g. `"New York, NY"`) or exact coordinates (e.g. `{"lat": 40.7128, "lon": -74.0060}`) to skip geocoding entirely.

---

## Getting Started

### Quick Start (macOS & Linux)

For macOS and Linux users, we provide a self-contained runner script that creates the virtual environment, installs dependencies, initializes the database, loads the default fuel prices, runs the test suite, and launches the server.

Simply run:
```bash
./run.sh
```

Once complete, open your browser and navigate to:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

### Manual Setup (Cross-Platform)

If you prefer to run setup steps manually or are on Windows:

#### 1. Setup Virtual Environment & Install Dependencies
```bash
# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### 2. Run Database Migrations
```bash
python manage.py migrate
```

#### 3. Import Fuel Price Data
The provided CSV does not contain station latitude/longitude coordinates. We generate a coordinates lookup using GeoNames centroids to map cities to coordinates, avoiding live-geocoding throttles.

```bash
# Generate the city coordinate cache mapping
python manage.py generate_city_lookup data/fuel-prices-for-be-assessment.csv data/fuel_city_coordinates.csv

# Import fuel stations and prices
python manage.py load_fuel_prices data/fuel-prices-for-be-assessment.csv --city-lookup data/fuel_city_coordinates.csv --clear
```

#### 4. Run Development Server
```bash
python manage.py runserver
```
Visit **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser.

---

## Running Tests

To run the full suite of unit and integration tests:
```bash
python manage.py test
```

---

## API Documentation

### `POST /api/routes/optimize/`

Accepts JSON request payload specifying start and destination locations.

#### Example Request Body (Text Search)
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

#### Example Request Body (Coordinates)
Coordinates avoid geocoding external calls entirely:
```json
{
  "start": { "lat": 40.7128, "lon": -74.0060, "label": "New York, NY" },
  "finish": { "lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL" }
}
```

#### Request Parameters
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `start` | `string` or `object` | *Required* | Starting point as a location string or `{"lat": float, "lon": float, "label": string}` |
| `finish` | `string` or `object` | *Required* | Destination point |
| `max_range_miles` | `number` | `500` | Maximum fuel tank range of the vehicle in miles |
| `starting_range_miles` | `number` | `500` | Initial fuel range in miles at the start of the trip |
| `mpg` | `number` | `10` | Vehicle fuel efficiency (Miles Per Gallon) |
| `corridor_miles` | `number` | `25` | Search radius in miles along the route to look for fuel stations |

#### Example Response Shape
```json
{
  "start": {
    "label": "New York, NY",
    "lat": 40.7128,
    "lon": -74.0060
  },
  "finish": {
    "label": "Chicago, IL",
    "lat": 41.8781,
    "lon": -87.6298
  },
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
    "total_cost_usd": 102.41,
    "total_gallons_purchased": 29.11,
    "stops": [
      {
        "name": "PILOT TRAVEL CENTER #280",
        "address": "4000 RED ROAD ROAD",
        "city": "Stonycreek",
        "state": "PA",
        "latitude": 40.0125,
        "longitude": -78.9211,
        "retail_price": 3.519,
        "route_mile": 290.12,
        "gallons": 29.11,
        "cost": 102.41
      }
    ]
  },
  "map": {
    "geojson": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "properties": { "kind": "route" },
          "geometry": {
            "type": "LineString",
            "coordinates": [[-74.0060, 40.7128], [-78.9211, 40.0125], [-87.6298, 41.8781]]
          }
        }
      ]
    },
    "openstreetmap_url": "https://www.openstreetmap.org/directions?..."
  }
}
```

---

## Algorithmic Details & Optimization Strategy

1. **Route Corridor Filtering:** All fuel stations loaded in the database are filtered using bounding-box queries relative to the coordinates of the route line returned by OSRM. A station is considered a candidate if its distance to the closest segment of the route is less than `corridor_miles`.
2. **DP Formulation:** The route is modeled as an ordered list of nodes starting at $S$ (mile 0), followed by $N$ candidate fuel stations sorted by their distance along the route, and ending at $F$ (destination mile $D$).
   - We define `dp[i]` as the tuple `(min_cost, min_stops)` to reach node `i` from $S$.
   - The state transition transitions from `start_index` to `end_index` if the distance between them is within the vehicle's remaining fuel range.
   - The cost of the leg is the distance multiplied by the fuel price at `start_index` divided by the MPG:
     $$\text{leg\_cost} = \frac{\text{dist}(\text{start}, \text{end})}{\text{mpg}} \times \text{price}(\text{start})$$
   - By sorting node transitions, we solve the optimal substructure in $O(N^2)$ time.
