"""Pydantic fact schemas — one model per fact type."""
import json
import logging
from typing import Literal, Optional, Union

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5


class FactBase(BaseModel):
    fact_type: str
    content: str
    confidence: float
    raw_evidence: str


class IdentityFact(FactBase):
    fact_type: Literal["identity"]


class ServiceFact(FactBase):
    fact_type: Literal["service"]
    service_name: str


class PricingFact(FactBase):
    fact_type: Literal["pricing"]
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_unit: Optional[str] = None


class LocationFact(FactBase):
    fact_type: Literal["location"]
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    service_area: list[str] = []


class CredibilityFact(FactBase):
    fact_type: Literal["credibility"]


class OperationalFact(FactBase):
    fact_type: Literal["operational"]


# ── Knowledge-base fact types (human-authored, not LLM-extracted) ─────────────

class ConditionalFact(FactBase):
    """Explicit if/then business rule authored in the knowledge base.

    Human-authored: confidence defaults to 1.0, raw_evidence is empty.
    Embedded text: "conditional: if {condition} then {response}"
    """

    fact_type: Literal["conditional"]
    condition: str
    response: str
    exception_note: Optional[str] = None
    priority: int = 5
    source_type: Literal["knowledge_base"] = "knowledge_base"
    confidence: float = 1.0
    raw_evidence: str = ""


class QAFact(FactBase):
    """Question/answer pair authored in the knowledge base.

    Also covers talking_point and pricing_override KB record types.
    Human-authored: confidence defaults to 1.0, raw_evidence is empty.
    """

    fact_type: Literal["qa"]
    question: str
    answer: str
    source_type: Literal["knowledge_base"] = "knowledge_base"
    confidence: float = 1.0
    raw_evidence: str = ""


AnyFact = Union[
    IdentityFact,
    ServiceFact,
    PricingFact,
    LocationFact,
    CredibilityFact,
    OperationalFact,
    ConditionalFact,
    QAFact,
]

_FACT_TYPE_MAP: dict[str, type] = {
    "identity": IdentityFact,
    "service": ServiceFact,
    "pricing": PricingFact,
    "location": LocationFact,
    "credibility": CredibilityFact,
    "operational": OperationalFact,
    "conditional": ConditionalFact,
    "qa": QAFact,
}


def parse_facts(raw_json: str) -> list[AnyFact]:
    """Parse the raw LLM JSON response into typed fact objects.

    Filters out facts below CONFIDENCE_THRESHOLD and logs but skips
    any Pydantic validation errors — never raises.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned invalid JSON: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning("LLM response is not a list; got %s", type(data))
        return []

    facts: list[AnyFact] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        fact_type = raw.get("fact_type", "")
        model_cls = _FACT_TYPE_MAP.get(fact_type)
        if model_cls is None:
            logger.debug("Unknown fact_type '%s'; skipping", fact_type)
            continue
        try:
            fact = model_cls(**raw)
        except ValidationError as exc:
            logger.debug("Validation error for %s: %s", fact_type, exc)
            continue
        if fact.confidence >= CONFIDENCE_THRESHOLD:
            facts.append(fact)
    return facts
