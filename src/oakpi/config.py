"""Configuration loading.

The pipeline reads every tunable value from ``config/config.yml`` so that the
analytical behaviour can be reviewed without reading Python. ``Config`` is a
thin dotted-path accessor over the parsed YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yml"
DEFAULT_DQ_RULES = PROJECT_ROOT / "config" / "dq_rules.yml"


class Config:
    """Dotted-path read access to the YAML configuration."""

    def __init__(self, data: dict[str, Any], root: Path = PROJECT_ROOT) -> None:
        self._data = data
        self.root = root

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        cfg_path = Path(path) if path else DEFAULT_CONFIG
        with open(cfg_path, "r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str, default: str | None = None) -> Path:
        """Resolve a configured relative path against the project root."""
        value = self.get(dotted, default)
        if value is None:
            raise KeyError(f"No path configured at '{dotted}'")
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Config(project={self.get('project.name')!r})"


def load_dq_rules(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    rules_path = Path(path) if path else DEFAULT_DQ_RULES
    with open(rules_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["rules"]
