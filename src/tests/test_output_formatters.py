"""Tests for the one-shot snapshot formatters (#126)."""

import json

from claude_monitor.output import build_snapshot, format_json, format_text

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
