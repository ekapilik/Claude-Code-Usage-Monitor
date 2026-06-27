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
