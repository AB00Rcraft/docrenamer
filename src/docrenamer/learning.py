"""Обезличенный журнал обучения: на чём алгоритм имён ошибается.

Самый ценный отзыв об алгоритме — это правка, сделанная человеком: программа
предложила одно, а человек написал другое. Из таких расхождений видно, какие
правила стоит менять.

Записывается только устройство решения, но не сами данные. В журнал не попадают
ни имена файлов, ни пути, ни фамилии, ни названия организаций, ни текст
документа — только вид документа из справочника, набор сегментов имени, длины и
коды состояний. Проверить это легко: файл журнала — обычный текст, и его можно
открыть перед отправкой.

Журнал остаётся на диске. Он никуда не уходит сам: отправку выполняет отдельная
программа обновления и только по прямой команде человека (раздел 3 ТЗ).
"""

from __future__ import annotations

import json
import os
import platform
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docrenamer.paths import AppPaths, default_paths
from docrenamer.types import FileAnalysis, PlanItem

#: Сколько записей хранить: журнал не должен расти бесконечно.
MAX_RECORDS = 5000

#: Разделитель частей имени — по нему имя раскладывается на сегменты.
SEPARATOR_RE = re.compile(r"[_\s]+")


def _bucket(value: float) -> str:
    """Уверенность округляется до десятых: точное число ничего не добавляет."""
    return f"{max(0.0, min(1.0, value)):.1f}"


def _shape(name: str) -> dict[str, Any]:
    """Устройство имени без его содержания.

    Сохраняются длина, число частей и признаки — есть ли дата, номер, слово
    «стр». Сами слова не сохраняются: в них могут быть фамилии.
    """
    stem = Path(name).stem
    parts = [part for part in SEPARATOR_RE.split(stem) if part]
    return {
        "length": len(stem),
        "parts": len(parts),
        "has_date": any(re.fullmatch(r"\d{1,4}[.\-]\d{1,2}[.\-]\d{1,4}", p) for p in parts),
        "has_digits": any(any(ch.isdigit() for ch in p) for p in parts),
        "has_page": any(p.casefold() == "стр" for p in parts),
    }


@dataclass(slots=True)
class LearningLog:
    """Журнал обучения в папке ``logs``."""

    paths: AppPaths = field(default_factory=default_paths)
    version: str = ""
    enabled: bool = True

    @property
    def file(self) -> Path:
        return self.paths.logs_dir / "learning.jsonl"

    # --- запись ------------------------------------------------------------

    def record_plan_item(self, item: PlanItem, *, event: str = "proposed") -> None:
        """Записать, что программа предложила для одного файла."""
        self._write(self._describe(item) | {"event": event})

    def record_edit(self, item: PlanItem, *, proposed: str, chosen: str) -> None:
        """Записать расхождение: программа предложила одно, человек — другое.

        Сами имена не сохраняются — только их устройство и то, что человек
        оставил от предложения: вид документа, дату, число частей.
        """
        before, after = _shape(proposed), _shape(chosen)
        record = self._describe(item) | {
            "event": "edited",
            "before": before,
            "after": after,
            "kept_first_word": _first_word_kept(proposed, chosen),
            "dropped_date": before["has_date"] and not after["has_date"],
            "shorter": after["parts"] < before["parts"],
        }
        self._write(record)

    def record_applied(self, items: list[PlanItem]) -> None:
        """Записать применённые переименования."""
        for item in items:
            self.record_plan_item(item, event="applied")

    def _describe(self, item: PlanItem) -> dict[str, Any]:
        """Обезличенное описание строки плана."""
        analysis: FileAnalysis | None = item.analysis
        metadata = (analysis.metadata if analysis is not None else {}) or {}
        review = metadata.get("name_review")
        record: dict[str, Any] = {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "version": self.version,
            "kind": item.kind,
            "extension": item.source_path.suffix.lower(),
            "confidence": _bucket(item.confidence),
            "status": item.status,
            "statuses": sorted(set(item.statuses))[:6],
            "proposed": _shape(item.proposed_filename or ""),
        }
        if analysis is not None:
            record["category"] = str(analysis.category)
            record["detected_type"] = analysis.detected_type
            # Вид документа — слово из справочника программы, а не из файла.
            record["document_type"] = str(metadata.get("document_type_canonical") or "")
            record["facts"] = {
                "type": analysis.document_type is not None,
                "date": analysis.document_date is not None,
                "number": analysis.document_number is not None,
                "persons": len(analysis.main_persons),
                "organizations": len(analysis.main_organizations),
            }
            record["scan_page"] = bool(metadata.get("scan_page"))
        if isinstance(review, list) and review:
            record["review"] = sorted({str(issue.get("code", "")) for issue in review})[:5]
        return record

    def _write(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
            with self.file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # Журнал обучения — вспомогательный: его сбой не должен мешать
            # основной работе.
            return
        self._trim()

    def _trim(self) -> None:
        """Не давать журналу расти без предела."""
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= MAX_RECORDS:
            return
        try:
            self.file.write_text(
                "\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8"
            )
        except OSError:
            return

    # --- отчёт -------------------------------------------------------------

    def records(self) -> list[dict[str, Any]]:
        """Прочитать журнал."""
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        result: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def build_report(self) -> dict[str, Any]:
        """Свести журнал в короткий отчёт для разработчика.

        Отчёт — это статистика: сколько файлов какого вида разобрано, где
        уверенность низкая, какие имена человек исправлял руками. Ни одного
        значения из самих документов в нём нет.
        """
        records = self.records()
        edits = [r for r in records if r.get("event") == "edited"]
        by_type: Counter[str] = Counter()
        edited_types: Counter[str] = Counter()
        low_confidence: Counter[str] = Counter()
        review_codes: Counter[str] = Counter()
        for record in records:
            document_type = str(record.get("document_type") or "—")
            extension = str(record.get("extension") or "")
            by_type[document_type] += 1
            if record.get("event") == "edited":
                edited_types[document_type] += 1
            if float(record.get("confidence") or 0) < 0.6:
                low_confidence[extension or "—"] += 1
            for code in record.get("review") or []:
                review_codes[str(code)] += 1
        return {
            "report_version": 1,
            "app_version": self.version,
            "system": f"{platform.system()} {platform.release()}",
            "records": len(records),
            "edited": len(edits),
            "edited_share": round(len(edits) / len(records), 3) if records else 0.0,
            "kept_first_word": sum(1 for r in edits if r.get("kept_first_word")),
            "dropped_date": sum(1 for r in edits if r.get("dropped_date")),
            "made_shorter": sum(1 for r in edits if r.get("shorter")),
            "by_document_type": dict(by_type.most_common(15)),
            "edited_document_types": dict(edited_types.most_common(15)),
            "low_confidence_by_extension": dict(low_confidence.most_common(10)),
            "name_review_codes": dict(review_codes.most_common(10)),
        }

    def report_text(self) -> str:
        """Отчёт в виде текста — ровно то, что уйдёт при отправке."""
        return json.dumps(self.build_report(), ensure_ascii=False, indent=2)

    def save_report(self) -> Path:
        """Сохранить отчёт рядом с журналом и вернуть путь."""
        target = self.paths.logs_dir / "learning_report.json"
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(self.report_text() + "\n", encoding="utf-8")
        return target

    def clear(self) -> None:
        """Удалить журнал обучения по требованию человека.

        Удаляется только собственный служебный файл программы в её папке
        ``logs``; к пользовательским файлам эта операция отношения не имеет.
        """
        target = self.file
        if target.parent != self.paths.logs_dir:
            return
        try:
            os.remove(target)
        except OSError:
            return


def _first_word_kept(proposed: str, chosen: str) -> bool:
    """Оставил ли человек первое слово предложенного имени.

    Первое слово — это вид документа. Если человек его сохранил, вид определён
    верно, и разбираться надо с остальными частями имени.
    """
    first = [p for p in SEPARATOR_RE.split(Path(proposed).stem) if p]
    other = [p for p in SEPARATOR_RE.split(Path(chosen).stem) if p]
    if not first or not other:
        return False
    return first[0].casefold() == other[0].casefold()
