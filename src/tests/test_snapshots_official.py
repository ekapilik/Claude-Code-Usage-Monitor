"""Trust-keystone integration: official statusline limits override local estimates."""

import argparse
from typing import Optional

from claude_monitor.output.snapshots import build_snapshot


def _args(plan: str = "pro") -> argparse.Namespace:
    return argparse.Namespace(plan=plan)


def _data(used: int = 12000, active: bool = True, limit_msg: Optional[list] = None) -> dict:
    block = {
        "isActive": active,
        "isGap": False,
        "startTime": "2026-06-27T12:00:00+00:00",
        "endTime": "2026-06-27T17:00:00+00:00",
        "tokenCounts": {
            "inputTokens": used,
            "outputTokens": 0,
            "cacheCreationInputTokens": 0,
            "cacheReadInputTokens": 0,
        },
        "totalTokens": used,
        "costUSD": 4.0,
        "durationMinutes": 60,
        "perModelStats": {},
        "sentMessagesCount": 1,
        "burnRate": {"tokensPerMinute": 100.0, "costPerHour": 1.0},
    }
    if limit_msg:
        block["limitMessages"] = limit_msg
    return {"blocks": [block]}


def _official(five_pct=42.5, five_reset=1782579600, seven=None, stale=False) -> dict:
    out = {
        "five_hour": {"used_percentage": five_pct, "resets_at_epoch": five_reset}
        if five_pct is not None or five_reset is not None
        else None,
        "seven_day": seven,
        "captured_at_epoch": 1751045000,
        "stale": stale,
    }
    return out


def test_official_five_hour_overrides_local() -> None:
    snap = build_snapshot(_data(used=12000), _args(), token_limit=19000, official=_official())
    five = snap["limits"]["five_hour"]
    assert five["confidence"] == "official"
    assert five["source"]["kind"] == "statusline"
    assert five["used_percentage"] == 42.5  # official, NOT the local ~63%
    assert five["resets_at_epoch"] == 1782579600
    assert five["resets_at"].startswith("2026-06-27T17:00")  # ISO from the epoch
    # Headline confidence reflects the official limit.
    assert snap["confidence"] == "official"


def test_official_drives_status_code_not_local() -> None:
    # Local would be ~63% (ok); official says 97% -> near_limit (code 10).
    snap = build_snapshot(_data(used=12000), _args(), token_limit=19000,
                          official=_official(five_pct=97.0))
    assert snap["status"]["code"] == 10
    assert snap["status"]["label"] == "near_limit"


def test_official_stale_flags_snapshot_but_still_used() -> None:
    snap = build_snapshot(_data(), _args(), token_limit=19000,
                          official=_official(stale=True))
    assert snap["stale"] is True
    assert snap["limits"]["five_hour"]["confidence"] == "official"


def test_leaked_official_percentage_falls_back_to_local() -> None:
    # used_percentage unavailable (dropped by the reader) -> keep local estimate.
    snap = build_snapshot(_data(used=12000), _args(), token_limit=19000,
                          official=_official(five_pct=None, five_reset=1751046000))
    five = snap["limits"]["five_hour"]
    assert five["confidence"] == "local_estimate"
    assert five["used_percentage"] == round(100 * 12000 / 19000, 1)


def test_official_seven_day_filled() -> None:
    snap = build_snapshot(
        _data(), _args(), token_limit=19000,
        official=_official(seven={"used_percentage": 18.0, "resets_at_epoch": 1751500000}),
    )
    seven = snap["limits"]["seven_day"]
    assert seven["confidence"] == "official"
    assert seven["used_percentage"] == 18.0
    assert seven["resets_at_epoch"] == 1751500000


def test_official_seven_day_exhaustion_drives_status() -> None:
    """Weekly exhaustion limits usage too: official seven_day>=100 -> limit_hit."""
    snap = build_snapshot(
        _data(used=1000), _args(), token_limit=19000,
        official=_official(
            five_pct=10.0,
            seven={"used_percentage": 100.0, "resets_at_epoch": 1782579600},
        ),
    )
    assert snap["status"]["label"] == "limit_hit"
    assert snap["status"]["code"] == 11


def test_no_official_keeps_local_behaviour() -> None:
    snap = build_snapshot(_data(used=12000), _args(), token_limit=19000)
    assert snap["limits"]["five_hour"]["confidence"] == "local_estimate"
    assert snap["confidence"] == "local_estimate"
    assert snap["limits"]["seven_day"]["confidence"] == "unknown"
