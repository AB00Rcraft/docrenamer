"""Статический аудит исходников (разделы 61, 77, 91 ТЗ).

Эти проверки заменяют ручной поиск по коду, который ТЗ требует выполнить перед
сдачей работы: сетевые библиотеки, удаление файлов, ``os.replace`` и открытие
пользовательских файлов на запись.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from docrenamer.security.offline_guard import audit_source

pytestmark = pytest.mark.safety

#: Аудит относится к программе обработки документов. Обновление вынесено в
#: отдельный пакет и отдельный исполняемый файл именно для того, чтобы этот
#: инвариант оставался безусловным (см. docrenamer_updater).
SRC = Path(__file__).resolve().parents[2] / "src" / "docrenamer"

#: Модули, которым разрешено атомарно заменять СОБСТВЕННЫЕ служебные файлы.
OS_REPLACE_ALLOWED = {"config.py"}

#: Модули, которым разрешено удалять файлы. Все они работают либо во временном
#: каталоге, либо снимают старую ссылку на уже сохранённое содержимое.
#: «learning.py» удаляет только собственный служебный журнал программы
#: в её папке logs — пользовательских файлов он не касается.
DELETE_ALLOWED = {"temp_cleanup.py", "config.py", "rename.py", "learning.py"}

DELETE_FUNCS = {"unlink", "remove", "rmtree", "rmdir", "removedirs"}
WRITE_MODES = {"w", "wb", "w+", "wb+", "a", "ab", "r+", "rb+", "x", "xb"}


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def test_no_network_imports_in_production_code() -> None:
    findings = audit_source(SRC)
    assert findings == [], "\n".join(f.format() for f in findings)


def test_os_replace_only_for_service_files() -> None:
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if _call_name(call) == "replace" and isinstance(call.func, ast.Attribute):
                owner = call.func.value
                is_os = isinstance(owner, ast.Name) and owner.id == "os"
                if is_os and path.name not in OS_REPLACE_ALLOWED:
                    offenders.append(f"{path}:{call.lineno}")
    assert offenders == [], f"os.replace вне служебных модулей: {offenders}"


def test_file_deletion_confined_to_allowed_modules() -> None:
    offenders = []
    for path in python_files():
        if path.name in DELETE_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if _call_name(call) in DELETE_FUNCS:
                offenders.append(f"{path}:{call.lineno}: {_call_name(call)}")
    assert offenders == [], f"Удаление файлов вне разрешённых модулей: {offenders}"


def test_readers_never_open_files_for_writing() -> None:
    """Ни один reader не имеет права открыть пользовательский файл на запись."""
    offenders = []
    for path in sorted((SRC / "docrenamer" / "readers").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if _call_name(call) != "open":
                continue
            mode_args = list(call.args[1:2])
            mode_args += [kw.value for kw in call.keywords if kw.arg == "mode"]
            modes = [
                arg.value
                for arg in mode_args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            if any(mode in WRITE_MODES for mode in modes):
                offenders.append(f"{path}:{call.lineno}")
    assert offenders == [], f"Reader открывает файл на запись: {offenders}"


def test_no_subprocess_with_shell() -> None:
    """subprocess вызывается только списком аргументов (раздел 55 ТЗ)."""
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if _call_name(call) not in {"run", "Popen", "call", "check_output", "check_call"}:
                continue
            for keyword in call.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                ):
                    offenders.append(f"{path}:{call.lineno}")
    assert offenders == [], f"subprocess с shell=True: {offenders}"


def test_no_silent_errors_ignore_in_decoding() -> None:
    """Запрет молчаливого ``errors='ignore'`` при декодировании (раздел 14A.2 ТЗ)."""
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            for keyword in call.keywords:
                if keyword.arg != "errors":
                    continue
                if not isinstance(keyword.value, ast.Constant):
                    continue
                if keyword.value.value == "ignore":
                    offenders.append(f"{path}:{call.lineno}")
    assert offenders == [], f"errors='ignore' в production-коде: {offenders}"
