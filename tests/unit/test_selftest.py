"""Самопроверка комплекта (требование приёмки).

Пользователь должен видеть, собралась ли программа правильно и подключено ли
всё нужное для распознавания.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.config import Config
from docrenamer.paths import AppPaths
from docrenamer.selftest import Level, run_selftest


@pytest.fixture
def report(config: Config, app_paths: AppPaths):
    return run_selftest(config, app_paths, probe_model=False)


def test_pipeline_check_actually_parses_a_document(report) -> None:
    """Проверяется вся цепочка: чтение, извлечение реквизитов, построение имени."""
    check = next(c for c in report.checks if c.name == "Разбор документа")

    assert check.level is Level.OK
    assert "27.07.2026" in check.detail
    assert "Постановление_СПИ" in check.detail


def test_core_checks_pass_on_correct_build(report) -> None:
    for name in ("Программа", "Словарь документов", "Чтение форматов", "Служебные каталоги"):
        check = next(c for c in report.checks if c.name == name)
        assert check.level is Level.OK, f"{name}: {check.detail}"


def test_missing_ocr_and_model_are_warnings_not_failures(
    config: Config, app_paths: AppPaths
) -> None:
    """Без OCR и модели программа работоспособна — это предупреждение."""
    config.allow_system_binaries = False
    result = run_selftest(config, app_paths, probe_model=False)

    ocr = next(c for c in result.checks if c.name == "Распознавание сканов")
    model = next(c for c in result.checks if c.name == "Локальная модель")

    assert ocr.level is Level.WARN
    assert model.level is Level.WARN
    assert "runtime" in ocr.hint
    assert "не скачивается" in model.hint
    assert result.ready, "программа остаётся работоспособной"
    assert not result.complete
    assert result.badge.startswith("!")


def test_media_backends_work_without_external_tools(
    config: Config, app_paths: AppPaths
) -> None:
    """Без ExifTool и ffprobe метаданные всё равно читаются — это не ограничение."""
    config.allow_system_binaries = False
    result = run_selftest(config, app_paths, probe_model=False)

    for name in ("Метаданные фото", "Метаданные видео", "Архивы"):
        check = next(c for c in result.checks if c.name == name)
        assert check.level is Level.OK, f"{name}: {check.detail}"


def test_broken_dictionary_is_a_failure(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Пустой словарь типов делает программу неработоспособной."""
    (app_paths.config_dir / "document_types.json").write_text(
        '{"types": []}', encoding="utf-8"
    )
    result = run_selftest(config, app_paths, probe_model=False)

    check = next(c for c in result.checks if c.name == "Словарь документов")
    assert check.level is Level.FAIL
    assert not result.ready
    assert result.badge.startswith("×")


def test_model_probe_reports_answer(
    config: Config, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пробный запрос к модели: доступность подтверждается ответом, а не наличием файла."""
    model_path = app_paths.models_dir / "document-model.gguf"
    model_path.write_bytes(b"GGUF" + bytes(2048))
    monkeypatch.setattr(
        "docrenamer.paths.AppPaths.llama_cli", lambda self, allow=True: Path("/bin/true")
    )
    monkeypatch.setattr(
        "docrenamer.ai.llama_cli.LlamaCliModel.generate",
        lambda self, prompt: ("Постановление", ""),
    )

    result = run_selftest(config, app_paths, probe_model=True)
    check = next(c for c in result.checks if c.name == "Локальная модель")

    assert check.level is Level.OK
    assert "отвечает" in check.detail


def test_silent_model_is_a_warning(
    config: Config, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    (app_paths.models_dir / "document-model.gguf").write_bytes(b"GGUF" + bytes(2048))
    monkeypatch.setattr(
        "docrenamer.paths.AppPaths.llama_cli", lambda self, allow=True: Path("/bin/true")
    )
    monkeypatch.setattr(
        "docrenamer.ai.llama_cli.LlamaCliModel.generate",
        lambda self, prompt: ("", "MODEL_FAILED"),
    )

    result = run_selftest(config, app_paths, probe_model=True)
    check = next(c for c in result.checks if c.name == "Локальная модель")

    assert check.level is Level.WARN
    assert result.ready, "без модели программа продолжает работать по правилам"


def test_report_is_serializable_and_human_readable(report) -> None:
    data = report.to_dict()
    assert data["app_version"]
    assert data["checks"]

    text = report.format_text()
    assert "Самопроверка DocRenamer Offline" in text
    assert "Разбор документа" in text
    assert report.verdict in text


def test_cli_selftest_prints_report(
    monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    from docrenamer import cli

    monkeypatch.setattr(cli, "default_paths", lambda: app_paths)
    monkeypatch.setattr(
        "docrenamer.selftest.run_selftest",
        lambda config=None, paths=None, probe_model=True: run_selftest(
            config, paths, probe_model=False
        ),
    )

    code = cli.main(["--selftest"])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Самопроверка" in output
    assert "Разбор документа" in output
