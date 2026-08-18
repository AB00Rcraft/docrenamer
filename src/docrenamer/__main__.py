"""Точка входа собранного приложения.

Без аргументов открывается графический интерфейс, с аргументами работает CLI —
оба вызывают одну и ту же бизнес-логику (раздел 7 ТЗ).
"""

from __future__ import annotations

import sys


def main() -> int:
    from docrenamer.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
