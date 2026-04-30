# Route Fuel Optimizer API

Django API for the backend engineering exercise. It accepts a USA start and finish location, calls a free routing service once per route request, finds fuel stations near the route from the provided fuel-price CSV, chooses cost-effective refueling stops for a 500-mile range, and returns route map data plus estimated fuel spend at 10 MPG.

## Stack

- Django 6.0.4, the current stable Django release as of April 2026.
- OSRM public route API for routing: https://project-osrm.org/docs/v5.24.0/api/
- Nominatim for geocoding text locations: https://operations.osmfoundation.org/policies/nominatim/
- SQLite by default for a local take-home friendly setup.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py generate_city_lookup data\fuel-prices-for-be-assessment.csv data\fuel_city_coordinates.csv
.\.venv\Scripts\python manage.py load_fuel_prices data\fuel-prices-for-be-assessment.csv --city-lookup data\fuel_city_coordinates.csv --clear
.\.venv\Scripts\python manage.py runserver
```

The provided assessment CSV does not include station latitude/longitude. `data\fuel_city_coordinates.csv` maps city/state pairs from the fuel file to GeoNames city coordinates so the API can place stations near the route without live-geocoding thousands of rows.

If you receive a newer fuel-price file with the same format, copy it into `data\` and reload:

```powershell
.\.venv\Scripts\python manage.py load_fuel_prices data\fuel-prices-for-be-assessment.csv --city-lookup data\fuel_city_coordinates.csv --clear
```

If a future CSV includes station-level latitude/longitude columns, the importer will use them directly. If it does not and the city lookup misses rows, `--geocode-missing` can fill gaps, but use it sparingly because public Nominatim calls are throttled:

```powershell
.\.venv\Scripts\python manage.py load_fuel_prices path\to\fuel_prices.csv --city-lookup data\fuel_city_coordinates.csv --clear --geocode-missing
```

## API

`POST /api/routes/optimize/`

```json
{
  "start": "New York, NY",
  "finish": "Chicago, IL"
}
```

Coordinates are also accepted, which avoids geocoding calls:

```json
{
  "start": {"lat": 40.7128, "lon": -74.0060, "label": "New York, NY"},
  "finish": {"lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL"}
}
```

Optional request fields:

- `max_range_miles`, default `500`
- `mpg`, default `10`
- `corridor_miles`, default `25`
- `starting_range_miles`, default `500`

For text location input, set `NOMINATIM_EMAIL` to a real contact email before running a public demo. Nominatim accepts coordinate input without geocoding, so using `{ "lat": ..., "lon": ... }` avoids those calls entirely.

## Assignment Compliance

- **Latest stable Django:** pinned to `Django==6.0.4`.
- **Start and finish locations in the USA:** text inputs are geocoded with `countrycodes=us`; coordinate inputs are accepted for API clients that already have USA coordinates.
- **Free map/routing API:** OSRM public routing API, one route request per optimization request.
- **Low external API usage:** coordinate input uses one OSRM call and no geocoding calls; text input uses two Nominatim geocoding calls and one OSRM call.
- **Route map result:** response includes route/stops as GeoJSON plus an OpenStreetMap directions URL.
- **Fuel prices:** data is loaded from `data\fuel-prices-for-be-assessment.csv`, the provided assessment file.
- **500-mile vehicle range:** default `max_range_miles` is `500`.
- **10 MPG cost calculation:** default `mpg` is `10`; gallons and total spend are calculated from route leg miles.
- **Optimal fuel stops:** stations are filtered to a route corridor, then the optimizer minimizes total fuel spend using the loaded price data.

## Location Accuracy Caveat

The provided fuel-price CSV contains station names, addresses, cities, states, and prices, but it does not contain exact latitude/longitude coordinates. To keep setup fast and avoid thousands of live geocoding calls, this project generates `data\fuel_city_coordinates.csv` from GeoNames and maps each fuel row to a city/state centroid.

That means:

- Fuel stop selection and total cost are based on the actual rows and prices from the provided assessment CSV.
- Fuel stop pins in the returned GeoJSON are approximate city-level locations, not guaranteed exact station driveway coordinates.
- If a future fuel file includes station-level latitude/longitude, the importer will use those exact coordinates directly.

Example response shape:

```json
{
  "start": {"label": "New York, NY", "lat": 40.7128, "lon": -74.006},
  "finish": {"label": "Chicago, IL", "lat": 41.8781, "lon": -87.6298},
  "route": {"distance_miles": 790.12, "duration_minutes": 742.5},
  "fuel_plan": {
    "total_cost_usd": 102.41,
    "total_gallons_purchased": 29.11,
    "stops": []
  },
  "map": {
    "geojson": {"type": "FeatureCollection", "features": []},
    "openstreetmap_url": "https://www.openstreetmap.org/directions?..."
  },
  "meta": {"external_calls": {"geocoding": 2, "routing": 1}}
}
```

## Assumptions

- The vehicle starts with `starting_range_miles` of usable range. The default is a full 500-mile tank, so the cost excludes fuel already in the vehicle at trip start.
- The optimizer minimizes fuel spend first, then uses fewer stops as a tie-breaker.
- Fuel bought at a selected station is the exact amount needed to reach the next selected station or destination.
- Candidate stations are fuel-price rows within `corridor_miles` of the route geometry.
- The route call is one OSRM request. Text input adds up to two geocoding calls; coordinate input avoids them.

## Tests

```powershell
.\.venv\Scripts\python manage.py test
```
