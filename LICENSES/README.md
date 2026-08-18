# Тексты лицензий сторонних компонентов

Каталог заполняется на этапе сборки дистрибутива (`build_windows.bat`, шаг 8).

Для каждого компонента из `THIRD_PARTY_NOTICES.md` сюда помещается файл с полным
текстом лицензии, например:

```text
LICENSES/
├── llama.cpp-MIT.txt
├── qwen3-4b-gguf-LICENSE.txt
├── tesseract-Apache-2.0.txt
├── exiftool-Artistic.txt
├── ffmpeg-LGPL-2.1.txt
├── 7zip-LGPL-2.1.txt
├── pypdf-BSD-3-Clause.txt
├── extract-msg-GPL-3.0.txt
└── mutagen-GPL-2.0.txt
```

Выпуск дистрибутива без заполненного каталога не допускается.
