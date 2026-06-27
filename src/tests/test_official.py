"""Tests for the official statusline limits reader (trust keystone)."""

import json
from pathlib import Path

from claude_monitor.output.official import (
    OFFICIAL_TTL_SECONDS,
    capture_statusline,
    default_statusline_path,
    format_statusline,
    read_official_limits,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_default_path_under_claude_monitor() -> None:
    p = default_statusline_path()
    assert p.name == "latest.json"
    assert p.parent.name == "statusline"
    assert ".claude-monitor" in str(p)


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_official_limits(tmp_path / "nope.json", now_epoch=1000) is None


def test_reads_both_windows(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    _write(
        f,
        {
            "captured_at_epoch": 1000,
            "rate_limits": {
                "five_hour": {"used_percentage": 42.5, "resets_at": 5000},
                "seven_day": {"used_percentage": 18.0, "resets_at": 9000},
            },
        },
    )
    out = read_official_limits(f, now_epoch=1100)

    assert out is not None
    assert out["five_hour"] == {"used_percentage": 42.5, "resets_at_epoch": 5000}
    assert out["seven_day"] == {"used_percentage": 18.0, "resets_at_epoch": 9000}
    assert out["captured_at_epoch"] == 1000
    assert out["stale"] is False


def test_fresh_within_ttl_and_stale_beyond(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    _write(
        f,
        {
            "captured_at_epoch": 1000,
            "rate_limits": {"five_hour": {"used_percentage": 10.0, "resets_at": 5000}},
        },
    )
    fresh = read_official_limits(f, now_epoch=1000 + OFFICIAL_TTL_SECONDS)
    stale = read_official_limits(f, now_epoch=1000 + OFFICIAL_TTL_SECONDS + 1)
    assert fresh["stale"] is False
    assert stale["stale"] is True


def test_leak_bug_52326_implausible_percentage_dropped(tmp_path: Path) -> None:
    """used_percentage can carry the resets_at epoch; an epoch-sized value is dropped."""
    f = tmp_path / "latest.json"
    _write(
        f,
        {
            "captured_at_epoch": 1000,
            "rate_limits": {
                "five_hour": {"used_percentage": 1719500000, "resets_at": 5000},
                "seven_day": {"used_percentage": 100.6, "resets_at": 9000},
            },
        },
    )
    out = read_official_limits(f, now_epoch=1100)
    # Epoch leak -> percentage unavailable, but the window/reset still reported.
    assert out["five_hour"]["used_percentage"] is None
    assert out["five_hour"]["resets_at_epoch"] == 5000
    # A small overshoot is a rounding artifact -> clamped to 100.
    assert out["seven_day"]["used_percentage"] == 100.0


def test_no_rate_limits_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    _write(f, {"captured_at_epoch": 1000, "model": {"id": "x"}})
    assert read_official_limits(f, now_epoch=1100) is None


def test_window_past_reset_drops_percentage(tmp_path: Path) -> None:
    """A window whose reset time has passed has rolled over; its old % is invalid."""
    f = tmp_path / "latest.json"
    _write(
        f,
        {
            "captured_at_epoch": 1000,
            "rate_limits": {"five_hour": {"used_percentage": 99.0, "resets_at": 5000}},
        },
    )
    before = read_official_limits(f, now_epoch=4000)  # still inside the window
    after = read_official_limits(f, now_epoch=6000)  # past the reset
    assert before["five_hour"]["used_percentage"] == 99.0
    assert after["five_hour"]["used_percentage"] is None
    assert after["five_hour"]["resets_at_epoch"] == 5000


def test_only_one_window_present(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    _write(
        f,
        {
            "captured_at_epoch": 1000,
            "rate_limits": {"five_hour": {"used_percentage": 30.0, "resets_at": 5000}},
        },
    )
    out = read_official_limits(f, now_epoch=1100)
    assert out["five_hour"]["used_percentage"] == 30.0
    assert out["seven_day"] is None


def test_corrupt_json_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    f.write_text("{not json")
    assert read_official_limits(f, now_epoch=1100) is None


# --- writer (the --statusline hook) ------------------------------------------


def test_capture_round_trips_through_reader(tmp_path: Path) -> None:
    """capture_statusline writes a file read_official_limits can consume."""
    f = tmp_path / "statusline" / "latest.json"
    stdin_payload = {
        "model": {"display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 55.0, "resets_at": 5000},
            "seven_day": {"used_percentage": 20.0, "resets_at": 9000},
        },
    }
    written = capture_statusline(stdin_payload, path=f, now_epoch=1000)
    assert written["captured_at_epoch"] == 1000

    out = read_official_limits(f, now_epoch=1050)
    assert out["five_hour"]["used_percentage"] == 55.0
    assert out["seven_day"]["used_percentage"] == 20.0


def test_capture_no_rate_limits_tombstones(tmp_path: Path) -> None:
    """No rate_limits -> write a tombstone (not nothing) so old official data clears."""
    f = tmp_path / "statusline" / "latest.json"
    assert capture_statusline({"model": {"display_name": "x"}}, path=f, now_epoch=1) is None
    assert f.exists()
    assert read_official_limits(f, now_epoch=2) is None


def test_tombstone_clears_prior_official(tmp_path: Path) -> None:
    """A plan downgrade (rate_limits disappears) must not keep serving stale official."""
    f = tmp_path / "statusline" / "latest.json"
    capture_statusline(
        {"rate_limits": {"five_hour": {"used_percentage": 99.0, "resets_at": 9999999999}}},
        path=f,
        now_epoch=1,
    )
    assert read_official_limits(f, now_epoch=2)["five_hour"]["used_percentage"] == 99.0
    capture_statusline({"model": {"display_name": "x"}}, path=f, now_epoch=3)
    assert read_official_limits(f, now_epoch=4) is None


def test_capture_is_atomic_leaves_no_tmp(tmp_path: Path) -> None:
    f = tmp_path / "statusline" / "latest.json"
    capture_statusline(
        {"rate_limits": {"five_hour": {"used_percentage": 1.0, "resets_at": 5}}},
        path=f,
        now_epoch=1,
    )
    assert f.exists()
    assert list(f.parent.glob("*.tmp")) == []


def test_format_statusline_shows_official_percentages() -> None:
    payload = {"model": {"display_name": "Opus 4.8"}}
    capture = {
        "rate_limits": {
            "five_hour": {"used_percentage": 42.0},
            "seven_day": {"used_percentage": 18.0},
        }
    }
    line = format_statusline(payload, capture)
    assert "Opus 4.8" in line
    assert "5h 42%" in line
    assert "7d 18%" in line


def test_format_statusline_fallback_when_no_limits() -> None:
    assert format_statusline({}, None) == "claude-monitor"


def test_format_statusline_ignores_leaked_percentage() -> None:
    capture = {"rate_limits": {"five_hour": {"used_percentage": 1719500000}}}
    line = format_statusline({"model": {"display_name": "Opus"}}, capture)
    assert "5h" not in line
    assert line == "Opus"


def test_format_statusline_survives_nondict_shapes() -> None:
    """Valid JSON with unexpected types must not raise (the hook can't crash)."""
    line = format_statusline({"model": "Opus"}, {"rate_limits": {"five_hour": "bad"}})
    assert line == "claude-monitor"
