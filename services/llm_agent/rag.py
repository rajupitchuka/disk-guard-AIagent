"""RAG retrieval — cosine similarity search over the pgvector knowledge_docs
table. Used by the LLM agent to ground its reasoning in runbooks + past
incident records.

The embedding model is loaded lazily (first call) so unit tests that don't
need RAG don't pay the model-load cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from shared.config import settings
from shared.db import pgvector_conn

log = logging.getLogger(__name__)

_model: Optional[SentenceTransformer] = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        log.info("loading embedding model %s", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model)
    return _model


@dataclass
class RetrievedDoc:
    doc_id: str
    source: str
    title: str
    content: str
    metadata: dict
    similarity: float  # 0..1, higher = more similar


def search(query: str, top_k: int = 5) -> list[RetrievedDoc]:
    model = _get_model()
    embedding = model.encode([query], normalize_embeddings=True)[0].tolist()

    with pgvector_conn() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_id, source, title, content, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_docs
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding, embedding, top_k),
            )
            rows = cur.fetchall()

    return [
        RetrievedDoc(
            doc_id=r["doc_id"],
            source=r["source"],
            title=r["title"],
            content=r["content"],
            metadata=r["metadata"] or {},
            similarity=float(r["similarity"]),
        )
        for r in rows
    ]


def format_for_prompt(docs: list[RetrievedDoc]) -> str:
    """Render retrieved docs as a single context block for the LLM."""
    if not docs:
        return "No relevant runbook content found."
    lines = []
    for i, d in enumerate(docs, 1):
        lines.append(
            f"[{i}] {d.title} (source={d.source}, similarity={d.similarity:.2f})\n{d.content}"
        )
    return "\n\n".join(lines)
