"""Настройка консольного вывода (раздел 14A.7 ТЗ).

Русские сообщения — основной язык программы, но консоль Windows по умолчанию
работает в однобайтовой кодировке (cp866 или cp1252), и попытка напечатать
кириллицу завершается ``UnicodeEncodeError``. Программа не имеет права падать
из-за собственного сообщения, поэтому потоки вывода переводятся в UTF-8.
"""

from __future__ import annotations

import sys


def configure_console() -> None:
    """Перевести стандартные потоки в UTF-8 с видимой заменой непечатаемого.

    Вызывается в начале каждой точки входа. ``errors="replace"`` выбран
    сознательно: молчаливое отбрасывание символов запрещено (раздел 14A.2 ТЗ),
    а замена видна пользователю и не прерывает работу.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # поток уже закрыт или не поддерживает
            continue
