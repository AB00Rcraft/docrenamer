"""Границы удаления временных данных (раздел 62 ТЗ)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from docrenamer.paths import AppPaths
from docrenamer.security.temp_cleanup import (
    SessionTemp,
    TempGuardError,
    cleanup_stale_sessions,
    purge,
    temp_dir_is_safe,
)

pytestmark = pytest.mark.safety


def test_purge_outside_temp_is_refused(app_paths: AppPaths, workdir: Path) -> None:
    victim = workdir / "важный.pdf"
    victim.write_bytes(b"%PDF")

    with pytest.raises(TempGuardError):
        purge(victim, app_paths.temp_dir)

    assert victim.exists()


def test_session_temp_is_removed_on_exit(app_paths: AppPaths) -> None:
    with SessionTemp(app_paths, "сессия1") as temp:
        artifact = temp.path("страница-1.png")
        artifact.write_bytes(b"PNG")
        assert artifact.exists()
        root = temp.root
    assert not root.exists()


def test_session_path_cannot_escape(app_paths: AppPaths) -> None:
    temp = SessionTemp(app_paths, "сессия2")
    temp.ensure()
    with pytest.raises(TempGuardError):
        temp.path("../../побег.txt")


def test_stale_sessions_cleaned_current_kept(app_paths: AppPaths) -> None:
    stale = app_paths.temp_dir / "старая"
    stale.mkdir(parents=True)
    (stale / "остаток.png").write_bytes(b"x")
    old = time.time() - 48 * 3600
    import os

    os.utime(stale, (old, old))

    current = SessionTemp(app_paths, "текущая")
    current.ensure()

    removed = cleanup_stale_sessions(app_paths, keep="текущая")

    assert removed == 1
    assert not stale.exists()
    assert current.root.exists()


def test_temp_dir_not_in_cloud_storage(app_paths: AppPaths) -> None:
    assert temp_dir_is_safe(app_paths)
    cloud = AppPaths(root=Path("/home/user/OneDrive/DocRenamer"))
    assert not temp_dir_is_safe(cloud)
