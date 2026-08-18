"""Инварианты транзакции переименования (разделы 48, 49, 76, 77 ТЗ)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docrenamer.operations.hashing import sha256_file
from docrenamer.operations.rename import CriticalSafetyError, rename_file
from docrenamer.types import Status

pytestmark = pytest.mark.safety

PAYLOAD = "ПОСТАНОВЛЕНИЕ\nот 27 июля 2026 года\nИванов Иван Иванович\n".encode()


@pytest.fixture
def source_file(workdir: Path) -> Path:
    path = workdir / "IMG_0032.pdf"
    path.write_bytes(PAYLOAD)
    return path


def test_rename_preserves_content_and_hash(source_file: Path, workdir: Path) -> None:
    sha_before = sha256_file(source_file)
    size_before = source_file.stat().st_size
    target = workdir / "2026-07-27__Постановление-СПИ__Иванов.pdf"

    outcome = rename_file(
        source_file,
        target,
        expected_size=size_before,
        expected_mtime=source_file.stat().st_mtime,
        expected_sha256=sha_before,
    )

    assert outcome.ok
    assert outcome.status == Status.RENAMED.value
    assert target.exists()
    assert not source_file.exists()
    assert target.read_bytes() == PAYLOAD
    assert target.stat().st_size == size_before
    assert outcome.record is not None
    assert outcome.record.sha256_before == outcome.record.sha256_after == sha_before


def test_never_overwrites_existing_file(source_file: Path, workdir: Path) -> None:
    occupied = workdir / "занято.pdf"
    occupied.write_bytes(b"NE TROGAT")

    outcome = rename_file(source_file, occupied)

    assert not outcome.ok
    assert occupied.read_bytes() == b"NE TROGAT"
    assert source_file.exists()
    assert source_file.read_bytes() == PAYLOAD


def test_move_to_other_directory_rejected(source_file: Path, tmp_path: Path) -> None:
    other = tmp_path / "другой"
    other.mkdir()

    outcome = rename_file(source_file, other / "имя.pdf")

    assert not outcome.ok
    assert outcome.status == Status.UNSAFE_PATH.value
    assert source_file.exists()
    assert not (other / "имя.pdf").exists()


def test_source_changed_after_preview_skipped(source_file: Path, workdir: Path) -> None:
    stale_sha = sha256_file(source_file)
    source_file.write_bytes(PAYLOAD + "\nдописано".encode())

    outcome = rename_file(source_file, workdir / "новое.pdf", expected_sha256=stale_sha)

    assert not outcome.ok
    assert outcome.status == Status.SOURCE_CHANGED_AFTER_PREVIEW.value
    assert source_file.exists()


def test_size_change_detected_before_hashing(source_file: Path, workdir: Path) -> None:
    outcome = rename_file(
        source_file,
        workdir / "новое.pdf",
        expected_size=999_999,
        expected_mtime=source_file.stat().st_mtime,
    )
    assert outcome.status == Status.SOURCE_CHANGED_AFTER_PREVIEW.value
    assert source_file.exists()


def test_missing_source_is_reported(workdir: Path) -> None:
    outcome = rename_file(workdir / "нет.pdf", workdir / "есть.pdf")
    assert not outcome.ok
    assert outcome.status == Status.SKIPPED.value


def test_same_name_is_not_a_rename(source_file: Path) -> None:
    outcome = rename_file(source_file, source_file)
    assert outcome.status == Status.NAME_UNCHANGED.value
    assert source_file.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink требует прав администратора в Windows")
def test_symlink_is_not_renamed(source_file: Path, workdir: Path) -> None:
    link = workdir / "ссылка.pdf"
    os.symlink(source_file, link)

    outcome = rename_file(link, workdir / "новая-ссылка.pdf")

    assert not outcome.ok
    assert outcome.status == Status.UNSAFE_PATH.value
    assert link.is_symlink()


def test_unsafe_target_name_rejected(source_file: Path, workdir: Path) -> None:
    outcome = rename_file(source_file, workdir / "CON.pdf")
    assert not outcome.ok
    assert outcome.status == Status.UNSAFE_PATH.value
    assert source_file.exists()


def test_hash_mismatch_raises_critical(monkeypatch: pytest.MonkeyPatch, source_file: Path,
                                       workdir: Path) -> None:
    """Расхождение SHA-256 обязано останавливать пакет (раздел 48 ТЗ)."""
    import docrenamer.operations.rename as rename_module

    calls = {"n": 0}
    real = rename_module.sha256_file

    def fake(path: Path, *args: object, **kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return real(path)
        return "0" * 64

    monkeypatch.setattr(rename_module, "sha256_file", fake)

    with pytest.raises(CriticalSafetyError):
        rename_file(source_file, workdir / "цель.pdf")


def test_russian_names_round_trip(workdir: Path) -> None:
    source = workdir / "Постановление Иванова И.И..pdf"
    source.write_bytes(PAYLOAD)
    sha = sha256_file(source)
    target = workdir / "2026-07-27__Постановление-СПИ__Иванов-ИИ__652102-26-77028-ИП.pdf"

    outcome = rename_file(source, target, expected_sha256=sha)

    assert outcome.ok
    assert target.exists()
    assert sha256_file(target) == sha


def test_link_fallback_also_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, source_file: Path, workdir: Path
) -> None:
    """Запасной путь ``link+unlink`` не перезаписывает существующий файл.

    На Linux используется ``renameat2(RENAME_NOREPLACE)``; на прочих POSIX —
    ``os.link`` с последующим снятием старого имени. Оба пути обязаны быть
    неперезаписывающими, поэтому запасной проверяется отдельно.
    """
    import docrenamer.operations.rename as rename_module

    monkeypatch.setattr(rename_module, "_renameat2_noreplace", lambda source, target: False)
    occupied = workdir / "занято.pdf"
    occupied.write_bytes(b"NE TROGAT")

    outcome = rename_file(source_file, occupied)

    assert not outcome.ok
    assert occupied.read_bytes() == b"NE TROGAT"
    assert source_file.exists()


def test_link_fallback_preserves_content(
    monkeypatch: pytest.MonkeyPatch, source_file: Path, workdir: Path
) -> None:
    """Запасной путь сохраняет содержимое и контрольную сумму."""
    import docrenamer.operations.rename as rename_module

    monkeypatch.setattr(rename_module, "_renameat2_noreplace", lambda source, target: False)
    sha_before = sha256_file(source_file)
    target = workdir / "2026-07-27__Постановление.pdf"

    outcome = rename_file(source_file, target, expected_sha256=sha_before)

    assert outcome.ok
    assert outcome.method == "link+unlink"
    assert not source_file.exists()
    assert sha256_file(target) == sha_before
    assert target.read_bytes() == PAYLOAD
