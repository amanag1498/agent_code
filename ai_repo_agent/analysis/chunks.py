"""Chunking for local repo memory and retrieval."""

from __future__ import annotations

from pathlib import Path

from ai_repo_agent.core.models import ChunkDescriptor, FileInventoryItem


class ChunkBuilder:
    """Create bounded text chunks for retrieval and future embeddings."""

    def build(self, files: list[FileInventoryItem], max_lines: int = 80) -> list[ChunkDescriptor]:
        chunks: list[ChunkDescriptor] = []
        for item in files:
            if item.is_binary or item.size > 250_000:
                continue
            path = Path(item.absolute_path)
            text = path.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            if not lines:
                continue
            for start in range(0, len(lines), max_lines):
                end = min(start + max_lines, len(lines))
                chunk_text = "\n".join(lines[start:end])
                chunks.append(
                    ChunkDescriptor(
                        file_path=item.path,
                        chunk_text=chunk_text,
                        metadata={"line_start": start + 1, "line_end": end, "language": item.language},
                    )
                )
        return chunks
