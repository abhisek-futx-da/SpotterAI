#!/usr/bin/env bash
set -e

echo "============================================="
echo "   Route Fuel Optimizer Setup & Startup      "
echo "============================================="

# Load API keys from .env if it exists
if [ -f ".env" ]; then
    set -o allexport
    source .env
    set +o allexport
    echo "Loaded API keys from .env"
fi

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not installed." >&2
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install / update dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Always apply migrations — pending ones after a git pull must never be skipped.
echo "Applying migrations..."
python manage.py migrate

# Load fuel data only on first init (it's a slow bulk import)
if [ ! -f "db.sqlite3" ] || [ "$(python manage.py shell -c 'from route_planner.models import FuelStation; print(FuelStation.objects.exists())' 2>/dev/null)" = "False" ]; then
    if [ ! -f "data/fuel_city_coordinates.csv" ]; then
        echo "Generating city coordinate mappings..."
        python manage.py generate_city_lookup data/fuel-prices-for-be-assessment.csv data/fuel_city_coordinates.csv
    fi
    echo "Loading fuel stations data..."
    python manage.py load_fuel_prices data/fuel-prices-for-be-assessment.csv --city-lookup data/fuel_city_coordinates.csv --clear
else
    echo "Fuel stations already loaded. Skipping data load."
fi

# Run tests
echo "Running unit tests..."
python manage.py test

echo ""
echo "=========================================================="
echo " Setup complete! Starting Django server..."
echo " Open your browser to: http://127.0.0.1:8000/"
echo "=========================================================="
echo ""

python manage.py runserver
