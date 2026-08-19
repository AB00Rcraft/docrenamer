# AGENTS.md — правила для coding agent

This repository contains a safety-sensitive local file renaming tool.

## NON-NEGOTIABLE RULES

1. Never modify user file contents. Единственное исключение —
   `src/docrenamer/operations/scrub.py`: снятие метаданных по прямой команде
   человека. Оно запускается отдельной операцией, по умолчанию создаёт копию,
   замену исходного файла подтверждает человек, и каждый случай записывается в
   отчёт `logs/scrub-*.json`. Никакой другой код права менять файл не имеет.
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
    собственных служебных файлов (manifest, config) при atomic write и для
    очистки метаданных (правило 1), где подмена файла — суть операции.
19. Не добавлять зависимость, если задача разумно решается standard library.
20. Любой subprocess вызывается только списком аргументов, `shell=False`, с timeout.

24. Очистка метаданных ничего не обещает сверх сделанного. В интерфейсе
    перечисляется и то, что снимается, и то, что остаётся: текст документа,
    исправления Word, копии файла в других местах. Формулировок вида «никто
    ничего не узнает» быть не должно.

## Обратная связь об именах — с чего начинать работу над именами

Пользователи присылают обезличенные отчёты кнопкой «Улучшение»: они приходят
обращениями с меткой `naming-report`. Прежде чем менять правила имён или
справочник видов документов, соберите их и посмотрите, что болит на практике:

```bash
python tools/collect_feedback.py --state all      # нужен gh auth login
cat feedback/SUMMARY.md
```

В своде важны две вещи: таблица «Что чинить в первую очередь» (виды документов,
имена которых чаще всего правят руками) и раздел «Как правят имена» — из него
видно, ошибается ли программа в виде документа, в дате или в длине имени.

Правила разбора отчёта:

21. Отчёт содержит только статистику. Ни имён файлов, ни фамилий, ни текста
    документов в нём быть не должно — если такое встретилось, это ошибка
    обезличивания в `src/docrenamer/learning.py`, и чинить надо её.
22. Изменение, сделанное по отчёту, сопровождается тестом на этот случай:
    отчёт говорит «часто правят», тест фиксирует, как должно быть.
23. Разобранное обращение закрывается с указанием версии, в которой учтено.

## Перед объявлением работы завершённой

```bash
pytest tests/unit tests/integration tests/safety
python -m docrenamer.security.offline_guard --audit src/docrenamer
ruff check src tests
mypy
```

Аудит проверяет `src/docrenamer` — программу, которая работает с документами.
Пакет `src/docrenamer_updater` содержит сетевой код по назначению, поэтому
`--audit src` сообщит о нарушениях; отдельный тест следит за тем, чтобы
`docrenamer` не импортировал пакет обновления.

Полное ТЗ: `documentation.md`. Архитектурная записка: `ARCHITECTURE.md`.
Устройство кода: `docs/РАЗРАБОТЧИКУ.md`. Руководство пользователя:
`docs/РУКОВОДСТВО.md`.
