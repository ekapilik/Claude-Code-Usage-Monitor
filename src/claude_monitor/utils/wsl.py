"""Windows Subsystem for Linux Claude data-path discovery."""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class WSLDetector:
    """Detect Claude data directories exposed by installed WSL distributions."""

    def __init__(self) -> None:
        self._cached_paths: Optional[List[str]] = None

    def data_paths(self) -> List[str]:
        """Return cached WSL Claude projects directories."""
        if self._cached_paths is None:
            self._cached_paths = self._detect_data_paths()
        return list(self._cached_paths)

    @staticmethod
    def decode_distro_list(raw: bytes) -> List[str]:
        """Decode ``wsl --list --quiet`` output, which is commonly UTF-16-LE."""
        if not raw:
            return []
        encodings = ("utf-16-le", "utf-8")
        text = ""
        for encoding in encodings:
            try:
                candidate = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if candidate.strip("\x00\r\n "):
                text = candidate
                break
        return [
            line.replace("\x00", "").strip()
            for line in text.splitlines()
            if line.replace("\x00", "").strip()
        ]

    def _detect_data_paths(self) -> List[str]:
        if platform.system() != "Windows":
            return []
        try:
            result = subprocess.run(
                ["wsl", "--list", "--quiet"],
                capture_output=True,
                check=False,
            )
        except OSError as e:
            logger.debug("WSL detection unavailable: %s", e)
            return []

        distros = self.decode_distro_list(result.stdout)
        paths: List[str] = []
        seen: set[str] = set()
        for distro in distros:
            for prefix in (r"\\wsl$", r"\\wsl.localhost"):
                home_root = Path(prefix) / distro / "home"
                if not home_root.exists():
                    continue
                try:
                    users = list(home_root.iterdir())
                except OSError as e:
                    logger.debug("Cannot scan WSL home root %s: %s", home_root, e)
                    continue
                for user_home in users:
                    candidate = user_home / ".claude" / "projects"
                    if not candidate.is_dir():
                        continue
                    value = str(candidate)
                    if value in seen:
                        continue
                    seen.add(value)
                    paths.append(value)
        return paths
