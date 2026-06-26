"""Tests for SessionDisplayComponent model-distribution visibility (issue #161)."""

from typing import Any

from claude_monitor.ui.session_display import SessionDisplayComponent


def _screen_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "plan": "pro",
        "timezone": "UTC",
        "tokens_used": 100,
        "token_limit": 1000,
        "usage_percentage": 10.0,
        "tokens_left": 900,
        "elapsed_session_minutes": 5.0,
        "total_session_minutes": 300.0,
        "burn_rate": 1.0,
        "session_cost": 0.5,
        "per_model_stats": {"claude-sonnet-4-5": {"input_tokens": 50, "output_tokens": 50}},
        "sent_messages": 3,
        "entries": [],
        "predicted_end_str": "13:00",
        "reset_time_str": "14:00",
        "current_time_str": "10:00",
    }
    base.update(overrides)
    return base


def test_model_distribution_shown_by_default() -> None:
    lines = SessionDisplayComponent().format_active_session_screen(**_screen_kwargs())
    assert any("Model Distribution" in line for line in lines)


def test_hide_model_distribution_omits_the_bar() -> None:
    lines = SessionDisplayComponent().format_active_session_screen(
        **_screen_kwargs(), hide_model_distribution=True
    )
    assert not any("Model Distribution" in line for line in lines)
    assert not any("Model Usage" in line for line in lines)
