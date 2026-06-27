"""README contract tests for the external tools boundary."""

from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _related_tools_section() -> str:
    text = _readme()
    marker = "## Related Tools"
    assert marker in text
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def _single_spaced(value: str) -> str:
    return " ".join(value.split())


def test_readme_has_awesome_badge_and_related_tools_nav() -> None:
    text = _readme()

    assert "[![Mentioned in Awesome Claude Code]" in text
    assert "https://awesome.re/mentioned-badge.svg" in text
    assert "https://github.com/hesreallyhim/awesome-claude-code" in text
    assert "- [Related Tools](#related-tools)" in text


def test_related_tools_codifies_state_file_boundary() -> None:
    section = _related_tools_section()
    compact = _single_spaced(section)

    assert "`--write-state`" in section
    assert "`--once --output json`" in section
    assert (
        "GUIs, tray apps, hardware dashboards, and provider adapters belong in "
        "separate repositories"
    ) in compact
    assert "consume the state/export protocol" in compact


def test_related_tools_lists_known_companions() -> None:
    section = _related_tools_section()

    assert "https://github.com/patwalls/headroom" in section
    assert "https://github.com/leeguooooo/claude-code-usage-bar" in section
    assert "https://github.com/amgb20/claude-monitor-cyd" in section
    assert "https://github.com/LyndonWangWork/Claude-Code-Usage-Tracker" in section


def test_related_tools_documents_adapter_trust_rules() -> None:
    section = _related_tools_section()
    compact = _single_spaced(section)

    assert "OpenCode" in section
    assert "`source.kind`" in section
    assert "default to Claude Code data" in compact
    assert "must not auto-merge" in compact
    assert "Claude 5-hour subscription window" in compact
    assert "Cursor" in section
    assert "Claude Desktop" in section
    assert "no local usage/limit signal" in compact
