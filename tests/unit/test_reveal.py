"""Переход к файлу: какая команда открывает проводник.

Сам запуск проводника проверить в тесте нечем, а вот команду — можно, и
именно в ней легко ошибиться: `explorer /select, путь` с пробелом открывает
«Документы» вместо нужной папки.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docrenamer.reveal import reveal, reveal_command


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "Дело Петрова" / "иск.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4\n")
    return path


def test_windows_selects_the_file(document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows умеет выделить сам файл — запятая без пробела обязательна."""
    monkeypatch.setattr(shutil, "which", lambda name: f"C:\\Windows\\{name}.exe")

    command = reveal_command(document, system="nt")

    assert command is not None
    assert command[1] == f"/select,{document}"
    assert " " not in command[1][:8]


def test_macos_reveals_the_file(document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/open" if name == "open" else None)

    assert reveal_command(document, system="posix") == ["/usr/bin/open", "-R", str(document)]


def test_linux_opens_the_folder(document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Единого способа выделить файл нет — открывается папка, где он лежит."""
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
    )

    assert reveal_command(document, system="posix") == [
        "/usr/bin/xdg-open",
        str(document.parent),
    ]


def test_no_opener_at_all(document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert reveal_command(document, system="posix") is None


def test_missing_file_is_explained(tmp_path: Path) -> None:
    """Файла нет — окно должно сказать об этом, а не промолчать."""
    assert reveal(tmp_path / "нет такого.pdf") == "Файла больше нет на прежнем месте."


def test_command_is_a_list_without_shell(document: Path) -> None:
    """Команда собирается списком: строковая склейка запрещена (правило 20)."""
    command = reveal_command(document, system="nt")

    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
