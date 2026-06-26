"""Seed demo knowledge base records for all three demo clients.

Inserts curated Q&A pairs, conditional facts, and pricing overrides that
the ingestion pipeline will sync into Qdrant. Requires a Postgres connection.

Usage:
    python seeds/seed_knowledge_base.py

Environment variables:
    DATABASE_URL  — Postgres connection string (e.g. postgresql://user:pw@host/db)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEED_RECORDS = [
    # ── demo_dental ──────────────────────────────────────────────────────────
    {
        "client_id": "demo_dental",
        "fact_type": "conditional",
        "title": "Cancellation policy",
        "condition": "caller asks about cancelling or missing an appointment",
        "response": "Inform them of the 48-hour cancellation window and $50 late cancellation fee.",
        "exception_note": "Waive the fee for platinum members or genuine emergencies.",
        "priority": 9,
    },
    {
        "client_id": "demo_dental",
        "fact_type": "qa",
        "title": "Payment plans — CareCredit",
        "condition": "Do you offer payment plans or financing?",
        "response": "Yes, we offer 0% interest financing through CareCredit for treatments over $500.",
        "priority": 8,
    },
    {
        "client_id": "demo_dental",
        "fact_type": "qa",
        "title": "New patient specials",
        "condition": "Do you have any specials for new patients?",
        "response": "New patients receive a complimentary cleaning and X-rays on their first visit — a $180 value.",
        "priority": 7,
    },
    {
        "client_id": "demo_dental",
        "fact_type": "pricing_override",
        "title": "Emergency visit fee",
        "condition": "Emergency dental visit pricing",
        "response": "Emergency same-day visit: $95 exam fee, waived if treatment is performed same day.",
        "priority": 8,
    },
    {
        "client_id": "demo_dental",
        "fact_type": "talking_point",
        "title": "CareCredit talking point",
        "condition": "CareCredit financing",
        "response": (
            "We partner with CareCredit to make dental care accessible. "
            "Patients can apply in office in under 5 minutes and get an instant decision."
        ),
        "priority": 6,
    },
    # ── demo_legal ───────────────────────────────────────────────────────────
    {
        "client_id": "demo_legal",
        "fact_type": "conditional",
        "title": "Consultation cancellation",
        "condition": "caller asks about cancelling or rescheduling a consultation",
        "response": "24-hour advance notice is required. A $75 no-show fee applies for late cancellations.",
        "exception_note": "Waive for documented emergencies — escalate to senior staff.",
        "priority": 9,
    },
    {
        "client_id": "demo_legal",
        "fact_type": "pricing_override",
        "title": "Initial consultation fee",
        "condition": "How much does an initial consultation cost?",
        "response": "Initial consultations are $150 for up to 60 minutes. Fee is applied to your retainer.",
        "priority": 8,
    },
    {
        "client_id": "demo_legal",
        "fact_type": "qa",
        "title": "Free consultation eligibility",
        "condition": "Do you offer free consultations?",
        "response": (
            "Free 15-minute phone consultations are available for personal injury cases. "
            "All other matters require the standard $150 consultation fee."
        ),
        "priority": 7,
    },
    {
        "client_id": "demo_legal",
        "fact_type": "talking_point",
        "title": "Contingency fee — PI cases",
        "condition": "Contingency fee structure for personal injury",
        "response": (
            "For personal injury cases we work on contingency — you pay nothing unless we win. "
            "Our standard contingency is 33% of the settlement."
        ),
        "priority": 8,
    },
    # ── demo_home_services ───────────────────────────────────────────────────
    {
        "client_id": "demo_home_services",
        "fact_type": "conditional",
        "title": "Cancellation / rescheduling policy",
        "condition": "caller wants to cancel or reschedule a service appointment",
        "response": "24-hour notice is appreciated but there is no cancellation fee.",
        "exception_note": "Same-day cancellations on jobs over $500 may incur a $50 scheduling fee.",
        "priority": 7,
    },
    {
        "client_id": "demo_home_services",
        "fact_type": "qa",
        "title": "Emergency service availability",
        "condition": "Do you offer emergency or after-hours service?",
        "response": "Yes — 24/7 emergency plumbing and HVAC service. Call our emergency line at (800) 555-0199.",
        "priority": 9,
    },
    {
        "client_id": "demo_home_services",
        "fact_type": "pricing_override",
        "title": "Service call fee",
        "condition": "How much is the service call fee?",
        "response": "$75 service call fee, credited toward any repair work performed that day.",
        "priority": 8,
    },
    {
        "client_id": "demo_home_services",
        "fact_type": "qa",
        "title": "Payment methods",
        "condition": "What payment methods do you accept?",
        "response": "We accept all major credit cards, check, and financing through GreenSky for jobs over $1,000.",
        "priority": 6,
    },
]


def seed(db_url: str | None = None) -> None:
    db_url = db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is required.")
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary is required: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    inserted = 0
    for record in SEED_RECORDS:
        cur.execute(
            """
            INSERT INTO client_knowledge_base
                (client_id, fact_type, title, condition, response, exception_note, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                record["client_id"],
                record["fact_type"],
                record.get("title"),
                record.get("condition"),
                record["response"],
                record.get("exception_note"),
                record.get("priority", 5),
            ),
        )
        inserted += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()
    print(f"Seeded {inserted} KB records ({len(SEED_RECORDS)} total attempted).")


if __name__ == "__main__":
    seed()
