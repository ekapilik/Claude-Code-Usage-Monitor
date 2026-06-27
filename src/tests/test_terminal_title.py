"""Tests for terminal title support (#142)."""

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from claude_monitor.core.settings import Settings

cli_main = importlib.import_module("claude_monitor.cli.main")
formatters = importlib.import_module("claude_monitor.output.formatters")
terminal_manager = importlib.import_module("claude_monitor.terminal.manager")


def _monitoring_payload(total: int = 12008) -> dict:
    return {
        "token_limit": 19000,
        "data": {
            "blocks": [
                {
                    "id": "b1",
                    "isActive": True,
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
                    "sentMessagesCount": 42,
                    "burnRate": {"tokensPerMinute": 158.4, "costPerHour": 1.31},
                }
            ]
        },
    }


class _FakeOnceOrchestrator:
    payload: Optional[dict] = None

    def __init__(self, **_: Any) -> None:
        pass

    def set_args(self, _args: Any) -> None:
        pass

    def force_refresh(self) -> Optional[dict]:
        return type(self).payload

    def stop(self) -> None:
        pass


def _run_once(args: argparse.Namespace, payload: Optional[dict]) -> int:
    _FakeOnceOrchestrator.payload = payload
    with (
        patch.object(cli_main, "discover_claude_data_paths", return_value=[Path("/x")]),
        patch.object(cli_main, "MonitoringOrchestrator", _FakeOnceOrchestrator),
        patch.object(cli_main, "read_official_limits", return_value=None),
    ):
        return cli_main._run_once(args)


def test_set_terminal_title_writes_osc_when_stdout_is_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    terminal_manager.set_terminal_title("63.2% pro")

    assert capsys.readouterr().out == "\033]0;63.2% pro\007"


def test_set_terminal_title_is_noop_when_stdout_is_not_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    terminal_manager.set_terminal_title("63.2% pro")

    assert capsys.readouterr().out == ""


def test_format_terminal_title_uses_snapshot_fields() -> None:
    snapshot = {
        "plan": "pro",
        "limits": {
            "five_hour": {
                "used_percentage": 63.2,
                "tokens_used": 12008,
                "token_limit": 19000,
                "resets_at": "2026-06-27T17:00:00+00:00",
            }
        },
        "local": {"cost_usd": 4.27},
    }

    title = formatters.format_terminal_title(
        snapshot,
        "{pct:.0f}% {plan} {used}/{limit} ${cost:.2f} reset {reset}",
    )

    assert title == "63% pro 12008/19000 $4.27 reset 17:00"


def test_format_terminal_title_handles_missing_snapshot_values() -> None:
    snapshot = {
        "plan": "pro",
        "limits": {"five_hour": {"used_percentage": None}},
        "local": {},
    }

    title = formatters.format_terminal_title(
        snapshot,
        "{pct:.0f}% {used}/{limit} reset {reset}",
    )

    assert title == "--% --/-- reset --:--"


def test_terminal_title_settings_default_and_namespace() -> None:
    default = Settings(_cli_parse_args=[])
    assert default.set_terminal_title is False
    assert default.title_format == "{pct}% {plan}"

    namespace = Settings(
        set_terminal_title=True,
        title_format="{pct:.0f}% {plan}",
        _cli_parse_args=[],
    ).to_namespace()

    assert namespace.set_terminal_title is True
    assert namespace.title_format == "{pct:.0f}% {plan}"


def test_title_format_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="Unknown title-format key: bad"):
        Settings(title_format="{bad}", _cli_parse_args=[])


def test_title_format_rejects_invalid_templates() -> None:
    with pytest.raises(ValueError, match="Invalid title-format template"):
        Settings(title_format="{pct", _cli_parse_args=[])


def test_once_sets_terminal_title_from_snapshot() -> None:
    args = argparse.Namespace(
        output="text",
        plan="pro",
        refresh_rate=10,
        theme="dark",
        compact=False,
        write_state=False,
        set_terminal_title=True,
        title_format="{pct:.1f}% {plan}",
    )

    with patch.object(cli_main, "set_terminal_title") as mock_title:
        rc = _run_once(args, _monitoring_payload())

    assert rc == 0
    mock_title.assert_called_once_with("63.2% pro")


def test_once_does_not_set_terminal_title_by_default() -> None:
    args = argparse.Namespace(
        output="text",
        plan="pro",
        refresh_rate=10,
        theme="dark",
        compact=False,
        write_state=False,
        set_terminal_title=False,
        title_format="{pct}% {plan}",
    )

    with patch.object(cli_main, "set_terminal_title") as mock_title:
        _run_once(args, _monitoring_payload())

    mock_title.assert_not_called()


def test_live_monitoring_sets_terminal_title_from_snapshot() -> None:
    args = argparse.Namespace(
        view="realtime",
        theme="dark",
        plan="pro",
        timezone="UTC",
        refresh_per_second=1.0,
        refresh_rate=10,
        compact=False,
        write_state=False,
        set_terminal_title=True,
        title_format="{pct:.0f}% {plan}",
        custom_limit_tokens=None,
    )

    class LiveOrchestrator:
        def __init__(self, **_: Any) -> None:
            self.callback = None

        def set_args(self, _args: argparse.Namespace) -> None:
            pass

        def register_update_callback(self, callback: Any) -> None:
            self.callback = callback

        def register_session_callback(self, _callback: Any) -> None:
            pass

        def start(self) -> None:
            assert self.callback is not None
            self.callback(_monitoring_payload())

        def wait_for_initial_data(self, timeout: float) -> bool:
            return True

        def stop(self) -> None:
            pass

    live_display = MagicMock()
    display_controller = Mock()
    display_controller.live_manager.create_live_display.return_value = live_display
    display_controller.create_loading_display.return_value = "loading"
    display_controller.create_data_display.return_value = "display"

    with (
        patch.object(cli_main, "discover_claude_data_paths", return_value=[Path("/x")]),
        patch.object(cli_main, "_get_initial_token_limit", return_value=19000),
        patch.object(cli_main, "get_themed_console", return_value=Mock()),
        patch.object(cli_main, "setup_terminal", return_value=None),
        patch.object(cli_main, "enter_alternate_screen"),
        patch.object(cli_main, "restore_terminal"),
        patch.object(cli_main, "DisplayController", return_value=display_controller),
        patch.object(cli_main, "MonitoringOrchestrator", LiveOrchestrator),
        patch.object(cli_main, "read_official_limits", return_value=None),
        patch.object(cli_main, "set_terminal_title") as mock_title,
        patch.object(cli_main.signal, "pause", side_effect=KeyboardInterrupt),
        patch.object(cli_main, "handle_cleanup_and_exit", side_effect=SystemExit(0)),
    ):
        with pytest.raises(SystemExit):
            cli_main._run_monitoring(args)

    mock_title.assert_called_once_with("63% pro")
