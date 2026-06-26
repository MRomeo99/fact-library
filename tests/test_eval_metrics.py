"""Tests for retrieval evaluation metrics — written first (TDD)."""

from quality.eval.metrics import mrr, precision_at_k, source_coverage

HITS_ALL_PRICING = [
    {"fact_type": "pricing", "source_type": "website"},
    {"fact_type": "pricing", "source_type": "knowledge_base"},
    {"fact_type": "pricing", "source_type": "website"},
]

HITS_NO_PRICING = [
    {"fact_type": "service", "source_type": "website"},
    {"fact_type": "location", "source_type": "document"},
    {"fact_type": "operational", "source_type": "website"},
]

HITS_MIXED = [
    {"fact_type": "service", "source_type": "website"},
    {"fact_type": "pricing", "source_type": "knowledge_base"},
    {"fact_type": "pricing", "source_type": "website"},
]


class TestPrecisionAtK:
    def test_all_relevant_returns_1(self):
        assert precision_at_k(HITS_ALL_PRICING, expected_fact_types=["pricing"], k=3) == 1.0

    def test_no_relevant_returns_0(self):
        assert precision_at_k(HITS_NO_PRICING, expected_fact_types=["pricing"], k=3) == 0.0

    def test_mixed_hits_correct_fraction(self):
        # HITS_MIXED: 2 pricing out of 3
        result = precision_at_k(HITS_MIXED, expected_fact_types=["pricing"], k=3)
        assert abs(result - 2 / 3) < 0.001

    def test_respects_k_limit(self):
        # pricing only at position 3 — k=2 must not reach it
        hits = [
            {"fact_type": "service"},
            {"fact_type": "location"},
            {"fact_type": "pricing"},
        ]
        result = precision_at_k(hits, expected_fact_types=["pricing"], k=2)
        assert result == 0.0

    def test_multiple_expected_types_any_match_counts(self):
        hits = [
            {"fact_type": "pricing"},
            {"fact_type": "conditional"},
            {"fact_type": "service"},
        ]
        result = precision_at_k(hits, expected_fact_types=["pricing", "conditional"], k=3)
        assert abs(result - 2 / 3) < 0.001

    def test_empty_hits_returns_0(self):
        assert precision_at_k([], expected_fact_types=["pricing"], k=3) == 0.0

    def test_k_larger_than_hits_uses_all_hits(self):
        hits = [{"fact_type": "pricing"}, {"fact_type": "pricing"}]
        assert precision_at_k(hits, expected_fact_types=["pricing"], k=10) == 1.0


class TestMRR:
    def test_first_hit_relevant_returns_1(self):
        queries = [[{"fact_type": "pricing"}, {"fact_type": "service"}]]
        assert mrr(queries, expected_fact_types_per_query=[["pricing"]]) == 1.0

    def test_second_hit_relevant_returns_half(self):
        queries = [[{"fact_type": "service"}, {"fact_type": "pricing"}]]
        assert mrr(queries, expected_fact_types_per_query=[["pricing"]]) == 0.5

    def test_no_relevant_returns_0(self):
        queries = [[{"fact_type": "service"}, {"fact_type": "location"}]]
        assert mrr(queries, expected_fact_types_per_query=[["pricing"]]) == 0.0

    def test_multiple_queries_averages_reciprocal_ranks(self):
        queries = [
            [{"fact_type": "pricing"}, {"fact_type": "service"}],  # rank 1 → 1.0
            [{"fact_type": "service"}, {"fact_type": "pricing"}],  # rank 2 → 0.5
        ]
        expected = [["pricing"], ["pricing"]]
        result = mrr(queries, expected_fact_types_per_query=expected)
        assert abs(result - 0.75) < 0.001

    def test_empty_queries_returns_0(self):
        assert mrr([], expected_fact_types_per_query=[]) == 0.0

    def test_third_hit_relevant_returns_one_third(self):
        queries = [[{"fact_type": "service"}, {"fact_type": "location"}, {"fact_type": "pricing"}]]
        result = mrr(queries, expected_fact_types_per_query=[["pricing"]])
        assert abs(result - 1 / 3) < 0.001


class TestSourceCoverage:
    def test_kb_fact_in_top_k_returns_true(self):
        hits = [
            {"fact_type": "pricing", "source_type": "knowledge_base"},
            {"fact_type": "pricing", "source_type": "website"},
        ]
        assert source_coverage(hits, expected_source_type="knowledge_base", k=3) is True

    def test_no_kb_fact_returns_false(self):
        hits = [
            {"fact_type": "pricing", "source_type": "website"},
            {"fact_type": "pricing", "source_type": "document"},
        ]
        assert source_coverage(hits, expected_source_type="knowledge_base", k=3) is False

    def test_kb_fact_outside_k_returns_false(self):
        hits = [
            {"fact_type": "pricing", "source_type": "website"},
            {"fact_type": "pricing", "source_type": "website"},
            {"fact_type": "pricing", "source_type": "website"},
            {"fact_type": "pricing", "source_type": "knowledge_base"},
        ]
        assert source_coverage(hits, expected_source_type="knowledge_base", k=3) is False

    def test_document_source_coverage(self):
        hits = [
            {"fact_type": "service", "source_type": "document"},
            {"fact_type": "service", "source_type": "website"},
        ]
        assert source_coverage(hits, expected_source_type="document", k=3) is True

    def test_empty_hits_returns_false(self):
        assert source_coverage([], expected_source_type="knowledge_base", k=3) is False
