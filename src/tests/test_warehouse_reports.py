"""Tests for warehouse-backed exports and reports."""

import argparse
import csv
import importlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from claude_monitor.core.models import UsageEntry
from claude_monitor.data.reports import build_warehouse_report, format_report_csv
from claude_monitor.data.warehouse import UsageWarehouse

cli_main = importlib.import_module("claude_monitor.cli.main")


def _entry(
    timestamp: datetime,
    *,
    message_id: str,
    total_tokens: int,
    project: str = "/workspace/app",
    model: str = "claude-3-haiku",
    source_account: str = "profile-a",
    cost_usd: float = 0.10,
) -> UsageEntry:
    return UsageEntry(
        timestamp=timestamp,
        input_tokens=total_tokens,
        output_tokens=0,
        cost_usd=cost_usd,
        model=model,
        message_id=message_id,
        request_id=f"req-{message_id}",
        project=project,
        source={"kind": "claude_code_jsonl", "account": source_account},
    )


def _store_with_sessions(path: Path) -> UsageWarehouse:
    store = UsageWarehouse(path)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_entries(
        [
            _entry(base.replace(hour=0), message_id="m1", total_tokens=100),
            _entry(base.replace(hour=6), message_id="m2", total_tokens=200),
            _entry(base.replace(hour=12), message_id="m3", total_tokens=300),
            _entry(base.replace(hour=18), message_id="m4", total_tokens=400),
            _entry(
                datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
                message_id="m5",
                total_tokens=500,
            ),
        ],
        now=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    store.upsert_limit_events(
        [
            {
                "type": "system_limit",
                "timestamp": base.replace(hour=18, minute=30),
                "content": "limit reached",
                "reset_time": base.replace(hour=23),
                "source": {"kind": "claude_code_jsonl", "account": "profile-a"},
            }
        ]
    )
    return store


def test_entries_report_exports_valid_json_shape_and_csv(tmp_path: Path) -> None:
    store = UsageWarehouse(tmp_path / "usage.json")
    store.upsert_entries(
        [
            _entry(
                datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                message_id="msg-1",
                total_tokens=123,
                cost_usd=0.42,
            )
        ],
        now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    report = build_warehouse_report(
        store,
        "entries",
        now=datetime(2024, 1, 2, tzinfo=timezone.utc),
        plan="pro",
    )
    encoded = json.dumps(report, allow_nan=False)
    decoded = json.loads(encoded)

    assert decoded["schema_version"] == "1.0"
    assert decoded["view"] == "entries"
    assert decoded["source"] == {
        "kind": "warehouse",
        "path": str(tmp_path / "usage.json"),
    }
    assert decoded["confidence"] == "local_estimate"
    assert decoded["entries"][0]["timestamp"] == "2024-01-01T12:00:00+00:00"
    assert decoded["entries"][0]["total_tokens"] == 123
    assert decoded["entries"][0]["cost_usd"] == 0.42

    rows = list(csv.DictReader(io.StringIO(format_report_csv(report))))
    assert rows[0]["timestamp"] == "2024-01-01T12:00:00+00:00"
    assert rows[0]["total_tokens"] == "123"
    assert rows[0]["source_kind"] == "claude_code_jsonl"
    assert rows[0]["source_account"] == "profile-a"


def test_sessions_report_has_percentiles_limit_count_and_estimated_recommendation(
    tmp_path: Path,
) -> None:
    store = _store_with_sessions(tmp_path / "usage.json")

    report = build_warehouse_report(
        store,
        "sessions",
        now=datetime(2024, 1, 2, 12, tzinfo=timezone.utc),
        plan="pro",
    )

    assert report["summary"]["session_count"] == 5
    assert report["summary"]["limit_ended_sessions"] == 1
    assert report["summary"]["average_tokens_per_session"] == 300
    assert report["summary"]["token_percentiles"] == {
        "p50": 300,
        "p90": 500,
        "p95": 500,
    }
    recommendation = report["plan_recommendation"]
    assert recommendation["confidence"] == "local_estimate"
    assert recommendation["recommended_plan"] == "pro"
    assert "estimate" in recommendation["disclaimer"].lower()
    assert report["sessions"][3]["ended_by_limit"] is True


def test_limit_events_do_not_mark_other_projects_on_same_source(
    tmp_path: Path,
) -> None:
    store = UsageWarehouse(tmp_path / "usage.json")
    timestamp = datetime(2024, 1, 1, 9, tzinfo=timezone.utc)
    store.upsert_entries(
        [
            _entry(
                timestamp,
                message_id="app",
                total_tokens=100,
                project="/workspace/app",
            ),
            _entry(
                timestamp,
                message_id="other",
                total_tokens=200,
                project="/workspace/other",
            ),
        ],
        now=timestamp,
    )
    store.upsert_limit_events(
        [
            {
                "type": "system_limit",
                "timestamp": timestamp.replace(minute=30),
                "content": "limit reached",
                "project": "/workspace/other",
                "source": {"kind": "claude_code_jsonl", "account": "profile-a"},
            }
        ]
    )

    report = build_warehouse_report(store, "sessions", now=timestamp, plan="pro")
    by_project = {row["project"]: row["ended_by_limit"] for row in report["sessions"]}

    assert by_project == {"/workspace/app": False, "/workspace/other": True}


def test_burn_rate_report_tracks_session_rates(tmp_path: Path) -> None:
    store = UsageWarehouse(tmp_path / "usage.json")
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_entries(
        [
            _entry(base.replace(hour=9), message_id="m1", total_tokens=100),
            _entry(base.replace(hour=9, minute=30), message_id="m2", total_tokens=200),
        ],
        now=base,
    )

    report = build_warehouse_report(
        store,
        "burn-rate",
        now=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        plan="pro",
    )

    assert report["view"] == "burn-rate"
    assert report["burn_rate"][0]["total_tokens"] == 300
    assert report["burn_rate"][0]["duration_minutes"] == 30
    assert report["burn_rate"][0]["tokens_per_minute"] == 10.0
    assert report["summary"]["tokens_per_minute_percentiles"] == {
        "p50": 10.0,
        "p90": 10.0,
        "p95": 10.0,
    }


def test_run_warehouse_report_outputs_json_and_csv(tmp_path: Path, capsys) -> None:
    store = _store_with_sessions(tmp_path / "usage.json")

    json_args = argparse.Namespace(
        view="sessions", output="json", warehouse_file=str(store.path), plan="pro"
    )
    assert cli_main._run_warehouse_report(json_args) == 0
    json_doc = json.loads(capsys.readouterr().out)
    assert json_doc["view"] == "sessions"
    assert json_doc["summary"]["session_count"] == 5

    csv_args = argparse.Namespace(
        view="sessions", output="csv", warehouse_file=str(store.path), plan="pro"
    )
    assert cli_main._run_warehouse_report(csv_args) == 0
    csv_rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert csv_rows[0]["start_time"] == "2024-01-01T00:00:00+00:00"
