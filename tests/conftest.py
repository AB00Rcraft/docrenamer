"""Общие фикстуры тестов.

Все тесты работают только с синтетическими данными во временных каталогах:
реальные конфиденциальные материалы не используются (раздел 73 ТЗ).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docrenamer.config import Config, load_config
from docrenamer.paths import AppPaths

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    """Изолированная portable-раскладка приложения во временном каталоге."""
    root = tmp_path / "DocRenamer"
    (root / "config").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "manifests").mkdir()
    (root / "runtime_temp").mkdir()
    (root / "models").mkdir()
    for name in ("config.json", "document_types.json"):
        source = REPO_ROOT / "config" / name
        if source.is_file():
            shutil.copy2(source, root / "config" / name)
    return AppPaths(root=root)


@pytest.fixture
def config(app_paths: AppPaths) -> Config:
    """Конфигурация из изолированной раскладки."""
    return load_config(paths=app_paths)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Каталог с пользовательскими файлами."""
    directory = tmp_path / "Дело Петрова"
    directory.mkdir()
    return directory


@pytest.fixture
def russian_files(workdir: Path) -> list[Path]:
    """Набор файлов с русскими именами (раздел 14A.5 ТЗ)."""
    names = [
        "Договор займа №17 от 18 августа 2026 года.docx",
        "Постановление Иванова И.И..pdf",
        "ООО «Альфа» — переписка.eml",
        "ёжик.txt",
        "№ 652102-26-77028-ИП.pdf",
    ]
    created = []
    for index, name in enumerate(names):
        path = workdir / name
        path.write_bytes(f"содержимое-{index}\n".encode())
        created.append(path)
    return created
