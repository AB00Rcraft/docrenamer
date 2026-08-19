"""Программа обновления DocRenamer.

Запускается пользователем — из главного окна или вручную. Ничего не делает
без явной команды и никогда не открывает пользовательские документы.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
    parser.add_argument(
        "--feedback",
        metavar="FILE",
        default="",
        help="открыть страницу отправки обезличенного отчёта об именах",
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

    if args.feedback:
        return send_feedback(Path(args.feedback), args.repository, current)

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

    # Установщик перезапишет и этот файл — работаем из временной копии.
    if relaunch_from_temp(sys.argv[1:]):
        return EXIT_OK

    try:
        target_dir = Path(tempfile.gettempdir()) / "docrenamer-update"
        installer = download(release, target_dir)
    except UpdateError as exc:
        print(f"Обновление не установлено: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Загружено: {installer}")
    return _install(installer, args.restart)


def feedback_url(report: str, repository: str, version: str) -> str:
    """Ссылка на страницу создания обращения с уже заполненным отчётом.

    Отчёт не отправляется сам: открывается обычная страница в браузере, где
    человек видит текст целиком и решает, отправлять его или нет. Никаких
    ключей доступа и скрытых запросов для этого не нужно.
    """
    from urllib.parse import quote

    body = (
        "Обезличенный отчёт об именах файлов. "
        "Ни имён файлов, ни фамилий, ни содержимого документов в нём нет.\n\n"
        f"```json\n{report.strip()}\n```\n"
    )
    title = quote(f"Отчёт об именах {version}")
    return (
        f"https://github.com/{repository}/issues/new"
        f"?title={title}&body={quote(body[:6000])}"
    )


def send_feedback(report_file: Path, repository: str, version: str) -> int:
    """Открыть страницу отправки отчёта в браузере."""
    import webbrowser

    try:
        report = report_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Отчёт не прочитан: {exc}", file=sys.stderr)
        return EXIT_ERROR
    url = feedback_url(report, repository, version)
    print(url)
    try:
        webbrowser.open(url)
    except Exception as exc:  # браузер может отсутствовать
        print(f"Не удалось открыть браузер: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _is_windows() -> bool:
    """Windows ли это. Отдельной функцией — чтобы проверять поведение в тестах."""
    return os.name == "nt"


def relaunch_from_temp(argv: list[str]) -> bool:
    """Перезапустить саму программу обновления из временного каталога.

    Установщик перезаписывает и сам файл ``DocRenamerUpdate.exe``. Если он
    запущен из каталога программы, файл занят, и установка спотыкается.
    Поэтому перед установкой программа обновления копирует себя во временный
    каталог и продолжает работу оттуда.

    Returns:
        True, если работа передана временной копии и текущий процесс должен
        завершиться.
    """
    if not getattr(sys, "frozen", False) or not _is_windows():
        return False
    current = Path(sys.executable).resolve()
    temp_dir = Path(tempfile.gettempdir()) / "docrenamer-update"
    temp_copy = temp_dir / current.name
    try:
        if current.parent.resolve() == temp_dir.resolve():
            return False
        temp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, temp_copy)
        subprocess.Popen(  # noqa: S603 — копия самой программы, список аргументов
            [str(temp_copy), *argv], shell=False, close_fds=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Не удалось подготовить обновление: {exc}", file=sys.stderr)
        return False
    return True


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
