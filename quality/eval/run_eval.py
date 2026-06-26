"""Retrieval evaluation runner.

Seeds demo data into Qdrant (in-memory or live) and evaluates
precision@3, MRR, and KB source coverage against a ground-truth
question set. Exits non-zero if thresholds are not met.

Usage:
    python quality/eval/run_eval.py \\
        --questions quality/eval/eval_questions.json \\
        --min-precision 0.75 \\
        --min-mrr 0.70
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from embedder.local_embedder import LocalEmbedder
from quality.eval.metrics import mrr, precision_at_k, source_coverage
from store.qdrant_store import QdrantStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def seed_eval_data(store: QdrantStore, embedder: LocalEmbedder) -> None:
    """Seed a known set of typed facts into Qdrant for deterministic eval.

    In CI (QDRANT_URL=memory), there is no persistent store and no real
    LLM, so we seed facts directly rather than running the full pipeline.
    This tests retrieval mechanics (source-type ranking, fact-type filtering)
    without requiring live LLM calls.
    """
    from extractor.schemas import (
        ConditionalFact,
        LocationFact,
        OperationalFact,
        PricingFact,
        QAFact,
        ServiceFact,
    )

    seed_facts = [
        # demo_dental — KB facts (should rank above website facts for same query)
        (
            "demo_dental",
            ConditionalFact(
                fact_type="conditional",
                content="If caller asks about cancellation, then inform them of 48-hour window and $50 fee",
                condition="caller asks about cancellation",
                response="inform them of the 48-hour cancellation window and $50 late fee",
                exception_note="unless they are a platinum member",
                priority=8,
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_dental",
            QAFact(
                fact_type="qa",
                content="Yes, we offer 0% financing through CareCredit for treatments over $500.",
                question="Do you offer payment plans?",
                answer="Yes, we offer 0% financing through CareCredit for treatments over $500.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_dental",
            PricingFact(
                fact_type="pricing",
                content="Dental cleaning starts at $89 for new patients.",
                confidence=0.92,
                raw_evidence="Dental cleaning $89 new patients",
                price_min=89.0,
                price_unit="per visit",
            ),
            "website",
            None,
        ),
        (
            "demo_dental",
            ServiceFact(
                fact_type="service",
                content="Professional teeth whitening using Zoom technology, results in one visit.",
                service_name="Teeth Whitening",
                confidence=0.95,
                raw_evidence="Professional teeth whitening Zoom technology one visit",
            ),
            "website",
            None,
        ),
        (
            "demo_dental",
            ServiceFact(
                fact_type="service",
                content="Comprehensive dental services including crowns, veneers, and implants.",
                service_name="Restorative Dentistry",
                confidence=0.9,
                raw_evidence="Crowns veneers implants restorative dentistry",
            ),
            "document",
            {"document_name": "dental_service_menu.txt", "page_number": 1},
        ),
        (
            "demo_dental",
            OperationalFact(
                fact_type="operational",
                content="Office hours: Monday–Friday 8am–5pm, Saturday 9am–2pm.",
                confidence=0.88,
                raw_evidence="Monday Friday 8am 5pm Saturday 9am 2pm",
            ),
            "website",
            None,
        ),
        # demo_legal
        (
            "demo_legal",
            ConditionalFact(
                fact_type="conditional",
                content="If caller asks about cancellation, then 24-hour notice required, $75 fee applies",
                condition="caller asks about cancelling a consultation",
                response="24-hour notice required; $75 no-show fee applies",
                priority=9,
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_legal",
            PricingFact(
                fact_type="pricing",
                content="Initial consultation fee is $150 for one hour.",
                confidence=0.95,
                raw_evidence="Initial consultation $150 one hour",
                price_min=150.0,
                price_unit="per hour",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_legal",
            ServiceFact(
                fact_type="service",
                content="Personal injury, family law, estate planning, and business litigation.",
                service_name="Practice Areas",
                confidence=0.92,
                raw_evidence="Personal injury family law estate planning business litigation",
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            LocationFact(
                fact_type="location",
                content="Serving Dallas, Fort Worth, Plano, and surrounding DFW metro area.",
                confidence=0.9,
                raw_evidence="Dallas Fort Worth Plano DFW metro",
                city="Dallas",
                state="TX",
                service_area=["Dallas", "Fort Worth", "Plano"],
            ),
            "website",
            None,
        ),
        # demo_home_services
        (
            "demo_home_services",
            ConditionalFact(
                fact_type="conditional",
                content="If caller asks about rescheduling, then 24-hour notice needed, no fee",
                condition="caller asks about rescheduling or cancelling",
                response="24-hour notice appreciated; no cancellation fee",
                priority=7,
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            OperationalFact(
                fact_type="operational",
                content="24/7 emergency plumbing service available. Call our emergency line.",
                confidence=0.93,
                raw_evidence="24/7 emergency plumbing service emergency line",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            LocationFact(
                fact_type="location",
                content="Serving Dallas, Garland, Mesquite, Irving, and all DFW suburbs.",
                confidence=0.88,
                raw_evidence="Dallas Garland Mesquite Irving DFW suburbs",
                city="Dallas",
                state="TX",
                service_area=["Dallas", "Garland", "Mesquite", "Irving"],
            ),
            "document",
            {"document_name": "home_services_areas.txt", "page_number": 1},
        ),
        (
            "demo_home_services",
            PricingFact(
                fact_type="pricing",
                content="Service call fee is $75 which is applied toward any repair work.",
                confidence=0.91,
                raw_evidence="Service call $75 applied toward repair",
                price_min=75.0,
                price_unit="per visit",
            ),
            "website",
            None,
        ),
    ]

    for client_id, fact, source_type, extra in seed_facts:
        embed_text = f"{fact.fact_type}: {fact.content}"
        vector = embedder.embed(embed_text)
        store.upsert_fact(
            client_id=client_id,
            fact=fact,
            vector=vector,
            source_url=f"seed://{client_id}",
            page_type=source_type,
            page_score=4,
            content_hash=f"seed:{client_id}:{fact.content[:40]}",
            source_type=source_type,
            extra_payload=extra,
        )
    logger.info("Seeded %d facts across 3 demo clients", len(seed_facts))


def run_eval(
    questions: list[dict],
    store: QdrantStore,
    embedder: LocalEmbedder,
    min_precision: float = 0.75,
    min_mrr: float = 0.70,
    k: int = 3,
) -> dict:
    """Run all eval questions and return metric results."""
    all_hits: list[list[dict]] = []
    all_expected_types: list[list[str]] = []
    kb_override_checks: list[bool] = []

    for q in questions:
        client_id = q["client_id"]
        query = q["question"]
        expected_types = q["expected_fact_types"]
        expected_sources = q.get("expected_source_types", [])

        query_vector = embedder.embed(query)
        hits = store.search(client_id=client_id, query_vector=query_vector, limit=k)

        all_hits.append(hits)
        all_expected_types.append(expected_types)

        if "knowledge_base" in expected_sources:
            kb_override_checks.append(source_coverage(hits, "knowledge_base", k=k))

    p_at_k = sum(
        precision_at_k(hits, expected_types, k=k)
        for hits, expected_types in zip(all_hits, all_expected_types)
    ) / max(len(questions), 1)

    mrr_score = mrr(all_hits, all_expected_types)

    kb_override_rate = (
        sum(kb_override_checks) / len(kb_override_checks) if kb_override_checks else 0.0
    )

    return {
        "total_questions": len(questions),
        "precision_at_3": round(p_at_k, 4),
        "mrr": round(mrr_score, 4),
        "kb_override_rate": round(kb_override_rate, 4),
        "passed_precision": p_at_k >= min_precision,
        "passed_mrr": mrr_score >= min_mrr,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval eval suite")
    parser.add_argument("--questions", default="quality/eval/eval_questions.json")
    parser.add_argument("--min-precision", type=float, default=0.75)
    parser.add_argument("--min-mrr", type=float, default=0.70)
    parser.add_argument("--seed", action="store_true", default=True, help="Seed demo data")
    args = parser.parse_args()

    questions_path = Path(args.questions)
    if not questions_path.exists():
        logger.error("Questions file not found: %s", args.questions)
        sys.exit(1)

    questions = json.loads(questions_path.read_text())

    store = QdrantStore()
    embedder = LocalEmbedder()

    if args.seed:
        logger.info("Seeding eval data…")
        seed_eval_data(store, embedder)

    logger.info("Running eval on %d questions…", len(questions))
    results = run_eval(
        questions=questions,
        store=store,
        embedder=embedder,
        min_precision=args.min_precision,
        min_mrr=args.min_mrr,
    )

    print("\n── Retrieval Eval Results ──────────────────────────")
    print(f"  Questions evaluated : {results['total_questions']}")
    print(
        f"  Precision@3         : {results['precision_at_3']:.2f}  (threshold: {args.min_precision})"
    )
    print(f"  MRR                 : {results['mrr']:.2f}  (threshold: {args.min_mrr})")
    print(f"  KB override rate    : {results['kb_override_rate']:.2f}")
    print("────────────────────────────────────────────────────\n")

    if not results["passed_precision"]:
        logger.error(
            "FAIL: Precision@3 %.2f < threshold %.2f",
            results["precision_at_3"],
            args.min_precision,
        )
        sys.exit(1)

    if not results["passed_mrr"]:
        logger.error(
            "FAIL: MRR %.2f < threshold %.2f",
            results["mrr"],
            args.min_mrr,
        )
        sys.exit(1)

    logger.info("PASS: All eval thresholds met.")


if __name__ == "__main__":
    main()
