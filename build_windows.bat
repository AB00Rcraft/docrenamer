@echo off
rem ============================================================================
rem  DocRenamer Offline — сборка portable-дистрибутива для Windows (раздел 70 ТЗ)
rem
rem  Использование:
rem    build_windows.bat            portable-каталог dist\DocRenamer\  (по ТЗ)
rem    build_windows.bat onefile    дополнительно один файл DocRenamer.exe
rem
rem  Порядок шагов:
rem    1. создать/использовать сборочное окружение;
rem    2. установить зафиксированные зависимости;
rem    3. прогнать тесты;
rem    4. запустить PyInstaller;
rem    5. скопировать runtime-бинарники;
rem    6. скопировать config;
rem    7. скопировать модель;
rem    8. сформировать уведомления о лицензиях;
rem    9. получить dist\DocRenamer\.
rem ============================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set PYTHON=py -3.12
set BUILD_VENV=.venv-build
set DIST=dist\DocRenamer
set ONEFILE=0
if /i "%~1"=="onefile" set ONEFILE=1

where py >nul 2>nul
if errorlevel 1 (
    echo.
    echo Не найден Python. Установите Python 3.12 x64 с https://www.python.org/downloads/
    echo При установке отметьте «Add python.exe to PATH».
    exit /b 1
)

echo [1/9] Сборочное окружение
if not exist "%BUILD_VENV%" (
    %PYTHON% -m venv "%BUILD_VENV%" || goto :error
)
call "%BUILD_VENV%\Scripts\activate.bat" || goto :error

echo [2/9] Зависимости
python -m pip install --upgrade pip >nul || goto :error
if exist requirements.lock.txt (
    python -m pip install -r requirements.lock.txt || goto :error
) else (
    echo     ВНИМАНИЕ: requirements.lock.txt не найден, версии не зафиксированы.
    python -m pip install -r requirements-dev.txt || goto :error
)
python -m pip install -e . || goto :error

echo [3/9] Тесты
python -m pytest tests -q || goto :error
python -m docrenamer.security.offline_guard --audit src || goto :error

echo [4/9] PyInstaller
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
python -m PyInstaller DocRenamer.spec --noconfirm || goto :error
if "%ONEFILE%"=="1" (
    echo       ... дополнительно собираем один файл
    set DOCRENAMER_ONEFILE=1
    python -m PyInstaller DocRenamer.spec --noconfirm --distpath dist\onefile --workpath build\onefile || goto :error
    set DOCRENAMER_ONEFILE=
)

echo [5/9] Runtime-бинарники
if exist runtime (
    xcopy /e /i /y runtime "%DIST%\runtime" >nul || goto :error
) else (
    echo     ВНИМАНИЕ: каталог runtime\ отсутствует.
    echo     Разместите llama-cli.exe, tesseract.exe с tessdata, exiftool.exe,
    echo     ffprobe.exe и 7z.exe согласно разделу 4 ТЗ.
)

echo [6/9] Конфигурация
if not exist "%DIST%\config" mkdir "%DIST%\config"
copy /y config\config.json "%DIST%\config\" >nul || goto :error
copy /y config\document_types.json "%DIST%\config\" >nul || goto :error

echo [7/9] Модель
if not exist "%DIST%\models" mkdir "%DIST%\models"
if exist models\document-model.gguf (
    copy /y models\document-model.gguf "%DIST%\models\" >nul || goto :error
) else (
    echo     ВНИМАНИЕ: models\document-model.gguf не найдена.
    echo     Приложение запустится, но выдаст LOCAL_MODEL_NOT_FOUND.
    echo     Загрузка модели из сети не выполняется никогда.
)

echo [8/9] Лицензии
if not exist "%DIST%\LICENSES" mkdir "%DIST%\LICENSES"
if exist LICENSES xcopy /e /i /y LICENSES "%DIST%\LICENSES" >nul
copy /y THIRD_PARTY_NOTICES.md "%DIST%\" >nul
copy /y README.md "%DIST%\" >nul
for %%D in (logs manifests runtime_temp) do if not exist "%DIST%\%%D" mkdir "%DIST%\%%D"

echo [9/9] Проверка результата
if not exist "%DIST%\DocRenamer.exe" goto :error
echo.
echo Готово: %DIST%\DocRenamer.exe
if "%ONEFILE%"=="1" echo Один файл: dist\onefile\DocRenamer.exe
echo Проверьте дистрибутив на чистой машине Windows без Python и без сети.
goto :eof

:error
echo.
echo СБОРКА НЕ ВЫПОЛНЕНА. Код ошибки: %errorlevel%
exit /b 1
