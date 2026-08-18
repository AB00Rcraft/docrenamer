# -*- mode: python ; coding: utf-8 -*-
"""Спецификация PyInstaller для portable-сборки (разделы 5, 70 ТЗ).

Два режима:

* **onedir** (по умолчанию, рекомендуется ТЗ) — каталог ``dist/DocRenamer/``.
  Приложение всё равно поставляется с локальной GGUF-моделью, данными OCR и
  внешними runtime-бинарниками, поэтому распаковка во временный каталог при
  каждом запуске только замедляет старт.
* **onefile** — один файл ``DocRenamer.exe``, удобно передать и запустить.
  Плата: при каждом запуске содержимое распаковывается во временный каталог
  системы, старт занимает несколько секунд. Модель и OCR в такой файл не
  вкладываются: они кладутся рядом в ``models\\`` и ``runtime\\``.

Сборка:

    pyinstaller DocRenamer.spec --noconfirm                  onedir
    set DOCRENAMER_ONEFILE=1 && pyinstaller DocRenamer.spec  один файл
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

PROJECT_ROOT = Path(SPECPATH)

# Данные приложения. Runtime-бинарники и модель копируются скриптом сборки
# отдельно: они не должны попадать в анализ зависимостей PyInstaller.
datas = [
    (str(PROJECT_ROOT / "config" / "config.json"), "config"),
    (str(PROJECT_ROOT / "config" / "document_types.json"), "config"),
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
# Библиотеки со встроенными данными: без них reader'ы падают в собранном
# приложении, хотя из исходников работают.
for package in ("pypdfium2_raw", "extract_msg"):
    datas += collect_data_files(package, include_py_files=False)


def package_tree(package: str, subdirectory: str) -> list[tuple[str, str]]:
    """Полностью включить каталог данных пакета.

    ``collect_data_files`` пропускает часть шаблонов python-docx и python-pptx
    (например ``templates/default-header.xml``), из-за чего собранное
    приложение не может открыть DOCX. Поэтому каталоги шаблонов включаются
    целиком и явно.
    """
    import importlib.util

    spec = importlib.util.find_spec(package)
    if spec is None or not spec.origin:
        return []
    root = Path(spec.origin).parent / subdirectory
    entries: list[tuple[str, str]] = []
    for item in root.rglob("*"):
        if item.is_file():
            destination = f"{package}/{subdirectory}/{item.parent.relative_to(root)}".rstrip("/.")
            entries.append((str(item), destination))
    return entries


datas += package_tree("docx", "templates")
datas += package_tree("pptx", "templates")


def ensure_package_dir(package: str, subpackage: str) -> list[tuple[str, str]]:
    """Создать в сборке физический каталог подпакета.

    python-docx открывает свои шаблоны по пути вида
    ``docx/parts/../templates/default-header.xml``. Операционная система
    разворачивает ``..`` только если каталог ``parts`` существует на диске, а в
    сборке подпакеты живут внутри архива. Поэтому кладём в него безобидный
    файл-маркер: без этого DOCX в собранном приложении не открывается.
    """
    import importlib.util

    spec = importlib.util.find_spec(package)
    if spec is None or not spec.origin:
        return []
    marker = Path(spec.origin).parent / "__init__.py"
    if not marker.is_file():
        return []
    return [(str(marker), f"{package}/{subpackage}")]


datas += ensure_package_dir("docx", "parts")
datas += ensure_package_dir("docx", "oxml")

hiddenimports = [
    "docrenamer.readers.pdf_reader",
    "docrenamer.readers.docx_reader",
    "docrenamer.readers.xlsx_reader",
    "docrenamer.readers.xls_reader",
    "docrenamer.readers.pptx_reader",
    "docrenamer.readers.text_reader",
    "docrenamer.readers.html_reader",
    "docrenamer.readers.xml_reader",
    "docrenamer.readers.json_reader",
    "docrenamer.readers.image_reader",
    "docrenamer.readers.media_reader",
    "docrenamer.readers.eml_reader",
    "docrenamer.readers.msg_reader",
    "docrenamer.readers.archive_reader",
    "docrenamer.readers.legacy_ole_reader",
    "pillow_heif",
    "charset_normalizer",
    "defusedxml.ElementTree",
]

# Сетевые и облачные библиотеки исключаются на уровне сборки: STRICT LOCAL MODE
# должен быть свойством дистрибутива, а не обещанием в интерфейсе (раздел 61 ТЗ).
excludes = [
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "websockets",
    "openai",
    "anthropic",
    "huggingface_hub",
    "transformers",
    "torch",
    "boto3",
    "sentry_sdk",
    "matplotlib",
    "numpy.distutils",
    "pytest",
    "IPython",
]

#: Режим сборки выбирается переменной окружения, чтобы спецификация
#: оставалась одной и той же для обоих вариантов.
ONEFILE = os.environ.get("DOCRENAMER_ONEFILE", "").strip().lower() in ("1", "true", "yes")

a = Analysis(
    [str(PROJECT_ROOT / "src" / "docrenamer" / "__main__.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# console=False: приложение оконное. Вывод CLI при этом остаётся доступным,
# если запускать из cmd.exe с перенаправлением, а обычный двойной щелчок не
# открывает лишнее чёрное окно.
common = {
    "name": "DocRenamer",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        runtime_tmpdir=None,
        **common,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="DocRenamer",
    )
