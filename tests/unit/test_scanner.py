"""Тесты сканера каталогов (раздел 9 ТЗ)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docrenamer.paths import AppPaths
from docrenamer.scanner import IGNORE_PATTERNS, Scanner, is_ignored_name, scan_directory


@pytest.mark.parametrize("name", ["Thumbs.db", "desktop.ini", "~$черновик.docx", "буфер.tmp"])
def test_service_files_ignored(name: str) -> None:
    assert is_ignored_name(name, IGNORE_PATTERNS)


def test_ignored_directories_not_scanned(workdir: Path) -> None:
    (workdir / "документ.pdf").write_bytes(b"%PDF-1.4")
    for ignored in (".git", "node_modules", "__pycache__", "logs", "manifests", "runtime_temp"):
        directory = workdir / ignored
        directory.mkdir()
        (directory / "скрытый.txt").write_text("x", encoding="utf-8")

    files, stats = scan_directory(workdir)
    assert [f.path.name for f in files] == ["документ.pdf"]
    assert stats.files_found == 1


def test_recursive_and_flat_modes(workdir: Path) -> None:
    (workdir / "верх.pdf").write_bytes(b"%PDF")
    nested = workdir / "Том 1" / "Раздел 2"
    nested.mkdir(parents=True)
    (nested / "вложенный.docx").write_bytes(b"PK\x03\x04")

    deep, _ = scan_directory(workdir, recursive=True)
    flat, _ = scan_directory(workdir, recursive=False)
    assert {f.path.name for f in deep} == {"верх.pdf", "вложенный.docx"}
    assert {f.path.name for f in flat} == {"верх.pdf"}


@pytest.mark.skipif(os.name == "nt", reason="symlink требует прав администратора в Windows")
def test_symlink_loop_does_not_hang(workdir: Path) -> None:
    (workdir / "файл.txt").write_text("x", encoding="utf-8")
    os.symlink(workdir, workdir / "петля")
    files, stats = scan_directory(workdir)
    assert [f.path.name for f in files] == ["файл.txt"]
    assert stats.symlinks_skipped >= 1


@pytest.mark.skipif(os.name == "nt", reason="symlink требует прав администратора в Windows")
def test_symlink_outside_tree_not_followed(workdir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "чужое"
    outside.mkdir()
    (outside / "секрет.pdf").write_bytes(b"%PDF")
    os.symlink(outside, workdir / "наружу")
    (workdir / "свой.pdf").write_bytes(b"%PDF")

    files, _ = scan_directory(workdir)
    assert [f.path.name for f in files] == ["свой.pdf"]


def test_own_service_directories_excluded(tmp_path: Path) -> None:
    root = tmp_path / "DocRenamer"
    (root / "logs").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "runtime_temp").mkdir()
    (root / "logs" / "rename_log.txt").write_text("x", encoding="utf-8")
    (root / "manifests" / "m.json").write_text("{}", encoding="utf-8")
    (root / "пользовательский.pdf").write_bytes(b"%PDF")

    scanner = Scanner(recursive=True, paths=AppPaths(root=root))
    files = list(scanner.scan(root))
    assert [f.path.name for f in files] == ["пользовательский.pdf"]


def test_russian_names_and_stats(russian_files: list[Path], workdir: Path) -> None:
    files, stats = scan_directory(workdir)
    found = {f.path.name for f in files}
    assert "ёжик.txt" in found
    assert "№ 652102-26-77028-ИП.pdf" in found
    assert stats.files_found == len(russian_files)
    assert "PDF: 2" in stats.summary_ru()


def test_scan_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        list(Scanner().scan(tmp_path / "нет-такого"))
