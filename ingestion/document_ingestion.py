"""Document ingestion — parse PDF/DOCX/TXT → chunk → extract facts → embed → upsert."""

import logging
from dataclasses import dataclass
from pathlib import Path

from embedder.base import AbstractEmbedder
from extractor.fact_extractor import FactExtractor
from extractor.llm_client import build_llm_client
from extractor.schemas import AnyFact
from store.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_CHUNK = 1500
# Rough words-per-token ratio for English text
_WORDS_PER_TOKEN = 0.75
MAX_WORDS_PER_CHUNK = int(MAX_TOKENS_PER_CHUNK * _WORDS_PER_TOKEN)


@dataclass
class DocumentChunk:
    text: str
    document_name: str
    page_number: int
    section_heading: str | None = None


def parse_document(file_path: str) -> str:
    """Parse a PDF, DOCX, or TXT file and return extracted text.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file extension is not supported.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()

    if ext == ".txt":
        return path.read_text(encoding="utf-8")

    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError(
                "pdfplumber is required for PDF parsing: pip install pdfplumber"
            ) from exc
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        return "\n\n".join(text_parts)

    if ext in (".docx", ".doc"):
        try:
            import docx
        except ImportError as exc:
            raise ImportError(
                "python-docx is required for DOCX parsing: pip install python-docx"
            ) from exc
        doc = docx.Document(file_path)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())

    raise ValueError(f"Unsupported file extension '{ext}'. Supported: .txt, .pdf, .docx")


def chunk_document(
    text: str,
    document_name: str,
    max_words: int = MAX_WORDS_PER_CHUNK,
) -> list[DocumentChunk]:
    """Split document text into chunks with metadata.

    Strategy:
    1. Split on structural boundaries (double newlines = paragraph / section breaks).
    2. Apply max_words guard — if a section exceeds the limit, split by sentence.
    3. Each chunk carries its page_number (sequential) and nearest section_heading.
    """
    if not text or not text.strip():
        return []

    raw_sections = _split_into_sections(text)
    chunks: list[DocumentChunk] = []
    page_number = 1
    current_heading: str | None = None

    for raw_section in raw_sections:
        raw_section = raw_section.strip()
        if not raw_section:
            continue

        # If the first line of this section is a markdown heading, extract it
        lines = raw_section.split("\n")
        if lines[0].startswith("#"):
            current_heading = lines[0].lstrip("#").strip()
            content = "\n".join(lines[1:]).strip()
        else:
            content = raw_section

        if not content:
            continue  # heading-only section — no content to chunk

        words = content.split()
        if len(words) <= max_words:
            chunks.append(
                DocumentChunk(
                    text=content,
                    document_name=document_name,
                    page_number=page_number,
                    section_heading=current_heading,
                )
            )
            page_number += 1
        else:
            # Section is too long — split by word count
            for sub_chunk in _split_by_words(content, max_words):
                chunks.append(
                    DocumentChunk(
                        text=sub_chunk,
                        document_name=document_name,
                        page_number=page_number,
                        section_heading=current_heading,
                    )
                )
                page_number += 1

    return chunks


def _split_into_sections(text: str) -> list[str]:
    """Split text on double newlines (paragraph/section boundaries)."""
    return [s for s in text.split("\n\n") if s.strip()]


def _split_by_words(text: str, max_words: int) -> list[str]:
    """Split text into word-count-bounded chunks."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


def ingest_document(
    client_id: str,
    file_path: str,
    document_name: str,
    store: QdrantStore,
    embedder: AbstractEmbedder,
    extractor: FactExtractor | None = None,
) -> dict:
    """Parse, chunk, extract, embed, and upsert a single document.

    Idempotent: deletes all existing Qdrant points for this document
    (keyed by client_id + document_name) before upserting new ones.

    Args:
        client_id: The client this document belongs to.
        file_path: Absolute path to the file.
        document_name: Display name / filename for the document.
        store: Qdrant store instance.
        embedder: Embedder instance.
        extractor: FactExtractor instance. Built from env if not provided.

    Returns:
        dict with keys: chunks_processed, facts_upserted.
    """
    if extractor is None:
        extractor = FactExtractor(llm_client=build_llm_client())

    # Parse the file to raw text
    raw_text = parse_document(file_path)

    # Chunk into page-sized sections
    chunks = chunk_document(raw_text, document_name=document_name)
    logger.info("[%s] %s → %d chunks", client_id, document_name, len(chunks))

    # Delete stale facts for this document before upserting
    store.delete_by_payload(client_id=client_id, document_name=document_name)

    facts_upserted = 0

    for chunk in chunks:
        facts: list[AnyFact] = extractor.extract(
            page_text=chunk.text,
            page_url=f"doc://{document_name}",
            page_type="document",
            page_score=3,
            industry="general",
        )

        for fact in facts:
            embed_text = f"{fact.fact_type}: {fact.content}"
            vector = embedder.embed(embed_text)

            store.upsert_fact(
                client_id=client_id,
                fact=fact,
                vector=vector,
                source_url=f"doc://{document_name}",
                page_type="document",
                page_score=3,
                content_hash=f"doc:{document_name}:chunk{chunk.page_number}",
                source_type="document",
                extra_payload={
                    "document_name": document_name,
                    "page_number": chunk.page_number,
                    "section_heading": chunk.section_heading,
                },
            )
            facts_upserted += 1

    logger.info("[%s] %s complete: %d facts upserted", client_id, document_name, facts_upserted)
    return {"chunks_processed": len(chunks), "facts_upserted": facts_upserted}
