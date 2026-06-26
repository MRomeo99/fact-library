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

    Each client has facts covering all expected fact types so every eval
    question has at least one matching fact in the collection. The thresholds
    in run_eval (precision ≥ 0.45, MRR ≥ 0.65) are calibrated against this
    seed set — not aspirational production targets.
    """
    from extractor.schemas import (
        ConditionalFact,
        CredibilityFact,
        IdentityFact,
        LocationFact,
        OperationalFact,
        PricingFact,
        QAFact,
        ServiceFact,
    )

    seed_facts = [
        # ── demo_dental ──────────────────────────────────────────────────────
        (
            "demo_dental",
            ConditionalFact(
                fact_type="conditional",
                content="If caller asks about cancellation, we require 48-hour notice and charge a $50 late fee.",
                condition="caller asks about cancellation",
                response="48-hour cancellation window required; $50 late fee applies",
                exception_note="waived for platinum members",
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
                question="Do you offer payment plans or financing?",
                answer="Yes, we offer 0% financing through CareCredit for treatments over $500.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_dental",
            QAFact(
                fact_type="qa",
                content="Yes, we are currently accepting new patients. You can book online or call our front desk.",
                question="Are you accepting new patients?",
                answer="Yes, we are currently accepting new patients. Book online or call to schedule.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_dental",
            PricingFact(
                fact_type="pricing",
                content="Dental cleaning starts at $89 for new patients. Whitening packages start at $299.",
                confidence=0.92,
                raw_evidence="Dental cleaning $89 new patients; whitening $299",
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
                content="Professional teeth whitening using Zoom technology, same-day results.",
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
                content="Full restorative dental services: crowns, veneers, implants, and bridges.",
                service_name="Restorative Dentistry",
                confidence=0.9,
                raw_evidence="Crowns veneers implants bridges restorative dentistry",
            ),
            "document",
            {"document_name": "dental_service_menu.txt", "page_number": 1},
        ),
        (
            "demo_dental",
            OperationalFact(
                fact_type="operational",
                content="Office hours: Monday–Friday 8am–5pm, Saturday 9am–2pm. Closed Sundays.",
                confidence=0.88,
                raw_evidence="Monday Friday 8am 5pm Saturday 9am 2pm closed Sunday",
            ),
            "website",
            None,
        ),
        (
            "demo_dental",
            LocationFact(
                fact_type="location",
                content="Located at 4501 Westside Drive, Dallas, TX 75205. Free parking available.",
                confidence=0.95,
                raw_evidence="4501 Westside Drive Dallas TX 75205 free parking",
                address="4501 Westside Drive",
                city="Dallas",
                state="TX",
                service_area=["Dallas", "Plano", "Frisco"],
            ),
            "website",
            None,
        ),
        (
            "demo_dental",
            CredibilityFact(
                fact_type="credibility",
                content="Board-certified by the American Dental Association. Rated 4.9 stars on Google with 320 reviews.",
                confidence=0.9,
                raw_evidence="ADA board certified 4.9 stars Google 320 reviews",
            ),
            "website",
            None,
        ),
        (
            "demo_dental",
            IdentityFact(
                fact_type="identity",
                content="Sunrise Family Dental — compassionate family dental care in Dallas since 2008.",
                confidence=0.98,
                raw_evidence="Sunrise Family Dental Dallas since 2008",
            ),
            "website",
            None,
        ),
        # ── demo_legal ───────────────────────────────────────────────────────
        (
            "demo_legal",
            ConditionalFact(
                fact_type="conditional",
                content="If caller cancels a consultation with less than 24-hour notice, a $75 no-show fee applies.",
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
                content="Initial consultation fee is $150 for one hour. We do not offer free consultations.",
                confidence=0.95,
                raw_evidence="Initial consultation $150 one hour no free consultations",
                price_min=150.0,
                price_unit="per hour",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_legal",
            QAFact(
                fact_type="qa",
                content="We do not offer free consultations. Our initial 60-minute session is $150.",
                question="Do you offer free consultations?",
                answer="We do not offer free consultations. Initial session is $150 for 60 minutes.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_legal",
            ServiceFact(
                fact_type="service",
                content="Practice areas: personal injury, family law, estate planning, and business litigation.",
                service_name="Practice Areas",
                confidence=0.92,
                raw_evidence="Personal injury family law estate planning business litigation",
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            ServiceFact(
                fact_type="service",
                content="Specializing in motor vehicle accidents, slip-and-fall, and wrongful death claims.",
                service_name="Personal Injury",
                confidence=0.9,
                raw_evidence="Motor vehicle accidents slip fall wrongful death personal injury",
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            LocationFact(
                fact_type="location",
                content="Serving Dallas, Fort Worth, Plano, Arlington, and the entire DFW metro area.",
                confidence=0.9,
                raw_evidence="Dallas Fort Worth Plano Arlington DFW metro area",
                city="Dallas",
                state="TX",
                service_area=["Dallas", "Fort Worth", "Plano", "Arlington"],
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            CredibilityFact(
                fact_type="credibility",
                content="Combined 25+ years of litigation experience. All attorneys are Texas State Bar certified.",
                confidence=0.93,
                raw_evidence="25 years litigation experience Texas State Bar certified attorneys",
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            IdentityFact(
                fact_type="identity",
                content="Johnson & Associates — a full-service law firm serving Texas clients since 1999.",
                confidence=0.97,
                raw_evidence="Johnson Associates full service law firm Texas 1999",
            ),
            "website",
            None,
        ),
        (
            "demo_legal",
            OperationalFact(
                fact_type="operational",
                content="New client intake: complete online form, provide ID and documents, attend initial consultation within 48 hours.",
                confidence=0.85,
                raw_evidence="New client intake online form ID documents consultation 48 hours",
            ),
            "document",
            {"document_name": "law_firm_faq.txt", "page_number": 2},
        ),
        # ── demo_home_services ───────────────────────────────────────────────
        (
            "demo_home_services",
            ConditionalFact(
                fact_type="conditional",
                content="If caller asks about rescheduling, 24-hour notice is appreciated and there is no cancellation fee.",
                condition="caller asks about rescheduling or cancelling",
                response="24-hour notice appreciated; no cancellation fee charged",
                priority=7,
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            OperationalFact(
                fact_type="operational",
                content="24/7 emergency plumbing available. Same-day service for calls placed before noon.",
                confidence=0.93,
                raw_evidence="24/7 emergency plumbing same day service before noon",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            QAFact(
                fact_type="qa",
                content="Yes, we offer same-day plumbing service for calls placed before noon on weekdays.",
                question="Do you offer same-day service?",
                answer="Yes, same-day service available for calls placed before noon on weekdays.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            QAFact(
                fact_type="qa",
                content="We accept cash, all major credit cards, and offer 12-month financing on repairs over $500.",
                question="What payment methods do you accept?",
                answer="Cash, all major credit cards, and 12-month financing available on repairs over $500.",
            ),
            "knowledge_base",
            None,
        ),
        (
            "demo_home_services",
            LocationFact(
                fact_type="location",
                content="Serving Dallas, Garland, Mesquite, Irving, and all DFW suburbs within 40 miles.",
                confidence=0.88,
                raw_evidence="Dallas Garland Mesquite Irving DFW suburbs 40 miles",
                city="Dallas",
                state="TX",
                service_area=["Dallas", "Garland", "Mesquite", "Irving"],
            ),
            "document",
            {"document_name": "home_services_areas.txt", "page_number": 1},
        ),
        (
            "demo_home_services",
            LocationFact(
                fact_type="location",
                content="Primary service area: Plano, Richardson, Allen, McKinney — all within 30 miles of Dallas.",
                confidence=0.85,
                raw_evidence="Plano Richardson Allen McKinney 30 miles Dallas service area",
                city="Plano",
                state="TX",
                service_area=["Plano", "Richardson", "Allen", "McKinney"],
            ),
            "website",
            None,
        ),
        (
            "demo_home_services",
            PricingFact(
                fact_type="pricing",
                content="Service call fee is $75, applied toward any repair. Free estimates on installations.",
                confidence=0.91,
                raw_evidence="Service call $75 applied toward repair free estimates installations",
                price_min=75.0,
                price_unit="per visit",
            ),
            "website",
            None,
        ),
        (
            "demo_home_services",
            ServiceFact(
                fact_type="service",
                content="Full plumbing services: drain cleaning, pipe repair, water heater installation, and leak detection.",
                service_name="Plumbing Services",
                confidence=0.94,
                raw_evidence="Drain cleaning pipe repair water heater installation leak detection plumbing",
            ),
            "website",
            None,
        ),
        (
            "demo_home_services",
            CredibilityFact(
                fact_type="credibility",
                content="Licensed and fully insured in Texas (License #TX-PLU-2891). Bonded for your protection.",
                confidence=0.96,
                raw_evidence="Licensed insured Texas TX-PLU-2891 bonded protection",
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
