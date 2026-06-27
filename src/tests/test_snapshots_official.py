"""Trust-keystone integration: official statusline limits override local estimates."""

import argparse
from typing import Optional

from claude_monitor.output.snapshots import build_snapshot


def _args(plan: str = "pro") -> argparse.Namespace:
    return argparse.Namespace(plan=plan)


def _data(
    used: int = 12000, active: bool = True, limit_msg: Optional[list] = None
) -> dict:
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
    snap = build_snapshot(
        _data(used=12000), _args(), token_limit=19000, official=_official()
    )
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
    snap = build_snapshot(
        _data(used=12000), _args(), token_limit=19000, official=_official(five_pct=97.0)
    )
    assert snap["status"]["code"] == 10
    assert snap["status"]["label"] == "near_limit"


def test_stale_official_falls_back_to_local_not_official_truth() -> None:
    """A stale capture must NOT drive status/confidence as current truth (invariant 4)."""
    snap = build_snapshot(
        _data(used=12000),
        _args(),
        token_limit=19000,
        official=_official(five_pct=96.0, stale=True),
    )
    five = snap["limits"]["five_hour"]
    # Falls back to the local estimate; still flagged stale for transparency.
    assert five["confidence"] == "local_estimate"
    assert snap["confidence"] == "local_estimate"
    assert snap["stale"] is True
    # Status is driven by the local ~63%, not the stale official 96% -> ok, not near.
    assert snap["status"]["code"] == 0


def test_official_drives_status_without_local_active_block() -> None:
    """Official 98% must drive the exit status even with no local active block (#contract)."""
    snap = build_snapshot(
        _data(active=False),
        _args(),
        token_limit=19000,
        official=_official(five_pct=98.0),
    )
    assert snap["limits"]["five_hour"]["confidence"] == "official"
    assert snap["status"]["code"] == 10
    assert snap["status"]["label"] == "near_limit"


def test_leaked_official_percentage_falls_back_to_local() -> None:
    # used_percentage unavailable (dropped by the reader) -> keep local estimate.
    snap = build_snapshot(
        _data(used=12000),
        _args(),
        token_limit=19000,
        official=_official(five_pct=None, five_reset=1751046000),
    )
    five = snap["limits"]["five_hour"]
    assert five["confidence"] == "local_estimate"
    assert five["used_percentage"] == round(100 * 12000 / 19000, 1)


def test_official_seven_day_filled() -> None:
    snap = build_snapshot(
        _data(),
        _args(),
        token_limit=19000,
        official=_official(
            seven={"used_percentage": 18.0, "resets_at_epoch": 1751500000}
        ),
    )
    seven = snap["limits"]["seven_day"]
    assert seven["confidence"] == "official"
    assert seven["used_percentage"] == 18.0
    assert seven["resets_at_epoch"] == 1751500000


def test_official_seven_day_exhaustion_drives_status() -> None:
    """Weekly exhaustion limits usage too: official seven_day>=100 -> limit_hit."""
    snap = build_snapshot(
        _data(used=1000),
        _args(),
        token_limit=19000,
        official=_official(
            five_pct=10.0,
            seven={"used_percentage": 100.0, "resets_at_epoch": 1782579600},
        ),
    )
    assert snap["status"]["label"] == "limit_hit"
    assert snap["status"]["code"] == 11


def test_local_reset_prefers_limit_message_over_block_end() -> None:
    """A parsed limit reset time wins over start+5h for the local reset (#114, #106)."""
    data = _data(used=1000)
    data["blocks"][0]["usageLimitResetTime"] = "2026-06-27T19:30:00+00:00"
    snap = build_snapshot(data, _args(), token_limit=19000)
    five = snap["limits"]["five_hour"]
    assert five["resets_at"] == "2026-06-27T19:30:00+00:00"  # not the 17:00 endTime
    assert five["confidence"] == "local_estimate"


def test_local_reset_falls_back_to_block_end_without_limit() -> None:
    snap = build_snapshot(_data(used=1000), _args(), token_limit=19000)
    assert snap["limits"]["five_hour"]["resets_at"] == "2026-06-27T17:00:00+00:00"


def test_local_history_total_is_cache_inclusive() -> None:
    """local_history.total_tokens must include cache tokens (matches local.tokens)."""
    data = {
        "blocks": [
            {
                "isActive": False,
                "isGap": False,
                "tokenCounts": {
                    "inputTokens": 1000,
                    "outputTokens": 500,
                    "cacheCreationInputTokens": 4000,
                    "cacheReadInputTokens": 8000,
                },
                "totalTokens": 1500,  # input+output only (display utilization)
                "costUSD": 2.0,
            }
        ]
    }
    snap = build_snapshot(data, _args(), token_limit=19000)
    assert snap["local_history"]["total_tokens"] == 13500  # 1000+500+4000+8000


def test_no_official_keeps_local_behaviour() -> None:
    snap = build_snapshot(_data(used=12000), _args(), token_limit=19000)
    assert snap["limits"]["five_hour"]["confidence"] == "local_estimate"
    assert snap["confidence"] == "local_estimate"
    assert snap["limits"]["seven_day"]["confidence"] == "unknown"
