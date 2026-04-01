"""SQLite repositories."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from ai_repo_agent.core.models import (
    AppSettings,
    ChatMessageRecord,
    ChatSessionRecord,
    DependencyRecord,
    EmbeddingChunkRecord,
    FileRecord,
    FileVersionRecord,
    FindingDeltaRecord,
    FindingRecord,
    LLMReviewRecord,
    PatchSuggestionRecord,
    RepoSnapshotRecord,
    RepositoryRecord,
    ScanRunRecord,
    SymbolRecord,
)


class BaseRepository:
    """Base repository wrapper."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection


class RepositoryStore(BaseRepository):
    """Persistence for tracked repositories."""

    def upsert(self, record: RepositoryRecord) -> RepositoryRecord:
        self.connection.execute(
            """
            INSERT INTO repositories(path, name, is_git_repo, fingerprint)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name=excluded.name,
                is_git_repo=excluded.is_git_repo,
                fingerprint=excluded.fingerprint,
                updated_at=CURRENT_TIMESTAMP
            """,
            (record.path, record.name, int(record.is_git_repo), record.fingerprint),
        )
        self.connection.commit()
        stored = self.get_by_path(record.path)
        if stored is None:
            raise RuntimeError(f"Repository upsert failed for path '{record.path}'.")
        return stored

    def get_by_id(self, repo_id: int) -> RepositoryRecord:
        row = self.connection.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Repository id '{repo_id}' was not found.")
        return RepositoryRecord(**dict(row))

    def get_by_path(self, path: str) -> RepositoryRecord | None:
        row = self.connection.execute("SELECT * FROM repositories WHERE path = ?", (path,)).fetchone()
        return RepositoryRecord(**dict(row)) if row else None

    def list_all(self) -> list[RepositoryRecord]:
        rows = self.connection.execute("SELECT * FROM repositories ORDER BY updated_at DESC").fetchall()
        return [RepositoryRecord(**dict(row)) for row in rows]


class SnapshotStore(BaseRepository):
    """Persistence for repo snapshots."""

    def create(self, record: RepoSnapshotRecord) -> RepoSnapshotRecord:
        cursor = self.connection.execute(
            """
            INSERT INTO repo_snapshots(repo_id, created_at, branch, commit_hash, dirty_flag,
                changed_files_count, diff_summary, scan_metadata, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.repo_id,
                record.created_at,
                record.branch,
                record.commit_hash,
                int(record.dirty_flag),
                record.changed_files_count,
                record.diff_summary,
                record.scan_metadata,
                record.summary,
            ),
        )
        self.connection.commit()
        return self.get(cursor.lastrowid)

    def get(self, snapshot_id: int) -> RepoSnapshotRecord:
        row = self.connection.execute("SELECT * FROM repo_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return RepoSnapshotRecord(**dict(row))

    def latest_for_repo(self, repo_id: int) -> RepoSnapshotRecord | None:
        row = self.connection.execute(
            "SELECT * FROM repo_snapshots WHERE repo_id = ? ORDER BY id DESC LIMIT 1",
            (repo_id,),
        ).fetchone()
        return RepoSnapshotRecord(**dict(row)) if row else None

    def previous_for_repo(self, repo_id: int, current_snapshot_id: int) -> RepoSnapshotRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM repo_snapshots
            WHERE repo_id = ? AND id < ?
            ORDER BY id DESC LIMIT 1
            """,
            (repo_id, current_snapshot_id),
        ).fetchone()
        return RepoSnapshotRecord(**dict(row)) if row else None

    def list_for_repo(self, repo_id: int) -> list[RepoSnapshotRecord]:
        rows = self.connection.execute(
            "SELECT * FROM repo_snapshots WHERE repo_id = ? ORDER BY id DESC",
            (repo_id,),
        ).fetchall()
        return [RepoSnapshotRecord(**dict(row)) for row in rows]


class FileStore(BaseRepository):
    """Persistence for files and file versions."""

    def upsert_file(self, record: FileRecord) -> int:
        self.connection.execute(
            """
            INSERT INTO files(repo_id, path, size, sha256, language, is_binary)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id, path) DO UPDATE SET
                size=excluded.size,
                sha256=excluded.sha256,
                language=excluded.language,
                is_binary=excluded.is_binary
            """,
            (record.repo_id, record.path, record.size, record.sha256, record.language, int(record.is_binary)),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT id FROM files WHERE repo_id = ? AND path = ?",
            (record.repo_id, record.path),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"File upsert failed for repo_id={record.repo_id} path='{record.path}'.")
        return int(row["id"])

    def add_version(self, record: FileVersionRecord) -> None:
        self.connection.execute(
            "INSERT INTO file_versions(file_id, snapshot_id, sha256, lines) VALUES (?, ?, ?, ?)",
            (record.file_id, record.snapshot_id, record.sha256, record.lines),
        )
        self.connection.commit()

    def list_for_repo(self, repo_id: int) -> list[FileRecord]:
        rows = self.connection.execute("SELECT * FROM files WHERE repo_id = ? ORDER BY path", (repo_id,)).fetchall()
        return [FileRecord(**dict(row)) for row in rows]

    def changed_paths_between_snapshots(self, previous_snapshot_id: int, current_snapshot_id: int) -> list[str]:
        previous_rows = self.connection.execute(
            """
            SELECT f.path, fv.sha256
            FROM file_versions fv
            JOIN files f ON f.id = fv.file_id
            WHERE fv.snapshot_id = ?
            """,
            (previous_snapshot_id,),
        ).fetchall()
        current_rows = self.connection.execute(
            """
            SELECT f.path, fv.sha256
            FROM file_versions fv
            JOIN files f ON f.id = fv.file_id
            WHERE fv.snapshot_id = ?
            """,
            (current_snapshot_id,),
        ).fetchall()
        previous_map = {row["path"]: row["sha256"] for row in previous_rows}
        current_map = {row["path"]: row["sha256"] for row in current_rows}
        changed = {
            path
            for path in set(previous_map) | set(current_map)
            if previous_map.get(path) != current_map.get(path)
        }
        return sorted(changed)


class DependencyStore(BaseRepository):
    """Persistence for dependencies."""

    def replace_for_snapshot(self, snapshot_id: int, dependencies: list[DependencyRecord]) -> None:
        self.connection.execute("DELETE FROM dependencies WHERE snapshot_id = ?", (snapshot_id,))
        self.connection.executemany(
            """
            INSERT INTO dependencies(snapshot_id, ecosystem, name, version, manifest_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(d.snapshot_id, d.ecosystem, d.name, d.version, d.manifest_path) for d in dependencies],
        )
        self.connection.commit()

    def list_for_snapshot(self, snapshot_id: int) -> list[DependencyRecord]:
        rows = self.connection.execute("SELECT * FROM dependencies WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
        return [DependencyRecord(**dict(row)) for row in rows]


class SymbolStore(BaseRepository):
    """Persistence for extracted symbols."""

    def replace_for_snapshot(self, snapshot_id: int, symbols: list[SymbolRecord]) -> None:
        self.connection.execute("DELETE FROM symbols WHERE snapshot_id = ?", (snapshot_id,))
        self.connection.executemany(
            """
            INSERT INTO symbols(snapshot_id, file_path, symbol_name, symbol_kind, line_start, line_end)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(s.snapshot_id, s.file_path, s.symbol_name, s.symbol_kind, s.line_start, s.line_end) for s in symbols],
        )
        self.connection.commit()

    def list_for_snapshot(self, snapshot_id: int) -> list[SymbolRecord]:
        rows = self.connection.execute("SELECT * FROM symbols WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
        return [SymbolRecord(**dict(row)) for row in rows]


class EmbeddingStore(BaseRepository):
    """Persistence for chunked repo memory."""

    def replace_for_snapshot(self, snapshot_id: int, chunks: list[EmbeddingChunkRecord]) -> None:
        self.connection.execute("DELETE FROM embedding_chunks WHERE snapshot_id = ?", (snapshot_id,))
        self.connection.executemany(
            """
            INSERT INTO embedding_chunks(snapshot_id, file_path, chunk_text, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            [(c.snapshot_id, c.file_path, c.chunk_text, c.metadata_json) for c in chunks],
        )
        self.connection.commit()

    def list_for_snapshot(self, snapshot_id: int) -> list[EmbeddingChunkRecord]:
        rows = self.connection.execute(
            "SELECT * FROM embedding_chunks WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [EmbeddingChunkRecord(**dict(row)) for row in rows]


class FindingStore(BaseRepository):
    """Persistence for findings and deltas."""

    def add_many(self, snapshot_id: int, findings: list[FindingRecord]) -> list[FindingRecord]:
        created: list[FindingRecord] = []
        for finding in findings:
            cursor = self.connection.execute(
                """
                INSERT INTO findings(repo_snapshot_id, scanner_name, rule_id, title, description, severity,
                    category, file_path, line_start, line_end, fingerprint, raw_payload, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    finding.scanner_name,
                    finding.rule_id,
                    finding.title,
                    finding.description,
                    finding.severity,
                    finding.category,
                    finding.file_path,
                    finding.line_start,
                    finding.line_end,
                    finding.fingerprint,
                    finding.raw_payload,
                    finding.status,
                ),
            )
            row = self.connection.execute("SELECT * FROM findings WHERE id = ?", (cursor.lastrowid,)).fetchone()
            created.append(FindingRecord(**dict(row)))
        self.connection.commit()
        return created

    def list_for_snapshot(self, snapshot_id: int) -> list[FindingRecord]:
        rows = self.connection.execute(
            "SELECT * FROM findings WHERE repo_snapshot_id = ? ORDER BY severity DESC, scanner_name",
            (snapshot_id,),
        ).fetchall()
        return [FindingRecord(**dict(row)) for row in rows]

    def add_deltas(self, deltas: list[FindingDeltaRecord]) -> None:
        self.connection.executemany(
            """
            INSERT INTO finding_deltas(repo_id, previous_finding_id, current_finding_id, delta_type, summary)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(d.repo_id, d.previous_finding_id, d.current_finding_id, d.delta_type, d.summary) for d in deltas],
        )
        self.connection.commit()


class ScanRunStore(BaseRepository):
    """Persistence for scan execution records."""

    def create(self, record: ScanRunRecord) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO scan_runs(repo_id, snapshot_id, started_at, finished_at, status, scanner_name, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.repo_id,
                record.snapshot_id,
                record.started_at,
                record.finished_at,
                record.status,
                record.scanner_name,
                record.message,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_status(self, run_id: int, status: str, message: str, finished_at: str | None = None) -> None:
        self.connection.execute(
            "UPDATE scan_runs SET status = ?, message = ?, finished_at = ? WHERE id = ?",
            (status, message, finished_at, run_id),
        )
        self.connection.commit()


class ReviewStore(BaseRepository):
    """Persistence for LLM reviews and cache."""

    def save_review(self, record: LLMReviewRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO llm_reviews(target_type, finding_id, snapshot_id, model_name, prompt_version,
                verdict, confidence, severity_override, reasoning_summary, remediation_summary,
                evidence_hash, raw_response, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.target_type,
                record.finding_id,
                record.snapshot_id,
                record.model_name,
                record.prompt_version,
                record.verdict,
                record.confidence,
                record.severity_override,
                record.reasoning_summary,
                record.remediation_summary,
                record.evidence_hash,
                record.raw_response,
                record.created_at,
            ),
        )
        self.connection.commit()

    def get_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT response_json FROM llm_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def set_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO llm_cache(cache_key, response_json) VALUES (?, ?)",
            (cache_key, json.dumps(payload)),
        )
        self.connection.commit()

    def list_for_snapshot(self, snapshot_id: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM llm_reviews WHERE snapshot_id = ? ORDER BY id DESC",
            (snapshot_id,),
        ).fetchall()


class ChatStore(BaseRepository):
    """Persistence for repo chat sessions and messages."""

    def create_session(self, record: ChatSessionRecord) -> ChatSessionRecord:
        cursor = self.connection.execute(
            "INSERT INTO chat_sessions(repo_id, title, created_at) VALUES (?, ?, ?)",
            (record.repo_id, record.title, record.created_at),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT * FROM chat_sessions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return ChatSessionRecord(**dict(row))

    def add_message(self, record: ChatMessageRecord) -> ChatMessageRecord:
        cursor = self.connection.execute(
            "INSERT INTO chat_messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (record.session_id, record.role, record.content, record.created_at),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT * FROM chat_messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return ChatMessageRecord(**dict(row))

    def list_sessions(self, repo_id: int) -> list[ChatSessionRecord]:
        rows = self.connection.execute("SELECT * FROM chat_sessions WHERE repo_id = ? ORDER BY id DESC", (repo_id,)).fetchall()
        return [ChatSessionRecord(**dict(row)) for row in rows]

    def list_messages(self, session_id: int) -> list[ChatMessageRecord]:
        rows = self.connection.execute("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [ChatMessageRecord(**dict(row)) for row in rows]


class PatchSuggestionStore(BaseRepository):
    """Persistence for generated patch suggestions."""

    def add(self, record: PatchSuggestionRecord) -> PatchSuggestionRecord:
        cursor = self.connection.execute(
            """
            INSERT INTO patch_suggestions(snapshot_id, finding_id, summary, rationale, suggested_diff, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.snapshot_id,
                record.finding_id,
                record.summary,
                record.rationale,
                record.suggested_diff,
                record.confidence,
                record.created_at,
            ),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT * FROM patch_suggestions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return PatchSuggestionRecord(**dict(row))

    def list_for_snapshot(self, snapshot_id: int) -> list[PatchSuggestionRecord]:
        rows = self.connection.execute(
            "SELECT * FROM patch_suggestions WHERE snapshot_id = ? ORDER BY id DESC",
            (snapshot_id,),
        ).fetchall()
        return [PatchSuggestionRecord(**dict(row)) for row in rows]


class SettingsStore(BaseRepository):
    """Persistence for app settings."""

    def load(self) -> AppSettings:
        defaults = asdict(AppSettings())
        rows = self.connection.execute("SELECT key, value FROM app_settings").fetchall()
        for row in rows:
            key = row["key"]
            if key not in defaults:
                continue
            default = defaults[key]
            if isinstance(default, bool):
                defaults[key] = row["value"] == "1"
            elif isinstance(default, int):
                defaults[key] = int(row["value"])
            else:
                defaults[key] = row["value"]
        return AppSettings(**defaults)

    def save(self, settings: AppSettings) -> None:
        self.connection.executemany(
            "INSERT OR REPLACE INTO app_settings(key, value) VALUES (?, ?)",
            [(key, "1" if value is True else "0" if value is False else str(value)) for key, value in asdict(settings).items()],
        )
        self.connection.commit()
