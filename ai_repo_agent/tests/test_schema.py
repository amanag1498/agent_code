"""Basic schema smoke test."""

from __future__ import annotations

from ai_repo_agent.db.database import connect_database


def test_schema_initializes(tmp_path) -> None:
    connection = connect_database(str(tmp_path / "test.db"))
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in tables}
    assert "repositories" in table_names
    assert "llm_reviews" in table_names
    assert "chat_sessions" in table_names
    assert "patch_suggestions" in table_names
