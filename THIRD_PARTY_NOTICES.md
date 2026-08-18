# Уведомления о стороннем программном обеспечении

DocRenamer Offline поставляется вместе со сторонними компонентами. Ниже
перечислено то, что входит в portable-дистрибутив или используется при сборке.
Тексты лицензий помещаются в каталог `LICENSES/` на этапе сборки.

Open source не означает отсутствия условий распространения: перед выпуском
дистрибутива лицензии обязательно проверяются заново (раздел 72 ТЗ).

---

## Bundled runtime (поставляются как исполняемые файлы)

| Компонент | Назначение | Лицензия | Источник |
|---|---|---|---|
| llama.cpp (`llama-cli`) | локальный вывод языковой модели | MIT | https://github.com/ggml-org/llama.cpp |
| GGUF-модель (стартовая — Qwen3-4B-GGUF) | семантический разбор документов | лицензия конкретной модели, проверяется отдельно | https://huggingface.co/Qwen/Qwen3-4B-GGUF |
| Tesseract OCR + `tessdata` (`rus`, `eng`, `osd`) | распознавание сканов | Apache-2.0 | https://github.com/tesseract-ocr/tesseract |
| ExifTool | метаданные фото и медиа | Perl Artistic / GPL-1.0-or-later | https://exiftool.org/ |
| FFmpeg (`ffprobe`) | метаданные видео и аудио | LGPL-2.1-or-later либо GPL — зависит от сборки | https://ffmpeg.org/ |
| 7-Zip (`7z`) | просмотр содержимого 7Z и RAR | LGPL-2.1-or-later, код RAR — отдельные условия | https://www.7-zip.org/ |

**Важно.** Сборка FFmpeg определяет применимую лицензию: варианты с
`--enable-gpl` или `--enable-nonfree` накладывают дополнительные обязательства.
Для распространяемого дистрибутива берите LGPL-сборку без nonfree-компонентов.

Лицензия распространения выбранной GGUF-модели проверяется до включения файла в
дистрибутив — условия у разных моделей отличаются.

---

## Библиотеки Python

| Пакет | Назначение | Лицензия |
|---|---|---|
| pypdf | чтение PDF | BSD-3-Clause |
| pypdfium2 | рендеринг страниц PDF для OCR | Apache-2.0 / BSD-3-Clause (PDFium) |
| python-docx | чтение DOCX | MIT |
| openpyxl | чтение XLSX/XLSM | MIT |
| xlrd | чтение устаревшего XLS | BSD-3-Clause |
| python-pptx | чтение PPTX | MIT |
| Pillow | работа с изображениями | MIT-CMU |
| pillow-heif | поддержка HEIC/HEIF/AVIF | BSD-3-Clause (libheif — LGPL) |
| beautifulsoup4 | разбор HTML | MIT |
| charset-normalizer | определение кодировки текста | MIT |
| defusedxml | безопасный разбор XML | PSF-2.0 |
| olefile | чтение контейнеров OLE2 | BSD-2-Clause |
| extract-msg | чтение писем Outlook MSG | GPL-3.0 |
| mutagen | теги аудиофайлов | GPL-2.0-or-later |
| PyInstaller | сборка дистрибутива (только сборка) | GPL-2.0 с исключением для собранных приложений |

**Важно.** `extract-msg` (GPL-3.0) и `mutagen` (GPL-2.0-or-later) распространяются
на условиях GPL. При поставке дистрибутива, включающего эти библиотеки,
соблюдайте требования соответствующих лицензий либо замените компоненты.
Это решение принимается до публикации дистрибутива.

---

## Компоненты, которые НЕ используются

Программа не содержит и не загружает:

- клиентов облачных AI-сервисов (OpenAI, Anthropic, Google, Mistral, Qwen Cloud,
  Hugging Face Inference, Azure AI);
- облачных OCR и облачных embeddings;
- средств телеметрии, аналитики и отправки отчётов об ошибках;
- механизмов автоматического обновления и проверки лицензии через Интернет;
- сетевых библиотек (`requests`, `httpx`, `aiohttp`, `urllib3` и подобных).

Отсутствие сетевой функциональности проверяется автоматически:

```bash
python -m docrenamer.security.offline_guard --audit src
```
