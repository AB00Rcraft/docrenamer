"""Что программа уже переименовывала раньше.

В рабочей папке файлы копятся годами, и повторный запуск обычно нужен ради
десятка новых, а не ради четырёх тысяч разобранных. Поэтому программа помнит
свою работу: в manifest каждой операции записаны новое имя файла и его
контрольная сумма.

По этим записям файл узнаётся снова, даже если его переложили: содержимое не
изменилось — значит, это тот самый файл, и предлагать ему новое имя не за чем.
Ничего кроме собственных manifest'ов программы для этого не читается.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from docrenamer.naming.collision import fold

#: Сколько manifest'ов просматривать: старые операции уже не важны, а разбор
#: всей папки manifest'ов на каждом запуске был бы напрасной работой.
MAX_MANIFESTS = 200


@dataclass(slots=True)
class RenameHistory:
    """Имена и контрольные суммы файлов, переименованных программой раньше."""

    #: Контрольная сумма → когда переименован.
    by_hash: dict[str, str] = field(default_factory=dict)
    #: Свёрнутое имя → когда переименован.
    by_name: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.by_hash or self.by_name)

    @classmethod
    def load(cls, manifests_dir: Path, *, limit: int = MAX_MANIFESTS) -> RenameHistory:
        """Собрать сведения из manifest'ов прошлых операций."""
        history = cls()
        try:
            files = sorted(
                (path for path in manifests_dir.glob("*.json") if path.is_file()),
                key=lambda path: path.name,
                reverse=True,
            )[:limit]
        except OSError:
            return history
        for path in files:
            history._read(path)
        return history

    def _read(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("status") != "RENAMED" or record.get("kind") == "folder":
                continue
            stamp = str(record.get("timestamp") or "")[:10]
            digest = str(record.get("sha256_after") or record.get("sha256_before") or "")
            name = str(record.get("new_filename") or "")
            if digest:
                self.by_hash.setdefault(digest, stamp)
            if name:
                self.by_name.setdefault(fold(name), stamp)

    def renamed_on(self, name: str, digest: str = "") -> str:
        """Когда программа переименовала этот файл, если переименовывала.

        Сначала сверяется содержимое: имя могли изменить руками, а файл
        остался тем же. Затем — само имя, потому что содержимое могло быть
        не прочитано.
        """
        if digest:
            stamp = self.by_hash.get(digest)
            if stamp is not None:
                return stamp or "ранее"
        stamp = self.by_name.get(fold(name))
        if stamp is not None:
            return stamp or "ранее"
        return ""

    def merge(self, others: Iterable[RenameHistory]) -> RenameHistory:
        """Объединить с другими сведениями (для проверок и будущих источников)."""
        for other in others:
            self.by_hash.update(other.by_hash)
            self.by_name.update(other.by_name)
        return self
