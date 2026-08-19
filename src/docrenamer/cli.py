"""Интерфейс командной строки (разделы 7, 8 ТЗ).

CLI не содержит бизнес-логики: он разбирает аргументы и вызывает те же методы
:class:`docrenamer.app.Application`, что и графический интерфейс.
По умолчанию выполняется предпросмотр — файлы не изменяются.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docrenamer import __version__
from docrenamer.app import Application, Cancelled
from docrenamer.config import ConfigError, load_config
from docrenamer.console import configure_console
from docrenamer.paths import default_paths
from docrenamer.types import Status, describe

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CRITICAL = 2
EXIT_CANCELLED = 130


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки раздела 7 ТЗ."""
    parser = argparse.ArgumentParser(
        prog="DocRenamer",
        description=(
            "Локальное безопасное переименование файлов по содержимому. "
            "Работает полностью офлайн. По умолчанию — предпросмотр без изменений."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            '  DocRenamer "D:\\\\Documents"              предпросмотр\n'
            '  DocRenamer "D:\\\\Documents" --apply      переименовать\n'
            "  DocRenamer --here --recursive          текущий каталог с подпапками\n"
            "  DocRenamer --undo manifest.json        откатить сессию\n"
        ),
    )
    parser.add_argument("directory", nargs="?", help="каталог с файлами")
    parser.add_argument("--here", action="store_true", help="работать в текущем каталоге")
    parser.add_argument(
        "--recursive", action="store_true", help="включая подкаталоги"
    )
    parser.add_argument(
        "--no-recursive", action="store_true", help="только выбранный каталог"
    )
    parser.add_argument("--dry-run", action="store_true", help="предпросмотр (по умолчанию)")
    parser.add_argument("--apply", action="store_true", help="выполнить переименование")
    parser.add_argument("--forensic", action="store_true", help="только отчёты, без изменений")
    parser.add_argument("--undo", metavar="MANIFEST", help="откатить сессию по manifest")
    parser.add_argument(
        "--scrub",
        action="store_true",
        help="снять метаданные с файлов каталога (копии в подпапку «Без метаданных»)",
    )
    parser.add_argument(
        "--scrub-replace",
        action="store_true",
        help="при очистке заменять исходные файлы; вернуть метаданные будет нельзя",
    )
    parser.add_argument("--config", metavar="PATH", help="путь к config.json")
    parser.add_argument("--no-ai", action="store_true", help="без локальной модели")
    parser.add_argument("--no-ocr", action="store_true", help="без распознавания текста")
    parser.add_argument("--verbose", action="store_true", help="подробный вывод")
    parser.add_argument("--gui", action="store_true", help="запустить графический интерфейс")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="проверить готовность программы: OCR, локальная модель, разбор документа",
    )
    parser.add_argument(
        "--wizard",
        action="store_true",
        help="пошаговый диалог в текстовом окне (для переносимой сборки)",
    )
    parser.add_argument(
        "--save-plan", metavar="PATH", help="сохранить план в файл rename_plan.json"
    )
    parser.add_argument("--version", action="version", version=f"DocRenamer {__version__}")
    return parser


def _resolve_directory(args: argparse.Namespace) -> Path | None:
    if args.here:
        return Path.cwd()
    if args.directory:
        return Path(args.directory)
    return None


def _print_plan(plan, verbose: bool) -> None:
    """Показать план в формате раздела 79 ТЗ."""
    for item in plan.items:
        if item.status == Status.NAME_UNCHANGED.value and not verbose:
            continue
        mark = "✓" if item.selected else "!"
        print(f"[{mark}] {item.source_path.name}")
        if item.is_rename:
            print(f"    → {item.proposed_filename}")
        print(f"    уверенность {item.confidence * 100:.0f}%  {item.status}")
        if item.message:
            print(f"    {item.message}")
        if not item.selected and item.is_rename:
            print("    НЕ БУДЕТ ПЕРЕИМЕНОВАН АВТОМАТИЧЕСКИ")
        if verbose and item.analysis is not None:
            for code in item.analysis.statuses:
                print(f"      · {code}: {describe(code)}")
    print()
    for key, value in plan.counters().items():
        print(f"{key}: {value}")


def _ask(prompt: str, default: str = "") -> str:
    """Спросить пользователя. Пустой ответ означает значение по умолчанию."""
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    return answer or default


def _is_yes(answer: str) -> bool:
    """Согласие на русском или латиницей."""
    return answer.strip().lower() in ("д", "да", "y", "yes", "1")


def run_wizard(app: Application, directory: Path | None) -> int:
    """Пошаговый диалог для тех, кто не работает с командной строкой.

    Порядок тот же, что и в графическом интерфейсе: показать план, дождаться
    явного согласия, только потом переименовывать (раздел 8 ТЗ).
    """
    print()
    print("=" * 62)
    print("  DocRenamer Offline — переименование файлов по содержимому")
    print("  Работает полностью локально, ничего не отправляет наружу.")
    print("=" * 62)

    while directory is None or not directory.is_dir():
        if directory is not None:
            print(f"Папка не найдена: {directory}")
        answer = _ask("\nУкажите папку с документами (или перетащите её сюда): ")
        if not answer:
            print("Отменено.")
            return EXIT_OK
        directory = Path(answer.strip().strip('"'))

    print(f"\nСмотрим папку: {directory}")
    print("Это займёт некоторое время. Файлы пока не меняются.\n")
    plan = app.preview(directory)
    _print_plan(plan, verbose=False)

    if not plan.selected_items:
        print("\nПереименовывать нечего: подходящих предложений нет.")
        return EXIT_OK

    print()
    if not _is_yes(_ask(f"Переименовать файлов: {len(plan.selected_items)}? [д/н]: ")):
        print("Ничего не изменено.")
        return EXIT_OK

    report = app.apply(plan)
    print()
    for key, value in report.counters().items():
        print(f"{key}: {value}")
    if report.log_path:
        print(f"\nЖурнал операции: {report.log_path}")
    if report.manifest_path:
        print(f"Данные для отмены: {report.manifest_path}")
    print("Отменить: запустите ОТМЕНИТЬ-ПЕРЕИМЕНОВАНИЕ (или ключ --undo).")
    if report.critical:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {report.critical}", file=sys.stderr)
        return EXIT_CRITICAL
    return EXIT_OK


def run_undo_wizard(app: Application, paths) -> int:
    """Диалог отката последней операции."""
    manifests = sorted(
        paths.manifests_dir.glob("rename_manifest_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        print("Отменять нечего: записей о переименовании нет.")
        return EXIT_OK

    latest = manifests[0]
    print(f"Последняя операция: {latest.name}")
    if not _is_yes(_ask("Вернуть прежние имена файлов? [д/н]: ")):
        print("Отменено.")
        return EXIT_OK

    report = app.undo(latest)
    print(f"\nВосстановлено: {report.restored}")
    print(f"Пропущено: {report.skipped}")
    print(f"Ошибок: {report.failed}")
    if report.log_path:
        print(f"Журнал: {report.log_path}")
    return EXIT_CRITICAL if report.critical else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = default_paths()
    try:
        config = load_config(Path(args.config) if args.config else None, paths=paths)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.no_ai:
        config.ai.enabled = False
    if args.no_ocr:
        config.ocr.enabled = False
    if args.recursive:
        config.recursive = True
    if args.no_recursive:
        config.recursive = False

    if args.selftest:
        from docrenamer.selftest import run_selftest

        selftest_report = run_selftest(config, paths)
        print(selftest_report.format_text())
        return EXIT_OK if selftest_report.ready else EXIT_ERROR

    directory = _resolve_directory(args)

    if args.wizard:
        # Без построчного эха: диалог сам печатает ровно то, что нужно человеку.
        app = Application(config, paths=paths)
        app.startup_maintenance()
        try:
            return run_wizard(app, directory)
        except KeyboardInterrupt:
            print("\nПрервано.", file=sys.stderr)
            return EXIT_CANCELLED
        finally:
            app.cleanup()

    if args.undo == "__last__":
        app = Application(config, paths=paths)
        try:
            return run_undo_wizard(app, paths)
        finally:
            app.cleanup()

    if args.gui or (directory is None and not args.undo):
        from docrenamer.gui import run_gui

        return run_gui(config=config, paths=paths, initial_directory=directory)

    app = Application(config, paths=paths, on_line=lambda line: print(line))
    app.startup_maintenance()

    try:
        if args.undo:
            undo_report = app.undo(Path(args.undo))
            print(f"Восстановлено: {undo_report.restored}")
            print(f"Пропущено: {undo_report.skipped}")
            print(f"Ошибок: {undo_report.failed}")
            if undo_report.log_path:
                print(f"Журнал: {undo_report.log_path}")
            return EXIT_CRITICAL if undo_report.critical else EXIT_OK

        if directory is None or not directory.is_dir():
            print(f"Каталог не найден: {directory}", file=sys.stderr)
            return EXIT_ERROR

        if args.scrub or args.scrub_replace:
            files = [scanned.path for scanned in app.scan(directory)]
            scrub_report = app.scrub(files, replace=args.scrub_replace)
            for name, value in scrub_report.counters().items():
                print(f"{name}: {value}")
            if scrub_report.report_path:
                print(f"Отчёт: {scrub_report.report_path}")
            return EXIT_ERROR if scrub_report.failed else EXIT_OK

        if args.forensic or config.forensic_mode:
            outputs = app.forensic(directory)
            for name, path in outputs.items():
                print(f"{name}: {path}")
            return EXIT_OK

        plan = app.preview(
            directory, save_plan_to=Path(args.save_plan) if args.save_plan else None
        )
        _print_plan(plan, args.verbose)

        if not args.apply:
            print("\nРежим предпросмотра: файлы не изменены. Для применения — --apply")
            return EXIT_OK

        report = app.apply(plan)
        print()
        for key, value in report.counters().items():
            print(f"{key}: {value}")
        if report.manifest_path:
            print(f"Manifest: {report.manifest_path}")
        if report.log_path:
            print(f"Журнал: {report.log_path}")
        if report.critical:
            print(f"КРИТИЧЕСКАЯ ОШИБКА: {report.critical}", file=sys.stderr)
            return EXIT_CRITICAL
        return EXIT_OK
    except Cancelled:
        print("Остановлено пользователем.", file=sys.stderr)
        return EXIT_CANCELLED
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return EXIT_CANCELLED
    finally:
        app.cleanup()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
