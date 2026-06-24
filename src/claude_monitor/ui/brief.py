"""Minimal one-line display for --brief mode (tmux-friendly)."""

import shutil


def _fmt_k(n: float) -> str:
    """Format a number as compact k-string."""
    if abs(n) >= 1000:
        v = n / 1000
        return f"{int(v)}k" if v == int(v) else f"{v:.1f}k"
    return str(int(n))


def _pct(used: float, limit: float) -> int:
    if limit <= 0:
        return 0
    return round(used / limit * 100)


def format_brief(
    tokens_used: int,
    token_limit: int,
    session_cost: float,
    cost_limit: float,
    sent_messages: int,
    messages_limit: int,
    burn_rate_per_min: float,
    reset_time_str: str,
    width: int = 0,
) -> str:
    """Return compact status string, wrapping at block boundaries to fit width."""
    if width <= 0:
        width = shutil.get_terminal_size().columns

    blocks = [
        f"tok: {_fmt_k(tokens_used)}/{_fmt_k(token_limit)} ({_pct(tokens_used, token_limit)}%)",
        f"cost: ${session_cost:.2f}/${cost_limit:.2f} ({_pct(session_cost, cost_limit)}%)",
        f"msgs: {sent_messages}/{messages_limit} ({_pct(sent_messages, messages_limit)}%)",
        f"burn: {_fmt_k(burn_rate_per_min * 60)}/hr",
        f"reset: {reset_time_str}",
    ]

    lines: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        # Length if we add this block to the current line
        needed = len(block) if not current else current_len + len(" | ") + len(block)
        if current and needed > width:
            lines.append(" | ".join(current))
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len = needed

    if current:
        lines.append(" | ".join(current))

    return "\n".join(lines)
