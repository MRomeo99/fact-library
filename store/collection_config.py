"""Qdrant collection schema definition."""

COLLECTION_NAME = "client_facts"


def get_collection_config() -> dict:
    return {
        "collection_name": COLLECTION_NAME,
        "vector_size": 384,
        "distance": "Cosine",
        # Payload fields indexed for filtering
        "indexed_fields": {
            "client_id": "keyword",
            "fact_type": "keyword",
            "page_type": "keyword",
            "confidence": "float",
            "content_hash": "keyword",
            "source_url": "keyword",
        },
    }
