"""Тесты локальной модели и защиты от выдумывания (разделы 33–38 ТЗ)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.ai.context_builder import build_context
from docrenamer.ai.enricher import AIEnricher
from docrenamer.ai.llama_cli import LlamaCliModel
from docrenamer.ai.prompt import build_prompt
from docrenamer.ai.validator import evidence_supported, extract_json, validate
from docrenamer.config import Config
from docrenamer.paths import AppPaths
from docrenamer.security.limits import Limits
from docrenamer.types import Candidate, Category, FileAnalysis, Source, Status

INPUT_TEXT = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Судебный пристав-исполнитель Сидорова А.А.\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)


class FakeModel:
    """Локальная модель, возвращающая заранее заданный ответ."""

    def __init__(self, answer: str, status: str = "") -> None:
        self.answer = answer
        self._status = status
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    def status(self) -> str:
        return self._status

    def missing_model_message(self) -> str:
        return "LOCAL_MODEL_NOT_FOUND"

    def info(self):
        from docrenamer.ai.base import ModelInfo

        return ModelInfo(engine="fake", available=True)

    def generate(self, prompt: str) -> tuple[str, str]:
        self.calls += 1
        return self.answer, ""


def make_analysis(path: Path) -> FileAnalysis:
    analysis = FileAnalysis(source_path=path, detected_type="pdf")
    analysis.category = Category.DOCUMENT
    analysis.candidates["dates"] = [
        Candidate(value="2026-07-27", position=60, context="от 27 июля 2026 года")
    ]
    return analysis


# --- разбор ответа ---------------------------------------------------------


def test_extract_json_from_noisy_output() -> None:
    payload = extract_json('Вот ответ:\n```json\n{"document_type": {"value": "Договор"}}\n```')
    assert payload is not None
    assert payload["document_type"]["value"] == "Договор"


def test_invalid_json_reported() -> None:
    answer = validate("модель ничего не поняла", INPUT_TEXT)
    assert Status.INVALID_AI_JSON.value in answer.statuses
    assert answer.values == {}


def test_unknown_fields_dropped() -> None:
    raw = '{"document_type": {"value": "Постановление", "evidence": "ПОСТАНОВЛЕНИЕ"}, "secret": 1}'
    answer = validate(raw, INPUT_TEXT)
    assert "secret" not in answer.values


# --- защита от выдумывания -------------------------------------------------


def test_value_without_evidence_rejected() -> None:
    """Значение, которого нет в INPUT, отбрасывается (раздел 37 ТЗ)."""
    raw = '{"document_number": {"value": "999-999", "confidence": 0.99, "evidence": "№ 999-999"}}'
    answer = validate(raw, INPUT_TEXT)

    assert answer.values == {}
    assert Status.AI_EVIDENCE_REJECTED.value in answer.statuses
    assert "document_number=999-999" in answer.rejected


def test_invented_date_rejected() -> None:
    raw = '{"document_date": {"value": "2020-01-01", "confidence": 0.9, "evidence": "01.01.2020"}}'
    answer = validate(raw, INPUT_TEXT)
    assert "document_date" not in answer.values
    assert Status.AI_EVIDENCE_REJECTED.value in answer.statuses


def test_supported_values_accepted() -> None:
    raw = (
        '{"document_type": {"value": "Постановление судебного пристава", "confidence": 0.98,'
        ' "evidence": "ПОСТАНОВЛЕНИЕ"},'
        ' "document_date": {"value": "2026-07-27", "confidence": 0.99, "evidence": "27 июля 2026"},'
        ' "main_persons": [{"value": "Иванов Иван Иванович", "role": "должник",'
        ' "confidence": 0.92, "evidence": "Должник: Иванов Иван Иванович"}]}'
    )
    answer = validate(raw, INPUT_TEXT)

    assert answer.values["document_date"]["value"] == "2026-07-27"
    assert answer.values["main_persons"][0]["role"] == "должник"


def test_evidence_supported_ignores_case_and_punctuation() -> None:
    assert evidence_supported("иванов иван иванович", "", INPUT_TEXT)
    assert not evidence_supported("Сидоров Сидор", "", INPUT_TEXT)


def test_classification_label_needs_word_support() -> None:
    """Ярлык типа принимается только при поддержке основ слов в INPUT."""
    raw = (
        '{"document_type": {"value": "Приговор суда присяжных", "confidence": 0.9,'
        ' "evidence": "ПОСТАНОВЛЕНИЕ"}}'
    )
    answer = validate(raw, INPUT_TEXT)
    assert "document_type" not in answer.values


def test_answer_stays_russian() -> None:
    """Русскоязычный документ не получает англоязычный тип (раздел 14A.8 ТЗ)."""
    raw = '{"document_type": {"value": "Bailiff order", "confidence": 0.9, "evidence": "order"}}'
    answer = validate(raw, INPUT_TEXT)
    assert "document_type" not in answer.values


# --- контекст и промпт -----------------------------------------------------


def test_context_is_compact_and_structured(tmp_path: Path, config: Config) -> None:
    analysis = make_analysis(tmp_path / "12345.pdf")
    block = build_context(analysis, INPUT_TEXT * 200, Limits.from_config(config))

    assert "FILE:" in block
    assert "DATE CANDIDATES:" in block
    assert "TEXT_HEAD:" in block
    assert len(block) <= config.limits.max_text_chars_for_ai


def test_prompt_forbids_invention_and_is_russian_first() -> None:
    prompt = build_prompt("INPUT")
    assert "You do not have permission to invent information" in prompt
    assert "не переводи" in prompt
    assert "Return valid JSON only" in prompt


# --- применение к анализу ---------------------------------------------------


def test_ai_not_called_when_rules_are_confident(tmp_path: Path, config: Config) -> None:
    """Дорогой вызов пропускается, если правила уже дали ответ (раздел 64 ТЗ)."""
    from docrenamer.types import Field

    analysis = make_analysis(tmp_path / "дело.pdf")
    analysis.document_type = Field("Постановление_СПИ", Source.TEXT, "ПОСТАНОВЛЕНИЕ", 0.96)
    analysis.document_date = Field("2026-07-27", Source.REGEX, "27 июля 2026", 0.97)
    analysis.document_number = Field("652102/26/77028-ИП", Source.REGEX, "№ 652102", 0.96)

    model = FakeModel("{}")
    AIEnricher(model, config, Limits.from_config(config)).enrich(analysis, INPUT_TEXT)

    assert model.calls == 0
    assert analysis.has_status(Status.AI_NOT_NEEDED)


def test_ai_fills_gaps_but_does_not_override_rules(tmp_path: Path, config: Config) -> None:
    from docrenamer.types import Field

    analysis = make_analysis(tmp_path / "дело.pdf")
    analysis.document_date = Field("2026-07-27", Source.REGEX, "27 июля 2026", 0.97)
    raw = (
        '{"document_type": {"value": "Постановление судебного пристава", "confidence": 0.95,'
        ' "evidence": "ПОСТАНОВЛЕНИЕ"},'
        ' "document_date": {"value": "2026-07-27", "confidence": 0.5, "evidence": "27 июля 2026"}}'
    )
    model = FakeModel(raw)
    AIEnricher(model, config, Limits.from_config(config)).enrich(analysis, INPUT_TEXT)

    assert model.calls == 1
    assert analysis.document_type is not None
    assert analysis.document_type.source is Source.LLM
    # Детерминированная дата не перезаписана моделью.
    assert analysis.document_date.source is Source.REGEX
    assert analysis.document_date.confidence == pytest.approx(0.97)


def test_missing_model_reported_without_download(
    tmp_path: Path, config: Config, app_paths: AppPaths
) -> None:
    """Отсутствие модели — сообщение, а не загрузка из сети (раздел 3 ТЗ)."""
    model = LlamaCliModel(config, app_paths)
    analysis = make_analysis(tmp_path / "дело.pdf")

    AIEnricher(model, config, Limits.from_config(config)).enrich(analysis, INPUT_TEXT)

    assert analysis.has_status(Status.MODEL_NOT_FOUND)
    assert "LOCAL_MODEL_NOT_FOUND" in analysis.metadata["model_error"]
    assert "document-model.gguf" in analysis.metadata["model_error"]


def test_model_info_has_no_network_fields(config: Config, app_paths: AppPaths) -> None:
    info = LlamaCliModel(config, app_paths).info().to_dict()
    assert info["engine"] == "llama_cpp_cli"
    assert "url" not in info
    assert info["available"] is False
