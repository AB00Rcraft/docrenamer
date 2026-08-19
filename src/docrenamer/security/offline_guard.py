"""Архитектурный запрет сетевой функциональности (разделы 3, 61 ТЗ).

Офлайн-режим не может быть обещанием в интерфейсе: он проверяется статическим
аудитом исходного кода и утверждениями во время выполнения.

Запуск аудита:

    python -m docrenamer.security.offline_guard --audit src
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

#: Модули, которых не должно быть в production-коде.
FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "urllib3",
        "http.client",
        "httplib",
        "websocket",
        "websockets",
        "ftplib",
        "telnetlib",
        "smtplib",
        "poplib",
        "imaplib",
        "xmlrpc",
        "socketserver",
        "openai",
        "anthropic",
        "google.generativeai",
        "mistralai",
        "cohere",
        "ollama",
        "huggingface_hub",
        "transformers",
        "boto3",
        "azure",
        "sentry_sdk",
    }
)

#: Модули, допустимые только в тестах офлайн-режима (для проверки отсутствия сети).
TEST_ONLY_IMPORTS: frozenset[str] = frozenset({"socket"})

#: Подозрительные строковые литералы: адреса облачных сервисов.
FORBIDDEN_URL_MARKERS: tuple[str, ...] = (
    "http://",
    "https://",
)

#: Модуль, который сам определяет правила аудита: его строковые литералы —
#: это описание запрета, а не сетевое обращение.
SELF_MODULE_NAME = "offline_guard.py"

#: Пространства имён XML выглядят как адреса, но адресами не являются: это
#: опознавательные строки формата, по ним никто никуда не ходит. Без такого
#: разбора нельзя было бы собрать даже пустые свойства документа Office.
XML_NAMESPACE_MARKERS: tuple[str, ...] = ("xmlns", "<?xml")


@dataclass(frozen=True, slots=True)
class Finding:
    """Находка аудита."""

    path: Path
    line: int
    kind: str
    detail: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.detail}"


def _module_root(name: str) -> str:
    return name.split(".")[0]


def _is_forbidden(module: str) -> bool:
    if module in FORBIDDEN_IMPORTS:
        return True
    root = _module_root(module)
    return root in {_module_root(f) for f in FORBIDDEN_IMPORTS if "." not in f}


def audit_source(root: Path, *, allow_socket: bool = False) -> list[Finding]:
    """Проверить дерево исходников на сетевые импорты и URL в коде."""
    findings: list[Finding] = []
    for file_path in sorted(Path(root).rglob("*.py")):
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            findings.append(
                Finding(file_path, exc.lineno or 0, "SYNTAX_ERROR", str(exc.msg))
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if _is_forbidden(name) or (not allow_socket and name in TEST_ONLY_IMPORTS):
                        findings.append(
                            Finding(file_path, node.lineno, "NETWORK_IMPORT", name)
                        )
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ""
                if _is_forbidden(name) or (not allow_socket and name in TEST_ONLY_IMPORTS):
                    findings.append(Finding(file_path, node.lineno, "NETWORK_IMPORT", name))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and file_path.name != SELF_MODULE_NAME
            ):
                value = node.value
                if any(marker in value for marker in XML_NAMESPACE_MARKERS):
                    continue
                if any(marker in value for marker in FORBIDDEN_URL_MARKERS):
                    # Документация в докстрингах допустима: проверяем, что это
                    # не исполняемая строка-адрес.
                    if _is_docstring(tree, node):
                        continue
                    findings.append(
                        Finding(file_path, node.lineno, "URL_LITERAL", value[:80])
                    )
    return findings


def _is_docstring(tree: ast.AST, node: ast.Constant) -> bool:
    """Является ли строковая константа докстрингом модуля/класса/функции."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(parent, "body", [])
            if body and isinstance(body[0], ast.Expr) and body[0].value is node:
                return True
    return False


def assert_no_network_modules() -> list[str]:
    """Проверить, что сетевые библиотеки не загружены в текущий процесс.

    Возвращает список нарушений (пустой список — норма).
    """
    loaded = set(sys.modules)
    violations = sorted(name for name in FORBIDDEN_IMPORTS if name in loaded)
    return violations


def main(argv: list[str] | None = None) -> int:
    """Точка входа аудита для CI и release-проверки (раздел 61 ТЗ)."""
    from docrenamer.console import configure_console

    configure_console()
    parser = argparse.ArgumentParser(
        prog="offline_guard",
        description="Аудит исходников на отсутствие сетевой функциональности.",
    )
    parser.add_argument("--audit", metavar="PATH", default="src", help="каталог исходников")
    parser.add_argument(
        "--allow-socket",
        action="store_true",
        help="разрешить импорт socket (для каталога тестов офлайн-режима)",
    )
    args = parser.parse_args(argv)

    findings = audit_source(Path(args.audit), allow_socket=args.allow_socket)
    if findings:
        print("Аудит офлайн-режима: обнаружены нарушения")
        for finding in findings:
            print("  " + finding.format())
        return 1
    print(f"Аудит офлайн-режима пройден: {args.audit} — сетевых зависимостей нет.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
