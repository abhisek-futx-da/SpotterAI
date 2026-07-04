#!/usr/bin/env bash
set -e

echo "Running migrations..."
python manage.py migrate --noinput

# Railway's filesystem is ephemeral — reload fuel station data on every boot.
if [ ! -f "data/fuel_city_coordinates.csv" ]; then
    echo "Generating city coordinate mappings..."
    python manage.py generate_city_lookup data/fuel-prices-for-be-assessment.csv data/fuel_city_coordinates.csv
fi

echo "Loading fuel stations data..."
python manage.py load_fuel_prices data/fuel-prices-for-be-assessment.csv --city-lookup data/fuel_city_coordinates.csv --clear

# Anchor station price levels to this week's EIA regional diesel averages,
# preserving station-to-station spreads. Never blocks boot if EIA is down.
echo "Calibrating fuel prices to current EIA regional averages..."
python manage.py refresh_fuel_prices || echo "Price calibration skipped (EIA unavailable) — using dataset prices."

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting gunicorn..."
exec gunicorn config.wsgi --bind 0.0.0.0:"${PORT:-8000}" --workers 2 --timeout 60
