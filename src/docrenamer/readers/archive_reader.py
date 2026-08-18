"""Архивы (разделы 32, 54 ТЗ).

Архивы только инспектируются: ни один элемент не распаковывается на диск.
Ограничивается и число записей, и коэффициент сжатия — защита от «архивных
бомб».
"""

from __future__ import annotations

import tarfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.security.subprocess_safe import run_tool
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def read_archive(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать список содержимого архива."""
    result = ReadResult()
    suffix = path.suffix.lower()
    if suffix == ".zip" or suffix == ".kmz":
        entries, metadata = _list_zip(path, context, result)
    elif suffix in (".tar", ".gz", ".tgz"):
        entries, metadata = _list_tar(path, context, result)
    else:
        entries, metadata = _list_with_sevenzip(path, context, result)

    if not entries and not result.statuses:
        result.add_status(Status.EMPTY_DOCUMENT)

    limit = context.config.archives.max_entries_to_analyze
    metadata["entry_count"] = len(entries)
    metadata["entries_sample"] = [nfc(e) for e in entries[:limit]][:50]
    metadata["extensions"] = dict(
        Counter(Path(e).suffix.lower() or "<без расширения>" for e in entries).most_common(10)
    )
    common = _common_theme(entries)
    if common:
        metadata["archive_theme"] = common
    result.metadata.update(safe_metadata(metadata))
    result.source_encoding = "archive/listing"
    result.encoding_confidence = 0.9

    text = "\n".join(nfc(e) for e in entries[:limit])
    return finalize_text(result, text, context.limits, check_mixed_alphabet=False)


def _list_zip(
    path: Path, context: ReaderContext, result: ReadResult
) -> tuple[list[str], dict[str, Any]]:
    """Список ZIP: читается только центральный каталог."""
    entries: list[str] = []
    metadata: dict[str, Any] = {"archive_format": "zip"}
    limits = context.limits
    try:
        with zipfile.ZipFile(path) as archive:
            total_compressed = 0
            total_uncompressed = 0
            for info in archive.infolist():
                if len(entries) >= limits.max_archive_entries:
                    result.add_status(Status.LIMIT_EXCEEDED)
                    break
                if info.is_dir():
                    continue
                entries.append(info.filename)
                total_compressed += info.compress_size
                total_uncompressed += info.file_size
                if info.flag_bits & 0x1:
                    metadata["encrypted"] = True
            metadata["uncompressed_size"] = total_uncompressed
            if total_compressed > 0:
                ratio = total_uncompressed / total_compressed
                metadata["compression_ratio"] = round(ratio, 2)
                if ratio > limits.max_archive_ratio:
                    result.add_status(Status.LIMIT_EXCEEDED)
                    result.decoding_warnings.append(
                        f"Подозрительный коэффициент сжатия {ratio:.0f}× — "
                        "архив не анализируется глубже."
                    )
            if metadata.get("encrypted"):
                result.add_status(Status.PASSWORD_PROTECTED)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"ZIP не прочитан: {exc}")
    return entries, metadata


def _list_tar(
    path: Path, context: ReaderContext, result: ReadResult
) -> tuple[list[str], dict[str, Any]]:
    """Список TAR/GZ без распаковки."""
    entries: list[str] = []
    metadata: dict[str, Any] = {"archive_format": "tar"}
    limits = context.limits
    try:
        with tarfile.open(path, "r:*") as archive:
            total = 0
            for member in archive:
                if len(entries) >= limits.max_archive_entries:
                    result.add_status(Status.LIMIT_EXCEEDED)
                    break
                if not member.isfile():
                    continue
                entries.append(member.name)
                total += member.size
            metadata["uncompressed_size"] = total
    except (tarfile.TarError, OSError, EOFError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"TAR не прочитан: {exc}")
    return entries, metadata


def _list_with_sevenzip(
    path: Path, context: ReaderContext, result: ReadResult
) -> tuple[list[str], dict[str, Any]]:
    """Список 7Z/RAR через локальный 7-Zip: только команда ``l``."""
    entries: list[str] = []
    metadata: dict[str, Any] = {"archive_format": path.suffix.lstrip(".").lower()}
    executable = context.paths.sevenzip(context.config.allow_system_binaries)
    if executable is None:
        result.add_status(Status.PARTIAL_SUPPORT)
        result.decoding_warnings.append("7-Zip не найден: содержимое архива не прочитано.")
        return entries, metadata

    tool = run_tool(
        executable,
        ["l", "-ba", "-slt", "-p", str(path)],
        timeout=context.limits.subprocess_timeout,
    )
    if not tool.stdout:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(tool.error or "7-Zip не вернул список.")
        return entries, metadata

    encrypted = False
    for line in tool.stdout.splitlines():
        if line.startswith("Path = "):
            name = line[len("Path = ") :].strip()
            if name:
                entries.append(name)
        elif line.startswith("Encrypted = +"):
            encrypted = True
        if len(entries) >= context.limits.max_archive_entries:
            result.add_status(Status.LIMIT_EXCEEDED)
            break
    if encrypted:
        metadata["encrypted"] = True
        result.add_status(Status.PASSWORD_PROTECTED)
    return entries, metadata


def _common_theme(entries: list[str]) -> str:
    """Общая тема архива по именам элементов.

    Возвращает наиболее частое значимое слово, если оно встречается хотя бы в
    половине имён — иначе пустую строку, чтобы не выдумывать сюжет.
    """
    if len(entries) < 3:
        return ""
    counter: Counter[str] = Counter()
    for entry in entries:
        stem = Path(entry).stem.lower()
        for token in stem.replace("_", " ").replace("-", " ").split():
            if len(token) >= 4 and not token.isdigit():
                counter[token] += 1
    if not counter:
        return ""
    word, count = counter.most_common(1)[0]
    if count >= max(3, len(entries) // 2):
        return word
    return ""
