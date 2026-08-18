"""Тесты командной строки (раздел 7 ТЗ)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docrenamer import cli
from docrenamer.paths import AppPaths
from tests.fixtures import builders

pytestmark = pytest.mark.integration


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths, workdir: Path) -> Path:
    """CLI работает в изолированной portable-раскладке."""
    monkeypatch.setattr(cli, "default_paths", lambda: app_paths)
    builders.make_pdf_with_text(workdir / "IMG_0032.pdf")
    builders.make_docx(workdir / "scan0007.docx")
    return workdir


def test_default_mode_is_dry_run(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Без флагов CLI только показывает план (раздел 7 ТЗ)."""
    before = {p.name for p in cli_env.iterdir()}

    code = cli.main([str(cli_env)])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert {p.name for p in cli_env.iterdir()} == before
    assert "Режим предпросмотра" in output
    assert "Постановление-СПИ" in output


def test_apply_renames_and_writes_manifest(
    cli_env: Path, app_paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main([str(cli_env), "--apply"])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Manifest:" in output
    manifests = list(app_paths.manifests_dir.glob("rename_manifest_*.json"))
    assert manifests
    assert not (cli_env / "IMG_0032.pdf").exists()


def test_undo_restores_names(
    cli_env: Path, app_paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.name for p in cli_env.iterdir()}
    cli.main([str(cli_env), "--apply"])
    capsys.readouterr()
    manifest = sorted(app_paths.manifests_dir.glob("rename_manifest_*.json"))[-1]

    code = cli.main(["--undo", str(manifest)])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Восстановлено: 2" in output
    assert {p.name for p in cli_env.iterdir()} == before


def test_forensic_mode_writes_reports_only(
    cli_env: Path, app_paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.name for p in cli_env.iterdir()}

    code = cli.main([str(cli_env), "--forensic"])
    capsys.readouterr()

    assert code == cli.EXIT_OK
    assert {p.name for p in cli_env.iterdir()} == before
    report = app_paths.manifests_dir / "analysis_report.json"
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8"))["strict_local_mode"] is True


def test_save_plan_option(cli_env: Path, tmp_path: Path) -> None:
    plan_path = tmp_path / "rename_plan.json"

    cli.main([str(cli_env), "--save-plan", str(plan_path)])

    assert plan_path.is_file()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["plan_format_version"] == 1
    # План самодостаточен для повторной проверки перед APPLY (раздел 49 ТЗ).
    for item in plan["items"]:
        assert len(item["sha256"]) == 64
        assert item["size"] >= 0
        assert "mtime" in item


def test_no_ai_and_no_ocr_flags(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main([str(cli_env), "--no-ai", "--no-ocr"])
    capsys.readouterr()
    assert code == cli.EXIT_OK


def test_missing_directory_reports_error(
    monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "default_paths", lambda: app_paths)

    code = cli.main([str(tmp_path / "нет-такой-папки")])
    error = capsys.readouterr().err

    assert code == cli.EXIT_ERROR
    assert "Каталог не найден" in error


def test_broken_config_reports_russian_error(
    monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "default_paths", lambda: app_paths)
    bad = tmp_path / "config.json"
    bad.write_text('{"strict_local_mode": false}', encoding="utf-8")

    code = cli.main([str(tmp_path), "--config", str(bad)])
    error = capsys.readouterr().err

    assert code == cli.EXIT_ERROR
    assert "STRICT LOCAL MODE" in error


def test_help_is_russian() -> None:
    parser = cli.build_parser()
    text = parser.format_help()
    assert "предпросмотр" in text
    assert "откатить сессию по manifest" in text


def test_wizard_previews_then_applies_on_confirmation(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пошаговый диалог: показать план, дождаться согласия, переименовать."""
    answers = iter([str(cli_env), "д"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    code = cli.main(["--wizard"])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Файлы пока не меняются" in output
    assert "Переименовано: 2" in output
    assert not (cli_env / "IMG_0032.pdf").exists()


def test_wizard_changes_nothing_on_refusal(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.name for p in cli_env.iterdir()}
    answers = iter([str(cli_env), "н"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    code = cli.main(["--wizard"])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Ничего не изменено" in output
    assert {p.name for p in cli_env.iterdir()} == before


def test_wizard_asks_again_for_wrong_path(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter([str(cli_env / "нет-такой"), str(cli_env), "н"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    cli.main(["--wizard"])
    output = capsys.readouterr().out

    assert "Папка не найдена" in output


def test_wizard_empty_answer_cancels(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    code = cli.main(["--wizard"])

    assert code == cli.EXIT_OK
    assert "Отменено" in capsys.readouterr().out


def test_undo_wizard_restores_last_operation(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.name for p in cli_env.iterdir()}
    cli.main([str(cli_env), "--apply"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt="": "д")
    code = cli.main(["--undo", "__last__"])
    output = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "Восстановлено: 2" in output
    assert {p.name for p in cli_env.iterdir()} == before


def test_undo_wizard_without_history(
    monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "default_paths", lambda: app_paths)

    code = cli.main(["--undo", "__last__"])

    assert code == cli.EXIT_OK
    assert "Отменять нечего" in capsys.readouterr().out
