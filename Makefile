.PHONY: up down mock-server crawl serve test lint pipeline reset install

up:
	docker compose up -d

down:
	docker compose down

mock-server:
	python seeds/mock_site_server.py

crawl:
	python -m pipeline.flows

serve:
	uvicorn serving.main:app --reload --port 8000

test:
	pytest tests/ -v

lint:
	ruff check .
	black --check .

pipeline: up mock-server crawl

reset:
	docker compose down -v
	docker compose up -d

install:
	pip install -e ".[dev]"
	playwright install chromium
