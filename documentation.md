# DocRenamer Offline — полное техническое описание и техническое задание

**Версия:** 1.0  
**Дата:** 18 августа 2026  
**Основная платформа MVP:** Windows 10/11 x64  
**Язык:** Python 3.12+  
**Режим:** полностью локальный, без обязательного доступа в Интернет

---

# 1. Назначение

Нужно разработать компактную переносимую программу, которая анализирует файлы в выбранной пользователем директории и безопасно предлагает или выполняет их переименование на основании содержимого и метаданных.

Программа должна учитывать:

- тип документа или файла;
- дату самого документа;
- дату съёмки фото/видео;
- номер документа, договора, дела, исполнительного производства и т. п.;
- ключевых физических лиц;
- ключевые организации;
- краткий предмет документа;
- юридически или фактически значимые реквизиты;
- EXIF/XMP/QuickTime/ID3 и иные metadata;
- OCR-текст сканов и изображений;
- локальный семантический анализ небольшой LLM, когда обычных правил недостаточно.

Программа должна работать **полностью офлайн** после подготовки portable-комплекта.

На целевом компьютере не должны требоваться:

- Интернет;
- Python;
- pip;
- Microsoft Office;
- Ollama;
- отдельный AI-сервер;
- установленный OCR;
- установленный FFmpeg/ExifTool;
- учётная запись;
- облачная авторизация.

Все runtime-компоненты поставляются внутри папки приложения.

---

# 2. Главный инженерный принцип

Программа **не является редактором пользовательских файлов**.

Она:

1. сканирует каталог;
2. читает файлы;
3. извлекает текст и metadata;
4. анализирует;
5. строит предложенное имя;
6. показывает preview;
7. по явной команде пользователя переименовывает;
8. проверяет SHA-256 до и после;
9. пишет лог и manifest;
10. позволяет undo.

В MVP разрешено только **переименование внутри текущей директории**.

Запрещено:

- пересохранять PDF/DOCX/XLSX/JPG/HEIC и т. п.;
- изменять EXIF/XMP;
- удалять файлы;
- перемещать их в другие каталоги;
- распаковывать и изменять архивы;
- выполнять макросы;
- выполнять JavaScript из PDF/HTML;
- отправлять содержимое во внешние API.

---

# 3. STRICT LOCAL MODE

`STRICT_LOCAL_MODE=true` — режим по умолчанию.

В нём запрещены:

- OpenAI API;
- Anthropic API;
- Gemini API;
- Mistral API;
- Qwen Cloud API;
- Hugging Face Inference API;
- Azure AI;
- Google Vision;
- ABBYY Cloud;
- облачные OCR;
- облачные embeddings;
- telemetry;
- analytics;
- crash-reporting наружу;
- автоматическая загрузка моделей;
- автоматическое обновление;
- проверка лицензии через Интернет.

Программа должна выполнить полный рабочий цикл при физически отключённом сетевом адаптере.

Если модель отсутствует:

```text
LOCAL_MODEL_NOT_FOUND
Expected: .\models\document-model.gguf
```

Программа не пытается её скачать.

Если отсутствует OCR:

```text
OCR_ENGINE_NOT_FOUND
```

Программа не пытается его скачать.

---

# 4. Portable layout

Предпочтительный distribution:

```text
DocRenamer/
│
├── DocRenamer.exe
├── config/
│   ├── config.json
│   └── document_types.json
│
├── runtime/
│   ├── llama/
│   │   └── llama-cli.exe
│   ├── tesseract/
│   │   ├── tesseract.exe
│   │   └── tessdata/
│   │       ├── rus.traineddata
│   │       └── eng.traineddata
│   ├── exiftool/
│   │   └── exiftool.exe
│   ├── ffmpeg/
│   │   └── ffprobe.exe
│   └── 7zip/
│       └── 7z.exe
│
├── models/
│   └── document-model.gguf
│
├── logs/
├── manifests/
├── runtime_temp/
├── README.md
├── THIRD_PARTY_NOTICES.md
└── LICENSES/
```

Приложение должно одинаково работать:

```text
E:\DocRenamer\DocRenamer.exe
C:\Tools\DocRenamer\DocRenamer.exe
D:\Case\Tools\DocRenamer\DocRenamer.exe
```

Никакой привязки к букве диска.

Все внутренние пути вычислять относительно расположения `DocRenamer.exe`.

---

# 5. Базовая технология

Основная бизнес-логика — Python.

Рекомендуемая сборочная база — Python 3.12 x64.

Для portable Windows build использовать **PyInstaller** в `onedir` режиме.

Официальные документы:

- https://pyinstaller.org/
- https://pyinstaller.org/en/stable/usage.html
- https://pyinstaller.org/en/stable/operating-mode.html
- https://pyinstaller.org/en/stable/spec-files.html

`onedir` предпочтительнее `onefile`, потому что приложение всё равно содержит локальную GGUF-модель, OCR-данные и внешние runtime binaries.

---

# 6. Минимальный GUI

Не использовать Electron, Chromium или встроенный web-server.

Использовать стандартный **Tkinter + ttk**.

Документация:

- https://docs.python.org/3/library/tkinter.html

Пример интерфейса:

```text
┌──────────────────────────────────────────────────────────────┐
│  DocRenamer Offline                           ● LOCAL ONLY   │
├──────────────────────────────────────────────────────────────┤
│ Папка: D:\Дело Петрова\Том 1                     [ Выбрать ] │
│                                                              │
│ Режим:  ○ Анализ   ● Предпросмотр   ○ Применить             │
├──────────────────────────────────────────────────────────────┤
│ [16:22:03] Найдено файлов: 184                               │
│ [16:22:04] PDF: 91 | DOCX: 32 | JPG/HEIC: 44 | другое: 17   │
│ [16:22:05] Анализ: 38/184                                   │
│ [16:22:05] → Постановление СПИ | confidence 0.96             │
│                     ... scrolling log ...                    │
├──────────────────────────────────────────────────────────────┤
│ [ Сканировать ] [ Предпросмотр ] [ Переименовать ] [ Undo ] │
│                                        [ ⚙ Настройки ]      │
└──────────────────────────────────────────────────────────────┘
```

Стиль:

- компактный;
- тёмный/нейтральный;
- моноширинный лог;
- 1 акцентный цвет;
- немного живой, но не игрушечный;
- никаких лишних экранов.

Всегда показывать:

```text
● LOCAL ONLY
```

Tooltip:

```text
Все документы обрабатываются локально.
Сетевые AI API не используются.
```

Основные кнопки:

- `Выбрать папку`;
- `Сканировать`;
- `Предпросмотр`;
- `Переименовать`;
- `Отменить последнее`;
- `Настройки`;
- `Открыть лог`;
- `Стоп`.

---

# 7. CLI

GUI и CLI должны вызывать одну и ту же бизнес-логику.

Поддержать:

```bash
DocRenamer.exe
DocRenamer.exe "D:\Documents"
DocRenamer.exe --here
DocRenamer.exe "D:\Documents" --recursive
DocRenamer.exe "D:\Documents" --dry-run
DocRenamer.exe "D:\Documents" --apply
DocRenamer.exe --undo ".\manifests\rename_manifest_....json"
DocRenamer.exe --config ".\config\config.json"
DocRenamer.exe --no-ai
DocRenamer.exe --no-ocr
DocRenamer.exe --verbose
DocRenamer.exe --forensic
```

По умолчанию — `--dry-run`.

---

# 8. Режимы

## ANALYZE

Только анализ.

## PREVIEW / DRY RUN

Строит точный план, но ничего не меняет.

## APPLY

Переименовывает только по утверждённому плану.

## FORENSIC

Вообще не выполняет rename. Создаёт только:

- `analysis_report.json`;
- `rename_plan.json`;
- текстовый лог.

## UNDO

Возвращает старые имена по manifest.

---

# 9. Сканирование каталогов

Сканер должен:

- поддерживать recursive mode;
- не уходить по symlink/junction/reparse point за пределы дерева;
- исключать собственную папку приложения;
- исключать логи, manifests и временные файлы;
- не входить в системные каталоги;
- не зацикливаться.

Ignore patterns:

```text
.git
.svn
__pycache__
node_modules
$RECYCLE.BIN
System Volume Information
runtime_temp
logs
manifests
Thumbs.db
desktop.ini
~$*
*.tmp
```

---

# 10. Реальный тип файла

Нельзя доверять только extension.

Алгоритм:

1. получить extension;
2. проверить сигнатуры основных форматов;
3. при возможности запросить `FileType` у ExifTool;
4. сопоставить extension и detected type;
5. при расхождении записать `EXTENSION_MISMATCH`.

В MVP extension автоматически не менять.

---

# 11. Форматы — полная поддержка MVP

## Документы

- PDF
- DOCX
- XLSX
- XLSM — только чтение, макросы не исполнять
- PPTX
- TXT
- MD
- CSV
- HTML
- HTM
- XML
- JSON
- RTF

## Изображения

- JPG / JPEG
- PNG
- TIFF / TIF
- HEIC / HEIF
- WEBP
- AVIF
- BMP
- GIF
- DNG

## Видео

- MP4
- MOV
- M4V
- AVI
- MKV
- WEBM
- 3GP
- MTS
- M2TS

## Аудио

- MP3
- M4A
- AAC
- WAV
- FLAC
- OGG
- OPUS
- WMA
- AIFF
- AMR — через ffprobe, если metadata доступна

## Почта

- EML
- MSG

## Архивы

- ZIP
- 7Z
- RAR
- TAR
- GZ
- TGZ

Архивы только инспектировать.

## Геоданные

- GPX
- KML
- KMZ

---

# 12. Частичная поддержка

## Legacy Office

- DOC
- XLS
- PPT

Для `.xls` использовать `xlrd`.

Для `.doc/.ppt`:

- определить OLE;
- читать SummaryInformation/DocumentSummaryInformation;
- извлекать доступные свойства;
- честно помечать ограничение full-text extraction.

Не включать тяжёлую обязательную конвертацию через LibreOffice в MVP.

## Camera RAW

Metadata-first:

- CR2
- CR3
- NEF
- ARW
- RAF
- ORF
- RW2
- PEF

В первой версии достаточно timestamp, camera make/model, GPS, dimensions и metadata.

---

# 13. Pipeline

```text
FILE DISCOVERY
      ↓
TYPE DETECTION
      ↓
READER
      ↓
CONTENT + METADATA
      ↓
DETERMINISTIC EXTRACTORS
      ↓
SEMANTIC CONTEXT BUILDER
      ↓
LOCAL LLM (только если нужна)
      ↓
NORMALIZED PROFILE
      ↓
NAME BUILDER
      ↓
CONFIDENCE / SAFETY GATE
      ↓
PREVIEW
      ↓
APPLY
      ↓
SHA-256 VERIFY
      ↓
MANIFEST + LOG
```

---

# 14. Единая модель анализа

Пример:

```json
{
  "source_path": "D:\\Case\\IMG_0032.pdf",
  "detected_type": "pdf",
  "category": "document",
  "document_type": "Постановление судебного пристава",
  "document_date": "2026-07-27",
  "document_number": "859189755/7728",
  "case_numbers": ["652102/26/77028-ИП"],
  "main_persons": [
    {"name": "Иванов Иван Иванович", "role": "должник", "confidence": 0.92}
  ],
  "main_organizations": [
    {"name": "Алтуфьевский ОСП", "role": "issuer", "confidence": 0.99}
  ],
  "subject": "исполнительное производство",
  "metadata": {},
  "evidence": [],
  "overall_confidence": 0.95,
  "proposed_filename": "2026-07-27__Постановление-СПИ__Иванов__652102-26-77028-ИП.pdf"
}
```

---


# 14A. Обязательный профиль RUSSIAN-FIRST

Около 90% реальных пользовательских файлов предполагаются русскоязычными. Поэтому русский язык, кириллица и старые русские кодировки являются не дополнительной локализацией, а **основным профилем обработки**.

## 14A.1. Внутреннее представление текста

Внутри Python весь нормализованный текст должен существовать только как Unicode `str`.

Запрещено таскать между модулями «непонятные bytes» после стадии декодирования.

Каждый reader должен возвращать:

```json
{
  "text": "...",
  "text_language_hint": "ru",
  "source_encoding": "utf-8|windows-1251|koi8-r|cp866|utf-16-le|...",
  "encoding_confidence": 0.0,
  "text_quality": 0.0,
  "decoding_warnings": []
}
```

## 14A.2. Кодировки, которые необходимо поддерживать

Для plain-text, CSV, HTML и иных byte-oriented источников обязательно учитывать:

- UTF-8;
- UTF-8 with BOM;
- UTF-16 LE;
- UTF-16 BE;
- Windows-1251 / CP1251;
- KOI8-R;
- CP866;
- ISO-8859-5.

Порядок определения:

1. BOM;
2. явная encoding declaration в формате файла;
3. строгая попытка UTF-8;
4. `charset-normalizer`;
5. сравнение нескольких вероятных русских legacy-кодировок;
6. проверка качества получившегося русского текста;
7. при недостаточной уверенности — `ENCODING_UNCERTAIN`.

Запрещено молча использовать:

```python
errors="ignore"
```

при декодировании пользовательского текста.

Потеря байтов или символов должна быть видимой ошибкой или предупреждением.

## 14A.3. Mojibake / «кракозябры»

Добавить `TextQualityValidator`.

Он должен обнаруживать признаки ошибочной декодировки, например:

- большое число `�` (`U+FFFD`);
- подозрительную долю control characters;
- последовательности, характерные для повторно/неверно декодированного UTF-8;
- отсутствие разумных русских слов при высокой доле псевдокириллицы;
- аномально высокий уровень нечитаемых символов.

Автоматическая «починка кодировки» допускается только если преобразование:

- однозначно;
- обратимо;
- улучшает text-quality score выше заданного порога.

Иначе сохранить исходное декодирование как диагностические данные и поставить:

```text
ENCODING_UNCERTAIN
```

## 14A.4. Unicode normalization

Для текста и имён использовать Unicode normalization **NFC**:

```python
unicodedata.normalize("NFC", value)
```

Не применять NFKC ко всему документу без необходимости.

Не заменять глобально:

```text
ё → е
```

Оригинальный текст и оригинальные ФИО должны сохраняться.

Для поиска и сопоставления допускается отдельный comparison key, в котором `е/ё` считаются эквивалентными, но display value остаётся исходным.

## 14A.5. Русские имена файлов

Все пути и filename внутри приложения должны передаваться как Unicode `str` / `pathlib.Path`.

Не выполнять ручное:

```python
path.encode(...)
path.decode(...)
```

для Windows paths.

Тесты должны обязательно содержать:

```text
Договор займа №17 от 18 августа 2026 года.docx
Постановление Иванова И.И..pdf
Фотографии с телефона — август 2026\IMG_0012.HEIC
ООО «Альфа» — переписка.eml
ёжик.txt
№ 652102-26-77028-ИП.pdf
```

## 14A.6. Служебные файлы приложения

Чтобы журналы и manifest гарантированно читались на русском:

### JSON

Писать UTF-8:

```python
json.dump(data, file, ensure_ascii=False, ...)
```

Русские символы не превращать без необходимости в:

```text
\u0418\u0432\u0430\u043d\u043e\u0432
```

### Markdown

UTF-8.

### Человекочитаемые TXT/LOG

По умолчанию UTF-8.

Допускается настройка `utf-8-sig` для максимальной совместимости с Windows-программами, которые лучше распознают UTF-8 по BOM.

В начале каждого log можно явно указывать:

```text
Encoding: UTF-8
Language profile: ru-RU
```

## 14A.7. Русский язык интерфейса

Язык GUI по умолчанию:

```text
ru-RU
```

Все сообщения об ошибках должны иметь понятное русское описание, даже если внутренний machine-code остаётся английским:

```text
ENCODING_UNCERTAIN
Не удалось надёжно определить кодировку текста.
```

## 14A.8. Русский язык локальной LLM

Русский является основным языком задачи.

Prompt локальной модели должен быть на русском либо двуязычным, но инструкции по извлечению русских юридических реквизитов должны быть явно сформулированы на русском.

LLM должна получать русский текст **в Unicode без предварительной транслитерации**.

Запрещено переводить документ на английский перед классификацией.

Canonical output для русскоязычного документа должен оставаться русскоязычным:

```json
{
  "document_type": "Постановление судебного пристава",
  "subject": "исполнительное производство"
}
```

а не:

```json
{
  "document_type": "Bailiff order"
}
```

## 14A.9. Русские даты

Deterministic date extractor должен понимать как минимум:

```text
18.08.2026
18.08.26
18 августа 2026
18 августа 2026 г.
18 августа 2026 года
«18» августа 2026 г.
```

Поддерживать русские названия месяцев и распространённые сокращения.

Двузначный год не интерпретировать без явно заданной безопасной политики.

## 14A.10. ФИО

Extractor должен учитывать:

```text
Иванов Иван Иванович
Иванов И.И.
И.И. Иванов
Иванов И. И.
```

а также то, что ФИО могут встречаться в разных падежах.

Автоматическая морфологическая нормализация не должна менять отображаемое имя без evidence.

## 14A.11. Смешанная кириллица/латиница

Документы могут содержать:

- русские ФИО;
- латинские e-mail;
- номера автомобилей;
- VIN;
- IBAN/SWIFT;
- URL;
- латинские названия компаний;
- английские вложения.

Поэтому `rus+eng` является базовым OCR-профилем.

Не заменять автоматически латинские и кириллические look-alike символы:

```text
A/А
B/В
C/С
E/Е
H/Н
K/К
M/М
O/О
P/Р
T/Т
X/Х
```

При подозрении можно создать warning:

```text
MIXED_ALPHABET_SUSPECTED
```

но исходное значение сохраняется.

---

# 15. PDF

Использовать **pypdf**:

- https://pypdf.readthedocs.io/
- https://pypdf.readthedocs.io/en/latest/user/extract-text.html

Задачи:

- читать PDF read-only;
- page count;
- text layer;
- metadata;
- encrypted/password state.

Image-only PDF не считать пустым до OCR.

Для рендеринга отдельных страниц использовать **pypdfium2**:

- https://pypdfium2.readthedocs.io/en/stable/
- https://pypdfium2.readthedocs.io/en/stable/readme.html

Не рендерить весь огромный PDF без необходимости.


## 15.1. Контроль качества русского text layer

Наличие непустого результата `extract_text()` ещё не означает, что русский текст извлечён корректно.

Для каждой выбранной PDF-страницы считать `text_quality`.

Признаки плохого extraction:

- текст пустой или почти пустой;
- высокая доля `U+FFFD`;
- большое количество control/gibberish characters;
- русские слова визуально присутствуют на странице, но extraction содержит нечитаемые последовательности;
- mapping шрифта не позволяет получить осмысленный Unicode;
- текст существенно хуже OCR-версии той же страницы.

Если text-layer существует, но `text_quality < threshold`, выполнить локальный OCR рендера страницы и сравнить результаты.

Предпочесть OCR-текст, если его quality score существенно выше.

Зафиксировать:

```text
PDF_TEXT_LAYER_LOW_QUALITY
PDF_OCR_FALLBACK_USED
```

Не считать такой PDF `EMPTY_DOCUMENT`.


---

# 16. OCR

Локальный Tesseract OCR.

Официальные источники:

- https://github.com/tesseract-ocr/tesseract
- https://tesseract-ocr.github.io/tessdoc/
- https://tesseract-ocr.github.io/tessdoc/Installation.html
- https://tesseract-ocr.github.io/tessdoc/Data-Files.html

Минимально поставлять:

```text
rus.traineddata
eng.traineddata
osd.traineddata
```

Базовый язык OCR:

```text
rus+eng
```

Для portable CPU-профиля предпочтительно начать с официального `tessdata_fast`.
Опционально предусмотреть переключение на `tessdata_best` для сложных сканов, если пользователь готов пожертвовать скоростью.

OCR использовать только если:

- PDF не имеет достаточного text layer;
- это изображение документа;
- OCR включён;
- reader считает OCR полезным.

Настройки:

```json
{
  "ocr_enabled": true,
  "ocr_languages": ["rus", "eng"],
  "ocr_pdf_max_pages": 12,
  "ocr_first_pages": 5,
  "ocr_last_pages": 3
}
```

---

# 17. DOCX

Использовать `python-docx`:

- https://python-docx.readthedocs.io/

Извлекать:

- paragraphs;
- tables;
- core properties;
- headers/footers при возможности;
- title/author/created/modified metadata.

Ничего не сохранять обратно.

---

# 18. XLSX / XLSM

Использовать `openpyxl`:

- https://openpyxl.readthedocs.io/

Открывать read-only.

Не выполнять макросы.

Извлекать:

- имена листов;
- ограниченный набор непустых ячеек;
- заголовки таблиц;
- document properties;
- даты/организации/номера.

Не отправлять гигантскую книгу целиком в LLM.

---

# 19. XLS

Использовать `xlrd` только для legacy `.xls`:

- https://xlrd.readthedocs.io/en/stable/

---

# 20. PPTX

Использовать `python-pptx`:

- https://python-pptx.readthedocs.io/

Извлекать:

- slide count;
- textual shapes;
- titles;
- core properties;
- notes, если надёжно доступны.

---

# 21. OLE / legacy Office

Использовать `olefile`:

- https://olefile.readthedocs.io/en/stable/

Назначение — распознавание и metadata legacy `.doc/.ppt/.xls/.msg` и других OLE2 контейнеров.

Если full-text extraction ненадёжен:

```text
PARTIAL_SUPPORT_LEGACY_OFFICE
```

---

# 22. TXT / CSV / LOG / MD

Для кодировок использовать `charset-normalizer`:

- https://charset-normalizer.readthedocs.io/en/stable/

Порядок:

1. BOM: UTF-8-SIG / UTF-16 LE / UTF-16 BE;
2. явная declaration кодировки, если формат её содержит;
3. строгий UTF-8;
4. `charset-normalizer`;
5. проверка кандидатов Windows-1251 / KOI8-R / CP866 / ISO-8859-5;
6. `TextQualityValidator`;
7. иначе `ENCODING_UNCERTAIN`.

Не использовать `errors="ignore"`.

Для CSV учитывать, что русский Excel/старые учётные системы часто дают legacy-encoded text; delimiter detection и encoding detection выполнять раздельно.

Ограничивать объём читаемого текста.

---

# 23. HTML

Использовать Beautiful Soup 4:

- https://www.crummy.com/software/BeautifulSoup/bs4/doc/

Извлекать:

- `<title>`;
- visible text;
- headings;
- meta tags.

Не исполнять JavaScript.

Не загружать внешние ресурсы и не переходить по ссылкам.


При разборе HTML учитывать:

1. BOM;
2. HTTP-equivalent/meta charset внутри самого файла;
3. encoding, определённую Beautiful Soup/UnicodeDammit;
4. общий Russian encoding pipeline как fallback.

Сохранять detected/original encoding в analysis metadata.


---

# 24. XML / KML / GPX

Для недоверенного XML использовать `defusedxml`:

- https://github.com/tiran/defusedxml

Запретить external entities и network references.

Для GPX извлекать:

- start/end time;
- число точек;
- приблизительную длину;
- start/end coordinate.

Для KML — name, placemarks, coordinates, timestamps.

---

# 25. JSON

Стандартный `json`.

Ограничивать размер и глубину анализа.

Для больших JSON читать структуру и релевантные фрагменты, а не сериализовать всё в prompt.

# 26. Изображения

## Pillow

- https://pillow.readthedocs.io/en/stable/
- https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html

Использовать только для чтения, preview и OCR preprocessing.

Не пересохранять исходник.

## HEIC / HEIF / AVIF

Использовать `pillow-heif`:

- https://pillow-heif.readthedocs.io/en/stable/
- https://pillow-heif.readthedocs.io/en/stable/pillow-plugin.html

## ExifTool

Главный metadata backend для фото и значительной части media:

- https://exiftool.org/
- https://exiftool.org/exiftool_pod2.html

Только read operations.

Рекомендуемый вызов:

```text
exiftool.exe -json -G -n <file>
```

Извлекать:

- DateTimeOriginal;
- CreateDate;
- ModifyDate;
- Make;
- Model;
- GPSLatitude;
- GPSLongitude;
- ImageWidth;
- ImageHeight;
- Orientation;
- Software;
- FileType;
- MIMEType.

---

# 27. Именование фото

Стратегия metadata-first.

Пример:

```text
IMG_7834.HEIC
```

может стать:

```text
2026-08-03_18-42-17__iPhone-16-Pro__IMG-7834.heic
```

При GPS:

```text
2026-08-03_18-42-17__GPS-55.7558_37.6173__IMG-7834.heic
```

Не выполнять online reverse geocoding.

Если фото определено как изображение документа и OCR надёжен:

```text
2026-06-18__Фото-документа__Договор__ООО-Альфа__IMG-7834.jpg
```

Обычной фотографии нельзя придумывать сюжет посредством text-only LLM.

---

# 28. Видео

Использовать `ffprobe` из FFmpeg:

- https://ffmpeg.org/ffprobe.html
- https://ffmpeg.org/documentation.html

Вызывать локальный:

```text
.\runtime\ffmpeg\ffprobe.exe
```

Получать JSON.

Извлекать:

- duration;
- creation_time;
- codec;
- width/height;
- frame rate;
- tags;
- location/GPS;
- device metadata.

Пример:

```text
VID_3871.MOV
→
2026-08-12_17-48-22__iPhone__01m42s__VID-3871.mov
```

Видео не перекодировать.

---

# 29. Аудио

Использовать `mutagen`:

- https://mutagen.readthedocs.io/

ffprobe — fallback.

Извлекать:

- artist;
- title;
- album;
- date;
- duration;
- bitrate;
- tags.

Для диктофонной записи:

```text
2026-08-17_13-22-41__Аудиозапись__17m32s.m4a
```

Whisper не входит в обязательный MVP.

---

# 30. EML

Использовать стандартный Python `email`:

- https://docs.python.org/3/library/email.html

Извлекать:

- Date;
- From;
- To;
- Cc;
- Subject;
- Message-ID;
- основной текст;
- filenames вложений.

Не анализировать attachment contents без отдельной настройки.

Пример:

```text
2026-05-14__Email__Иванов--Петров__проект-договора.eml
```

---

# 31. MSG

Использовать `extract-msg`:

- https://msg-extractor.readthedocs.io/

Извлекать sender, recipients, subject, date, body и attachment names.

Ничего не пересохранять.

---

# 32. Архивы

Архивы по умолчанию **не распаковывать**.

ZIP/TAR/GZ — standard library Python.

Для 7Z/RAR можно bundled 7-Zip CLI:

- https://www.7-zip.org/
- https://www.7-zip.org/download.html
- https://www.7-zip.org/faq.html

Только listing/test commands.

Пример:

```text
archive17.zip
→
2026-04-12__Архив__договоры-ООО-Альфа__37-файлов.zip
```

если это можно установить по списку содержимого с высокой уверенностью.

---

# 33. Локальная LLM

## Engine

Использовать `llama.cpp`:

- https://github.com/ggml-org/llama.cpp

Предпочтительно вызывать локальный `llama-cli.exe` через `subprocess`.

Не использовать `llama-server`.

Не использовать HTTP API даже на localhost, если CLI достаточно.

Не использовать `-hf` и другие механизмы загрузки моделей.

Путь:

```text
.\models\document-model.gguf
```

## Модель

Для MVP — проверенная GGUF text model класса примерно 4B.

Рекомендуемый старт:

**Qwen3-4B-GGUF**

- https://huggingface.co/Qwen/Qwen3-4B-GGUF

Код не должен зависеть от названия Qwen.

Модель должна заменяться через config.

Целевой диапазон — примерно 1B–8B совместимых GGUF models.

---

# 34. Роль LLM

LLM не должна выполнять всю работу.

До LLM Python должен извлечь:

- даты;
- номера документов;
- номера дел;
- номера исполнительных производств;
- номера договоров;
- ИНН;
- ОГРН;
- суммы;
- вероятные ФИО;
- организации;
- заголовки;
- юридические маркеры.

LLM получает компактный контекст и разрешает неоднозначность.

---

# 35. Context Builder

Нельзя отправлять даже локальной модели весь огромный документ без необходимости.

Собирать:

- filename;
- detected type;
- metadata;
- заголовок;
- первые содержательные абзацы;
- первую страницу;
- последние/резолютивные фрагменты для судебных актов;
- snippets вокруг номеров;
- snippets вокруг ФИО;
- snippets вокруг дат;
- deterministic candidates.

Пример:

```text
FILE:
12345.pdf

DETECTED TITLE:
ПОСТАНОВЛЕНИЕ

DATE CANDIDATES:
27.07.2026 [header]
15.03.2025 [body]
18.04.2025 [body]

NUMBER CANDIDATES:
859189755/7728
652102/26/77028-ИП

PERSON CANDIDATES:
Иванов Иван Иванович
Петров Сергей Андреевич

ORG CANDIDATES:
Алтуфьевский ОСП

TEXT_HEAD:
...

TEXT_TAIL:
...
```

---

# 36. Structured AI output

Только JSON.

Пример:

```json
{
  "document_type": {
    "value": "Постановление судебного пристава",
    "confidence": 0.98,
    "evidence": "ПОСТАНОВЛЕНИЕ"
  },
  "document_date": {
    "value": "2026-07-27",
    "confidence": 0.99,
    "evidence": "27 июля 2026 г."
  },
  "document_number": {
    "value": "859189755/7728",
    "confidence": 0.98,
    "evidence": "№ 859189755/7728"
  },
  "main_persons": [],
  "main_organizations": [],
  "subject": {
    "value": "исполнительное производство",
    "confidence": 0.92,
    "evidence": "..."
  }
}
```

Парсер обязан:

- валидировать JSON;
- проверять типы;
- отбрасывать неожиданные поля;
- проверять evidence;
- отбрасывать вымышленные значения.

---

# 37. Anti-hallucination

**LLM не является источником фактов.**

Для каждого значения, которое попадёт в filename, должно существовать:

- regex evidence; или
- metadata evidence; или
- text-span evidence; или
- иной проверяемый structured source.

Если модель вернула дату, которой нет в INPUT, значение отклонить.

Неизвестное → `null`.

---

# 38. System prompt локальной модели

```text
You are a local document metadata classifier.

You do not have permission to invent information.
Use only facts explicitly present in INPUT.
If a value is uncertain or absent, return null.

Your task is not to summarize the whole document.
Select only metadata useful for identifying the file:
- document type
- document date
- document number
- major persons/parties
- major organizations
- case/contract identifiers
- short subject

For every non-null value provide evidence from INPUT.
Return valid JSON only.
```

---

# 39. Юридические типы документов

Создать расширяемый `document_types.json` минимум с типами:

- Договор
- Дополнительное соглашение
- Акт
- Доверенность
- Претензия
- Исковое заявление
- Отзыв
- Возражения
- Жалоба
- Апелляционная жалоба
- Кассационная жалоба
- Ходатайство
- Заявление
- Ответ
- Запрос
- Уведомление
- Письмо
- Справка
- Постановление
- Постановление судебного пристава
- Постановление следователя
- Постановление дознавателя
- Определение суда
- Решение суда
- Приговор
- Судебный приказ
- Протокол судебного заседания
- Протокол допроса
- Протокол осмотра
- Протокол обыска
- Протокол выемки
- Обвинительное заключение
- Обвинительный акт
- Заключение эксперта
- Исполнительный лист
- Платёжное поручение
- Счёт
- Счёт-фактура
- Акт сверки
- Выписка
- Банковская выписка
- Расписка
- Товарная накладная
- Служебная записка
- Приказ
- Распоряжение.

Каждый тип:

```json
{
  "canonical_name": "...",
  "aliases": [],
  "markers": [],
  "priority": 0,
  "filename_abbreviation": "..."
}
```

---

# 40. Deterministic extractors

Отдельные модули:

```text
extractors/
    dates.py
    persons.py
    organizations.py
    case_numbers.py
    document_numbers.py
    contracts.py
    tax_ids.py
    amounts.py
    court_markers.py
    legal_document_types.py
```

Номера нужно типизировать, а не складывать в одно поле.

Дата-кандидат:

```json
{
  "value": "2026-07-27",
  "position": 182,
  "context": "Постановление от 27 июля 2026 года",
  "source": "text",
  "role_guess": "document_date",
  "confidence": 0.96
}
```

---

# 41. Дата документа

Приоритет:

1. специализированная metadata, если надёжна;
2. дата рядом с заголовком;
3. дата рядом с номером документа;
4. дата в верхней части первой страницы;
5. semantic selection локальной LLM;
6. filesystem timestamp — только fallback и с отдельной маркировкой.

Для фото:

1. EXIF `DateTimeOriginal`;
2. media `CreateDate`;
3. filesystem timestamp — только fallback.

Нельзя выдавать filesystem mtime за установленную дату документа.

---

# 42. Основные лица

Не помещать в filename всех людей.

Роли:

- заявитель;
- истец;
- ответчик;
- обвиняемый;
- подозреваемый;
- свидетель;
- потерпевший;
- должник;
- взыскатель;
- судья;
- следователь;
- пристав;
- автор;
- адресат;
- подписант;
- сторона договора;
- представитель.

В filename максимум 1–3 ключевых лица.

---

# 43. Организации

Полное значение хранить в manifest.

Для filename нормализовать:

```text
Общество с ограниченной ответственностью "Альфа"
→
ООО-Альфа
```

---

# 44. Filename grammar

Базовый формат:

```text
DATE__TYPE__SUBJECT__ENTITIES__IDENTIFIER.ext
```

Не все сегменты обязательны.

Примеры:

```text
2026-07-27__Постановление-СПИ__Иванов__652102-26-77028-ИП.pdf
2025-11-14__Договор-займа__ООО-Альфа--Иванов__№17.docx
2026-03-05__Протокол-допроса__Петров-AA__дело-Куштова.pdf
2026-08-03_18-42-17__iPhone-16-Pro__IMG-7834.heic
2026-05-14__Email__Иванов--Петров__проект-договора.eml
```

---

# 45. Filename sanitizer

Обязательно:

- сохранить extension;
- удалить Windows forbidden chars `< > : " / \ | ? *`;
- удалить control chars;
- нормализовать whitespace;
- убрать trailing space/dot;
- исключить `.` и `..`;
- исключить reserved names `CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`;
- ограничить длину.

Рекомендованный предел:

```json
"max_filename_length": 160
```

При сокращении сначала убирать второстепенные semantic segments, а не важные identifiers.

---

# 46. Confidence

Не использовать только self-reported confidence LLM.

Итог формировать из:

- type confidence;
- date confidence;
- identifier confidence;
- entity confidence;
- subject confidence;
- reliability источника.

Рекомендуемый APPLY threshold:

```json
"auto_rename_confidence": 0.88
```

Ниже:

```text
SKIPPED_LOW_CONFIDENCE
```

Proposal всё равно показывается пользователю.

---

# 47. Коллизии

Никогда не overwrite.

Если имя занято:

```text
имя.pdf
имя__02.pdf
имя__03.pdf
```

Коллизию проверить повторно непосредственно перед rename.

---

# 48. Транзакция rename

Перед каждым rename:

1. source exists;
2. target отсутствует;
3. получить size;
4. SHA-256 before;
5. проверить, что source не изменился после preview;
6. rename внутри той же директории;
7. target exists;
8. SHA-256 after;
9. hashes equal;
10. записать manifest.

Если hash не совпал:

```text
CRITICAL_HASH_MISMATCH
```

Не продолжать автоматическую серию без заранее определённой safety policy.

---

# 49. TOCTOU protection

`rename_plan.json` должен хранить:

- SHA-256;
- size;
- mtime.

Перед APPLY проверить повторно.

Изменилось:

```text
SOURCE_CHANGED_AFTER_PREVIEW
```

Файл пропустить.

---

# 50. Логи

На каждый запуск:

```text
logs\rename_log_YYYY-MM-DD_HHMMSS.txt
```

Пример:

```text
[16:03:11] FILE 37/184

OLD:
D:\Case\IMG_003421.pdf

PROPOSED:
D:\Case\2026-07-27__Постановление-СПИ__Иванов__652102-26-77028-ИП.pdf

TYPE:
Постановление судебного пристава

DATE:
2026-07-27

CONFIDENCE:
0.94

SHA256 BEFORE:
...

SHA256 AFTER:
...

RESULT:
RENAMED
```

---

# 51. Manifest

Создавать:

```text
manifests\rename_manifest_YYYY-MM-DD_HHMMSS.json
```

Хранить:

- session ID;
- app version;
- config fingerprint;
- strict local mode;
- model ID/hash;
- original/new path;
- original/new filename;
- SHA-256;
- size;
- mtime;
- detected type;
- analysis result;
- evidence;
- confidence;
- timestamp;
- status.

---

# 52. Undo

```bash
DocRenamer.exe --undo manifest.json
```

Перед undo:

- current file exists;
- SHA-256 совпадает;
- старое имя свободно;
- extension ожидаем;
- никакого overwrite.

Конфликт:

```text
UNDO_TARGET_EXISTS
```

Undo также пишет собственный лог.

---

# 53. Ошибки

Единый словарь кодов:

```text
OK
RENAMED
SKIPPED
SKIPPED_LOW_CONFIDENCE
UNSUPPORTED_FORMAT
PARTIAL_SUPPORT
READ_ERROR
ACCESS_DENIED
FILE_LOCKED
PASSWORD_PROTECTED
EMPTY_DOCUMENT
OCR_FAILED
OCR_ENGINE_NOT_FOUND
MODEL_NOT_FOUND
MODEL_FAILED
INVALID_AI_JSON
AI_EVIDENCE_REJECTED
EXTENSION_MISMATCH
NAME_COLLISION_RESOLVED
SOURCE_CHANGED_AFTER_PREVIEW
HASH_ERROR
CRITICAL_HASH_MISMATCH
UNDO_TARGET_EXISTS
PATH_TOO_LONG
UNSAFE_PATH
```

Одна ошибка не останавливает весь batch, кроме специально определённых критических safety failures.

# 54. Недоверенный вход и parser safety

Любой пользовательский файл считать потенциально повреждённым или специально сформированным.

Требования:

- не выполнять macros;
- не выполнять JavaScript;
- не запускать вложения;
- XML читать безопасным parser;
- ограничивать decompression;
- не распаковывать архивы автоматически;
- ограничивать максимальный объём full-text parsing;
- ограничивать OCR pages;
- ставить subprocess timeout;
- корректно закрывать file handles.

---

# 55. Безопасный subprocess

Для `llama-cli`, `tesseract`, `exiftool`, `ffprobe`, `7z` использовать только список аргументов:

```python
subprocess.run(
    args,
    shell=False,
    capture_output=True,
    timeout=timeout,
    check=False,
)
```

Не строить shell command путём строковой конкатенации.

---

# 56. Config

Пример `config/config.json`:

```json
{
  "strict_local_mode": true,
  "language": "ru-RU",
  "internal_text_encoding": "utf-8",
  "human_log_encoding": "utf-8",
  "unicode_normalization": "NFC",
  "recursive": true,
  "dry_run_default": true,
  "forensic_mode": false,

  "ai": {
    "enabled": true,
    "engine": "llama_cpp_cli",
    "model_path": "./models/document-model.gguf",
    "context_size": 8192,
    "max_output_tokens": 900,
    "temperature": 0.1,
    "timeout_seconds": 120
  },

  "ocr": {
    "enabled": true,
    "languages": ["rus", "eng"],
    "pdf_max_pages": 12,
    "first_pages": 5,
    "last_pages": 3,
    "timeout_seconds": 60
  },

  "naming": {
    "max_filename_length": 160,
    "max_persons_in_filename": 3,
    "max_organizations_in_filename": 2,
    "confidence_threshold": 0.88,
    "separator": "__"
  },

  "media": {
    "use_exif": true,
    "use_ffprobe": true,
    "include_device": true,
    "include_gps_coordinates": false
  },

  "archives": {
    "inspect_only": true,
    "max_entries_to_analyze": 500
  },

  "limits": {
    "max_text_chars_for_ai": 24000,
    "max_plaintext_file_mb": 50,
    "max_single_file_mb": 4096
  }
}
```

---

# 57. GUI settings

Минимум:

```text
[✓] Рекурсивно
[✓] Использовать локальный ИИ
[✓] OCR для сканов
[✓] Обрабатывать фото
[✓] Обрабатывать видео/аудио
[✓] Анализировать архивы без распаковки

Порог уверенности: [ 0.88 ]
Максимальная длина имени: [ 160 ]

Модель:
.\models\document-model.gguf

OCR:
rus + eng

[ Сохранить ]
```

---

# 58. Структура исходного проекта

```text
docrenamer/
│
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── AGENTS.md
├── THIRD_PARTY_NOTICES.md
├── DocRenamer.spec
├── build_windows.bat
│
├── src/
│   └── docrenamer/
│       ├── __init__.py
│       ├── app.py
│       ├── cli.py
│       ├── gui.py
│       ├── config.py
│       ├── paths.py
│       ├── scanner.py
│       ├── types.py
│       ├── file_signature.py
│       │
│       ├── readers/
│       │   ├── base.py
│       │   ├── pdf_reader.py
│       │   ├── docx_reader.py
│       │   ├── xlsx_reader.py
│       │   ├── xls_reader.py
│       │   ├── pptx_reader.py
│       │   ├── text_reader.py
│       │   ├── html_reader.py
│       │   ├── xml_reader.py
│       │   ├── json_reader.py
│       │   ├── image_reader.py
│       │   ├── media_reader.py
│       │   ├── eml_reader.py
│       │   ├── msg_reader.py
│       │   ├── archive_reader.py
│       │   └── legacy_ole_reader.py
│       │
│       ├── extractors/
│       │   ├── dates.py
│       │   ├── persons.py
│       │   ├── organizations.py
│       │   ├── identifiers.py
│       │   ├── amounts.py
│       │   └── document_types.py
│       │
│       ├── ai/
│       │   ├── base.py
│       │   ├── llama_cli.py
│       │   ├── context_builder.py
│       │   ├── prompt.py
│       │   └── validator.py
│       │
│       ├── ocr/
│       │   ├── engine.py
│       │   └── page_selector.py
│       │
│       ├── metadata/
│       │   ├── exiftool.py
│       │   └── ffprobe.py
│       │
│       ├── naming/
│       │   ├── builder.py
│       │   ├── sanitizer.py
│       │   └── collision.py
│       │
│       ├── operations/
│       │   ├── planner.py
│       │   ├── rename.py
│       │   ├── undo.py
│       │   ├── hashing.py
│       │   └── safety.py
│       │
│       ├── logging/
│       │   ├── text_log.py
│       │   └── manifest.py
│       │
│       └── security/
│           ├── offline_guard.py
│           ├── limits.py
│           └── temp_cleanup.py
│
└── tests/
    ├── fixtures/
    ├── unit/
    ├── integration/
    └── safety/
```

---

# 59. Python dependencies

Production baseline:

```text
pypdf
pypdfium2
python-docx
openpyxl
xlrd
python-pptx
Pillow
pillow-heif
beautifulsoup4
charset-normalizer
defusedxml
olefile
extract-msg
mutagen
```

Build:

```text
pyinstaller
```

Development:

```text
pytest
pytest-timeout
ruff
mypy
```

Не добавлять dependency, если задача разумно решается standard library.

---

# 60. Bundled runtime components

## Обязательные

### llama.cpp

- https://github.com/ggml-org/llama.cpp

### Qwen3-4B-GGUF — стартовая модель

- https://huggingface.co/Qwen/Qwen3-4B-GGUF

### Tesseract OCR

- https://github.com/tesseract-ocr/tesseract
- https://tesseract-ocr.github.io/tessdoc/Data-Files.html

### ExifTool

- https://exiftool.org/

### FFmpeg / ffprobe

- https://ffmpeg.org/

## Опционально для archive inspection

### 7-Zip

- https://www.7-zip.org/

---

# 61. Offline Guard

Создать `security/offline_guard.py` и архитектурно исключить сетевую функциональность.

Production code не должен использовать:

- requests;
- httpx;
- aiohttp;
- urllib.request;
- websocket clients;
- cloud SDK.

Правила:

1. модель открывается только локальным path;
2. `llama-server` не используется;
3. automatic download отсутствует;
4. CI/source audit проверяет network imports;
5. integration test проходит без сети.

Не пытаться имитировать «офлайн» через обещание в UI. Это должно быть свойством архитектуры.

---

# 62. Временные данные

OCR images, prompt contexts и промежуточные JSON:

- по возможности в RAM;
- иначе `runtime_temp/<session-id>/`;
- удалять после завершения;
- очищать stale sessions на следующем старте;
- не хранить в OneDrive;
- не использовать `%APPDATA%` для содержания документов;
- не оставлять OCR-текст на чужом компьютере без необходимости.

---

# 63. Source evidence

Каждое существенное поле:

```json
{
  "value": "...",
  "source": "text|metadata|regex|llm",
  "evidence": "...",
  "confidence": 0.0
}
```

Name Builder использует только accepted values.

---

# 64. Performance strategy

Порядок от дешёвого к дорогому:

```text
metadata
→ deterministic regex/rules
→ document reader
→ OCR if needed
→ local LLM last
```

Не запускать LLM для файла, если имя можно сформировать с высокой уверенностью без неё.

Кэш в рамках сессии:

```text
SHA-256 + analyzer_version + config_hash
```

Не создавать скрытый постоянный индекс пользовательских документов без явной функции.

---

# 65. Фото без EXIF

Если есть только filesystem timestamp, не придумывать событие.

Допустимо:

```text
2026-08-18_14-22-03__Фото__IMG-1822.jpg
```

только с внутренней отметкой:

```text
DATE_SOURCE=filesystem_mtime
```

В config должна быть возможность запретить filesystem date fallback.

---

# 66. Дубликаты

В MVP дубликаты не удалять.

По SHA-256 можно определить:

```text
DUPLICATE_CONTENT
```

UI:

```text
Найдено 4 идентичных файла — никаких действий с дубликатами не выполнено.
```

---

# 67. Sidecar files

Учитывать:

- AAE;
- XMP;
- THM.

Не переименовывать независимо по умолчанию.

Если обнаружена связанная пара:

```text
IMG_1234.HEIC
IMG_1234.AAE
```

MVP должен пометить:

```text
SIDECAR_DETECTED — manual review
```

Позже можно добавить безопасный group rename.

---

# 68. iPhone Live Photos

Возможная пара:

```text
IMG_1234.HEIC
IMG_1234.MOV
```

Нужно обнаруживать общий basename и потенциальную связанность.

В первой версии либо:

- пропускать автоматический rename пары и показывать review;
- либо реализовать group transaction с одинаковым semantic stem.

Если один rename группы невозможен — не применять группу частично.

---

# 69. Filesystem restrictions

Перед APPLY:

- проверить write permission каталога;
- source/target должны быть в одной директории;
- проверить target collision;
- проверить path length;
- не перемещать между volumes.

---

# 70. Windows build

`build_windows.bat` должен:

1. создать/использовать build venv;
2. установить pinned dependencies;
3. запустить tests;
4. запустить PyInstaller;
5. скопировать runtime binaries;
6. скопировать config;
7. скопировать model или валидированный model package;
8. сформировать third-party notices;
9. получить `dist\DocRenamer\`.

Финальный executable:

```text
dist\DocRenamer\DocRenamer.exe
```

---

# 71. Dependency pinning

Для release все dependency versions должны быть pinned.

Не оставлять production build на произвольных `>=` constraints.

Перед upgrade:

- unit tests;
- integration tests;
- offline tests;
- PyInstaller build;
- sample corpus regression.

---

# 72. Third-party licenses

Создать:

```text
THIRD_PARTY_NOTICES.md
LICENSES/
```

Проверить лицензии:

- llama.cpp;
- конкретной GGUF-модели;
- Tesseract;
- ExifTool;
- FFmpeg;
- 7-Zip;
- Python packages.

Не считать, что open source автоматически означает отсутствие условий распространения.

---

# 73. Test corpus

Использовать synthetic fixtures, а не реальные конфиденциальные материалы.

```text
pdf_text/
pdf_scan/
pdf_encrypted/
docx/
xlsx/
xls/
pptx/
txt_utf8/
txt_cp1251/
html/
xml/
json/
jpg_exif/
heic/
png_scan/
mov/
mp4/
mp3/
m4a/
eml/
msg/
zip/
7z/
gpx/
corrupted/
unicode_names/
long_names/
```

---

# 74. Автоматические тесты

Обязательные сценарии:

- PDF text;
- scan PDF;
- mixed PDF;
- encrypted PDF;
- corrupt PDF;
- DOCX;
- XLSX;
- XLS;
- PPTX;
- TXT UTF-8;
- TXT cp1251;
- HTML;
- hostile XML;
- JSON;
- JPG EXIF;
- HEIC EXIF;
- image without EXIF;
- MOV metadata;
- MP4;
- MP3 ID3;
- M4A;
- EML;
- MSG;
- ZIP;
- RAR/7Z listing;
- GPX;
- unsupported file;
- extension mismatch;
- Unicode filename;
- Windows reserved filename candidate;
- long name;
- collision;
- duplicate SHA;
- source changes after preview;
- access denied;
- file locked;
- rename failure;
- undo;
- undo collision;
- SHA before/after;
- no overwrite;
- no move;
- no content modification.

---

# 75. Offline tests

Создать отдельный suite, например:

```text
tests/safety/test_offline_runtime.py
```

Он должен доказать:

- app запускается без сети;
- text extraction работает;
- OCR работает;
- local LLM работает;
- ExifTool работает;
- ffprobe работает;
- archive listing работает;
- отсутствие модели не инициирует download;
- отсутствие OCR data не инициирует download.

---

# 76. Integrity tests

Для каждого rename test:

```text
sha256_before == sha256_after
size_before == size_after
```

Использовать binary fixtures.

---

# 77. No-overwrite

Ни один production code path не должен overwrite пользовательский файл.

Не использовать `os.replace()` для пользовательских документов.

`os.replace()` допустим только для собственных временных/manifest файлов при atomic service write.

---

# 78. GUI statuses

```text
● LOCAL ONLY
✓ Текст найден
✓ EXIF найден
○ OCR не нужен
◇ Локальный AI анализирует
✓ Имя готово
! Нужна проверка
× Не удалось прочитать
```

Без навязчивых animation.

---

# 79. Preview list

Пример:

```text
[✓] IMG_0032.pdf
    → 2026-07-27__Постановление-СПИ__Иванов__652102-26-77028-ИП.pdf
    confidence 96%

[!] scan0007.pdf
    → 2024-11-17__Договор__ООО-Альфа--Петров.pdf
    confidence 74%
    НЕ БУДЕТ ПЕРЕИМЕНОВАН АВТОМАТИЧЕСКИ
```

Пользователь может снять галку.

Можно разрешить ручное редактирование proposed filename перед APPLY.

---

# 80. Progress

Показывать:

```text
38 / 184
READ → EXTRACT → OCR → ANALYZE → NAME
```

Статистика:

```text
Найдено: 184
Готово: 38
Предлагается rename: 31
Низкая уверенность: 5
Ошибок: 2
```

---

# 81. Cancel

Кнопка `Стоп` должна остановить запуск новых задач.

Уже выполненные rename автоматически не откатывать.

Manifest должен оставаться консистентным.

---

# 82. Threading

GUI не должен зависать.

Использовать worker thread / controlled task queue.

Tkinter widgets обновлять только из UI thread.

По умолчанию:

- lightweight readers: несколько workers;
- OCR: 1–2;
- LLM: 1.

---

# 83. Recovery после сбоя

Manifest писать incrementally.

После каждого успешного rename сохранять transaction record.

После аварии на следующем старте можно показать:

```text
Обнаружена незавершённая сессия.
Переименовано 37 из 112 файлов.

[ Открыть лог ] [ Продолжить анализ ] [ Undo выполненных ]
```

---

# 84. Atomic service files

Для manifest/config:

1. write `.tmp`;
2. flush;
3. fsync, где применимо;
4. atomic replace служебного файла.

Это не относится к пользовательским документам.

---

# 85. README пользователя

Объяснить простым языком:

## Быстрый запуск

1. Запустите `DocRenamer.exe`.
2. Выберите папку.
3. Нажмите `Сканировать`.
4. Проверьте предложения.
5. Нажмите `Переименовать`.

## Гарантии

- Интернет не нужен;
- данные не отправляются наружу;
- файлы не пересохраняются;
- default — preview;
- есть журнал;
- есть undo;
- SHA-256 проверяется до/после rename.

Первый запуск рекомендовать делать на копии директории.

---

# 86. AGENTS.md для coding agent

Создать в корне:

```text
This repository contains a safety-sensitive local file renaming tool.

NON-NEGOTIABLE RULES:

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
```

---

# 87. Порядок реализации для coding AI

## Phase 1 — Architecture

Перед кодом:

- прочитать этот документ целиком;
- создать architecture note;
- определить trust boundaries;
- перечислить filesystem mutations;
- сформировать support matrix;
- составить implementation plan.

Не начинать с GUI.

## Phase 2 — Safety Core

Сначала реализовать:

- scanner;
- hashing;
- filename sanitizer;
- collision resolver;
- preview plan;
- rename transaction;
- manifest;
- undo;
- tests.

Пока без AI.

## Phase 3 — Readers

Добавлять readers по одному с тестами.

## Phase 4 — Metadata

ExifTool + ffprobe.

## Phase 5 — OCR

PDFium + Tesseract.

## Phase 6 — Deterministic extraction

Regex, dictionaries, legal markers.

## Phase 7 — Local LLM

llama.cpp + JSON + evidence validation.

## Phase 8 — GUI

Только после стабильного safety core.

## Phase 9 — Packaging

PyInstaller + runtime binaries.

## Phase 10 — Release audit

- offline test;
- integrity test;
- no-overwrite audit;
- no-delete audit;
- no-network audit;
- license audit;
- clean Windows machine test.

---

# 88. Definition of Done

MVP готов только если:

1. Работает на Windows 10/11 x64.
2. Не требует Python.
3. Запускается с USB.
4. Запускается после копирования в любую локальную папку.
5. Работает при полностью отключённом Интернете.
6. Не скачивает model.
7. Не скачивает OCR.
8. Читает основные заявленные форматы.
9. OCR работает для scan PDF.
10. HEIC/JPG metadata читается.
11. Media metadata читается.
12. Имена формируются осмысленно.
13. Есть dry-run.
14. Нет overwrite.
15. Нет delete.
16. Нет изменения содержимого.
17. SHA-256 совпадает до/после rename.
18. Есть TXT log.
19. Есть JSON manifest.
20. Undo работает.
21. Low-confidence автоматически не меняется.
22. GUI не зависает.
23. Safety tests проходят.
24. Portable distribution проверен на чистой Windows-системе.

---

# 89. Что НЕ делать в MVP

Не делать:

- облачные аккаунты;
- web UI;
- cloud sync;
- vision model для обычных фотографий;
- массовую audio transcription;
- vector DB;
- перемещение по каталогам;
- удаление duplicates;
- legacy Office conversion;
- metadata editing;
- попытку заменить Explorer.

Цель v1:

> локально понять файл настолько, насколько возможно, предложить хорошее имя и контролируемо переименовать его без изменения содержимого.

---

# 90. Версия 2

После стабильного MVP можно добавить:

- локальную vision model;
- локальный Whisper;
- локальную базу GPS → населённый пункт;
- OCR рукописей;
- полноценный sidecar/Live Photo group rename;
- локальный индекс;
- поиск;
- entity graph;
- «паспорт файла»;
- экспорт в локальную базу знаний.

Все расширения должны оставаться offline-first.

---

# 91. Финальное задание coding agent

**Не создавать демонстрационный однофайловый скрипт.**

Нужен законченный portable Windows MVP.

Результат должен включать:

```text
source code
tests
README
AGENTS.md
config example
document type dictionary
PyInstaller spec
Windows build script
third-party notices
portable runtime layout
synthetic fixtures
```

Перед завершением coding agent обязан:

```text
1. run unit tests
2. run integration tests
3. run filesystem safety tests
4. run offline tests
5. run rename/undo cycle tests
6. verify SHA-256 integrity tests
7. search source for network libraries
8. search source for delete/unlink/rmtree usage
9. search source for os.replace usage against user files
10. self-review every filesystem mutation
11. document unsupported/partial formats honestly
```

Нельзя считать задачу завершённой, если не проверена цепочка:

```text
SCAN
→ ANALYZE
→ PREVIEW
→ APPLY
→ VERIFY
→ MANIFEST
→ UNDO
```

---

# 92. Ключевой принцип качества

При конфликте между:

- «сделать название красивее»

и

- «гарантированно не ошибиться и не повредить исходник»

всегда выбирать второе.

Лучше:

```text
SKIPPED_LOW_CONFIDENCE
```

чем неправильное имя.

Лучше:

```text
UNSUPPORTED_FORMAT
```

чем попытка угадать.

Лучше оставить файл неизменным, чем выполнить непроверяемое действие.

---

# 93. Краткая карта официальных источников

## Packaging / UI

- PyInstaller — https://pyinstaller.org/
- Tkinter — https://docs.python.org/3/library/tkinter.html

## Documents

- pypdf — https://pypdf.readthedocs.io/
- pypdfium2 — https://pypdfium2.readthedocs.io/en/stable/
- python-docx — https://python-docx.readthedocs.io/
- openpyxl — https://openpyxl.readthedocs.io/
- xlrd — https://xlrd.readthedocs.io/en/stable/
- python-pptx — https://python-pptx.readthedocs.io/
- olefile — https://olefile.readthedocs.io/en/stable/
- Beautiful Soup — https://www.crummy.com/software/BeautifulSoup/bs4/doc/
- charset-normalizer — https://charset-normalizer.readthedocs.io/en/stable/
- defusedxml — https://github.com/tiran/defusedxml

## OCR / image / media

- Tesseract — https://github.com/tesseract-ocr/tesseract
- Pillow — https://pillow.readthedocs.io/en/stable/
- pillow-heif — https://pillow-heif.readthedocs.io/en/stable/
- ExifTool — https://exiftool.org/
- FFmpeg/ffprobe — https://ffmpeg.org/ffprobe.html
- Mutagen — https://mutagen.readthedocs.io/

## Email / archive

- Python email — https://docs.python.org/3/library/email.html
- extract-msg — https://msg-extractor.readthedocs.io/
- 7-Zip — https://www.7-zip.org/

## Local AI

- llama.cpp — https://github.com/ggml-org/llama.cpp
- Qwen3-4B-GGUF — https://huggingface.co/Qwen/Qwen3-4B-GGUF

---

# 94. Примечание по актуальности зависимостей

Перед началом реализации coding agent должен проверить актуальные stable releases, совместимость с выбранной версией Python и лицензии. Нельзя слепо копировать номер версии пакета из этого документа: версии должны быть зафиксированы в lock-файле уже после успешной сборки и regression tests.

При этом **архитектурные ограничения этого ТЗ не должны меняться** из-за обновления библиотек: offline-only, no-overwrite, no-delete, content integrity, preview-first и undo являются инвариантами проекта.


---

# 95. Russian-first release gate

Так как русский язык является основным рабочим языком программы, релиз запрещён, если хотя бы один из следующих тестов не пройден:

1. Русские Unicode filenames корректно сканируются, отображаются, переименовываются и восстанавливаются через Undo.
2. `SHA-256` до/после rename совпадает для файлов с кириллическими именами.
3. CP1251/KOI8-R/CP866 не превращаются молча в mojibake.
4. Некачественный русский PDF text layer не принимается за достоверный только потому, что он непустой.
5. OCR `rus+eng` работает полностью локально.
6. Локальная LLM получает и возвращает кириллицу без транслитерации и без Unicode corruption.
7. JSON manifest хранит кириллицу корректно.
8. TXT/LOG открываются как читаемый русский текст.
9. GUI корректно показывает `ё`, `№`, `«»`, длинное тире и кириллические пути.
10. Ни один encoding fallback не использует silent `errors="ignore"`.

Эти требования являются частью `Definition of Done`, а не факультативным улучшением.

