#!/bin/bash
set -e

echo "Upgrading database..."
alembic upgrade head

echo "Starting FastAPI server..."
exec uv run uvicorn main:app --host 0.0.0.0 --port 5000 --reload