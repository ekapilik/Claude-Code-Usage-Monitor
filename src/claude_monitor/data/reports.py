"""Warehouse-backed exports and reports."""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from claude_monitor.core.plans import Plans
from claude_monitor.data.warehouse import UsageWarehouse

REPORT_SCHEMA_VERSION = "1.0"
LOCAL_ESTIMATE = "local_estimate"
SESSION_DURATION = timedelta(hours=5)


def build_warehouse_report(
    warehouse: UsageWarehouse,
    view: str,
    *,
    now: Optional[datetime] = None,
    plan: str = "custom",
) -> Dict[str, Any]:
    """Build a versioned JSON report from warehouse rows."""
    doc = warehouse.load()
    records = [record for record in doc["records"] if isinstance(record, dict)]
    generated_at = _coerce_now(now).isoformat()
    base: Dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "view": view,
        "source": {"kind": "warehouse", "path": str(warehouse.path)},
        "confidence": LOCAL_ESTIMATE,
        "plan": plan,
    }

    if view == "entries":
        entries = [_entry_row(record) for record in records]
        base["entries"] = entries
        base["summary"] = _entry_summary(entries)
        return base

    sessions = _build_sessions(records, doc.get("limit_events", []))
    session_rows = [_session_row(session) for session in sessions]
    if view == "sessions":
        base["sessions"] = session_rows
        base["summary"] = _session_summary(session_rows)
        base["plan_recommendation"] = _plan_recommendation(
            base["summary"]["token_percentiles"].get("p90"), plan
        )
        return base

    if view == "burn-rate":
        burn_rows = [_burn_rate_row(session) for session in sessions]
        base["burn_rate"] = burn_rows
        base["summary"] = _burn_rate_summary(burn_rows)
        return base

    raise ValueError(f"Unsupported warehouse report view: {view}")


def format_report_csv(report: Dict[str, Any]) -> str:
    """Format a warehouse report as CSV."""
    view = report.get("view")
    if view == "entries":
        return _write_csv(
            report.get("entries", []),
            [
                "timestamp",
                "day",
                "project",
                "model",
                "source_kind",
                "source_account",
                "input_tokens",
                "output_tokens",
                "cache_creation_tokens",
                "cache_read_tokens",
                "total_tokens",
                "cost_usd",
                "message_id",
                "request_id",
            ],
        )
    if view == "sessions":
        return _write_csv(
            report.get("sessions", []),
            [
                "start_time",
                "end_time",
                "actual_end_time",
                "project",
                "source_kind",
                "source_account",
                "models",
                "total_tokens",
                "total_cost",
                "entries_count",
                "ended_by_limit",
            ],
        )
    if view == "burn-rate":
        return _write_csv(
            report.get("burn_rate", []),
            [
                "start_time",
                "end_time",
                "actual_end_time",
                "project",
                "source_kind",
                "source_account",
                "total_tokens",
                "total_cost",
                "duration_minutes",
                "tokens_per_minute",
                "cost_per_hour",
                "ended_by_limit",
            ],
        )
    raise ValueError(f"Unsupported warehouse report view: {view}")


def _write_csv(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def _coerce_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _source_parts(source: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    return source.get("kind", "unknown"), source.get("account")


def _entry_row(record: Dict[str, Any]) -> Dict[str, Any]:
    source_kind, source_account = _source_parts(record.get("source") or {})
    return {
        "timestamp": record.get("timestamp"),
        "day": record.get("day"),
        "project": record.get("project", "unknown"),
        "model": record.get("model", "unknown"),
        "source_kind": source_kind,
        "source_account": source_account,
        "input_tokens": int(record.get("input_tokens", 0)),
        "output_tokens": int(record.get("output_tokens", 0)),
        "cache_creation_tokens": int(record.get("cache_creation_tokens", 0)),
        "cache_read_tokens": int(record.get("cache_read_tokens", 0)),
        "total_tokens": int(record.get("total_tokens", 0)),
        "cost_usd": float(record.get("cost_usd", 0.0)),
        "message_id": record.get("message_id", ""),
        "request_id": record.get("request_id", ""),
    }


def _entry_summary(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "entries_count": len(entries),
        "total_tokens": sum(row["total_tokens"] for row in entries),
        "total_cost": round(sum(row["cost_usd"] for row in entries), 10),
    }


class _Session(Dict[str, Any]):
    pass


def _build_sessions(
    records: Iterable[Dict[str, Any]], limit_events: Iterable[Dict[str, Any]]
) -> List[_Session]:
    grouped: Dict[Tuple[str, Optional[str], str], List[Dict[str, Any]]] = {}
    for record in records:
        source_kind, source_account = _source_parts(record.get("source") or {})
        key = (source_kind, source_account, record.get("project", "unknown"))
        grouped.setdefault(key, []).append(record)

    event_rows = [event for event in limit_events if isinstance(event, dict)]
    sessions: List[_Session] = []
    for (source_kind, source_account, project), group_records in grouped.items():
        group_records.sort(key=lambda record: record.get("timestamp", ""))
        current: Optional[_Session] = None
        for record in group_records:
            timestamp = _parse_timestamp(record["timestamp"])
            if current is None or timestamp - current["actual_end"] >= SESSION_DURATION:
                if current is not None:
                    sessions.append(_finalize_session(current, event_rows))
                current = _new_session(source_kind, source_account, project, timestamp)
            _add_record_to_session(current, record, timestamp)

        if current is not None:
            sessions.append(_finalize_session(current, event_rows))

    sessions.sort(key=lambda session: session["start"])
    return sessions


def _new_session(
    source_kind: str, source_account: Optional[str], project: str, start: datetime
) -> _Session:
    return _Session(
        start=start,
        end=start + SESSION_DURATION,
        actual_end=start,
        project=project,
        source_kind=source_kind,
        source_account=source_account,
        models=set(),
        total_tokens=0,
        total_cost=0.0,
        entries_count=0,
        ended_by_limit=False,
    )


def _add_record_to_session(
    session: _Session, record: Dict[str, Any], timestamp: datetime
) -> None:
    session["actual_end"] = max(session["actual_end"], timestamp)
    session["models"].add(record.get("model", "unknown"))
    session["total_tokens"] += int(record.get("total_tokens", 0))
    session["total_cost"] += float(record.get("cost_usd", 0.0))
    session["entries_count"] += 1


def _finalize_session(
    session: _Session, limit_events: Sequence[Dict[str, Any]]
) -> _Session:
    session["ended_by_limit"] = _session_has_limit_event(session, limit_events)
    return session


def _session_has_limit_event(
    session: _Session, limit_events: Sequence[Dict[str, Any]]
) -> bool:
    for event in limit_events:
        source_kind, source_account = _source_parts(event.get("source") or {})
        if source_kind != session["source_kind"]:
            continue
        if source_account != session["source_account"]:
            continue
        event_project = event.get("project", "unknown")
        if event_project != "unknown" and event_project != session["project"]:
            continue
        try:
            timestamp = _parse_timestamp(event["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        if session["start"] <= timestamp <= session["end"]:
            return True
    return False


def _session_row(session: _Session) -> Dict[str, Any]:
    return {
        "start_time": session["start"].isoformat(),
        "end_time": session["end"].isoformat(),
        "actual_end_time": session["actual_end"].isoformat(),
        "project": session["project"],
        "source_kind": session["source_kind"],
        "source_account": session["source_account"],
        "models": ",".join(sorted(session["models"])),
        "total_tokens": session["total_tokens"],
        "total_cost": round(session["total_cost"], 10),
        "entries_count": session["entries_count"],
        "ended_by_limit": session["ended_by_limit"],
    }


def _burn_rate_row(session: _Session) -> Dict[str, Any]:
    duration_minutes = max(
        (session["actual_end"] - session["start"]).total_seconds() / 60,
        1.0,
    )
    total_tokens = session["total_tokens"]
    total_cost = session["total_cost"]
    return {
        "start_time": session["start"].isoformat(),
        "end_time": session["end"].isoformat(),
        "actual_end_time": session["actual_end"].isoformat(),
        "project": session["project"],
        "source_kind": session["source_kind"],
        "source_account": session["source_account"],
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 10),
        "duration_minutes": round(duration_minutes, 4),
        "tokens_per_minute": round(total_tokens / duration_minutes, 4),
        "cost_per_hour": round((total_cost / duration_minutes) * 60, 4),
        "ended_by_limit": session["ended_by_limit"],
    }


def _session_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    tokens = [row["total_tokens"] for row in rows]
    session_count = len(rows)
    return {
        "session_count": session_count,
        "limit_ended_sessions": sum(1 for row in rows if row["ended_by_limit"]),
        "average_tokens_per_session": (
            round(sum(tokens) / session_count, 2) if session_count else 0
        ),
        "token_percentiles": _percentiles(tokens),
    }


def _burn_rate_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rates = [row["tokens_per_minute"] for row in rows]
    return {
        "session_count": len(rows),
        "tokens_per_minute_percentiles": _percentiles(rates),
    }


def _percentiles(values: Sequence[Any]) -> Dict[str, Any]:
    if not values:
        return {"p50": 0, "p90": 0, "p95": 0}
    ordered = sorted(values)
    return {
        "p50": _nearest_rank(ordered, 50),
        "p90": _nearest_rank(ordered, 90),
        "p95": _nearest_rank(ordered, 95),
    }


def _nearest_rank(ordered_values: Sequence[Any], percentile: int) -> Any:
    index = max(0, math.ceil((percentile / 100) * len(ordered_values)) - 1)
    return ordered_values[index]


def _plan_recommendation(p90_tokens: Any, current_plan: str) -> Dict[str, Any]:
    try:
        p90_value = int(p90_tokens)
    except (TypeError, ValueError):
        p90_value = 0

    recommended = "custom"
    for plan_name, limit in (
        ("pro", Plans.get_plan_by_name("pro").token_limit),
        ("max5", Plans.get_plan_by_name("max5").token_limit),
        ("max20", Plans.get_plan_by_name("max20").token_limit),
    ):
        if p90_value <= limit:
            recommended = plan_name
            break

    return {
        "recommended_plan": recommended,
        "current_plan": current_plan,
        "basis": "p90_session_tokens",
        "p90_session_tokens": p90_value,
        "confidence": LOCAL_ESTIMATE,
        "disclaimer": (
            "This recommendation is an estimate from local warehouse history; "
            "verify against official Claude limits and your subscription terms."
        ),
    }
