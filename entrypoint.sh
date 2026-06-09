#!/bin/bash
set -e

echo "Upgrading database, $SQLALCHEMY_DATABASE_URI..."
uv run alembic upgrade head

echo "Starting FastAPI server..."
exec uv run uvicorn main:app --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-3000} --reload
