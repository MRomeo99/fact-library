"""Tests for the LLM fact extractor."""

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# Stub optional heavy dependencies so tests run without them installed
def _stub_module(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# portkey_ai stub
_pk_stub = _stub_module("portkey_ai")
_pk_stub.Portkey = MagicMock  # type: ignore

# google.generativeai stub
_gai_parent = _stub_module("google")
_gai_stub = _stub_module("google.generativeai")
_gai_stub.configure = MagicMock()  # type: ignore
_gai_stub.GenerativeModel = MagicMock()  # type: ignore
if not hasattr(_gai_parent, "generativeai"):
    _gai_parent.generativeai = _gai_stub  # type: ignore

from extractor.fact_extractor import FactExtractor
from extractor.llm_client import build_llm_client
from extractor.schemas import (
    CredibilityFact,
    IdentityFact,
    LocationFact,
    OperationalFact,
    PricingFact,
    ServiceFact,
    parse_facts,
)

# ── Schema tests ──────────────────────────────────────────────────────────────


class TestFactSchemas:
    def test_identity_fact_validates(self):
        f = IdentityFact(
            fact_type="identity",
            content="Sunrise Dental is a family dental practice founded in 2005.",
            confidence=0.95,
            raw_evidence="Sunrise Dental — serving families since 2005.",
        )
        assert f.fact_type == "identity"
        assert 0.0 <= f.confidence <= 1.0

    def test_service_fact_requires_service_name(self):
        f = ServiceFact(
            fact_type="service",
            content="We offer teeth whitening services.",
            confidence=0.9,
            raw_evidence="Professional teeth whitening — $199 per session.",
            service_name="Teeth Whitening",
        )
        assert f.service_name == "Teeth Whitening"

    def test_pricing_fact_nullable_fields(self):
        f = PricingFact(
            fact_type="pricing",
            content="Consultation starts at $150.",
            confidence=0.88,
            raw_evidence="Initial consultation: $150",
            price_min=150.0,
            price_max=None,
            price_unit="per session",
        )
        assert f.price_min == 150.0
        assert f.price_max is None

    def test_location_fact_service_area_list(self):
        f = LocationFact(
            fact_type="location",
            content="We serve the Dallas metro area.",
            confidence=0.9,
            raw_evidence="Serving Dallas, Plano, Frisco and surrounding areas.",
            address=None,
            city="Dallas",
            state="TX",
            service_area=["Dallas", "Plano", "Frisco"],
        )
        assert "Dallas" in f.service_area

    def test_credibility_fact_validates(self):
        f = CredibilityFact(
            fact_type="credibility",
            content="Board-certified orthodontist with 15 years experience.",
            confidence=0.92,
            raw_evidence="Dr. Smith, board-certified, 15 years in practice.",
        )
        assert f.fact_type == "credibility"

    def test_operational_fact_validates(self):
        f = OperationalFact(
            fact_type="operational",
            content="Open Monday through Friday 8am–6pm.",
            confidence=0.97,
            raw_evidence="Hours: Mon-Fri 8:00 AM – 6:00 PM",
        )
        assert f.fact_type == "operational"

    def test_low_confidence_fact_below_threshold(self):
        f = PricingFact(
            fact_type="pricing",
            content="Prices are competitive.",
            confidence=0.3,
            raw_evidence="Competitive pricing available.",
            price_min=None,
            price_max=None,
            price_unit=None,
        )
        assert f.confidence < 0.5


class TestParseFacts:
    def test_parse_valid_json_list(self):
        raw = json.dumps(
            [
                {
                    "fact_type": "identity",
                    "content": "Sunrise Dental is a family practice.",
                    "confidence": 0.9,
                    "raw_evidence": "Sunrise Dental — family practice.",
                }
            ]
        )
        facts = parse_facts(raw)
        assert len(facts) == 1
        assert facts[0].fact_type == "identity"

    def test_parse_filters_low_confidence(self):
        raw = json.dumps(
            [
                {
                    "fact_type": "pricing",
                    "content": "Competitive pricing.",
                    "confidence": 0.3,
                    "raw_evidence": "Competitive pricing.",
                    "price_min": None,
                    "price_max": None,
                    "price_unit": None,
                },
                {
                    "fact_type": "identity",
                    "content": "Sunrise Dental.",
                    "confidence": 0.9,
                    "raw_evidence": "Sunrise Dental.",
                },
            ]
        )
        facts = parse_facts(raw)
        assert len(facts) == 1
        assert facts[0].fact_type == "identity"

    def test_parse_invalid_json_returns_empty(self):
        facts = parse_facts("not valid json at all {{{}}")
        assert facts == []

    def test_parse_skips_invalid_fact_objects(self):
        raw = json.dumps(
            [
                {"fact_type": "unknown_type_xyz", "confidence": 0.9},
                {
                    "fact_type": "identity",
                    "content": "Good fact.",
                    "confidence": 0.9,
                    "raw_evidence": "Good fact.",
                },
            ]
        )
        facts = parse_facts(raw)
        # The valid one survives; the malformed one is skipped
        assert any(f.fact_type == "identity" for f in facts)


# ── LLM client factory tests ──────────────────────────────────────────────────


class TestBuildLlmClient:
    def test_portkey_mode_requires_env_vars(self):
        # Remove the two required portkey vars so os.environ["PORTKEY_API_KEY"] raises
        env_without = {
            k: v for k, v in os.environ.items() if k not in ("PORTKEY_API_KEY", "PORTKEY_CONFIG")
        }
        env_without["LLM_MODE"] = "portkey"
        with patch.dict(os.environ, env_without, clear=True):
            with pytest.raises(KeyError):
                build_llm_client()

    def test_unknown_mode_raises(self):
        with patch.dict(os.environ, {"LLM_MODE": "bogus_mode"}):
            with pytest.raises(ValueError, match="Unknown LLM_MODE"):
                build_llm_client()

    def test_direct_mode_google_provider(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MODE": "direct",
                "LLM_PROVIDER": "google",
                "LLM_MODEL_DIRECT": "gemini-2.5-flash",
                "GOOGLE_API_KEY": "fake-key",
            },
        ):
            client = build_llm_client()
            assert client is not None
            assert hasattr(client, "chat")

    def test_direct_mode_openai_provider(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MODE": "direct",
                "LLM_PROVIDER": "openai",
                "LLM_MODEL_DIRECT": "gpt-4o-mini",
                "OPENAI_API_KEY": "fake-key",
            },
        ):
            client = build_llm_client()
            assert client is not None


# ── FactExtractor tests ───────────────────────────────────────────────────────


class TestFactExtractor:
    def _make_mock_llm_response(self, facts_json: str):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = facts_json
        return mock_response

    def test_extract_returns_fact_list(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_llm_response(
            json.dumps(
                [
                    {
                        "fact_type": "identity",
                        "content": "Sunrise Dental is a family practice.",
                        "confidence": 0.9,
                        "raw_evidence": "Sunrise Dental — family practice.",
                    }
                ]
            )
        )
        extractor = FactExtractor(llm_client=mock_client)
        facts = extractor.extract(
            page_text="Sunrise Dental — family practice.",
            page_url="http://localhost:8888/dental/",
            page_type="homepage",
            page_score=4,
            industry="dental",
        )
        assert len(facts) == 1
        assert facts[0].fact_type == "identity"

    def test_extract_filters_low_confidence(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_llm_response(
            json.dumps(
                [
                    {
                        "fact_type": "pricing",
                        "content": "Competitive pricing.",
                        "confidence": 0.2,
                        "raw_evidence": "Competitive pricing.",
                        "price_min": None,
                        "price_max": None,
                        "price_unit": None,
                    }
                ]
            )
        )
        extractor = FactExtractor(llm_client=mock_client)
        facts = extractor.extract(
            page_text="Competitive pricing.",
            page_url="http://localhost:8888/dental/pricing",
            page_type="pricing",
            page_score=4,
            industry="dental",
        )
        assert facts == []

    def test_extract_handles_llm_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("LLM timeout")
        extractor = FactExtractor(llm_client=mock_client)
        facts = extractor.extract(
            page_text="Some text",
            page_url="http://localhost:8888/dental/",
            page_type="homepage",
            page_score=4,
            industry="dental",
        )
        assert facts == []
