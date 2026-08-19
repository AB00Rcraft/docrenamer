"""Русский release gate (раздел 95 ТЗ).

Десять проверок, без которых выпуск запрещён. Это часть Definition of Done, а
не факультативное улучшение: нумерация тестов соответствует пунктам ТЗ.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from docrenamer.analysis import ReaderContext
from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.encoding import decode_bytes
from docrenamer.operations.hashing import sha256_file
from docrenamer.paths import AppPaths
from docrenamer.readers.pdf_reader import read_pdf
from docrenamer.security.limits import Limits
from docrenamer.types import Status
from tests.fixtures import builders

pytestmark = pytest.mark.safety

SRC = Path(__file__).resolve().parents[2] / "src"

RUSSIAN_NAMES = [
    "Договор займа №17 от 18 августа 2026 года.docx",
    "Постановление Иванова И.И..pdf",
    "Фотографии — август 2026.txt",
    "ООО «Альфа» — переписка.eml",
    "ёжик.txt",
    "№ 652102_26_77028_ИП.pdf",
]


@pytest.fixture
def russian_corpus(workdir: Path) -> dict[str, str]:
    """Файлы с русскими именами и известными контрольными суммами."""
    hashes: dict[str, str] = {}
    for index, name in enumerate(RUSSIAN_NAMES):
        path = workdir / name
        payload = (
            f"ДОГОВОР ЗАЙМА № {17 + index}\n"
            "город Москва, 18 августа 2026 года\n"
            "Займодавец ООО «Альфа», Заёмщик Иванов Иван Иванович\n"
        )
        path.write_bytes(payload.encode())
        hashes[name] = sha256_file(path)
    return hashes


# --- 1 и 2 -----------------------------------------------------------------


def test_gate_1_russian_filenames_full_cycle(
    config: Config, app_paths: AppPaths, workdir: Path, russian_corpus: dict[str, str]
) -> None:
    """Русские имена сканируются, переименовываются и восстанавливаются."""
    app = Application(config, paths=app_paths)

    plan = app.preview(workdir)
    assert {item.source_path.name for item in plan.items} == set(russian_corpus)

    report = app.apply(plan)
    assert not report.critical
    assert report.manifest_path is not None

    undo_report = app.undo(report.manifest_path)
    assert undo_report.failed == 0
    assert {p.name for p in workdir.iterdir()} == set(russian_corpus)


def test_gate_2_sha256_matches_for_cyrillic_names(
    config: Config, app_paths: AppPaths, workdir: Path, russian_corpus: dict[str, str]
) -> None:
    """SHA-256 до и после совпадает для файлов с кириллицей в имени."""
    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    assert report.manifest_path is not None

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    for record in manifest["records"]:
        assert record["sha256_before"] == record["sha256_after"]
        assert record["sha256_before"] == russian_corpus[record["original_filename"]]


# --- 3 ---------------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["windows-1251", "koi8-r", "cp866"])
def test_gate_3_legacy_encodings_do_not_become_mojibake(encoding: str) -> None:
    text = (
        "Договор займа номер 17 от 18 августа 2026 года. "
        "Иванов Иван Иванович, город Москва, сумма сто тысяч рублей"
    )
    result = decode_bytes(text.encode(encoding))

    assert result.text.strip() == text
    assert Status.MOJIBAKE_SUSPECTED.value not in result.statuses
    assert result.quality > 0.7


# --- 4 ---------------------------------------------------------------------


def test_gate_4_bad_pdf_text_layer_not_trusted(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Непустой, но нечитаемый текстовый слой не принимается за достоверный."""
    context = ReaderContext(config=config, paths=app_paths, limits=Limits.from_config(config))
    path = builders.make_pdf_bad_text_layer(tmp_path / "плохой-слой.pdf")

    result = read_pdf(path, context)

    assert Status.PDF_TEXT_LAYER_LOW_QUALITY.value in result.statuses
    assert result.text_quality < 0.6


def test_gate_4_ocr_preferred_over_bad_layer(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """При плохом слое используется результат OCR, если он лучше."""

    class FakeOCR:
        def ocr_pdf(self, path: Path, page_count: int) -> tuple[str, str]:
            return builders.POSTANOVLENIE_TEXT, ""

    context = ReaderContext(config=config, paths=app_paths, limits=Limits.from_config(config))
    context.extras["ocr"] = FakeOCR()
    path = builders.make_pdf_bad_text_layer(tmp_path / "плохой-слой.pdf")

    result = read_pdf(path, context)

    assert Status.PDF_OCR_FALLBACK_USED.value in result.statuses
    assert "ПОСТАНОВЛЕНИЕ" in result.text


# --- 5 ---------------------------------------------------------------------


def test_gate_5_ocr_is_local_and_russian_first(config: Config, app_paths: AppPaths) -> None:
    """OCR настроен на rus+eng и работает только локально."""
    from docrenamer.ocr.engine import TesseractEngine

    assert config.ocr.language_spec == "rus+eng"
    engine = TesseractEngine(config, app_paths)
    if engine.executable is not None:
        assert Path(engine.executable).exists()
    else:
        assert engine.status_if_unavailable() == Status.OCR_ENGINE_NOT_FOUND.value


@pytest.mark.requires_tesseract
def test_gate_5_ocr_reads_russian(config: Config, app_paths: AppPaths, tmp_path: Path) -> None:
    """Реальное распознавание русского текста (если Tesseract установлен)."""
    from docrenamer.ocr.engine import TesseractEngine

    engine = TesseractEngine(config, app_paths)
    if not engine.available:
        pytest.skip("Tesseract недоступен в этой среде")

    path = builders.make_png_document(tmp_path / "скан.png", "ДОГОВОР ЗАЙМА")
    text, status = engine.ocr_image(path)

    assert status == ""
    assert "ДОГОВОР" in text.upper()


# --- 6 ---------------------------------------------------------------------


def test_gate_6_llm_round_trip_preserves_cyrillic(config: Config, tmp_path: Path) -> None:
    """Модель получает и возвращает кириллицу без транслитерации и порчи."""
    import unicodedata

    from docrenamer.ai.context_builder import build_context
    from docrenamer.ai.enricher import AIEnricher
    from docrenamer.types import Candidate, Category, FileAnalysis

    captured: dict[str, str] = {}

    class EchoModel:
        available = True

        def status(self) -> str:
            return ""

        def missing_model_message(self) -> str:
            return ""

        def info(self):
            from docrenamer.ai.base import ModelInfo

            return ModelInfo(engine="fake", available=True)

        def generate(self, prompt: str) -> tuple[str, str]:
            captured["prompt"] = prompt
            return (
                '{"document_type": {"value": "Постановление судебного пристава",'
                ' "confidence": 0.95, "evidence": "ПОСТАНОВЛЕНИЕ"},'
                ' "subject": {"value": "исполнительное производство",'
                ' "confidence": 0.9, "evidence": "исполнительного производства"}}'
            ), ""

    analysis = FileAnalysis(source_path=tmp_path / "ёжик.pdf", detected_type="pdf")
    analysis.category = Category.DOCUMENT
    analysis.candidates["dates"] = [
        Candidate(value="2026-07-27", position=10, context="от 27 июля")
    ]
    text = builders.POSTANOVLENIE_TEXT

    enricher = AIEnricher(EchoModel(), config, Limits.from_config(config))
    enricher.enrich(analysis, text)

    # Кириллица уходит в модель как есть, без транслитерации.
    assert "ПОСТАНОВЛЕНИЕ" in captured["prompt"]
    assert "Иванов Иван Иванович" in captured["prompt"]
    assert "Ivanov" not in captured["prompt"]
    # И возвращается неповреждённой, в форме NFC.
    assert analysis.document_type is not None
    value = str(analysis.document_type.value)
    assert value == "Постановление судебного пристава"
    assert value == unicodedata.normalize("NFC", value)
    assert "�" not in value
    # Контекст для модели тоже русскоязычный.
    block = build_context(analysis, text, Limits.from_config(config))
    assert "Должник" in block


# --- 7 и 8 -----------------------------------------------------------------


def test_gate_7_manifest_stores_readable_cyrillic(
    config: Config, app_paths: AppPaths, workdir: Path, russian_corpus: dict[str, str]
) -> None:
    """JSON manifest хранит кириллицу текстом, а не \\uXXXX-последовательностями."""
    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    assert report.manifest_path is not None

    raw = report.manifest_path.read_text(encoding="utf-8")
    assert "\\u0414" not in raw
    assert "Договор" in raw or "ёжик" in raw
    assert json.loads(raw)["records"]


def test_gate_8_logs_are_readable_russian_text(
    config: Config, app_paths: AppPaths, workdir: Path, russian_corpus: dict[str, str]
) -> None:
    """TXT-журнал открывается как читаемый русский текст."""
    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    assert report.log_path is not None

    raw = report.log_path.read_text(encoding="utf-8")
    assert raw.startswith("Encoding: UTF-8")
    assert "Language profile: ru-RU" in raw
    assert "ёжик" in raw
    assert "�" not in raw


# --- 9 ---------------------------------------------------------------------


def test_gate_9_interface_shows_russian_typography(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Строки предпросмотра сохраняют «ё», «№», кавычки и длинное тире."""
    from docrenamer.presentation import format_plan_row

    name = "№ 652102 — ёжик «Альфа».pdf"
    payload = (
        "ДОГОВОР ЗАЙМА № 17\n"
        "город Москва, 18 августа 2026 года\n"
        "Займодавец ООО «Альфа», Заёмщик Иванов Иван Иванович\n"
    )
    (workdir / name).write_bytes(payload.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    item = next(i for i in plan.items if i.source_path.name == name)
    row = format_plan_row(item)

    # Имя файла показывается во второй колонке: первая — отметка выбора.
    for char in "№—ё«»":
        assert char in row[1], f"символ {char} потерян в интерфейсе"
    assert row[0] in ("☑", "☐")
    assert str(workdir) in str(item.source_path)


def test_gate_9_status_descriptions_are_russian() -> None:
    """Каждый машинный код имеет человекочитаемое русское описание."""
    from docrenamer.types import STATUS_DESCRIPTIONS_RU, Status

    missing = [code.value for code in Status if code.value not in STATUS_DESCRIPTIONS_RU]
    assert missing == [], f"Нет русского описания для: {missing}"


# --- 10 --------------------------------------------------------------------


def test_gate_10_no_silent_errors_ignore_anywhere() -> None:
    """Ни один путь декодирования не использует молчаливое errors='ignore'."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "errors":
                    continue
                if isinstance(keyword.value, ast.Constant) and keyword.value.value == "ignore":
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"errors='ignore' обнаружен: {offenders}"


def test_gate_10_data_loss_is_visible() -> None:
    """Потеря символов видна как предупреждение, а не скрывается."""
    broken = "Договор".encode("cp1251") + b"\x00\x01\x02" + "займа".encode("cp1251")
    result = decode_bytes(broken)

    assert result.statuses or result.warnings, "потеря данных прошла незаметно"
