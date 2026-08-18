"""Проверка и загрузка обновления (только эта часть программы знает про сеть).

Используется исключительно стандартная библиотека: сторонних сетевых клиентов
в дистрибутиве нет.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docrenamer_updater.version import is_newer

#: Откуда берутся релизы. Значение можно переопределить в настройках.
DEFAULT_REPOSITORY = "AB00Rcraft/docrenamer"

#: Имена файлов релиза.
INSTALLER_ASSET = "DocRenamer-Setup.exe"
PORTABLE_ASSET = "DocRenamer-portable.zip"
CHECKSUMS_ASSET = "SHA256SUMS.txt"

USER_AGENT = "DocRenamer-Updater"
TIMEOUT_SECONDS = 30
MAX_ASSET_BYTES = 500 * 1024 * 1024


class UpdateError(RuntimeError):
    """Обновление невозможно; сообщение предназначено пользователю."""


@dataclass(slots=True)
class Release:
    """Сведения о доступной версии."""

    version: str
    notes: str = ""
    assets: dict[str, str] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)

    def installer_url(self) -> str:
        for name in (INSTALLER_ASSET, PORTABLE_ASSET):
            if name in self.assets:
                return self.assets[name]
        raise UpdateError("В релизе нет файла установки.")

    def installer_name(self) -> str:
        for name in (INSTALLER_ASSET, PORTABLE_ASSET):
            if name in self.assets:
                return name
        raise UpdateError("В релизе нет файла установки.")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "notes": self.notes, "assets": sorted(self.assets)}


def _open(url: str, timeout: int = TIMEOUT_SECONDS) -> Any:
    """Открыть HTTPS-соединение с проверкой сертификата."""
    if not url.startswith("https://"):
        raise UpdateError("Обновление загружается только по защищённому соединению.")
    # Схема проверена выше: допускается только https.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    context = ssl.create_default_context()
    try:
        return urllib.request.urlopen(  # noqa: S310
            request, timeout=timeout, context=context
        )
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Сервер обновлений ответил ошибкой {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Не удалось связаться с сервером обновлений: {exc}") from exc


def fetch_latest(repository: str = DEFAULT_REPOSITORY) -> Release:
    """Узнать про последнюю опубликованную версию."""
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    with _open(url) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))

    assets = {
        str(item.get("name")): str(item.get("browser_download_url"))
        for item in payload.get("assets", [])
        if item.get("name") and item.get("browser_download_url")
    }
    release = Release(
        version=str(payload.get("tag_name") or payload.get("name") or ""),
        notes=str(payload.get("body") or ""),
        assets=assets,
    )
    if CHECKSUMS_ASSET in assets:
        release.checksums = _fetch_checksums(assets[CHECKSUMS_ASSET])
    return release


def _fetch_checksums(url: str) -> dict[str, str]:
    """Прочитать файл контрольных сумм релиза."""
    with _open(url) as response:
        text = response.read(64 * 1024).decode("utf-8", errors="replace")
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            result[parts[1]] = parts[0].lower()
    return result


def check(current_version: str, repository: str = DEFAULT_REPOSITORY) -> Release | None:
    """Есть ли версия новее текущей."""
    release = fetch_latest(repository)
    if not release.version or not is_newer(release.version, current_version):
        return None
    return release


def download(release: Release, target_dir: Path) -> Path:
    """Скачать файл установки и сверить его контрольную сумму.

    Файл без подтверждённой контрольной суммы не сохраняется: подменённый
    установщик получил бы права на запись в каталог программы.
    """
    name = release.installer_name()
    url = release.installer_url()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name

    digest = hashlib.sha256()
    written = 0
    with _open(url, timeout=TIMEOUT_SECONDS * 10) as response, open(target, "wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_ASSET_BYTES:
                target.unlink(missing_ok=True)
                raise UpdateError("Файл обновления неправдоподобно большой.")
            digest.update(chunk)
            handle.write(chunk)

    expected = release.checksums.get(name, "")
    if not expected:
        target.unlink(missing_ok=True)
        raise UpdateError(
            "В релизе нет контрольной суммы для файла обновления — установка отменена."
        )
    if digest.hexdigest() != expected:
        target.unlink(missing_ok=True)
        raise UpdateError(
            "Контрольная сумма загруженного файла не совпала — установка отменена."
        )
    return target
