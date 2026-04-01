"""Dependency detection."""

from __future__ import annotations

import json
from pathlib import Path

from ai_repo_agent.core.models import DependencyDescriptor


class DependencyAnalyzer:
    """Read common dependency manifests."""

    def detect(self, root: Path) -> list[DependencyDescriptor]:
        dependencies: list[DependencyDescriptor] = []
        package_json = root / "package.json"
        if package_json.exists():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                for name, version in data.get(section, {}).items():
                    dependencies.append(DependencyDescriptor("npm", name, str(version), "package.json"))
        requirements = root / "requirements.txt"
        if requirements.exists():
            for line in requirements.read_text(encoding="utf-8").splitlines():
                clean = line.strip()
                if not clean or clean.startswith("#"):
                    continue
                name, _, version = clean.partition("==")
                dependencies.append(DependencyDescriptor("python", name, version or None, "requirements.txt"))
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            dependencies.append(DependencyDescriptor("python", "pyproject-managed", None, "pyproject.toml"))
        cargo = root / "Cargo.toml"
        if cargo.exists():
            dependencies.append(DependencyDescriptor("rust", "cargo-managed", None, "Cargo.toml"))
        return dependencies
