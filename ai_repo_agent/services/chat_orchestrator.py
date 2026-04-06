"""Repo chat orchestration."""

from __future__ import annotations

from datetime import datetime
import logging

from ai_repo_agent.core.models import ChatMessageRecord, ChatSessionRecord
from ai_repo_agent.db.repositories import ChatStore, EmbeddingStore, ReviewStore
from ai_repo_agent.llm.provider import ProviderBase
from ai_repo_agent.llm.workflows import RepoChatLLMService

LOGGER = logging.getLogger(__name__)


class ChatOrchestrator:
    """Persist chat sessions and answer questions from local repo memory."""

    def __init__(self, chat_store: ChatStore, embedding_store: EmbeddingStore, review_store: ReviewStore, provider: ProviderBase | None) -> None:
        self.chat_store = chat_store
        self.embedding_store = embedding_store
        self.review_store = review_store
        self.provider = provider

    def ensure_session(self, repo_id: int, title: str = "Repo Chat") -> ChatSessionRecord:
        sessions = self.chat_store.list_sessions(repo_id)
        return sessions[0] if sessions else self.chat_store.create_session(
            ChatSessionRecord(id=None, repo_id=repo_id, title=title, created_at=datetime.utcnow().isoformat(timespec="seconds"))
        )

    def ask(self, repo_id: int, snapshot_id: int, question: str) -> str:
        LOGGER.info("Starting repo chat request: repo_id=%s snapshot_id=%s", repo_id, snapshot_id)
        session = self.ensure_session(repo_id)
        self.chat_store.add_message(
            ChatMessageRecord(id=None, session_id=session.id or 0, role="user", content=question, created_at=datetime.utcnow().isoformat(timespec="seconds"))
        )
        if not self.provider:
            answer = "No LLM provider is configured. Update the LLM settings to enable repo chat."
        else:
            history = [{"role": msg.role, "content": msg.content} for msg in self.chat_store.list_messages(session.id or 0)]
            chunks = self.embedding_store.list_for_snapshot(snapshot_id)
            LOGGER.info("Repo chat retrieved %s chunks and %s prior messages", len(chunks), len(history))
            ranked = sorted(chunks, key=lambda chunk: self._chunk_score(chunk, question), reverse=True)
            llm = RepoChatLLMService(self.provider, self.review_store)
            try:
                response = llm.answer(question, ranked[:12], history)
                citations = f"\n\nCited files: {', '.join(response.cited_files[:5])}" if response.cited_files else ""
                answer = f"{response.answer}{citations}"
                LOGGER.info("Repo chat completed successfully for repo_id=%s snapshot_id=%s", repo_id, snapshot_id)
            except Exception as exc:
                LOGGER.warning("Repo chat LLM request failed: %s", exc)
                answer = f"LLM chat request failed: {exc}"
        self.chat_store.add_message(
            ChatMessageRecord(id=None, session_id=session.id or 0, role="assistant", content=answer, created_at=datetime.utcnow().isoformat(timespec="seconds"))
        )
        return answer

    @staticmethod
    def _chunk_score(chunk, question: str) -> int:
        import json
        import re

        terms = [term for term in re.findall(r"[a-zA-Z_]{3,}", question.lower()) if len(term) >= 3]
        metadata = {}
        try:
            metadata = json.loads(chunk.metadata_json)
        except Exception:
            metadata = {}
        haystack = f"{chunk.file_path}\n{chunk.chunk_text}\n{chunk.metadata_json}".lower()
        score = 0
        for term in terms:
            if term in chunk.file_path.lower():
                score += 9
            if term in haystack:
                score += 3
            if term in " ".join(metadata.get("imports", [])).lower():
                score += 5
        if metadata.get("chunk_kind") in {"function", "method", "class"}:
            score += 4
        if "test" in chunk.file_path.lower():
            score -= 3
        return score
