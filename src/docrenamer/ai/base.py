"""Контракт локальной модели (раздел 33 ТЗ).

Сетевые движки запрещены архитектурно: реализация обязана быть локальным
процессом, читающим модель с диска.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ModelInfo:
    """Сведения о модели для manifest (раздел 51 ТЗ)."""

    engine: str = ""
    model_path: str = ""
    model_id: str = ""
    model_sha256: str = ""
    size_bytes: int = 0
    available: bool = False
    error: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "model_path": self.model_path,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "size_bytes": self.size_bytes,
            "available": self.available,
            "error": self.error,
            **self.extras,
        }


class LocalModel(Protocol):
    """Локальная языковая модель."""

    @property
    def available(self) -> bool:
        """Готова ли модель к работе."""
        ...

    def info(self) -> ModelInfo:
        """Сведения о модели."""
        ...

    def generate(self, prompt: str) -> tuple[str, str]:
        """Выполнить запрос. Возвращает ``(ответ, код_состояния)``."""
        ...
