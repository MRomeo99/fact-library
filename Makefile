.PHONY: up down mock-server crawl serve test lint pipeline reset install \
        seed-kb seed-docs seed-all eval pipeline-all

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

# ── Part 2: Multi-source ingestion ───────────────────────────────────────────

seed-kb:
	python seeds/seed_knowledge_base.py

seed-docs:
	@echo "Copying sample documents to watched folder…"
	@mkdir -p documents/demo_dental documents/demo_legal documents/demo_home_services
	cp seeds/sample_documents/dental_service_menu.txt documents/demo_dental/
	cp seeds/sample_documents/law_firm_faq.txt documents/demo_legal/
	cp seeds/sample_documents/home_services_areas.txt documents/demo_home_services/
	@echo "Documents copied. Run 'make crawl' to ingest them."

seed-all: seed-kb seed-docs
	@echo "All demo data seeded."

eval:
	python quality/eval/run_eval.py \
		--questions quality/eval/eval_questions.json \
		--min-precision 0.75 \
		--min-mrr 0.70

pipeline-all: up seed-all crawl
	@echo "Full pipeline (website + KB + docs) complete."
