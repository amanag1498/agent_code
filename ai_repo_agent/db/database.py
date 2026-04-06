"""SQLite database initialization and access."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_git_repo INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS repo_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    branch TEXT,
    commit_hash TEXT,
    dirty_flag INTEGER NOT NULL,
    changed_files_count INTEGER NOT NULL,
    diff_summary TEXT NOT NULL,
    scan_metadata TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY(repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    language TEXT NOT NULL,
    is_binary INTEGER NOT NULL,
    UNIQUE(repo_id, path),
    FOREIGN KEY(repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    lines INTEGER NOT NULL,
    FOREIGN KEY(file_id) REFERENCES files(id),
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_kind TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    ecosystem TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    manifest_path TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_snapshot_id INTEGER NOT NULL,
    scanner_name TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    file_path TEXT,
    line_start INTEGER,
    line_end INTEGER,
    fingerprint TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    status TEXT NOT NULL,
    family_id TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    framework_tags_json TEXT NOT NULL DEFAULT '[]',
    evidence_quality REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY(repo_snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS finding_deltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    previous_finding_id INTEGER,
    current_finding_id INTEGER,
    delta_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY(repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS embedding_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS embedding_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    chunk_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    vector_model TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id),
    FOREIGN KEY(chunk_id) REFERENCES embedding_chunks(id)
);

CREATE TABLE IF NOT EXISTS architecture_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(finding_id) REFERENCES findings(id)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    snapshot_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    scanner_name TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY(repo_id) REFERENCES repositories(id),
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
);

CREATE TABLE IF NOT EXISTS patch_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    finding_id INTEGER,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    suggested_diff TEXT NOT NULL,
    confidence REAL NOT NULL,
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(snapshot_id) REFERENCES repo_snapshots(id),
    FOREIGN KEY(finding_id) REFERENCES findings(id)
);

CREATE TABLE IF NOT EXISTS llm_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    finding_id INTEGER,
    snapshot_id INTEGER,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    severity_override TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    remediation_summary TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect_database(path: str) -> sqlite3.Connection:
    """Open and initialize a SQLite database."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    _apply_additive_migrations(connection)
    connection.commit()
    return connection


def _apply_additive_migrations(connection: sqlite3.Connection) -> None:
    """Add additive columns required by newer app versions."""
    _ensure_columns(
        connection,
        "findings",
        {
            "family_id": "TEXT NOT NULL DEFAULT ''",
            "confidence": "REAL NOT NULL DEFAULT 0.0",
            "framework_tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "evidence_quality": "REAL NOT NULL DEFAULT 0.0",
        },
    )
    _ensure_columns(
        connection,
        "patch_suggestions",
        {
            "alternatives_json": "TEXT NOT NULL DEFAULT '[]'",
            "validation_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name in existing:
            continue
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
