"""Применение локальной модели к анализу (разделы 34, 37, 64 ТЗ).

Модель не выполняет всю работу: к моменту её вызова Python уже извлёк даты,
номера, ФИО и организации. LLM только разрешает неоднозначность — и только
если без неё уверенности не хватает.
"""

from __future__ import annotations

from typing import Any

from docrenamer.ai.base import ModelInfo
from docrenamer.ai.context_builder import build_context
from docrenamer.ai.llama_cli import LlamaCliModel
from docrenamer.ai.prompt import build_prompt
from docrenamer.ai.validator import validate
from docrenamer.config import Config
from docrenamer.security.limits import Limits
from docrenamer.types import EntityRef, Field, FileAnalysis, Source, Status

#: Минимальная длина текста, при которой обращение к модели вообще осмысленно.
MIN_TEXT_FOR_AI = 120


class AIEnricher:
    """Дополняет анализ результатами локальной модели."""

    def __init__(self, model: LlamaCliModel, config: Config, limits: Limits) -> None:
        self.model = model
        self.config = config
        self.limits = limits

    def model_info(self) -> ModelInfo:
        return self.model.info()

    def needed(self, analysis: FileAnalysis, text: str) -> bool:
        """Нужна ли модель для этого файла (раздел 64 ТЗ).

        Если детерминированные правила уже дали тип, дату и идентификатор с
        достаточной уверенностью, дорогой вызов не выполняется.
        """
        if len(text.strip()) < MIN_TEXT_FOR_AI:
            return False
        document_type = analysis.document_type
        document_date = analysis.document_date
        number = analysis.document_number
        has_type = document_type is not None and document_type.accepted
        has_date = document_date is not None and document_date.accepted
        has_identifier = (number is not None and number.accepted) or bool(analysis.case_numbers)
        if has_type and has_date and has_identifier and document_type and document_date:
            confidence = min(document_type.confidence, document_date.confidence)
            if confidence >= self.config.naming.confidence_threshold:
                return False
        return True

    def enrich(self, analysis: FileAnalysis, text: str) -> None:
        """Вызвать модель и принять только подтверждённые значения."""
        if not self.needed(analysis, text):
            analysis.add_status(Status.AI_NOT_NEEDED)
            return

        blocked = self.model.status()
        if blocked:
            analysis.add_status(blocked)
            if blocked == Status.MODEL_NOT_FOUND.value:
                analysis.metadata["model_error"] = self.model.missing_model_message()
            return

        context_block = build_context(analysis, text, self.limits)
        raw, status = self.model.generate(build_prompt(context_block))
        if status:
            analysis.add_status(status)
            return

        answer = validate(raw, context_block)
        for code in answer.statuses:
            analysis.add_status(code)
        if answer.rejected:
            analysis.metadata["ai_rejected"] = answer.rejected
        if not answer.values:
            return

        analysis.metadata["ai_used"] = True
        self._apply(analysis, answer.values)

    def _apply(self, analysis: FileAnalysis, values: dict[str, Any]) -> None:
        """Перенести проверенные значения в анализ, не затирая надёжные факты."""
        for name, attribute in (
            ("document_type", "document_type"),
            ("document_date", "document_date"),
            ("document_number", "document_number"),
            ("subject", "subject"),
        ):
            entry = values.get(name)
            if not entry:
                continue
            current: Field | None = getattr(analysis, attribute)
            # Детерминированное значение имеет приоритет: модель лишь дополняет.
            if current is not None and current.accepted and current.source is not Source.LLM:
                continue
            setattr(
                analysis,
                attribute,
                Field(
                    value=entry["value"],
                    source=Source.LLM,
                    evidence=entry["evidence"],
                    confidence=min(0.9, float(entry["confidence"])),
                ),
            )

        if not analysis.case_numbers and values.get("case_numbers"):
            analysis.case_numbers = [
                Field(
                    value=item["value"],
                    source=Source.LLM,
                    evidence=item["evidence"],
                    confidence=min(0.9, float(item["confidence"])),
                )
                for item in values["case_numbers"]
            ]

        if not analysis.main_persons and values.get("main_persons"):
            analysis.main_persons = [
                EntityRef(
                    name=item["value"],
                    role=item.get("role", ""),
                    confidence=min(0.9, float(item["confidence"])),
                    evidence=item["evidence"],
                    source=Source.LLM,
                )
                for item in values["main_persons"][: self.config.naming.max_persons_in_filename]
            ]

        if not analysis.main_organizations and values.get("main_organizations"):
            limit = self.config.naming.max_organizations_in_filename
            analysis.main_organizations = [
                EntityRef(
                    name=item["value"],
                    role=item.get("role", ""),
                    confidence=min(0.9, float(item["confidence"])),
                    evidence=item["evidence"],
                    source=Source.LLM,
                )
                for item in values["main_organizations"][:limit]
            ]
