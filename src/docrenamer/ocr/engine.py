"""Локальный OCR через Tesseract (раздел 16 ТЗ).

Движок и языковые данные поставляются внутри приложения. Если их нет,
фиксируется ``OCR_ENGINE_NOT_FOUND`` — попыток загрузки из сети не делается.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docrenamer.config import Config
from docrenamer.ocr.page_selector import select_pages
from docrenamer.paths import AppPaths
from docrenamer.security.subprocess_safe import run_tool
from docrenamer.security.temp_cleanup import SessionTemp
from docrenamer.types import Status, nfc

#: Режим сегментации страницы: 3 — полностью автоматический, без OSD.
DEFAULT_PSM = "3"


@dataclass(slots=True)
class OCROutcome:
    """Результат распознавания."""

    text: str = ""
    status: str = ""
    pages: int = 0


class TesseractEngine:
    """Обёртка над локальным ``tesseract``."""

    def __init__(
        self,
        config: Config,
        paths: AppPaths,
        *,
        temp: SessionTemp | None = None,
    ) -> None:
        self.config = config
        self.paths = paths
        self.temp = temp
        self.executable = paths.tesseract(config.allow_system_binaries)
        self._checked_languages: bool | None = None

    @property
    def available(self) -> bool:
        return self.executable is not None

    def status_if_unavailable(self) -> str:
        return "" if self.available else Status.OCR_ENGINE_NOT_FOUND.value

    # --- изображения -------------------------------------------------------

    def ocr_image(self, path: Path) -> tuple[str, str]:
        """Распознать изображение. Возвращает ``(текст, код_состояния)``."""
        if not self.available:
            return "", Status.OCR_ENGINE_NOT_FOUND.value
        return self._run(path)

    # --- PDF ---------------------------------------------------------------

    def ocr_pdf(self, path: Path, page_count: int) -> tuple[str, str]:
        """Отрендерить выбранные страницы PDF и распознать их."""
        if not self.available:
            return "", Status.OCR_ENGINE_NOT_FOUND.value
        pages = select_pages(page_count, self.config.ocr)
        if not pages:
            return "", ""
        try:
            import pypdfium2
        except ImportError:  # pragma: no cover — зависимость обязательна в сборке
            return "", Status.OCR_FAILED.value

        workdir = self._workdir()
        texts: list[str] = []
        status = ""
        document = None
        try:
            document = pypdfium2.PdfDocument(str(path))
            scale = self.config.ocr.render_dpi / 72.0
            for index in pages:
                if index >= len(document):
                    continue
                page = document[index]
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                image_path = workdir / f"page-{index + 1:04d}.png"
                image.save(image_path)
                text, page_status = self._run(image_path)
                if page_status and not status:
                    status = page_status
                if text.strip():
                    texts.append(text)
        except Exception as exc:  # недоверенный вход и внешний рендер
            return "\n".join(texts), f"{Status.OCR_FAILED.value}: {exc}"[:200]
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception:  # закрытие не должно ломать анализ
                    status = status or Status.OCR_FAILED.value
            self._cleanup(workdir)

        return "\n".join(texts), status

    # --- внутреннее --------------------------------------------------------

    def _workdir(self) -> Path:
        """Каталог для промежуточных изображений — только внутри runtime_temp."""
        if self.temp is not None:
            base = self.temp.ensure() / "ocr"
        else:
            base = self.paths.temp_dir / "ocr"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _cleanup(self, workdir: Path) -> None:
        """Удалить промежуточные изображения (раздел 62 ТЗ)."""
        from docrenamer.security.temp_cleanup import purge

        try:
            purge(workdir, self.paths.temp_dir)
        except Exception:  # очистка не должна ломать анализ
            return

    def _run(self, image_path: Path) -> tuple[str, str]:
        """Запустить tesseract для одного изображения."""
        if self.executable is None:
            return "", Status.OCR_ENGINE_NOT_FOUND.value
        arguments = [
            str(image_path),
            "stdout",
            "-l",
            self.config.ocr.language_spec,
            "--psm",
            DEFAULT_PSM,
        ]
        tessdata = self.paths.tessdata_dir
        if tessdata.is_dir():
            arguments += ["--tessdata-dir", str(tessdata)]
        result = run_tool(
            self.executable,
            arguments,
            timeout=self.config.ocr.timeout_seconds,
        )
        if result.timed_out:
            return "", Status.OCR_FAILED.value
        if not result.ok and not result.stdout.strip():
            message = (result.stderr or result.error).lower()
            if "failed loading language" in message or "tessdata" in message:
                return "", Status.OCR_ENGINE_NOT_FOUND.value
            return "", Status.OCR_FAILED.value
        return nfc(result.stdout), ""


def build_ocr_engine(
    config: Config, paths: AppPaths, *, temp: SessionTemp | None = None
) -> TesseractEngine | None:
    """Создать движок OCR, если он включён в настройках."""
    if not config.ocr.enabled:
        return None
    return TesseractEngine(config, paths, temp=temp)
