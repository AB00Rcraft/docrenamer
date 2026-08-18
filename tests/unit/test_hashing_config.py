"""Тесты хэширования и конфигурации (разделы 48, 56 ТЗ)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docrenamer.config import Config, ConfigError, load_config, write_json_atomic
from docrenamer.operations.hashing import HashError, sha256_bytes, sha256_file


def test_sha256_matches_reference(tmp_path: Path) -> None:
    path = tmp_path / "файл.bin"
    payload = "Иванов Иван Иванович".encode()
    path.write_bytes(payload)
    assert sha256_file(path) == sha256_bytes(payload)


def test_sha256_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(HashError):
        sha256_file(tmp_path / "нет.bin")


def test_sha256_large_file_chunked(tmp_path: Path) -> None:
    path = tmp_path / "большой.bin"
    payload = b"\xd0\x98" * 500_000
    path.write_bytes(payload)
    assert sha256_file(path, chunk_size=4096) == sha256_bytes(payload)


def test_config_defaults_match_specification(config: Config) -> None:
    assert config.strict_local_mode is True
    assert config.dry_run_default is True
    assert config.naming.confidence_threshold == pytest.approx(0.88)
    assert config.naming.max_filename_length == 160
    assert config.ocr.language_spec == "rus+eng"
    assert config.limits.max_text_chars_for_ai == 24_000


@pytest.mark.parametrize(
    "payload",
    [
        {"strict_local_mode": False},
        {"unicode_normalization": "NFKC"},
        {"archives": {"inspect_only": False}},
        {"ai": {"engine": "openai"}},
        {"human_log_encoding": "windows-1251"},
    ],
)
def test_unsafe_config_rejected(payload: dict) -> None:
    with pytest.raises(ConfigError):
        Config.from_dict(payload)


def test_config_fingerprint_is_stable_and_sensitive() -> None:
    base = Config()
    same = Config()
    changed = Config.from_dict({"naming": {"confidence_threshold": 0.5}})
    assert base.fingerprint() == same.fingerprint()
    assert base.fingerprint() != changed.fingerprint()


def test_broken_config_reports_russian_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ не json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "JSON" in str(exc.value)


def test_atomic_json_keeps_cyrillic_readable(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_json_atomic(path, {"фио": "Иванов Иван Иванович", "тип": "Постановление"})
    raw = path.read_text(encoding="utf-8")
    assert "Иванов Иван Иванович" in raw
    assert "\\u0418" not in raw
    assert json.loads(raw)["тип"] == "Постановление"
    assert not list(path.parent.glob("*.tmp"))


def test_config_falls_back_to_bundled_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Без каталога config рядом с программой берётся вшитая копия.

    Так собранное приложение остаётся работоспособным, даже если каталог
    ``config/`` не скопирован рядом с исполняемым файлом.
    """
    from docrenamer import paths as paths_module
    from docrenamer.config import load_document_types

    empty_root = tmp_path / "DocRenamer"
    empty_root.mkdir()
    bundled = tmp_path / "bundle"
    (bundled / "config").mkdir(parents=True)
    (bundled / "config" / "document_types.json").write_text(
        '{"types": [{"canonical_name": "Договор", "markers": ["договор"]}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(paths_module, "bundled_root", lambda: bundled)

    app_paths = paths_module.AppPaths(root=empty_root)

    assert app_paths.document_types_file.is_file()
    assert load_document_types(paths=app_paths)[0]["canonical_name"] == "Договор"
