"""Formatters for the one-shot snapshot (#126): json and greppable text."""

from __future__ import annotations

import json
from typing import Any, List


def format_json(snapshot: dict) -> str:
    """Pretty, stable JSON (indent=2, unicode preserved)."""
    return json.dumps(snapshot, indent=2, ensure_ascii=False)


def _abbrev(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def format_compact(snapshot: dict) -> str:
    """One glanceable line from the snapshot: usage, burn rate, reset, cost (#65)."""
    five = snapshot.get("limits", {}).get("five_hour", {})
    local = snapshot.get("local", {})

    pct = five.get("used_percentage")
    pct_s = f"{pct:.1f}%" if pct is not None else "--%"
    limit = five.get("token_limit")
    used_s = f"{_abbrev(five.get('tokens_used') or 0)}/{_abbrev(limit) if limit else '?'}"

    bpm = local.get("burn_rate_tokens_per_minute")
    bpm_s = f"{_abbrev(bpm)}/min" if bpm is not None else "--/min"

    resets_at = five.get("resets_at")
    reset_s = resets_at[11:16] if resets_at else "--:--"  # HH:MM from ISO

    cost = local.get("cost_usd") or 0.0
    return f"claude {pct_s} ({used_s}) | {bpm_s} | reset {reset_s} | ${cost:.2f}"


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
