"""Knowledge retrieval: chunking, embeddings, hybrid search, reranking, and stores.
InMemoryVectorStore runs anywhere; PgVectorStore uses PostgreSQL + pgvector (schema.sql).
The hashing embedder is an offline stand-in: swap in a real embedding model in production."""
from __future__ import annotations
import hashlib, math, re
from typing import Callable, Optional
from .config import EMBED_DIM
from .models import Doc

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    toks = tokens(text)
    vec = [0.0] * dim
    for gram in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]:
        h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 64) % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def chunk_document(text: str, max_words: int = 500, overlap: int = 75) -> list[str]:
    """Semantic chunking: split on blank lines/headings, pack to ~max_words with overlap."""
    units = [u.strip() for u in re.split(r"\n\s*\n", text) if u.strip()]
    chunks, cur = [], []
    for unit in units:
        words = unit.split()
        if cur and len(cur) + len(words) > max_words:
            chunks.append(" ".join(cur))
            cur = cur[-overlap:]
        cur += words
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def ingest(store, doc: Doc) -> None:
    """Chunk a document and store every chunk with the parent's metadata and version info."""
    parts = chunk_document(doc.text)
    for n, part in enumerate(parts or [doc.text]):
        meta = {**doc.metadata, "doc_id": doc.id}
        cid = doc.id if len(parts) <= 1 else f"{doc.id}#{n}"
        store.add(Doc(cid, part, doc.kind, doc.source, doc.version, doc.status,
                      doc.effective, doc.expires, meta))


def _matches(doc: Doc, filters: Optional[dict]) -> bool:
    return all(getattr(doc, k) in v for k, v in (filters or {}).items())


def _rerank(query: str, scored: list[tuple[float, Doc]], k: int) -> list[Doc]:
    qt = set(tokens(query))
    out = []
    for sim, doc in scored:
        kw = len(qt & set(tokens(doc.text))) / max(1, len(qt))
        bonus = 0.05 if doc.status == "active" else 0.0
        out.append((0.6 * sim + 0.4 * kw + bonus + int(doc.effective[:4]) / 1e6, doc))
    return [d for _, d in sorted(out, key=lambda x: -x[0])[:k]]


class InMemoryVectorStore:
    def __init__(self, embedder: Callable[[str], list[float]] = embed):
        self.embedder, self.rows = embedder, []

    def add(self, doc: Doc) -> None:
        self.rows.append((doc, self.embedder(doc.text)))

    def search(self, query: str, k: int = 8, filters: Optional[dict] = None) -> list[Doc]:
        qv = self.embedder(query)
        scored = [(sum(a * b for a, b in zip(qv, v)), d) for d, v in self.rows if _matches(d, filters)]
        return _rerank(query, sorted(scored, key=lambda x: -x[0])[: k * 3], k)


class PgVectorStore:
    """Requires `pip install psycopg[binary]` and the schema in schema.sql."""

    def __init__(self, dsn: str, embedder: Callable[[str], list[float]] = embed):
        import psycopg  # lazy import
        self.conn, self.embedder = psycopg.connect(dsn, autocommit=True), embedder

    @staticmethod
    def _vec(v: list[float]) -> str:
        return "[" + ",".join(f"{x:.6f}" for x in v) + "]"

    def add(self, doc: Doc) -> None:
        import json
        self.conn.execute(
            """INSERT INTO knowledge_chunks (id, kind, source, version, status, effective, expires, text, metadata, embedding)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
               ON CONFLICT (id) DO UPDATE SET kind=EXCLUDED.kind, source=EXCLUDED.source,
                 version=EXCLUDED.version, status=EXCLUDED.status, effective=EXCLUDED.effective,
                 expires=EXCLUDED.expires, text=EXCLUDED.text, metadata=EXCLUDED.metadata,
                 embedding=EXCLUDED.embedding""",
            (doc.id, doc.kind, doc.source, doc.version, doc.status, doc.effective, doc.expires,
             doc.text, json.dumps(doc.metadata), self._vec(self.embedder(doc.text))))

    def search(self, query: str, k: int = 8, filters: Optional[dict] = None) -> list[Doc]:
        kinds = (filters or {}).get("kind")
        rows = self.conn.execute(
            """SELECT id, kind, source, version, status, effective::text, expires::text, text, metadata,
                      1 - (embedding <=> %s::vector) AS sim
               FROM knowledge_chunks WHERE (%s::text[] IS NULL OR kind = ANY(%s))
               ORDER BY embedding <=> %s::vector LIMIT %s""",
            (self._vec(self.embedder(query)), kinds, kinds, self._vec(self.embedder(query)), k * 3)).fetchall()
        scored = [(r[9], Doc(r[0], r[7], r[1], r[2], r[3], r[4], r[5], r[6], r[8])) for r in rows]
        return _rerank(query, scored, k)
