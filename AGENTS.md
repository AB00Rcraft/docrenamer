# AGENTS.md — правила для coding agent

This repository contains a safety-sensitive local file renaming tool.

## NON-NEGOTIABLE RULES

1. Never modify user file contents.
2. Never overwrite an existing user file.
3. Never delete a user file.
4. Never move a user file to another directory in MVP.
5. Default mode is dry-run.
6. Every apply operation must have a manifest.
7. Verify SHA-256 before and after rename.
8. If source changes after preview, skip it.
9. Strict local mode must work with no network.
10. Do not add cloud APIs.
11. Do not auto-download models.
12. Never run embedded macros/scripts.
13. Treat all parsed files as untrusted input.
14. Add tests for every filesystem mutation.
15. Run the complete safety test suite before declaring work finished.

## Дополнительные правила проекта

16. Русский язык — основной профиль обработки, а не локализация (раздел 14A ТЗ).
    Ни один encoding fallback не имеет права использовать `errors="ignore"`.
17. LLM не является источником фактов. Любое значение, попадающее в имя файла,
    обязано иметь проверяемый evidence (regex / metadata / text-span).
18. `os.replace()` запрещён для пользовательских файлов. Допустим только для
    собственных служебных файлов (manifest, config) при atomic write.
19. Не добавлять зависимость, если задача разумно решается standard library.
20. Любой subprocess вызывается только списком аргументов, `shell=False`, с timeout.

## Перед объявлением работы завершённой

```bash
pytest tests/unit tests/integration tests/safety
python -m docrenamer.security.offline_guard --audit src
ruff check src tests
```

Полное ТЗ: `documentation.md`. Архитектурная записка: `ARCHITECTURE.md`.
