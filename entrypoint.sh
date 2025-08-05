#!/bin/bash
set -e

echo "Upgrading database, $SQLALCHEMY_DATABASE_URI..."
uv run alembic upgrade head

echo "Starting FastAPI server..."
exec uv run uvicorn main:app --host 0.0.0.0 --port 3000 --reload