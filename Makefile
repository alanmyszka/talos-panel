.PHONY: up down logs test lint migrate dev dev-build dev-logs dev-down

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

dev:
	docker compose -f compose.yaml -f compose.dev.yaml up -d

dev-build:
	docker compose -f compose.yaml -f compose.dev.yaml up -d --build

dev-logs:
	docker compose -f compose.yaml -f compose.dev.yaml logs -f panel

dev-down:
	docker compose -f compose.yaml -f compose.dev.yaml down
