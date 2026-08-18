"""Программа обновления DocRenamer.

Запускается пользователем — из главного окна или вручную. Ничего не делает
без явной команды и никогда не открывает пользовательские документы.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from docrenamer_updater import __version__
from docrenamer_updater.client import DEFAULT_REPOSITORY, UpdateError, check, download

EXIT_OK = 0
EXIT_ERROR = 1
#: Обновлений нет — это не ошибка, но отличать её полезно.
EXIT_UP_TO_DATE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="DocRenamerUpdate",
        description=(
            "Проверка и установка обновлений DocRenamer. "
            "Сама программа обработки документов в сеть не выходит."
        ),
    )
    parser.add_argument("--current", default="", help="текущая версия программы")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY, help="источник релизов")
    parser.add_argument("--check", action="store_true", help="только проверить наличие версии")
    parser.add_argument("--json", action="store_true", help="вывод в формате JSON")
    parser.add_argument("--install", action="store_true", help="скачать и установить обновление")
    parser.add_argument(
        "--restart",
        metavar="PATH",
        default="",
        help="запустить указанную программу после установки",
    )
    parser.add_argument("--version", action="version", version=f"DocRenamerUpdate {__version__}")
    return parser


def _current_version(argument: str) -> str:
    if argument:
        return argument
    try:
        from docrenamer import __version__ as app_version
    except ImportError:
        return "0.0.0"
    return app_version


def main(argv: list[str] | None = None) -> int:
    from docrenamer.console import configure_console

    configure_console()
    args = build_parser().parse_args(argv)
    current = _current_version(args.current)

    try:
        release = check(current, args.repository)
    except UpdateError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Не удалось проверить обновления: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if release is None:
        if args.json:
            print(json.dumps({"update": False, "current": current}, ensure_ascii=False))
        else:
            print(f"Установлена последняя версия ({current}).")
        return EXIT_UP_TO_DATE

    if args.json:
        print(json.dumps({"update": True, "current": current, **release.to_dict()},
                         ensure_ascii=False))
    else:
        print(f"Доступна версия {release.version} (установлена {current}).")

    if args.check or not args.install:
        return EXIT_OK

    try:
        target_dir = Path(tempfile.gettempdir()) / "docrenamer-update"
        installer = download(release, target_dir)
    except UpdateError as exc:
        print(f"Обновление не установлено: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Загружено: {installer}")
    return _install(installer, args.restart)


def _install(installer: Path, restart: str) -> int:
    """Запустить установщик и, если попросили, перезапустить программу."""
    if installer.suffix.lower() != ".exe":
        print(
            "Скачан переносимый архив. Распакуйте его поверх текущей папки:\n"
            f"  {installer}"
        )
        return EXIT_OK

    arguments = [str(installer), "/SILENT", "/NOCANCEL", "/SUPPRESSMSGBOXES"]
    if restart:
        arguments.append(f'/RUN="{restart}"')
    try:
        completed = subprocess.run(  # noqa: S603 — список аргументов, без оболочки
            arguments, shell=False, check=False, timeout=1800
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Не удалось запустить установщик: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if completed.returncode != 0:
        print(f"Установщик завершился с кодом {completed.returncode}.", file=sys.stderr)
        return EXIT_ERROR

    print("Обновление установлено.")
    if restart and Path(restart).exists():
        try:
            subprocess.Popen(  # noqa: S603 — перезапуск собственной программы
                [restart], shell=False, close_fds=True
            )
        except OSError as exc:
            print(f"Программа не перезапущена: {exc}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
