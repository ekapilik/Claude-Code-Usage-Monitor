"""One-shot usage snapshot builder — the single machine-readable contract (#126).

Builds a versioned, source-labeled snapshot from the local JSONL analysis. Every
number is a LOCAL estimate (``confidence="local_estimate"``); official account
limits (statusline ``rate_limits``) are not wired yet, so the ``limits`` block is
shaped exactly like the official ``rate_limits.{five_hour,seven_day}`` and can
later have its source flipped to ``statusline``/``official`` without breaking
consumers. No I/O and no network — the same builder ``--write-state`` (#184) reuses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from claude_monitor._version import __version__
from claude_monitor.core.plans import Plans

SNAPSHOT_SCHEMA_VERSION = "1.0"

_KIND = "claude_code_jsonl"
_LOCAL = "local_estimate"
_UNKNOWN = "unknown"


def _family_of(model: str) -> str:
    name = model.lower()
    if "sonnet" in name:
        return "sonnet"
    if "opus" in name:
        return "opus"
    if "haiku" in name:
        return "haiku"
    return "other"


def _epoch(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except (ValueError, TypeError):
        return None


def _status(active: Optional[dict], used_pct: Optional[float]) -> tuple[int, str]:
    if active is None:
        return 20, "no_active_session"
    if used_pct is None:
        return 20, "indeterminate"  # active, but utilization unknown (no limit)
    if active.get("limitMessages") or used_pct >= 100.0:
        return 11, "limit_hit"
    if used_pct >= Plans.LIMIT_DETECTION_THRESHOLD * 100:
        return 10, "near_limit"
    return 0, "ok"


def _model_distribution(per_model: Optional[dict]) -> List[Dict[str, Any]]:
    families: Dict[str, Dict[str, Any]] = {}
    for model, stats in (per_model or {}).items():
        agg = families.setdefault(
            _family_of(model),
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
        agg["input_tokens"] += stats.get("input_tokens", 0)
        agg["output_tokens"] += stats.get("output_tokens", 0)
        agg["cost_usd"] += stats.get("cost_usd", 0.0) or 0.0
    # Percentages are relative to the model token sum (input+output) so they sum
    # to ~100 — NOT the cache-inclusive total, which cache reads would dominate.
    model_total = sum(a["input_tokens"] + a["output_tokens"] for a in families.values())
    out: List[Dict[str, Any]] = []
    for family, agg in families.items():
        fam_tokens = agg["input_tokens"] + agg["output_tokens"]
        pct = round(100 * fam_tokens / model_total, 1) if model_total else 0.0
        out.append(
            {
                "family": family,
                "percentage": pct,
                "input_tokens": agg["input_tokens"],
                "output_tokens": agg["output_tokens"],
                "cost_usd": round(agg["cost_usd"], 4),
            }
        )
    out.sort(key=lambda m: m["percentage"], reverse=True)
    return out


def build_snapshot(data: Optional[dict], args: Any, token_limit: int) -> dict:
    """Build the one-shot snapshot dict from a single analysis payload.

    Args:
        data: the inner monitoring payload (has a ``blocks`` list of 5h blocks).
        args: parsed CLI namespace (uses ``plan``, optional ``data_path``).
        token_limit: the active token limit (plan or P90) for utilization.

    Returns:
        The versioned snapshot dict (see module docstring).
    """
    blocks = (data or {}).get("blocks", []) or []
    active = next((b for b in blocks if b.get("isActive")), None)

    plan = getattr(args, "plan", "custom")
    data_path = getattr(args, "data_path", None)
    has_limit = token_limit > 0

    if active is not None:
        tc = active.get("tokenCounts") or {}
        tokens = {
            "input_tokens": tc.get("inputTokens", 0),
            "output_tokens": tc.get("outputTokens", 0),
            "cache_creation_input_tokens": tc.get("cacheCreationInputTokens", 0),
            "cache_read_input_tokens": tc.get("cacheReadInputTokens", 0),
        }
        tokens["total_tokens"] = sum(tokens.values())  # cache-inclusive honest total
        used = active.get("totalTokens", 0)  # input+output, matches displayed util
        # Real (unclamped) ratio drives the exit code so rounding can't false-fire;
        # a local estimate may legitimately exceed 100% (over the P90/plan limit).
        raw_pct = (100 * used / token_limit) if has_limit else None
        used_pct = round(raw_pct, 1) if raw_pct is not None else None
        burn = active.get("burnRate") or {}
        local = {
            "is_active": True,
            "session_start": active.get("startTime"),
            "session_end": active.get("endTime"),
            "tokens": tokens,
            "cost_usd": active.get("costUSD", 0.0),
            "sent_messages": active.get("sentMessagesCount", 0),
            "burn_rate_tokens_per_minute": burn.get("tokensPerMinute"),
            "burn_rate_cost_per_hour": burn.get("costPerHour"),
            "model_distribution": _model_distribution(active.get("perModelStats")),
        }
        five_hour = {
            "used_percentage": used_pct,
            "tokens_used": used,
            "token_limit": token_limit if has_limit else None,
            "resets_at": active.get("endTime"),
            "resets_at_epoch": _epoch(active.get("endTime")),
            "source": {"kind": _KIND},
            "confidence": _LOCAL,
        }
        tokens_remaining = max(0, token_limit - used) if has_limit else None
        # Forecast on an input+output burn rate (used / duration) so the basis
        # matches tokens_remaining; the cache-inclusive burn rate would be wrong here.
        duration = active.get("durationMinutes") or 0
        io_burn = used / duration if duration else 0
        minutes_remaining = (
            round(tokens_remaining / io_burn, 1)
            if io_burn and tokens_remaining is not None
            else None
        )
        exhausted_at = exhausted_epoch = None
        if minutes_remaining is not None:
            dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_remaining)
            exhausted_at = dt.isoformat()
            exhausted_epoch = int(dt.timestamp())
        forecast = {
            "predicted_tokens_exhausted_at": exhausted_at,
            "predicted_tokens_exhausted_epoch": exhausted_epoch,
            "tokens_remaining": tokens_remaining,
            "minutes_remaining": minutes_remaining,
            "basis": "input_output_tokens_per_minute",
            "confidence": _LOCAL,
        }
    else:
        raw_pct = None
        local = {
            "is_active": False,
            "session_start": None,
            "session_end": None,
            "tokens": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "total_tokens": 0,
            },
            "cost_usd": 0.0,
            "sent_messages": 0,
            "burn_rate_tokens_per_minute": None,
            "burn_rate_cost_per_hour": None,
            "model_distribution": [],
        }
        five_hour = {
            "used_percentage": None,
            "tokens_used": 0,
            "token_limit": token_limit if has_limit else None,
            "resets_at": None,
            "resets_at_epoch": None,
            "source": {"kind": _KIND},
            "confidence": _UNKNOWN,
        }
        forecast = {
            "predicted_tokens_exhausted_at": None,
            "predicted_tokens_exhausted_epoch": None,
            "tokens_remaining": None,
            "minutes_remaining": None,
            "basis": "burn_rate_tokens_per_minute",
            "confidence": _UNKNOWN,
        }

    real_blocks = [b for b in blocks if not b.get("isGap")]
    hist_tokens = sum(b.get("totalTokens", 0) for b in real_blocks)
    hist_cost = round(sum(b.get("costUSD", 0.0) or 0.0 for b in real_blocks), 4)

    code, label = _status(active, raw_pct)

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"name": "claude-monitor", "version": __version__},
        "source": {
            "kind": _KIND,
            "account": None,
            "data_paths": [data_path] if data_path else [],
        },
        "confidence": _LOCAL,
        "stale": False,
        "plan": plan,
        "limits": {
            "five_hour": five_hour,
            # seven_day is the OFFICIAL weekly slot, deferred until the statusline
            # keystone fills it. It is NOT the local window sum (that lives in
            # local_history, and the analysis window is ~8 days, not 7).
            "seven_day": {
                "used_percentage": None,
                "tokens_used": None,
                "token_limit": None,
                "resets_at": None,
                "resets_at_epoch": None,
                "source": {"kind": _KIND},
                "confidence": _UNKNOWN,
            },
        },
        "local": local,
        "local_history": {
            "total_tokens": hist_tokens,
            "total_cost_usd": hist_cost,
            "source": {"kind": _KIND},
            "confidence": _LOCAL,
        },
        "forecast": forecast,
        "status": {"code": code, "label": label},
    }
