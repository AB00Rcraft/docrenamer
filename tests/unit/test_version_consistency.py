"""Версия объявлена в одном месте (иначе обновление работает неверно)."""

from __future__ import annotations

import re
from pathlib import Path

import docrenamer
import docrenamer_updater

ROOT = Path(__file__).resolve().parents[2]


def test_packages_share_one_version() -> None:
    assert docrenamer.__version__ == docrenamer_updater.__version__


def test_pyproject_matches_code() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == docrenamer.__version__


def test_installer_matches_code() -> None:
    text = (ROOT / "installer" / "DocRenamer.iss").read_text(encoding="utf-8")
    match = re.search(r'#define AppVersion "([^"]+)"', text)
    assert match is not None
    assert match.group(1) == docrenamer.__version__


def test_update_check_is_silent_for_same_version() -> None:
    """Установленная версия не должна считаться устаревшей сама по себе."""
    from docrenamer_updater.version import is_newer

    assert not is_newer(f"v{docrenamer.__version__}", docrenamer.__version__)
