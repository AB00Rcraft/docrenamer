# DocRenamer Offline — архитектурная записка

Документ обязателен по разделу 87 (Phase 1) ТЗ. Источник истины по требованиям —
`documentation.md`. Здесь фиксируются trust boundaries, перечень мутаций файловой
системы, support matrix и план реализации.

---

## 1. Инварианты проекта

Эти свойства не могут быть изменены ни обновлением библиотек, ни продуктовыми
пожеланиями (разделы 2, 86, 92, 94 ТЗ):

| Инвариант | Как обеспечивается технически |
|---|---|
| Содержимое пользовательского файла не меняется | Ни один reader не открывает файл на запись; `operations/rename.py` — единственный модуль с мутацией; SHA-256 до/после |
| Нет overwrite | `naming/collision.py` + повторная проверка target прямо перед `Path.rename`; `os.replace` запрещён для user files |
| Нет удаления | `unlink/rmtree` разрешены только в `security/temp_cleanup.py` внутри `runtime_temp/` |
| Нет перемещения | `operations/safety.py` проверяет, что `src.parent == dst.parent` |
| Preview-first | `dry_run_default = true`; APPLY принимает только утверждённый `RenamePlan` |
| Undo | Каждый APPLY пишет manifest инкрементально; `--undo` работает по нему |
| Offline | Архитектурный запрет сетевых импортов + audit в `security/offline_guard.py` |
| Russian-first | Единый pipeline декодирования + `TextQualityValidator`; release gate раздела 95 |
| Evidence-based naming | В имя попадают только значения с `source` и `evidence` |

---

## 2. Trust boundaries

```
┌─ ДОВЕРЕННАЯ ЗОНА ───────────────────────────────────────────────┐
│ код приложения, config, document_types.json, собственные        │
│ manifest/log файлы, bundled runtime binaries                     │
└──────────────────────────────────────────────────────────────────┘
        ▲ проверка                        ▲ проверка
┌───────┴────────────────┐   ┌─────────────┴──────────────────────┐
│ НЕДОВЕРЕННЫЙ ВХОД      │   │ НЕДОВЕРЕННЫЙ ВЫХОД LLM             │
│ пользовательские файлы │   │ JSON локальной модели              │
│ имена файлов и пути    │   │                                    │
└────────────────────────┘   └────────────────────────────────────┘
```

**Граница 1 — пользовательские файлы** (`readers/*`). Любой файл считается
повреждённым или специально сформированным (раздел 54). Обязательно: лимиты
объёма, timeout на subprocess, `defusedxml` для XML, отсутствие исполнения
макросов/JS, отсутствие автоматической распаковки архивов, контроль ratio при
инспекции ZIP.

**Граница 2 — имена и пути.** Всё, что пришло из файловой системы или из анализа,
проходит `naming/sanitizer.py` перед тем, как стать target-именем.

**Граница 3 — вывод LLM** (`ai/validator.py`). JSON валидируется по схеме, поля с
неизвестными именами отбрасываются, каждое значение проверяется на присутствие в
INPUT (anti-hallucination, раздел 37). Модель не может создать факт.

**Граница 4 — subprocess** (`llama-cli`, `tesseract`, `exiftool`, `ffprobe`, `7z`).
Только список аргументов, `shell=False`, timeout, `check=False`.

---

## 3. Полный перечень мутаций файловой системы

Мутации ограничены четырьмя местами. Любое расширение этого списка требует
отдельного review и тестов (правило 14 AGENTS.md).

| # | Модуль | Операция | Цель | Защита |
|---|---|---|---|---|
| 1 | `operations/rename.py` | `Path.rename` | пользовательский файл | 10-шаговая транзакция раздела 48, SHA-256 до/после, проверка отсутствия target |
| 2 | `operations/undo.py` | `Path.rename` | пользовательский файл | те же проверки + сверка SHA с manifest |
| 3 | `logging/manifest.py`, `logging/text_log.py`, `config.py` | запись/atomic replace | собственные служебные файлы в `manifests/`, `logs/`, `config/` | `.tmp` → `flush` → `fsync` → `os.replace` |
| 4 | `security/temp_cleanup.py` | создание/удаление | только `runtime_temp/<session-id>/` | путь обязан лежать внутри `runtime_temp`, проверка через `is_relative_to` |

Пользовательские файлы **никогда** не открываются в режимах `w`, `a`, `r+`, `x`.

---

## 4. Support matrix

Обозначения: **F** — полная поддержка MVP, **P** — частичная (честно
маркируется кодом `PARTIAL_SUPPORT`), **I** — только инспекция, **—** — не MVP.

| Категория | Форматы | Ур. | Backend | Что извлекается |
|---|---|---|---|---|
| PDF | pdf | F | pypdf + pypdfium2 + Tesseract | text layer, quality score, метаданные, OCR fallback |
| OOXML | docx, xlsx, xlsm, pptx | F | python-docx, openpyxl (read-only, макросы не исполняются), python-pptx | текст, таблицы, core properties |
| Legacy Office | doc, ppt | P | olefile | OLE-свойства SummaryInformation; full-text ненадёжен |
| Legacy Excel | xls | P | xlrd | листы, ячейки |
| Plain text | txt, md, csv, log | F | stdlib + charset-normalizer | текст с определением кодировки (UTF-8/1251/KOI8-R/CP866/ISO-8859-5) |
| Разметка | html, htm | F | BeautifulSoup | title, visible text, meta; JS не исполняется |
| XML-семейство | xml, kml, kmz, gpx | F | defusedxml | без external entities и сетевых ссылок |
| JSON | json | F | stdlib | структура и релевантные фрагменты, с лимитами |
| RTF | rtf | P | собственный минимальный парсер | текст без исполнения |
| Изображения | jpg, png, tif, webp, bmp, gif, heic, heif, avif, dng | F | Pillow + pillow-heif + ExifTool, запасной разбор EXIF средствами Pillow | EXIF/XMP, размеры, GPS, устройство |
| Camera RAW | cr2, cr3, nef, arw, raf, orf, rw2, pef | P | ExifTool | metadata-first: timestamp, камера, GPS |
| Видео | mp4, mov, m4v, avi, mkv, webm, 3gp, mts, m2ts | F | ffprobe, запасной разбор боксов ISO BMFF для mp4/mov | duration, creation_time, кодек, разрешение, GPS |
| Аудио | mp3, m4a, aac, wav, flac, ogg, opus, wma, aiff, amr | F | mutagen + ffprobe | теги, duration, bitrate |
| Почта | eml | F | stdlib `email` | заголовки, тело, имена вложений |
| Почта | msg | F | extract-msg | то же |
| Архивы | zip, 7z, rar, tar, gz, tgz | I | stdlib + 7z CLI | только listing, без распаковки |

---

### Работа без внешних программ

ExifTool, ffprobe, Tesseract и llama.cpp поставляются отдельно и могут
отсутствовать. Чтобы приложение оставалось полезным в виде одного файла,
предусмотрены запасные источники метаданных на чистом Python:

| Отсутствует | Что берёт на себя запасной путь | Чего не будет |
|---|---|---|
| ExifTool | `metadata/pillow_exif.py` — дата съёмки, устройство, GPS, размеры | XMP, экзотические теги, метаданные RAW |
| ffprobe | `metadata/mp4_atoms.py` — дата, длительность, GPS, наличие дорожек для MP4/MOV | AVI, MKV, WEBM, кодеки, разрешение |
| Tesseract | — | распознавание сканов (`OCR_ENGINE_NOT_FOUND`) |
| llama.cpp + модель | детерминированные extractors | разрешение неоднозначностей (`MODEL_NOT_FOUND`) |

Формат результата у запасных backend'ов совпадает с основным, поэтому reader
не различает источники.

---

## 5. Слои и порядок вызова

```
cli.py / gui.py           тонкие оболочки, бизнес-логики не содержат
        │
        ▼
app.py                    оркестратор: Application(config).run(...)
        │
        ├── scanner.py            обход каталога, ignore patterns, защита от symlink-петель
        ├── file_signature.py     реальный тип по сигнатуре + сверка с extension
        ├── readers/*             текст + метаданные (недоверенный вход)
        ├── metadata/*            exiftool, ffprobe
        ├── ocr/*                 выбор страниц + Tesseract
        ├── extractors/*          детерминированные факты (даты, ФИО, номера, ИНН/ОГРН)
        ├── ai/*                  context builder → llama-cli → JSON → validator
        ├── naming/*              builder → sanitizer → collision
        └── operations/*          planner → rename (транзакция) → manifest → undo
```

Порядок «от дешёвого к дорогому» (раздел 64): metadata → regex → reader → OCR →
LLM. LLM не запускается, если имя уже собирается с достаточной уверенностью.

---

## 6. Модель данных

Ключевой тип — `FileAnalysis` (`types.py`), в котором каждое значимое поле
представлено `Field`-обёрткой:

```python
Field(value=..., source="text|metadata|regex|llm|filesystem", evidence="...", confidence=0.0)
```

`NameBuilder` использует только принятые (`accepted`) значения. Значение без
evidence в имя файла попасть не может.

---

## 7. План реализации

| Phase | Содержание | Статус |
|---|---|---|
| 1 | Архитектура, каркас, config, типы | ✅ |
| 2 | Safety core: scanner, hashing, sanitizer, collision, planner, rename, manifest, undo + тесты | ✅ |
| 3 | Readers по одному с тестами | ✅ |
| 4 | ExifTool + ffprobe | ✅ |
| 5 | OCR: pypdfium2 + Tesseract | ✅ |
| 6 | Детерминированные extractors | ✅ |
| 7 | Локальная LLM: llama.cpp + JSON + evidence validation | ✅ |
| 8 | GUI (только после стабильного safety core) | ✅ |
| 9 | Packaging: PyInstaller + runtime binaries | ✅ спецификация и скрипт готовы |
| 10 | Release audit | ✅ автоматизирован тестами |

Автоматизированные проверки перед выпуском:

```bash
pytest tests/unit tests/integration            # функциональность
pytest -m safety                               # инварианты файловой системы
pytest -m offline                              # работа без сети
python -m docrenamer.security.offline_guard --audit src
ruff check src tests && mypy
```

Проверки раздела 91 ТЗ (поиск сетевых библиотек, вызовов удаления и
`os.replace` по пользовательским файлам) выполняются не вручную, а тестами в
`tests/safety/test_source_audit.py`: они не дадут внести такой код незаметно.

---

## 8. Что не проверено в среде разработки

Разработка велась на Linux, поэтому следующее требует проверки на целевой
платформе перед выпуском:

- запуск собранного `DocRenamer.exe` на чистой Windows 10/11 x64 без Python.
  PyInstaller не поддерживает кросс-компиляцию: исполняемый файл Windows
  создаётся только на Windows. В среде разработки собиралась и проверялась
  сборка для Linux (оба режима, onedir и onefile) — этим проверена сама
  спецификация сборки, состав данных и запуск без интерпретатора;
- работа с USB-носителя и из произвольного каталога;
- графический интерфейс (Tkinter входит в состав Python для Windows; в среде
  разработки пакет `python3-tk` отсутствовал, поэтому проверялись логика
  представления `docrenamer/presentation.py` и корректность модуля, но не
  внешний вид окна);
- реальный OCR Tesseract и реальный вывод локальной GGUF-модели: движки в среде
  разработки не устанавливались, их поведение покрыто контрактными тестами с
  подставными реализациями и проверкой кодов `OCR_ENGINE_NOT_FOUND` и
  `LOCAL_MODEL_NOT_FOUND`;
- ExifTool: недоступен в среде разработки, метаданные фото проверялись через
  Pillow, а контракт backend'а — тестами.

---

## 9. Известные ограничения MVP

- `.doc` / `.ppt`: полный текст не извлекается, только OLE-свойства → `PARTIAL_SUPPORT`.
- Camera RAW: metadata-only.
- Архивы: только listing, имя строится по содержимому списка.
- Sidecar (AAE/XMP/THM) и Live Photo пары: помечаются для ручной проверки,
  автоматический групповой rename в MVP не выполняется.
- Whisper, vision-модели, обратное геокодирование, поиск и индекс — версия 2.
