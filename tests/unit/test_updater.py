"""Программа обновления (требование приёмки).

Обновление вынесено в отдельный исполняемый файл: программа обработки
документов остаётся полностью офлайновой. Здесь проверяется и это разделение,
и безопасность самой загрузки — ни один тест в сеть не ходит.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path

import pytest

from docrenamer_updater import cli
from docrenamer_updater.client import Release, UpdateError, check, download, fetch_latest
from docrenamer_updater.version import is_newer, parse

SRC = Path(__file__).resolve().parents[2] / "src"


class FakeResponse(io.BytesIO):
    """Минимальная замена ответа HTTP."""

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def fake_opener(pages: dict[str, bytes]):
    def _open(url: str, timeout: int = 30) -> FakeResponse:
        if url not in pages:
            raise UpdateError(f"неизвестный адрес: {url}")
        return FakeResponse(pages[url])

    return _open


def release_pages(payload_version: str, body: bytes) -> tuple[dict[str, bytes], str]:
    digest = hashlib.sha256(body).hexdigest()
    api = "https://api.github.com/repos/owner/repo/releases/latest"
    setup_url = "https://github.com/owner/repo/releases/download/v9/DocRenamer-Setup.exe"
    sums_url = "https://github.com/owner/repo/releases/download/v9/SHA256SUMS.txt"
    payload = {
        "tag_name": payload_version,
        "body": "Что нового",
        "assets": [
            {"name": "DocRenamer-Setup.exe", "browser_download_url": setup_url},
            {"name": "SHA256SUMS.txt", "browser_download_url": sums_url},
        ],
    }
    pages = {
        api: json.dumps(payload).encode("utf-8"),
        setup_url: body,
        sums_url: f"{digest}  DocRenamer-Setup.exe\n".encode(),
    }
    return pages, digest


# --- разделение обязанностей ------------------------------------------------


def test_main_program_has_no_network_code() -> None:
    """В самой программе обработки документов сетевых импортов нет."""
    from docrenamer.security.offline_guard import audit_source

    assert audit_source(SRC / "docrenamer") == []


def test_main_program_does_not_import_updater() -> None:
    """Пакет docrenamer не тянет за собой сетевой код обновления."""
    offenders = []
    for path in sorted((SRC / "docrenamer").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name.startswith("docrenamer_updater") for name in names):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"docrenamer импортирует обновление: {offenders}"


def test_updater_never_touches_user_documents() -> None:
    """Программа обновления не содержит кода чтения пользовательских файлов."""
    forbidden = {"docrenamer.readers", "docrenamer.analysis", "docrenamer.operations"}
    for path in sorted((SRC / "docrenamer_updater").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            assert not any(module.startswith(bad) for bad in forbidden), f"{path}: {module}"


# --- сравнение версий -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.0.0", (1, 0, 0)), ("v1.2.3", (1, 2, 3)), ("2.1", (2, 1, 0)), ("мусор", (0, 0, 0))],
)
def test_version_parsing(value: str, expected: tuple[int, int, int]) -> None:
    assert parse(value) == expected


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("v1.0.1", "1.0.0", True),
        ("v1.0.0", "1.0.0", False),
        ("v0.9.9", "1.0.0", False),
        ("v1.10.0", "1.9.0", True),
    ],
)
def test_version_comparison(candidate: str, current: str, newer: bool) -> None:
    assert is_newer(candidate, current) is newer


# --- проверка обновления ----------------------------------------------------


def test_check_reports_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    pages, _ = release_pages("v1.0.1", b"installer")
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))

    release = check("1.0.0", "owner/repo")

    assert release is not None
    assert release.version == "v1.0.1"
    assert release.installer_name() == "DocRenamer-Setup.exe"


def test_check_is_silent_when_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    pages, _ = release_pages("v1.0.0", b"installer")
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))

    assert check("1.0.0", "owner/repo") is None


def test_only_https_is_allowed() -> None:
    release = Release(version="v2", assets={"DocRenamer-Setup.exe": "http://example.invalid/x"})
    with pytest.raises(UpdateError) as exc:
        download(release, Path("/tmp"))
    assert "защищённому" in str(exc.value)


# --- загрузка и проверка целостности ---------------------------------------


def test_download_verifies_checksum(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pages, digest = release_pages("v1.0.1", b"installer-bytes")
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))
    release = fetch_latest("owner/repo")

    installer = download(release, tmp_path)

    assert installer.read_bytes() == b"installer-bytes"
    assert hashlib.sha256(installer.read_bytes()).hexdigest() == digest


def test_tampered_download_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Подменённый установщик не сохраняется: он получил бы права на запись."""
    pages, _ = release_pages("v1.0.1", b"installer-bytes")
    setup_url = "https://github.com/owner/repo/releases/download/v9/DocRenamer-Setup.exe"
    pages[setup_url] = "ПОДМЕНА".encode()
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))
    release = fetch_latest("owner/repo")

    with pytest.raises(UpdateError) as exc:
        download(release, tmp_path)

    assert "Контрольная сумма" in str(exc.value)
    assert not list(tmp_path.iterdir()), "повреждённый файл не должен оставаться на диске"


def test_missing_checksum_blocks_installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages, _ = release_pages("v1.0.1", b"installer-bytes")
    release = Release(
        version="v1.0.1",
        assets={
            "DocRenamer-Setup.exe": (
                "https://github.com/owner/repo/releases/download/v9/DocRenamer-Setup.exe"
            )
        },
    )
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))

    with pytest.raises(UpdateError) as exc:
        download(release, tmp_path)

    assert "контрольной суммы" in str(exc.value)


def test_oversized_download_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("docrenamer_updater.client.MAX_ASSET_BYTES", 16)
    pages, _ = release_pages("v1.0.1", b"x" * 64)
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))
    release = fetch_latest("owner/repo")

    with pytest.raises(UpdateError):
        download(release, tmp_path)

    # Незавершённая загрузка не остаётся на диске (в Windows файл нельзя
    # удалить, пока он открыт, — проверяется именно порядок операций).
    assert not list(tmp_path.iterdir())


# --- командная строка -------------------------------------------------------


def test_cli_reports_available_update(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pages, _ = release_pages("v1.0.1", b"installer")
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))

    code = cli.main(["--check", "--json", "--current", "1.0.0", "--repository", "owner/repo"])
    payload = json.loads(capsys.readouterr().out.strip())

    assert code == cli.EXIT_OK
    assert payload["update"] is True
    assert payload["version"] == "v1.0.1"


def test_cli_reports_up_to_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pages, _ = release_pages("v1.0.0", b"installer")
    monkeypatch.setattr("docrenamer_updater.client._open", fake_opener(pages))

    code = cli.main(["--check", "--current", "1.0.0", "--repository", "owner/repo"])

    assert code == cli.EXIT_UP_TO_DATE
    assert "последняя версия" in capsys.readouterr().out


def test_cli_survives_network_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(url: str, timeout: int = 30) -> None:
        raise UpdateError("сеть недоступна")

    monkeypatch.setattr("docrenamer_updater.client._open", broken)

    code = cli.main(["--check", "--current", "1.0.0"])

    assert code == cli.EXIT_ERROR
    assert "Не удалось проверить обновления" in capsys.readouterr().err


def test_closed_source_reports_understandable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Закрытый репозиторий отвечает 404 — пользователю нужен понятный текст."""
    import urllib.error

    from docrenamer_updater import client

    def raising(request: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "https://api.github.com", 404, "Not Found", {}, None  # type: ignore[arg-type]
        )

    monkeypatch.setattr(client.urllib.request, "urlopen", raising)

    with pytest.raises(UpdateError) as exc:
        client.fetch_latest("owner/private")

    assert "закрыт" in str(exc.value)
    assert "404" not in str(exc.value)


# --- обновление поверх установленной версии ---------------------------------


def test_updater_relaunches_itself_from_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Программа обновления уходит во временный каталог перед установкой.

    Установщик перезаписывает и её файл: запущенный из каталога программы, он
    занят, и установка спотыкается.
    """
    import subprocess as subprocess_module

    from docrenamer_updater import cli as updater_cli

    installed = tmp_path / "program" / "DocRenamerUpdate.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"MZ")
    launched: dict[str, object] = {}

    monkeypatch.setattr(updater_cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_cli.sys, "executable", str(installed), raising=False)
    monkeypatch.setattr(updater_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(updater_cli.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
    monkeypatch.setattr(
        subprocess_module, "Popen", lambda command, **kwargs: launched.update(command=command)
    )

    assert updater_cli.relaunch_from_temp(["--install"]) is True
    assert "temp" in str(launched["command"][0])
    assert launched["command"][1] == "--install"
    assert (tmp_path / "temp" / "docrenamer-update" / "DocRenamerUpdate.exe").is_file()


def test_updater_does_not_relaunch_in_a_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Уже запущенная из временного каталога копия себя не копирует."""
    from docrenamer_updater import cli as updater_cli

    temp_dir = tmp_path / "temp" / "docrenamer-update"
    temp_dir.mkdir(parents=True)
    running = temp_dir / "DocRenamerUpdate.exe"
    running.write_bytes(b"MZ")

    monkeypatch.setattr(updater_cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_cli.sys, "executable", str(running), raising=False)
    monkeypatch.setattr(updater_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(updater_cli.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))

    assert updater_cli.relaunch_from_temp(["--install"]) is False


def test_relaunch_is_skipped_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Из исходников программа обновления работает как есть."""
    from docrenamer_updater import cli as updater_cli

    monkeypatch.setattr(updater_cli.sys, "frozen", False, raising=False)
    assert updater_cli.relaunch_from_temp(["--install"]) is False


def test_installer_handles_upgrade_over_previous_version() -> None:
    """Установщик умеет ставиться поверх прежней версии."""
    script = (Path(__file__).resolve().parents[2] / "installer" / "DocRenamer.iss").read_text(
        encoding="utf-8"
    )

    assert "CloseApplications=yes" in script, "занятые файлы должны закрываться"
    assert "PrepareToInstall" in script, "прежняя версия должна сниматься заранее"
    assert "UsePreviousAppDir=yes" in script
    assert "SetupMutex" in script, "два установщика одновременно недопустимы"
