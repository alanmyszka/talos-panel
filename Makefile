.PHONY: up down logs test lint migrate

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f panel

test:
	pytest

lint:
	ruff check talos_panel tests migrations

migrate:
	docker compose exec panel alembic upgrade head
