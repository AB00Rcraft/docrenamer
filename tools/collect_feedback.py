#!/usr/bin/env python3
"""Собрать отчёты об именах из обращений на GitHub (инструмент разработчика).

Программа для пользователя в сеть не выходит и этот файл в сборку не попадает:
он лежит вне ``src`` и запускается вручную перед работой над алгоритмом имён.

Как устроен круг обратной связи::

    пользователь → кнопка «Улучшение» в программе
                 → обезличенный отчёт в обращении на GitHub (метка naming-report)
                 → этот сценарий собирает обращения в один свод
                 → feedback/SUMMARY.md читает разработчик или кодовая модель
                 → правки в справочнике и правилах имён уходят в следующий выпуск

Запуск::

    python tools/collect_feedback.py                 # свод по открытым обращениям
    python tools/collect_feedback.py --state all     # включая закрытые
    python tools/collect_feedback.py --limit 200

Нужен установленный и авторизованный ``gh``: сетевые запросы делает он, а не
этот сценарий.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "feedback"

#: Метка, которой помечаются обращения с отчётами.
LABEL = "naming-report"

#: Блок ```json … ``` в теле обращения — это и есть отчёт.
JSON_BLOCK_RE = re.compile(r"```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL)


def fetch_issues(repository: str, state: str, limit: int) -> list[dict[str, Any]]:
    """Забрать обращения через ``gh``."""
    command = [
        "gh", "issue", "list",
        "--repo", repository,
        "--label", LABEL,
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,body,createdAt,state",
    ]
    try:
        completed = subprocess.run(  # noqa: S603 — список аргументов, без оболочки
            command, capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        print("Не найден gh. Установите GitHub CLI и выполните gh auth login.", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as exc:
        print(f"gh вернул ошибку: {exc.stderr.strip()}", file=sys.stderr)
        return []
    try:
        data = json.loads(completed.stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def extract_report(body: str) -> dict[str, Any] | None:
    """Достать отчёт из тела обращения."""
    match = JSON_BLOCK_RE.search(body or "")
    if match is None:
        return None
    try:
        value = json.loads(match.group("body"))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def merge(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Свести отчёты в один: где алгоритм имён ошибается чаще всего."""
    by_type: Counter[str] = Counter()
    edited_types: Counter[str] = Counter()
    low_confidence: Counter[str] = Counter()
    review_codes: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    records = edited = kept_first = dropped_date = shorter = 0

    for report in reports:
        records += int(report.get("records") or 0)
        edited += int(report.get("edited") or 0)
        kept_first += int(report.get("kept_first_word") or 0)
        dropped_date += int(report.get("dropped_date") or 0)
        shorter += int(report.get("made_shorter") or 0)
        versions[str(report.get("app_version") or "—")] += 1
        for name, counter in (
            ("by_document_type", by_type),
            ("edited_document_types", edited_types),
            ("low_confidence_by_extension", low_confidence),
            ("name_review_codes", review_codes),
        ):
            values = report.get(name)
            if isinstance(values, dict):
                for key, count in values.items():
                    counter[str(key)] += int(count or 0)

    #: Виды документов, которые чаще всего приходится править руками, —
    #: это и есть очередь работ по алгоритму имён.
    priorities = [
        {
            "document_type": name,
            "edited": count,
            "seen": by_type.get(name, 0),
            "edit_share": round(count / by_type[name], 3) if by_type.get(name) else 1.0,
        }
        for name, count in edited_types.most_common()
    ]
    priorities.sort(key=lambda row: (-row["edited"], -row["edit_share"]))

    return {
        "reports": len(reports),
        "records": records,
        "edited": edited,
        "edit_share": round(edited / records, 3) if records else 0.0,
        "kept_first_word": kept_first,
        "dropped_date": dropped_date,
        "made_shorter": shorter,
        "versions": dict(versions.most_common()),
        "by_document_type": dict(by_type.most_common(30)),
        "edited_document_types": dict(edited_types.most_common(30)),
        "low_confidence_by_extension": dict(low_confidence.most_common(20)),
        "name_review_codes": dict(review_codes.most_common(20)),
        "priorities": priorities[:15],
    }


def summary_text(merged: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """Свод по-русски: что чинить в первую очередь."""
    lines = [
        "# Обратная связь об именах",
        "",
        f"Обращений разобрано: {merged['reports']}. "
        f"Записей в отчётах: {merged['records']}. "
        f"Из них поправлено руками: {merged['edited']} "
        f"({merged['edit_share'] * 100:.0f}%).",
        "",
        "## Что чинить в первую очередь",
        "",
    ]
    if merged["priorities"]:
        lines.append("| Вид документа | Правок | Встречался | Доля правок |")
        lines.append("|---|---:|---:|---:|")
        for row in merged["priorities"]:
            lines.append(
                f"| {row['document_type']} | {row['edited']} | "
                f"{row['seen']} | {row['edit_share'] * 100:.0f}% |"
            )
    else:
        lines.append("Правок руками пока не поступало.")
    lines += [
        "",
        "## Как правят имена",
        "",
        f"- вид документа оставляют как есть: {merged['kept_first_word']}",
        f"- дату убирают: {merged['dropped_date']}",
        f"- имя укорачивают: {merged['made_shorter']}",
        "",
        "## Где не хватает уверенности",
        "",
    ]
    for extension, count in merged["low_confidence_by_extension"].items():
        lines.append(f"- `{extension}`: {count}")
    if merged["name_review_codes"]:
        lines += ["", "## Замечания самопроверки имени", ""]
        for code, count in merged["name_review_codes"].items():
            lines.append(f"- `{code}`: {count}")
    lines += ["", "## Источники", ""]
    for source in sources:
        lines.append(
            f"- #{source['number']} ({source.get('state', '')}, "
            f"{str(source.get('createdAt', ''))[:10]}): {source.get('title', '')}"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Свод отчётов об именах с GitHub")
    parser.add_argument("--repository", default="AB00Rcraft/docrenamer")
    parser.add_argument("--state", default="open", choices=("open", "closed", "all"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--input",
        metavar="FILE",
        default="",
        help="разобрать сохранённый отчёт вместо обращений (для проверки)",
    )
    args = parser.parse_args(argv)

    sources: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    if args.input:
        raw = Path(args.input).read_text(encoding="utf-8")
        report = extract_report(raw)
        if report is None:
            try:
                report = json.loads(raw)
            except ValueError:
                print("Файл не похож на отчёт.", file=sys.stderr)
                return 1
        reports.append(report)
        sources.append({"number": 0, "title": args.input, "state": "local"})
    else:
        for issue in fetch_issues(args.repository, args.state, args.limit):
            report = extract_report(str(issue.get("body") or ""))
            if report is None:
                continue
            reports.append(report)
            sources.append(issue)

    if not reports:
        print("Отчётов не найдено.")
        return 0

    merged = merge(reports)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "aggregated.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = summary_text(merged, sources)
    (OUTPUT_DIR / "SUMMARY.md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
