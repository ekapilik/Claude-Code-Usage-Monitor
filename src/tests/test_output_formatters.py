"""Tests for the one-shot snapshot formatters (#126)."""

import json

from claude_monitor.output import (
    build_snapshot,
    format_compact,
    format_json,
    format_text,
)

_SNAP = {
    "schema_version": "1.0",
    "stale": False,
    "confidence": "local_estimate",
    "limits": {"five_hour": {"used_percentage": 63.2, "resets_at": None}},
    "local": {"model_distribution": [{"family": "opus", "percentage": 71.3}]},
}


def test_format_json_roundtrips() -> None:
    assert json.loads(format_json(_SNAP)) == _SNAP


def test_format_json_rejects_non_finite() -> None:
    """A stray NaN/Infinity must raise, never emit invalid JSON for consumers."""
    import pytest

    with pytest.raises(ValueError):
        format_json({"x": float("nan")})


def test_format_json_indent_and_unicode() -> None:
    out = format_json({"k": "zażółć"})
    assert "\n  " in out  # indent=2
    assert "zażółć" in out  # ensure_ascii=False


def test_format_text_greppable_key_value_lines() -> None:
    out = format_text(_SNAP)
    assert "schema_version=1.0" in out
    assert "limits.five_hour.used_percentage=63.2" in out
    assert "local.model_distribution[0].family=opus" in out
    # None renders as the explicit token 'null' (distinct from an empty string)
    assert "limits.five_hour.resets_at=null" in out
    assert "resets_at=None" not in out


def test_format_text_escapes_newlines_in_values() -> None:
    """A value with a newline must not split into a second, malformed line."""
    out = format_text({"source": {"data_paths": ["/a\nrogue=value"]}})
    assert "/a\\nrogue=value" in out
    # Every emitted line is a single key=value record (no bare continuation line).
    assert all("=" in line for line in out.splitlines())


def test_format_text_no_rich_markup() -> None:
    out = format_text(_SNAP)
    assert "[" not in out.replace("[0]", "").replace("[1]", "")  # no [value] markup


def test_package_exports_build_snapshot() -> None:
    assert callable(build_snapshot)


def test_format_compact_single_line() -> None:
    snap = {
        "limits": {
            "five_hour": {
                "used_percentage": 63.2,
                "tokens_used": 12008,
                "token_limit": 19000,
                "resets_at": "2026-06-27T17:00:00+00:00",
            }
        },
        "local": {"burn_rate_tokens_per_minute": 158.4, "cost_usd": 4.27},
    }
    line = format_compact(snap)
    assert "\n" not in line
    assert "63.2%" in line
    assert "12.0K/19.0K" in line
    assert "158/min" in line
    assert "reset 17:00" in line
    assert "$4.27" in line


def test_format_compact_handles_missing_fields() -> None:
    line = format_compact({"limits": {"five_hour": {}}, "local": {}})
    assert "\n" not in line
    assert "--%" in line
    assert "reset --:--" in line


def test_format_compact_official_omits_token_detail() -> None:
    """Official limits have no token counts -> no misleading (0/?) parenthetical."""
    snap = {
        "limits": {
            "five_hour": {
                "used_percentage": 73.5,
                "tokens_used": None,
                "token_limit": None,
                "resets_at": "2026-06-27T17:00:00+00:00",
                "confidence": "official",
            }
        },
        "local": {"burn_rate_tokens_per_minute": 200.0, "cost_usd": 9.0},
    }
    line = format_compact(snap)
    assert "73.5%" in line
    assert "(" not in line  # no token parenthetical
    assert "claude 73.5% |" in line


def test_format_compact_includes_pace_token() -> None:
    snap = {
        "limits": {"five_hour": {"used_percentage": 75.0}},
        "local": {},
        "pace": {"label": "slow down", "confidence": "official"},
    }

    line = format_compact(snap)

    assert "pace=slow-down" in line


def test_format_compact_weekly_renders_only_official_seven_day() -> None:
    local_only = {
        "limits": {
            "five_hour": {"used_percentage": 60.0},
            "seven_day": {"used_percentage": None, "confidence": "unknown"},
        },
        "local": {},
    }
    official_weekly = {
        "limits": {
            "five_hour": {"used_percentage": 60.0},
            "seven_day": {"used_percentage": 18.0, "confidence": "official"},
        },
        "local": {},
    }

    assert "7d" not in format_compact(local_only)
    assert "7d 18.0%" in format_compact(official_weekly)
