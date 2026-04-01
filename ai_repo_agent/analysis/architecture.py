"""Architecture heuristics placeholder."""

from __future__ import annotations

from ai_repo_agent.core.models import FileInventoryItem


class ArchitectureMapper:
    """Placeholder architecture observer."""

    def observe(self, files: list[FileInventoryItem]) -> list[str]:
        observations: list[str] = []
        paths = [item.path for item in files]
        if any(path.startswith("src/") for path in paths) and any(path.startswith("tests/") for path in paths):
            observations.append("Source and tests are separated, which suggests conventional layering.")
        if sum(1 for path in paths if path.endswith(".py")) > 100:
            observations.append("Large Python footprint may benefit from AST-based symbol graphing.")
        if any("migrations/" in path for path in paths):
            observations.append("Database migration directories detected.")
        return observations or ["Architecture mapper is using placeholder heuristics."]
