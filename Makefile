export COMPOSE_BAKE=true

# Docker commands
build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

down-rm:
	docker compose down --rmi all

drop-db:
	docker volume rm apiserver_db_data

# Run FASTAPI in dev mode
run-dev:
	fastapi dev main.py

# Unit Tests
test:
	pytest -xv --cov
	coverage html

# Alembic migration commands
migrate-upgrade:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(message)"

migrate-rollback:
	alembic downgrade -1

# Create a new empty migration file
migrate-empty:
	alembic revision -m "$(message)"

# Show current revision
migrate-current:
	alembic current
