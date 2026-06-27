"""Tests for Windows Subsystem for Linux data-path discovery (#92)."""

from claude_monitor.utils.wsl import WSLDetector


def test_wsl_detector_decodes_utf16_le_distro_output() -> None:
    raw = "Ubuntu\x00\nDebian\x00\n".encode("utf-16-le")

    assert WSLDetector.decode_distro_list(raw) == ["Ubuntu", "Debian"]


def test_wsl_detector_caches_detected_paths() -> None:
    calls = 0

    class FakeDetector(WSLDetector):
        def _detect_data_paths(self) -> list[str]:
            nonlocal calls
            calls += 1
            return [r"\\wsl$\Ubuntu\home\maciek\.claude\projects"]

    detector = FakeDetector()

    assert detector.data_paths() == [r"\\wsl$\Ubuntu\home\maciek\.claude\projects"]
    assert detector.data_paths() == [r"\\wsl$\Ubuntu\home\maciek\.claude\projects"]
    assert calls == 1
