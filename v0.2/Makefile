.PHONY: dev services wait-for-db api migrate test lint typecheck eval ingest

# Start Postgres + embedder, wait for DB, run migrations, start API
dev: services wait-for-db migrate api

# Infrastructure only
services:
	docker compose up -d postgres embedder

# Block until Postgres is accepting connections
wait-for-db:
	@echo "Waiting for Postgres..."
	@until docker compose exec postgres pg_isready -U unichat > /dev/null 2>&1; do sleep 1; done
	@echo "Postgres is ready."

# API with hot reload (run on host for fast iteration)
api:
	uv run uvicorn packages.api.server:app --reload --host 0.0.0.0 --port 8000

# Run Alembic migrations
migrate:
	uv run alembic upgrade head

# Full test suite (unit only by default; use `make test-all` for integration)
test:
	uv run pytest tests/ -v -m "not integration"

# All tests including integration (requires running services)
test-all:
	uv run pytest tests/ -v

# Linting
lint:
	uv run ruff check packages/ tests/
	uv run ruff format --check packages/ tests/

# Type checking
typecheck:
	uv run mypy packages/

# Run eval harness against golden set
eval:
	uv run python -m packages.eval.run

# Run ingestion against fixture university
ingest:
	uv run python -m packages.ingestion.run

# Stop all services
down:
	docker compose down
