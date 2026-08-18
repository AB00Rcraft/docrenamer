"""Вычисление SHA-256 пользовательских файлов (разделы 48, 76 ТЗ).

Файлы открываются строго на чтение. Ни один режим открытия здесь не должен
допускать запись.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Размер блока чтения. 1 МиБ — компромисс между syscall-нагрузкой и памятью.
CHUNK_SIZE = 1024 * 1024


class HashError(OSError):
    """Не удалось вычислить контрольную сумму."""


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Полный SHA-256 файла.

    Raises:
        HashError: файл недоступен или исчез во время чтения.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise HashError(f"Не удалось прочитать файл для контрольной суммы: {path}") from exc
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """SHA-256 для блока данных (используется в тестах и кэше)."""
    return hashlib.sha256(data).hexdigest()


def file_signature(path: Path) -> tuple[int, float]:
    """Дешёвая подпись файла ``(size, mtime)`` для проверки изменений."""
    stat = path.stat()
    return stat.st_size, stat.st_mtime
