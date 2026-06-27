"""Integration tests for one-shot mode `_run_once` (#126)."""

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest

cli_main = importlib.import_module("claude_monitor.cli.main")


def _args(output: str = "json") -> argparse.Namespace:
    return argparse.Namespace(output=output, plan="pro", refresh_rate=10, theme="dark")


def _payload(active: bool = True, total: int = 12008) -> dict:
    return {
        "token_limit": 19000,
        "data": {
            "blocks": [
                {
                    "id": "b1",
                    "isActive": active,
                    "isGap": False,
                    "startTime": "2026-06-27T12:00:00+00:00",
                    "endTime": "2026-06-27T17:00:00+00:00",
                    "tokenCounts": {
                        "inputTokens": 8500,
                        "outputTokens": 3508,
                        "cacheCreationInputTokens": 5000,
                        "cacheReadInputTokens": 2000,
                    },
                    "totalTokens": total,
                    "costUSD": 4.27,
                    "perModelStats": {
                        "claude-opus-4-8": {"input_tokens": 6200, "output_tokens": 2900}
                    },
                    "sentMessagesCount": 42,
                    "burnRate": {"tokensPerMinute": 158.4, "costPerHour": 1.31},
                }
            ]
        },
    }


class _FakeOrch:
    payload: Optional[dict] = None

    def __init__(self, **_: Any) -> None:
        pass

    def set_args(self, _args: Any) -> None:
        pass

    def force_refresh(self) -> Optional[dict]:
        return type(self).payload

    def stop(self) -> None:
        pass


def _run(args: argparse.Namespace, payload: Optional[dict], paths=(Path("/x"),)):
    _FakeOrch.payload = payload
    with (
        patch.object(cli_main, "discover_claude_data_paths", return_value=list(paths)),
        patch.object(cli_main, "MonitoringOrchestrator", _FakeOrch),
    ):
        return cli_main._run_once(args)


def test_once_json_prints_valid_json_and_exit_0(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("json"), _payload())
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert doc["schema_version"] == "1.0"
    assert doc["status"]["code"] == 0
    assert doc["limits"]["five_hour"]["confidence"] == "local_estimate"


def test_once_text_greppable(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("text"), _payload())
    out = capsys.readouterr().out
    assert rc == 0
    assert "schema_version=1.0" in out
    assert "status.code=0" in out


def test_once_limit_hit_exit_11(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("json"), _payload(total=20000))  # >100% of 19000
    capsys.readouterr()
    assert rc == 11


def test_once_no_active_exit_20(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("json"), _payload(active=False))
    capsys.readouterr()
    assert rc == 20


def test_once_no_paths_exit_30(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("json"), _payload(), paths=())
    err = capsys.readouterr().err
    assert rc == 30
    assert "No Claude data directory" in err


def test_once_force_refresh_none_exit_30(capsys: pytest.CaptureFixture) -> None:
    rc = _run(_args("json"), None)
    capsys.readouterr()
    assert rc == 30


def test_once_honors_custom_limit_tokens(capsys: pytest.CaptureFixture) -> None:
    """--plan custom --custom-limit-tokens N is used, not the P90 estimate (codex P1)."""
    args = argparse.Namespace(
        output="json", plan="custom", refresh_rate=10, theme="dark",
        custom_limit_tokens=50000,
    )
    _run(args, _payload())  # payload token_limit is 19000; custom override wins
    doc = json.loads(capsys.readouterr().out)
    assert doc["limits"]["five_hour"]["token_limit"] == 50000


def test_once_write_state_writes_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """--write-state writes the snapshot to the state file in one-shot mode (#184)."""
    state = tmp_path / "state" / "latest.json"
    args = argparse.Namespace(
        output="json", plan="pro", refresh_rate=10, theme="dark",
        write_state=True, state_file=str(state),
    )
    _run(args, _payload())
    capsys.readouterr()
    assert json.loads(state.read_text())["schema_version"] == "1.0"


def test_once_consumes_official_limits(capsys: pytest.CaptureFixture) -> None:
    """When official statusline limits exist, the snapshot uses them (trust keystone)."""
    official = {
        "five_hour": {"used_percentage": 88.0, "resets_at_epoch": 1782579600},
        "seven_day": None,
        "captured_at_epoch": 1782570000,
        "stale": False,
    }
    with patch.object(cli_main, "read_official_limits", return_value=official):
        _run(_args("json"), _payload())
    doc = json.loads(capsys.readouterr().out)
    assert doc["limits"]["five_hour"]["confidence"] == "official"
    assert doc["limits"]["five_hour"]["used_percentage"] == 88.0
    assert doc["confidence"] == "official"


def test_once_compact_prints_single_line(capsys: pytest.CaptureFixture) -> None:
    """--once --compact prints one glanceable line, not the full TUI or JSON (#65)."""
    args = argparse.Namespace(
        output="rich", plan="pro", refresh_rate=10, theme="dark", compact=True
    )
    _run(args, _payload())
    out = capsys.readouterr().out.strip()
    assert "\n" not in out
    assert out.startswith("claude") and "%" in out and "reset" in out
