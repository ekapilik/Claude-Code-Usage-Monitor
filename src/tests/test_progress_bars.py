"""Tests for ModelUsageBar — every model family must be visible (issues #124, #164)."""

from claude_monitor.ui.progress_bars import ModelUsageBar


def _tokens(n: int) -> dict[str, int]:
    return {"input_tokens": n // 2, "output_tokens": n - n // 2}


def test_render_shows_haiku_family_not_just_sonnet_opus() -> None:
    """Sonnet + Haiku must both show; Haiku must not vanish into a hidden 'other'."""
    bar = ModelUsageBar(width=50)
    out = bar.render(
        {
            "claude-sonnet-4-5": _tokens(60),
            "claude-haiku-4-5": _tokens(40),
        }
    )
    assert "Sonnet" in out and "60.0%" in out
    assert "Haiku" in out and "40.0%" in out


def test_render_lists_every_present_family() -> None:
    """Three families present -> all three named in the summary."""
    bar = ModelUsageBar(width=50)
    out = bar.render(
        {
            "claude-sonnet-4-5": _tokens(50),
            "claude-opus-4-5": _tokens(30),
            "claude-haiku-4-5": _tokens(20),
        }
    )
    for family in ("Sonnet", "Opus", "Haiku"):
        assert family in out


def test_render_unknown_family_shown_as_other_not_dropped() -> None:
    """An unmapped family still appears (as 'Other'); its share is not silently lost."""
    bar = ModelUsageBar(width=50)
    out = bar.render(
        {
            "claude-sonnet-4-5": _tokens(50),
            "some-future-model": _tokens(50),
        }
    )
    assert "Sonnet" in out and "50.0%" in out
    assert "Other" in out
