"""Formatters for the one-shot snapshot (#126): json and greppable text."""

from __future__ import annotations

import json
from typing import Any, List


def format_json(snapshot: dict) -> str:
    """Pretty, stable JSON (indent=2, unicode preserved)."""
    return json.dumps(snapshot, indent=2, ensure_ascii=False)


def format_text(snapshot: dict) -> str:
    """Flat, greppable ``dotted.key=value`` lines with no Rich markup."""
    lines: List[str] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, val in value.items():
                walk(f"{prefix}.{key}" if prefix else key, val)
        elif isinstance(value, list):
            for i, val in enumerate(value):
                walk(f"{prefix}[{i}]", val)
        else:
            lines.append(f"{prefix}={'null' if value is None else value}")

    walk("", snapshot)
    return "\n".join(lines)
