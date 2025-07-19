export COMPOSE_BAKE=true

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