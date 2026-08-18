"""Локальная модель через ``llama-cli`` (раздел 33 ТЗ).

Используется только CLI-режим llama.cpp: ``llama-server`` и HTTP API не
применяются даже на localhost. Модель открывается исключительно по локальному
пути; механизмы загрузки моделей (``-hf`` и подобные) запрещены.
"""

from __future__ import annotations

import hashlib
import os

from docrenamer.ai.base import ModelInfo
from docrenamer.config import Config
from docrenamer.paths import AppPaths, resolve_model_path
from docrenamer.security.subprocess_safe import run_tool
from docrenamer.types import Status, nfc

#: Сколько байт модели хэшируется для идентификации. Полный SHA-256 файла в
#: несколько гигабайт считался бы на каждом запуске неоправданно долго.
MODEL_FINGERPRINT_BYTES = 8 * 1024 * 1024


class LlamaCliModel:
    """Обёртка над локальным ``llama-cli``."""

    def __init__(self, config: Config, paths: AppPaths) -> None:
        self.config = config
        self.paths = paths
        self.executable = paths.llama_cli(config.allow_system_binaries)
        self.model_path = resolve_model_path(paths, config.ai.model_path)
        self._info: ModelInfo | None = None

    @property
    def available(self) -> bool:
        return (
            self.executable is not None
            and self.model_path.is_file()
            and self.config.ai.enabled
        )

    def status(self) -> str:
        """Код состояния, если модель использовать нельзя."""
        if not self.config.ai.enabled:
            return Status.AI_DISABLED.value
        if not self.model_path.is_file():
            return Status.MODEL_NOT_FOUND.value
        if self.executable is None:
            return Status.MODEL_NOT_FOUND.value
        return ""

    def missing_model_message(self) -> str:
        """Сообщение раздела 3 ТЗ об отсутствующей модели."""
        return f"LOCAL_MODEL_NOT_FOUND\nExpected: {self.model_path}"

    def info(self) -> ModelInfo:
        """Сведения о модели, включая отпечаток файла."""
        if self._info is not None:
            return self._info
        info = ModelInfo(
            engine="llama_cpp_cli",
            model_path=str(self.model_path),
            model_id=self.model_path.name,
            available=self.available,
        )
        if self.model_path.is_file():
            try:
                info.size_bytes = self.model_path.stat().st_size
                info.model_sha256 = self._fingerprint()
            except OSError as exc:
                info.error = f"Модель недоступна: {exc}"
        else:
            info.error = self.missing_model_message()
        self._info = info
        return info

    def _fingerprint(self) -> str:
        """Отпечаток модели: SHA-256 первых мегабайт и размера файла."""
        digest = hashlib.sha256()
        with open(self.model_path, "rb") as handle:
            digest.update(handle.read(MODEL_FINGERPRINT_BYTES))
        digest.update(str(self.model_path.stat().st_size).encode("ascii"))
        return digest.hexdigest()

    def generate(self, prompt: str) -> tuple[str, str]:
        """Выполнить запрос к локальной модели."""
        blocked = self.status()
        if blocked or self.executable is None:
            return "", blocked or Status.MODEL_NOT_FOUND.value

        threads = self.config.ai.threads or max(1, (os.cpu_count() or 2) - 1)
        arguments = [
            "-m",
            str(self.model_path),
            "-p",
            prompt,
            "-n",
            str(self.config.ai.max_output_tokens),
            "-c",
            str(self.config.ai.context_size),
            "--temp",
            str(self.config.ai.temperature),
            "-t",
            str(threads),
            "-no-cnv",
            "--no-display-prompt",
            "--simple-io",
        ]
        result = run_tool(
            self.executable,
            arguments,
            timeout=self.config.ai.timeout_seconds,
        )
        if result.timed_out:
            return "", Status.MODEL_FAILED.value
        if not result.stdout.strip():
            return "", Status.MODEL_FAILED.value
        return nfc(result.stdout), ""


def build_model(config: Config, paths: AppPaths) -> LlamaCliModel | None:
    """Создать локальную модель, если ИИ включён в настройках."""
    if not config.ai.enabled:
        return None
    return LlamaCliModel(config, paths)
