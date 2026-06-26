"""Retrieval evaluation metrics: Precision@k, MRR, Source Coverage."""


def precision_at_k(
    hits: list[dict],
    expected_fact_types: list[str],
    k: int = 3,
) -> float:
    """Fraction of the top-k results that contain an expected fact type.

    Args:
        hits: Ranked list of result dicts, each with a 'fact_type' key.
        expected_fact_types: Fact types considered relevant.
        k: Number of top results to evaluate.

    Returns:
        Float in [0.0, 1.0].
    """
    if not hits:
        return 0.0
    top_k = hits[:k]
    relevant = sum(1 for h in top_k if h.get("fact_type") in expected_fact_types)
    return relevant / len(top_k)


def mrr(
    queries_hits: list[list[dict]],
    expected_fact_types_per_query: list[list[str]],
) -> float:
    """Mean Reciprocal Rank across a set of queries.

    For each query, find the rank of the first relevant result. The
    reciprocal rank is 1/rank. MRR is the average across queries.

    Args:
        queries_hits: List of ranked hit lists, one per query.
        expected_fact_types_per_query: Parallel list of expected fact types.

    Returns:
        Float in [0.0, 1.0]. 0.0 if no queries supplied.
    """
    if not queries_hits:
        return 0.0

    reciprocal_ranks = []
    for hits, expected_types in zip(queries_hits, expected_fact_types_per_query):
        rr = 0.0
        for rank, hit in enumerate(hits, start=1):
            if hit.get("fact_type") in expected_types:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def source_coverage(
    hits: list[dict],
    expected_source_type: str,
    k: int = 3,
) -> bool:
    """Whether a fact from the expected source type appears in the top-k results.

    Used to verify that KB facts rank above crawled/document facts when present.

    Args:
        hits: Ranked list of result dicts, each with a 'source_type' key.
        expected_source_type: Source type to look for (e.g. "knowledge_base").
        k: Number of top results to check.

    Returns:
        True if the expected source type appears in hits[:k].
    """
    return any(h.get("source_type") == expected_source_type for h in hits[:k])
