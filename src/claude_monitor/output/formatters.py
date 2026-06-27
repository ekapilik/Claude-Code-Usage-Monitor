"""Formatters for the one-shot snapshot (#126): json and greppable text."""

from __future__ import annotations

import json
import math
from typing import Any, List


def format_json(snapshot: dict) -> str:
    """Pretty, stable JSON (indent=2, unicode preserved).

    ``allow_nan=False`` so a stray non-finite value raises here rather than
    emitting ``NaN``/``Infinity`` literals that are invalid JSON for consumers.
    """
    return json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False)


def _abbrev(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _compact_pace_label(label: Any) -> str:
    return str(label).strip().lower().replace(" ", "-")


def format_compact(snapshot: dict) -> str:
    """One glanceable line from the snapshot: usage, burn rate, reset, cost (#65)."""
    limits = snapshot.get("limits", {})
    five = limits.get("five_hour", {})
    local = snapshot.get("local", {})

    pct = five.get("used_percentage")
    pct_s = f"{pct:.1f}%" if pct is not None else "--%"

    # Official limits report a percentage but no token counts; only show the
    # (used/limit) detail when we actually have a local token count.
    tokens_used = five.get("tokens_used")
    if tokens_used is not None:
        limit = five.get("token_limit")
        used_s = f" ({_abbrev(tokens_used)}/{_abbrev(limit) if limit else '?'})"
    else:
        used_s = ""

    bpm = local.get("burn_rate_tokens_per_minute")
    bpm_s = f"{_abbrev(bpm)}/min" if bpm is not None else "--/min"

    resets_at = five.get("resets_at")
    reset_s = resets_at[11:16] if resets_at else "--:--"  # HH:MM from ISO

    cost = local.get("cost_usd") or 0.0
    parts = [f"claude {pct_s}{used_s}", bpm_s, f"reset {reset_s}"]

    seven = limits.get("seven_day") or {}
    if (
        seven.get("confidence") == "official"
        and seven.get("used_percentage") is not None
    ):
        parts.append(f"7d {seven['used_percentage']:.1f}%")

    pace = snapshot.get("pace") or {}
    pace_label = _compact_pace_label(pace.get("label", ""))
    if pace_label and pace_label != "unknown":
        parts.append(f"pace={pace_label}")

    parts.append(f"${cost:.2f}")
    return " | ".join(parts)


class _MissingTitleValue:
    def __format__(self, _format_spec: str) -> str:
        return "--"

    def __str__(self) -> str:
        return "--"


_MISSING_TITLE_VALUE = _MissingTitleValue()


def _title_number(value: Any) -> Any:
    if value is None:
        return _MISSING_TITLE_VALUE
    if isinstance(value, (int, float)) and not math.isfinite(value):
        return _MISSING_TITLE_VALUE
    return value


def _title_reset(value: Any) -> str:
    if isinstance(value, str) and len(value) >= 16:
        return value[11:16]
    return "--:--"


def format_terminal_title(snapshot: dict, template: str) -> str:
    """Format a terminal title from the canonical snapshot fields (#142)."""
    five = snapshot.get("limits", {}).get("five_hour", {})
    local = snapshot.get("local", {})
    values = {
        "pct": _title_number(five.get("used_percentage")),
        "plan": snapshot.get("plan") or "unknown",
        "used": _title_number(five.get("tokens_used")),
        "limit": _title_number(five.get("token_limit")),
        "cost": _title_number(local.get("cost_usd")),
        "reset": _title_reset(five.get("resets_at")),
    }
    return template.format(**values)


def format_text(snapshot: dict) -> str:
    """Flat, greppable ``dotted.key=value`` lines with no Rich markup."""
    lines: List[str] = []

    def scalar(value: Any) -> str:
        if value is None:
            return "null"
        # Keep one record per line: escape control chars so a value containing a
        # newline can't split into a second, malformed key=value line.
        return (
            str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
        )

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, val in value.items():
                walk(f"{prefix}.{key}" if prefix else key, val)
        elif isinstance(value, list):
            for i, val in enumerate(value):
                walk(f"{prefix}[{i}]", val)
        else:
            lines.append(f"{prefix}={scalar(value)}")

    walk("", snapshot)
    return "\n".join(lines)
