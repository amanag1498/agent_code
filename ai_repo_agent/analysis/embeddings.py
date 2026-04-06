"""Local deterministic embeddings and retrieval helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from ai_repo_agent.core.models import EmbeddingChunkRecord, EmbeddingVectorRecord, RetrievalHit


TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")


@dataclass(slots=True)
class LocalEmbeddingModel:
    """Simple local embedding model based on hashed token features."""

    dimensions: int = 96
    model_name: str = "local-hash-v1"

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 12) / 24.0
            vector[index] += sign * weight
        return self._normalize(vector)

    def content_hash(self, chunk: EmbeddingChunkRecord) -> str:
        return hashlib.sha256(
            f"{chunk.file_path}\n{chunk.chunk_text}\n{chunk.metadata_json}".encode("utf-8")
        ).hexdigest()

    def build_vector_record(self, snapshot_id: int, chunk: EmbeddingChunkRecord) -> EmbeddingVectorRecord:
        return EmbeddingVectorRecord(
            id=None,
            snapshot_id=snapshot_id,
            chunk_id=chunk.id or 0,
            file_path=chunk.file_path,
            vector_json=json.dumps(self.embed_text(chunk.chunk_text)),
            vector_model=self.model_name,
            content_hash=self.content_hash(chunk),
        )

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class EmbeddingRetrievalService:
    """Combine local vector similarity with lightweight ranking heuristics."""

    def __init__(self, model: LocalEmbeddingModel | None = None) -> None:
        self.model = model or LocalEmbeddingModel()

    def rank_for_query(
        self,
        query: str,
        chunks: list[EmbeddingChunkRecord],
        vectors: list[EmbeddingVectorRecord],
        file_priority: set[str] | None = None,
        symbol_priority: set[str] | None = None,
        limit: int = 8,
    ) -> list[RetrievalHit]:
        vector_map = {vector.chunk_id: json.loads(vector.vector_json) for vector in vectors}
        query_vector = self.model.embed_text(query)
        hits: list[RetrievalHit] = []
        for chunk in chunks:
            embedding_score = self._cosine(query_vector, vector_map.get(chunk.id or 0, []))
            lexical_score, reasons = self._heuristic_score(query, chunk, file_priority or set(), symbol_priority or set())
            total = embedding_score * 0.7 + lexical_score * 0.3
            hits.append(RetrievalHit(chunk=chunk, score=total, reasons=reasons))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return self._diversify(hits, limit)

    @staticmethod
    def _heuristic_score(
        query: str,
        chunk: EmbeddingChunkRecord,
        file_priority: set[str],
        symbol_priority: set[str],
    ) -> tuple[float, list[str]]:
        metadata = {}
        try:
            metadata = json.loads(chunk.metadata_json)
        except Exception:
            metadata = {}
        score = 0.0
        reasons: list[str] = []
        haystack = f"{chunk.file_path}\n{chunk.chunk_text}\n{chunk.metadata_json}".lower()
        tokens = {token.lower() for token in TOKEN_RE.findall(query)}
        for token in tokens:
            if token in chunk.file_path.lower():
                score += 0.9
                reasons.append(f"path:{token}")
            if token in haystack:
                score += 0.35
        if chunk.file_path in file_priority:
            score += 1.2
            reasons.append("focused-file")
        if metadata.get("symbol_name") in symbol_priority:
            score += 1.0
            reasons.append("focused-symbol")
        if metadata.get("chunk_kind") in {"function", "method", "class"}:
            score += 0.2
        if "test" in chunk.file_path.lower():
            score -= 0.2
        return score, reasons

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        return sum(left[index] * right[index] for index in range(size))

    @staticmethod
    def _diversify(hits: list[RetrievalHit], limit: int) -> list[RetrievalHit]:
        selected: list[RetrievalHit] = []
        per_file: dict[str, int] = {}
        for hit in hits:
            count = per_file.get(hit.chunk.file_path, 0)
            if count >= 2:
                continue
            selected.append(hit)
            per_file[hit.chunk.file_path] = count + 1
            if len(selected) >= limit:
                break
        return selected
