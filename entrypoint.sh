#!/bin/sh
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting Talos Panel..."
exec uvicorn talos_panel.main:app --host 0.0.0.0 --port 8000
