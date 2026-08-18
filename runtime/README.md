# Локальные компоненты (runtime)

Каталог заполняется вручную перед сборкой дистрибутива. Программа **никогда**
не скачивает эти компоненты сама (разделы 3, 61 ТЗ): если чего-то нет, она
сообщает об ограничении и продолжает работать без него.

Каталог `runtime/` целиком исключён из репозитория (`.gitignore`).

## Требуемая раскладка

```text
runtime/
├── llama/
│   └── llama-cli.exe          локальный вывод языковой модели
├── tesseract/
│   ├── tesseract.exe          распознавание текста
│   └── tessdata/
│       ├── rus.traineddata
│       ├── eng.traineddata
│       └── osd.traineddata
├── exiftool/
│   └── exiftool.exe           метаданные фото и медиа
├── ffmpeg/
│   └── ffprobe.exe            метаданные видео и аудио
└── 7zip/
    └── 7z.exe                 просмотр 7Z и RAR (необязательно)
```

Модель кладётся отдельно:

```text
models/
└── document-model.gguf
```

## Где брать

| Компонент | Источник | Что скачивать |
|---|---|---|
| llama.cpp | https://github.com/ggml-org/llama.cpp/releases | сборку для Windows x64 (CPU), нужен `llama-cli.exe` |
| Модель | https://huggingface.co/Qwen/Qwen3-4B-GGUF | один файл `.gguf`, квантование Q4_K_M для CPU |
| Tesseract | https://tesseract-ocr.github.io/tessdoc/Installation.html | сборку для Windows; `tessdata` — https://github.com/tesseract-ocr/tessdata_fast |
| ExifTool | https://exiftool.org/ | Windows Executable, переименовать в `exiftool.exe` |
| FFmpeg | https://ffmpeg.org/download.html | из архива нужен только `ffprobe.exe` |
| 7-Zip | https://www.7-zip.org/download.html | `7z.exe` из установленного пакета |

Языковые данные OCR: начните с `tessdata_fast` (быстро, достаточно для
большинства сканов). Для сложных сканов можно заменить на `tessdata_best`,
пожертвовав скоростью.

Файл модели переименуйте в `document-model.gguf` либо укажите фактическое имя
в `config/config.json` → `ai.model_path`. Код не привязан к названию Qwen:
подходит любая совместимая GGUF-модель примерно от 1B до 8B.

## Проверка комплектности

После раскладки:

```bat
DocRenamer.exe "D:\Тестовая папка" --verbose
```

Если компонент не найден, в журнале появится соответствующий код:
`LOCAL_MODEL_NOT_FOUND`, `OCR_ENGINE_NOT_FOUND`. Это не ошибка сборки —
программа работает и без них, но с меньшими возможностями.

## Лицензии

Каждый добавленный компонент обязан быть отражён в `THIRD_PARTY_NOTICES.md`, а
текст его лицензии — помещён в `LICENSES/`. Отдельно проверьте условия
распространения выбранной GGUF-модели и вариант сборки FFmpeg (LGPL или GPL).
