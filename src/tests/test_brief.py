"""Tests for --brief one-shot display mode."""

import pytest

from claude_monitor.ui.brief import format_brief


def _make_brief(**overrides):
    defaults = dict(
        tokens_used=12000,
        token_limit=44000,
        session_cost=0.43,
        cost_limit=5.00,
        sent_messages=45,
        messages_limit=200,
        burn_rate_per_min=35.0,  # tokens/min → 2.1k/hr
        reset_time_str="14:32",
        width=200,
    )
    defaults.update(overrides)
    return format_brief(**defaults)


def test_all_blocks_present():
    out = _make_brief()
    assert "tok:" in out
    assert "cost:" in out
    assert "msgs:" in out
    assert "burn:" in out
    assert "reset:" in out


def test_wide_terminal_single_line():
    out = _make_brief(width=200)
    assert out.count("\n") == 0


def test_narrow_terminal_wraps_between_blocks():
    # Each block is ~20 chars; at width=25 each block must be on its own line
    out = _make_brief(width=25)
    lines = out.splitlines()
    assert len(lines) > 1
    # No line exceeds width
    for line in lines:
        assert len(line) <= 25


def test_no_block_split_mid_block():
    # Each block label must appear intact on a single line, not broken across lines
    out = _make_brief(width=25)
    for line in out.splitlines():
        assert " | " not in line or all(
            block in line
            for block in [s for s in ["tok:", "cost:", "msgs:", "burn:", "reset:"] if s in line]
        )


def test_token_values_in_output():
    out = _make_brief(tokens_used=12000, token_limit=44000)
    assert "12k" in out
    assert "44k" in out


def test_cost_values_in_output():
    out = _make_brief(session_cost=0.43, cost_limit=5.00)
    assert "$0.43" in out
    assert "$5.00" in out


def test_burn_rate_in_khr():
    # 35 tokens/min * 60 = 2100/hr → "2.1k/hr"
    out = _make_brief(burn_rate_per_min=35.0)
    assert "2.1k/hr" in out


def test_reset_time_in_output():
    out = _make_brief(reset_time_str="14:32")
    assert "14:32" in out


def test_zero_limits_no_crash():
    out = _make_brief(token_limit=0, cost_limit=0.0, messages_limit=0)
    assert "tok:" in out


def test_percentage_shown():
    out = _make_brief(tokens_used=11000, token_limit=44000)
    assert "25%" in out
