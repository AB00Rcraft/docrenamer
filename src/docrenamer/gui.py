"""Графический интерфейс на Tkinter + ttk (разделы 6, 57, 78–82 ТЗ).

Ни Electron, ни Chromium, ни встроенного веб-сервера. Интерфейс компактный,
тёмный, с моноширинным журналом и постоянным индикатором ``● LOCAL ONLY``.

Вся тяжёлая работа выполняется в рабочем потоке; виджеты обновляются только из
потока интерфейса через очередь событий (раздел 82 ТЗ).
"""

from __future__ import annotations

import base64
import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from docrenamer import __version__
from docrenamer.app import Application, Cancelled
from docrenamer.config import Config, load_config
from docrenamer.learning import LearningLog
from docrenamer.logging.manifest import find_incomplete_sessions
from docrenamer.operations.planner import (
    RenamePlan,
    build_plan,
    make_plan_item,
    merge_as_document,
    set_manual_name,
)
from docrenamer.operations.scrub import can_scrub
from docrenamer.paths import AppPaths, default_paths
from docrenamer.presentation import (
    plan_row_label,
    plan_row_values,
    progress_label,
    row_tag,
)
from docrenamer.preview import (
    file_card,
    folder_preview,
    text_preview,
    thumbnail_png,
)
from docrenamer.security.subprocess_safe import hidden_process_options
from docrenamer.types import PlanItem

#: Тёмная нейтральная палитра с одним акцентным цветом.
COLORS = {
    "bg": "#161a20",
    "panel": "#1f242c",
    "field": "#12161b",
    "hover": "#2b3240",
    "text": "#dde3ec",
    "muted": "#8b93a1",
    "disabled": "#5b636f",
    "accent": "#4fa3ff",
    "accent_hover": "#6fb5ff",
    "accent_text": "#0f1319",
    "ok": "#6fcf7f",
    "warn": "#e2b344",
    "error": "#e06c75",
}

#: Единая шкала отступов. Все поля, кнопки и панели используют только её,
#: поэтому расстояния в окне кратны одной величине.
PAD_XS = 2
PAD_S = 6
PAD_M = 10
PAD_L = 16

#: Единая типографика: один шрифт интерфейса и один моноширинный.
FONT_FAMILY = "Segoe UI"
FONT_MONO_FAMILY = "Consolas"
FONT_TITLE = (FONT_FAMILY, 14, "bold")
FONT_UI = (FONT_FAMILY, 10)
FONT_UI_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SECTION = (FONT_FAMILY, 9, "bold")
FONT_MONO = (FONT_MONO_FAMILY, 10)

#: Размеры элементов. Все кнопки одной ширины — ряд выглядит выверенным.
BUTTON_WIDTH = 13
ROW_HEIGHT = 26
DETAILS_HEIGHT = 7
PROGRESS_HEIGHT = 6
LEFT_MIN_WIDTH = 660
RIGHT_MIN_WIDTH = 430
#: Желаемый размер окна. При запуске он ужимается под экран: на ноутбуке с
#: невысоким разрешением окно должно помещаться целиком, а не уезжать за край.
WINDOW_WIDTH = 1320
WINDOW_HEIGHT = 860
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 640

#: Наименьшая высота панелей правой колонки: предпросмотр, сведения, журнал.
PREVIEW_MIN_HEIGHT = 220
DETAILS_MIN_HEIGHT = 150
LOG_MIN_HEIGHT = 110

#: Название программы для человека. Латинское DocRenamer остаётся именем
#: файлов и репозитория, но в глаза пользователю смотрит русское.
APP_TITLE = "Ренеймер документов"
APP_SUBTITLE = "работает без Интернета"

LOCAL_ONLY_TOOLTIP = (
    "Все документы обрабатываются локально.\nСетевые AI API не используются."
)

#: Подсказки к элементам управления. Каждый элемент объясняет сам себя.
TOOLTIPS: dict[str, str] = {
    "choose": "Выбрать папку с документами.\nВложенные папки обрабатываются, "
              "если включено «Включая подпапки».",
    "folder": "Путь к папке с документами.\nМожно вписать вручную или вставить из буфера.",
    "scan": "Посмотреть, какие файлы есть в папке.\n"
            "Ничего не читает и не меняет — только считает файлы по типам.",
    "preview": "Разобрать файлы и показать предлагаемые имена.\n"
               "Файлы при этом не меняются.",
    "apply": "Переименовать файлы по показанному плану.\n"
             "Содержимое не меняется, контрольная сумма сверяется до и после.\n"
             "Операцию можно отменить.",
    "undo": "Вернуть прежние имена по записи предыдущей операции.\n"
            "Файл, который изменился после переименования, не трогается.",
    "stop": "Прекратить запуск новых задач.\n"
            "Уже переименованные файлы остаются как есть — их можно отменить.",
    "selftest": "Проверить, всё ли на месте: распознавание сканов, локальная модель,\n"
                "чтение метаданных, и пройдёт ли разбор тестового документа.",
    "logs": "Открыть папку с журналами работы.\n"
            "В журнале видно, почему файл получил именно такое имя.",
    "settings": "Порог уверенности, длина имени, формат даты,\n"
                "использование распознавания и локальной модели.",
    "updates": "Проверить, вышла ли новая версия.\n"
               "Обновление выполняет отдельная программа: приложение,\n"
               "которое читает документы, в сеть не выходит.",
    "edit_name": "Изменить предложенное имя вручную.\n"
                 "То же самое делает двойной щелчок по имени и клавиша F2.",
    "merge": "Считать несколько файлов страницами одного документа.\n"
             "Откроется окно, где страницы отмечаются мышью — протяжкой,\n"
             "с Shift или Ctrl, — и задаётся общее имя. Страницы получат\n"
             "номера по порядку прежней нумерации.",
    "more": "Служебное: самопроверка, журнал работы, отчёт об именах,\n"
            "настройки и проверка обновлений.",
    "scrub": "Снять с выбранных файлов метаданные: EXIF и GPS у снимков,\n"
             "автора и историю правок у документов Office, свойства у PDF.\n"
             "По умолчанию рядом создаются очищенные копии.",
    "feedback": "Показать обезличенный отчёт о работе алгоритма имён\n"
                "и, если согласитесь, открыть страницу его отправки.\n"
                "Имён файлов, фамилий и текста документов в отчёте нет.",
    "preview_pane": "Содержимое выбранного файла: снимок и первая страница PDF —\n"
                    "картинкой, документ — началом распознанного текста.\n"
                    "По нему сразу видно, отвечает ли имя содержимому.",
    "readiness": "Готовность комплекта. Нажмите «Самопроверка» для подробностей.",
    "mode": "Анализ — только разобрать файлы.\n"
            "Предпросмотр — показать предлагаемые имена.\n"
            "Применить — переименовать по плану.",
    "recursive": "Обрабатывать файлы и во вложенных папках.",
    "table": "Дерево файлов и папок: сначала корень, ниже — вложенные папки.\n"
             "Щелчок по галочке включает или исключает строку; галочка на папке\n"
             "распространяется на всё её содержимое.\n"
             "Двойной щелчок по имени — правка вручную, пробел — отметка.\n"
             "Правая кнопка мыши открывает действия над файлом: изменить имя,\n"
             "пересканировать, считать одним документом, очистить метаданные.\n"
             "Несколько строк выбираются мышью с Shift или Ctrl.",
    "select_all": "Отметить все файлы, для которых есть предложение.\n"
                  "Повторное нажатие снимает отметки.",
    "details": "Сведения о выбранном файле: что распознано и на каком основании,\n"
               "насколько программа уверена, размер, время изменения и контрольная\n"
               "сумма. При переименовании они не меняются — программа сверяет их\n"
               "до и после операции.",
    "log": "Ход работы: что найдено, что предложено, что переименовано.",
    # Настройки
    "set_recursive": "Обрабатывать вложенные папки.",
    "set_ai": "Использовать локальную языковую модель для сложных случаев.\n"
              "Без неё имена строятся по правилам.",
    "set_ocr": "Распознавать текст на сканах и фотографиях документов.\n"
               "Требует локальный Tesseract.",
    "set_exif": "Читать дату съёмки, модель камеры и координаты из фотографий.",
    "set_media": "Читать дату съёмки и длительность из видео и аудио.",
    "set_archives": "Читать список содержимого архивов. Архивы не распаковываются.",
    "set_gps": "Добавлять координаты съёмки в имя фотографии.\n"
               "Выключено по умолчанию: координаты — чувствительные данные.",
    "set_threshold": "Насколько программа должна быть уверена, чтобы переименовать сама.\n"
                     "Ниже порога файл показывается, но не переименовывается.",
    "set_length": "Предельная длина имени файла в символах.",
}


def _resolved(path: Path) -> Path:
    """Путь в сравнимом виде: без «..» и по возможности без ссылок."""
    try:
        return path.resolve()
    except OSError:  # путь может быть недоступен — сравниваем как есть
        return path


class Tooltip:
    """Всплывающая подсказка для виджета."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: object = None) -> None:
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.window,
            text=self.text,
            justify="left",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=4,
        )
        label.pack()

    def _hide(self, _event: object = None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class CenterProgress:
    """Тонкая полоса хода работы, расходящаяся от середины окна.

    Обычная полоса прогресса занимает высоту и притягивает взгляд вниз. Здесь
    достаточно знать, что команда выполняется, поэтому полоса тонкая, стоит
    под заголовком и растёт от середины в обе стороны. Когда работы нет, её
    не видно вовсе.
    """

    HEIGHT = 3
    #: Шаг «дыхания», когда общее число шагов заранее неизвестно.
    PULSE_STEP = 0.08

    def __init__(self, parent: tk.Misc) -> None:
        self.canvas = tk.Canvas(
            parent,
            height=self.HEIGHT,
            bg=COLORS["bg"],
            highlightthickness=0,
            bd=0,
        )
        self.fraction = 0.0
        self._pulse = 0.0
        self._pulse_up = True
        self._job: str | None = None
        self.canvas.bind("<Configure>", lambda _event: self._draw())

    def grid(self, **options: object) -> None:
        self.canvas.grid(**options)  # type: ignore[arg-type]

    def set(self, done: int, total: int) -> None:
        """Показать долю выполненного."""
        self.stop_pulse()
        self.fraction = 0.0 if total <= 0 else max(0.0, min(1.0, done / total))
        self._draw()

    def start_pulse(self) -> None:
        """Показать, что работа идёт, когда число шагов заранее неизвестно."""
        if self._job is not None:
            return
        self._pulse, self._pulse_up = 0.0, True
        self._tick()

    def stop_pulse(self) -> None:
        if self._job is not None:
            self.canvas.after_cancel(self._job)
            self._job = None

    def clear(self) -> None:
        """Убрать полосу: работы нет."""
        self.stop_pulse()
        self.fraction = 0.0
        self._draw()

    def _tick(self) -> None:
        self._pulse += self.PULSE_STEP if self._pulse_up else -self.PULSE_STEP
        if self._pulse >= 1.0:
            self._pulse, self._pulse_up = 1.0, False
        elif self._pulse <= 0.15:
            self._pulse, self._pulse_up = 0.15, True
        self.fraction = self._pulse
        self._draw()
        self._job = self.canvas.after(60, self._tick)

    def _draw(self) -> None:
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        if width <= 1:
            # Пока окно не показано, действительная ширина не известна:
            # рисуем по запрошенной, иначе первый ход работы не виден.
            width = self.canvas.winfo_reqwidth()
        if width <= 1 or self.fraction <= 0:
            return
        middle = width / 2
        half = middle * self.fraction
        self.canvas.create_rectangle(
            middle - half,
            0,
            middle + half,
            self.HEIGHT,
            fill=COLORS["accent"],
            width=0,
        )


class MergeDialog:
    """Выбор файлов, которые надо считать страницами одного документа.

    Отмечать страницы в общем списке неудобно: они перемешаны с папками и
    другими документами. Поэтому по команде открывается отдельное окно —
    посреди окна программы, а не в углу экрана.

    Список в нём редактируемый: щелчок отмечает и снимает отметку, лишние
    строки убираются, а недостающие файлы добавляются с диска. Одним
    документом могут быть только страницы из одной папки.
    """

    def __init__(
        self,
        parent: tk.Misc,
        items: list[PlanItem],
        *,
        preselected: list[PlanItem] | None = None,
        suggestion: str = "",
        root: Path | None = None,
        on_add: Callable[[Path], PlanItem | None] | None = None,
    ) -> None:
        self.items = list(items)
        self.root_directory = root
        self.on_add = on_add
        self.added: list[PlanItem] = []
        self.result: tuple[list[PlanItem], str] | None = None
        self._marks: dict[str, bool] = {}

        self.window = tk.Toplevel(parent)
        self.window.title("Объединить в один документ")
        self.window.configure(bg=COLORS["bg"])
        self.window.transient(parent.winfo_toplevel())
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        ttk.Label(
            self.window,
            text=(
                "Отметьте страницы одного документа: щелчок по строке ставит и\n"
                "снимает отметку. Лишние файлы можно убрать, недостающие — добавить."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=PAD_L, pady=(PAD_L, PAD_S))

        frame = ttk.Frame(self.window)
        frame.grid(row=1, column=0, sticky="nsew", padx=PAD_L)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame, columns=("mark", "file"), show="headings", selectmode="extended", height=14
        )
        self.tree.heading("mark", text="✓")
        self.tree.column("mark", width=36, minwidth=36, stretch=False, anchor="center")
        self.tree.heading("file", text="Файл")
        self.tree.column("file", width=420, minwidth=220, stretch=True, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._on_click, add="+")
        self.tree.bind("<space>", lambda _event: self._toggle_selected_rows())

        chosen = {item.source_path for item in preselected or []}
        for item in self.items:
            self._insert(item, marked=not chosen or item.source_path in chosen)

        edit = ttk.Frame(self.window)
        edit.grid(row=2, column=0, sticky="w", padx=PAD_L, pady=(PAD_S, 0))
        for column, (text, command) in enumerate(
            (
                ("Отметить все", lambda: self._mark_all(True)),
                ("Снять все", lambda: self._mark_all(False)),
                ("Добавить файлы…", self._add_files),
                ("Убрать из списка", self._remove_rows),
            )
        ):
            ttk.Button(edit, text=text, width=BUTTON_WIDTH + 3, command=command).grid(
                row=0, column=column, padx=(0, PAD_S)
            )

        name_row = ttk.Frame(self.window)
        name_row.grid(row=3, column=0, sticky="ew", padx=PAD_L, pady=(PAD_M, 0))
        name_row.columnconfigure(1, weight=1)
        ttk.Label(name_row, text="Общее имя:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=suggestion)
        entry = ttk.Entry(name_row, textvariable=self.name_var, font=FONT_UI)
        entry.grid(row=0, column=1, sticky="ew", padx=(PAD_M, 0))

        buttons = ttk.Frame(self.window)
        buttons.grid(row=4, column=0, sticky="e", padx=PAD_L, pady=PAD_L)
        ttk.Button(
            buttons, text="Отмена", width=BUTTON_WIDTH, command=self._cancel
        ).grid(row=0, column=0)
        ttk.Button(
            buttons,
            text="Объединить",
            width=BUTTON_WIDTH,
            style="Accent.TButton",
            command=self._accept,
        ).grid(row=0, column=1, padx=(PAD_M, 0))

        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.bind("<Return>", lambda _event: self._accept())
        entry.focus_set()
        self._center_over(parent)

    # --- размещение ---------------------------------------------------------

    def _center_over(self, parent: tk.Misc) -> None:
        """Поставить окно посреди окна программы, а не в углу экрана."""
        self.window.update_idletasks()
        top = parent.winfo_toplevel()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        left = top.winfo_rootx() + max(0, (top.winfo_width() - width) // 2)
        upper = top.winfo_rooty() + max(0, (top.winfo_height() - height) // 3)
        self.window.geometry(f"+{max(0, left)}+{max(0, upper)}")

    # --- список -------------------------------------------------------------

    def _insert(self, item: PlanItem, *, marked: bool) -> str:
        """Добавить строку файла в список окна."""
        folders = {other.source_path.parent for other in self.items}
        row = str(len(self._marks))
        self._marks[row] = marked
        self.tree.insert(
            "",
            "end",
            iid=row,
            values=("☑" if marked else "☐", self._label(item, show_folder=len(folders) > 1)),
        )
        return row

    def _label(self, item: PlanItem, *, show_folder: bool) -> str:
        """Подпись файла в списке: с папкой, когда папок несколько."""
        if not show_folder:
            return item.source_path.name
        directory = item.source_path.parent
        if self.root_directory is not None:
            try:
                directory = directory.relative_to(self.root_directory)
            except ValueError:
                pass
        if str(directory) == ".":
            return item.source_path.name
        return f"{directory}{os.sep}{item.source_path.name}"

    def _row_items(self) -> list[tuple[str, PlanItem]]:
        """Строки окна вместе с их файлами, в показанном порядке."""
        pairs: list[tuple[str, PlanItem]] = []
        for row in self.tree.get_children(""):
            index = int(row)
            if index < len(self.items):
                pairs.append((row, self.items[index]))
        return pairs

    def selected_items(self) -> list[PlanItem]:
        """Отмеченные файлы — в том порядке, в каком они показаны."""
        return [item for row, item in self._row_items() if self._marks.get(row)]

    def _set_mark(self, row: str, value: bool) -> None:
        self._marks[row] = value
        values = list(self.tree.item(row, "values"))
        values[0] = "☑" if value else "☐"
        self.tree.item(row, values=values)

    def _on_click(self, event: tk.Event) -> str | None:
        """Щелчок по строке ставит и снимает отметку."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self._set_mark(row, not self._marks.get(row, False))
        return "break"

    def _toggle_selected_rows(self) -> None:
        for row in self.tree.selection():
            self._set_mark(row, not self._marks.get(row, False))

    def _mark_all(self, value: bool) -> None:
        for row in self.tree.get_children(""):
            self._set_mark(row, value)

    def _remove_rows(self) -> None:
        """Убрать выделенные строки из списка окна.

        Сами файлы это не трогает: они просто не участвуют в объединении.
        """
        rows = self.tree.selection() or [
            row for row in self.tree.get_children("") if not self._marks.get(row)
        ]
        for row in rows:
            self.tree.delete(row)
            self._marks.pop(row, None)

    def _add_files(self) -> None:
        """Добавить в список файлы с диска.

        Пригождается, когда нужная страница не попала в разбор: например, это
        снимок, который программа сочла служебным, или файл, добавленный в
        папку уже после сканирования.
        """
        if self.on_add is None:
            return
        known = {item.source_path for item in self.items}
        directory = next(iter({item.source_path.parent for item in self.items}), None)
        chosen = filedialog.askopenfilenames(
            parent=self.window,
            title="Добавить файлы к документу",
            initialdir=str(directory) if directory else None,
        )
        for raw in chosen or ():
            path = Path(raw)
            if path in known or not path.is_file():
                continue
            item = self.on_add(path)
            if item is None:
                continue
            self.items.append(item)
            self.added.append(item)
            known.add(path)
            self._insert(item, marked=True)

    # --- решение ------------------------------------------------------------

    def _accept(self) -> None:
        chosen = self.selected_items()
        if len(chosen) < 2:
            messagebox.showinfo(
                "Один документ",
                "Отметьте хотя бы два файла — страницы одного документа.",
                parent=self.window,
            )
            return
        if len({item.source_path.parent for item in chosen}) > 1:
            messagebox.showinfo(
                "Один документ",
                "Страницы одного документа должны лежать в одной папке.\n"
                "Снимите отметки с файлов из других папок.",
                parent=self.window,
            )
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showinfo(
                "Один документ", "Задайте общее имя документа.", parent=self.window
            )
            return
        self.result = (chosen, name)
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> tuple[list[PlanItem], str] | None:
        """Показать окно и дождаться решения человека."""
        self.window.grab_set()
        self.window.wait_window()
        return self.result


class DocRenamerGUI:
    """Главное окно приложения."""

    def __init__(self, config: Config, paths: AppPaths, initial_directory: Path | None) -> None:
        self.config = config
        self.paths = paths
        self.directory: Path | None = initial_directory
        self.plan: RenamePlan | None = None
        #: Узлы дерева для папок: путь → строка Treeview.
        self.nodes: dict[Path, str] = {}
        self.learning = LearningLog(
            paths=paths, version=__version__, enabled=config.learning.enabled
        )
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.app = Application(
            config,
            paths=paths,
            on_line=lambda line: self.events.put(("log", line)),
            on_progress=lambda done, total, stage: self.events.put(
                ("progress", (done, total, stage))
            ),
        )

        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {__version__}")
        self._apply_geometry()
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.root.configure(bg=COLORS["bg"])
        self._set_window_icon()
        self._build_style()
        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)
        self.root.after(200, self._check_recovery)
        # Быстрая проверка готовности при запуске: без обращения к модели,
        # чтобы окно открывалось сразу.
        self.root.after(300, lambda: self._selftest(probe_model=False, quiet=True))
        if self.config.update.enabled and self.config.update.check_on_start:
            self.root.after(1500, self._check_updates)

    def _apply_geometry(self) -> None:
        """Раскрыть окно по размеру экрана и поставить его посередине.

        Жёсткий размер окна плох одинаково в обе стороны: на маленьком экране
        оно уезжает за край, на большом — оставляет половину места пустой.
        """
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = max(WINDOW_MIN_WIDTH, min(WINDOW_WIDTH, screen_width - 120))
        height = max(WINDOW_MIN_HEIGHT, min(WINDOW_HEIGHT, screen_height - 140))
        left = max(0, (screen_width - width) // 2)
        top = max(0, (screen_height - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{left}+{top}")

    # --- построение интерфейса --------------------------------------------

    def _load_logo(self) -> tk.PhotoImage | None:
        """Знак программы для заголовка окна."""
        path = self.paths.assets_dir / "logo40.png"
        if not path.is_file():
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None

    def _set_window_icon(self) -> None:
        """Поставить фирменный значок окна.

        В Windows используется .ico — он же показывается на панели задач;
        в остальных системах — PNG. Отсутствие файла не должно мешать работе.
        """
        assets = self.paths.assets_dir
        try:
            icon = assets / "icon.ico"
            if os.name == "nt" and icon.is_file():
                self.root.iconbitmap(default=str(icon))
                return
            png = assets / "logo.png"
            if png.is_file():
                self._icon_image = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_image)
        except tk.TclError:
            return

    def _build_style(self) -> None:
        """Единая типографика и палитра.

        Все размеры берутся из одной шкалы отступов, чтобы поля, кнопки и
        панели выглядели выверенно, а не подогнанно по месту.
        """
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:  # pragma: no cover — тема зависит от системы
            pass

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["panel"])
        style.configure(
            "Preview.TLabel", background=COLORS["panel"], foreground=COLORS["muted"]
        )
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_UI)
        style.configure(
            "Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_TITLE
        )
        style.configure(
            "Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=FONT_SMALL
        )
        style.configure(
            "Section.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=FONT_SECTION
        )
        for name, color in (
            ("Local.TLabel", COLORS["ok"]),
            ("Warn.TLabel", COLORS["warn"]),
            ("Error.TLabel", COLORS["error"]),
        ):
            style.configure(
                name, background=COLORS["bg"], foreground=color, font=FONT_UI_BOLD
            )

        style.configure(
            "TButton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=FONT_UI,
            padding=(PAD_M, PAD_S),
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "TButton",
            background=[("active", COLORS["hover"]), ("disabled", COLORS["panel"])],
            foreground=[("disabled", COLORS["disabled"])],
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground=COLORS["accent_text"],
            font=FONT_UI_BOLD,
            padding=(PAD_M, PAD_S),
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["panel"])],
            foreground=[("disabled", COLORS["disabled"])],
        )

        style.configure(
            "TRadiobutton", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_UI
        )
        style.map("TRadiobutton", background=[("active", COLORS["bg"])])
        style.configure(
            "TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_UI
        )
        style.map("TCheckbutton", background=[("active", COLORS["bg"])])
        style.configure(
            "TEntry",
            fieldbackground=COLORS["field"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
            borderwidth=0,
            padding=PAD_S,
        )
        style.configure(
            "Treeview",
            background=COLORS["field"],
            fieldbackground=COLORS["field"],
            foreground=COLORS["text"],
            font=FONT_UI,
            rowheight=ROW_HEIGHT,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", COLORS["accent"])],
                  foreground=[("selected", COLORS["accent_text"])])
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=FONT_SECTION,
            padding=(PAD_S, PAD_S),
            borderwidth=0,
        )
        style.configure(
            "TProgressbar",
            background=COLORS["accent"],
            troughcolor=COLORS["field"],
            borderwidth=0,
            thickness=PROGRESS_HEIGHT,
        )
        style.configure("TPanedwindow", background=COLORS["bg"])
        style.configure("Sash", sashthickness=PAD_M, gripcount=0)

    def _build_widgets(self) -> None:
        """Собрать окно.

        Раскладка: заголовок, панель выбора папки, рабочая область из двух
        колонок (слева список файлов и подробности, справа журнал), строка
        прогресса и ряд кнопок. Журнал занимает отдельную колонку и поэтому
        виден всегда, сколько бы файлов ни было в списке.
        """
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        self._build_header()
        # Тонкая полоса хода работы идёт сразу под заголовком: она не занимает
        # места и видна, куда бы ни смотрел человек.
        self.progress = CenterProgress(self.root)
        self.progress.grid(row=1, column=0, sticky="ew", padx=PAD_L)
        self._build_toolbar()
        self._build_workspace()
        self._build_status()
        self._build_actions()

        self._log(f"{APP_TITLE} {__version__}. Все данные обрабатываются локально.")

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(PAD_L, PAD_M, PAD_L, PAD_S))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        # Знак и название программы.
        title_block = ttk.Frame(header)
        title_block.grid(row=0, column=0, sticky="w")
        self._logo_image = self._load_logo()
        if self._logo_image is not None:
            ttk.Label(title_block, image=self._logo_image, background=COLORS["bg"]).grid(
                row=0, column=0, rowspan=2, sticky="w", padx=(0, PAD_M)
            )
        ttk.Label(title_block, text=APP_TITLE, style="Title.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(title_block, text=__version__, style="Muted.TLabel").grid(
            row=0, column=2, sticky="sw", padx=(PAD_S, 0), pady=(0, PAD_XS)
        )
        ttk.Label(title_block, text=APP_SUBTITLE, style="Muted.TLabel").grid(
            row=1, column=1, sticky="w"
        )

        self.readiness_var = tk.StringVar(value="… проверка готовности")
        self.readiness_label = ttk.Label(
            header, textvariable=self.readiness_var, style="Muted.TLabel"
        )
        self.readiness_label.grid(row=0, column=1, sticky="e", padx=(PAD_M, PAD_L))
        Tooltip(self.readiness_label, TOOLTIPS["readiness"])

        badge = ttk.Label(header, text="● LOCAL ONLY", style="Local.TLabel")
        badge.grid(row=0, column=2, sticky="e")
        Tooltip(badge, LOCAL_ONLY_TOOLTIP)

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(PAD_L, 0, PAD_L, PAD_M))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="Папка").grid(row=0, column=0, sticky="w", padx=(0, PAD_M))
        self.directory_var = tk.StringVar(value=str(self.directory or ""))
        entry = ttk.Entry(toolbar, textvariable=self.directory_var, font=FONT_UI)
        entry.grid(row=0, column=1, sticky="ew", ipady=PAD_XS)
        Tooltip(entry, TOOLTIPS["folder"])
        choose = ttk.Button(
            toolbar, text="Выбрать", width=BUTTON_WIDTH, command=self._choose_directory
        )
        choose.grid(row=0, column=2, sticky="e", padx=(PAD_M, 0))
        Tooltip(choose, TOOLTIPS["choose"])

        modes = ttk.Frame(toolbar)
        modes.grid(row=1, column=0, columnspan=3, sticky="w", pady=(PAD_M, 0))
        self.mode_var = tk.StringVar(value="preview")
        for index, (value, label) in enumerate(
            (("analyze", "Анализ"), ("preview", "Предпросмотр"), ("apply", "Применить"))
        ):
            button = ttk.Radiobutton(modes, text=label, value=value, variable=self.mode_var)
            button.grid(row=0, column=index, sticky="w", padx=(0, PAD_L))
            Tooltip(button, TOOLTIPS["mode"])
        self.recursive_var = tk.BooleanVar(value=self.config.recursive)
        recursive = ttk.Checkbutton(
            modes, text="Включая подпапки", variable=self.recursive_var
        )
        recursive.grid(row=0, column=3, sticky="w")
        Tooltip(recursive, TOOLTIPS["recursive"])

    def _build_workspace(self) -> None:
        """Две колонки: список файлов и журнал."""
        workspace = ttk.PanedWindow(self.root, orient="horizontal")
        workspace.grid(row=3, column=0, sticky="nsew", padx=PAD_L)

        left = ttk.Frame(workspace, width=LEFT_MIN_WIDTH)
        left.columnconfigure(0, weight=1)
        # Карточка файла переехала под предпросмотр, поэтому список занимает
        # всю высоту левой колонки.
        left.rowconfigure(1, weight=1)
        workspace.add(left, weight=3)

        header_row = ttk.Frame(left)
        header_row.grid(row=0, column=0, sticky="ew", pady=(0, PAD_S))
        header_row.columnconfigure(0, weight=1)
        ttk.Label(header_row, text="ЧТО БУДЕТ ПЕРЕИМЕНОВАНО", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.select_all_var = tk.StringVar(value="Выбрать все")
        self.select_all_button = ttk.Button(
            header_row,
            textvariable=self.select_all_var,
            width=BUTTON_WIDTH,
            command=self._toggle_all,
        )
        self.select_all_button.grid(row=0, column=1, sticky="e")
        Tooltip(self.select_all_button, TOOLTIPS["select_all"])

        table = ttk.Frame(left)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table,
            columns=("mark", "proposed", "confidence", "status"),
            show="tree headings",
            # Несколько строк выбираются мышью с Ctrl или Shift: так
            # отмечаются страницы, которые надо объединить в один документ.
            selectmode="extended",
        )
        # Колонка дерева показывает вложенность: сначала файлы корня, затем
        # папка и её содержимое под ней — структуру видно без догадок.
        self.tree.heading("#0", text="Файл или папка")
        self.tree.column("#0", width=230, minwidth=140, stretch=False, anchor="w")
        # Ширины подобраны под заголовки: предлагаемое имя тянется, остальные
        # колонки занимают ровно столько, сколько нужно их содержимому.
        columns: tuple[tuple[str, str, int, int, bool, bool], ...] = (
            ("mark", "✓", 34, 34, True, False),
            ("proposed", "Предлагаемое имя", 340, 200, False, True),
            ("confidence", "Уверенность", 92, 80, True, False),
            ("status", "Состояние", 130, 100, False, False),
        )
        for column, title, width, minwidth, centered, stretch in columns:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=minwidth, stretch=stretch)
            self.tree.column(column, anchor="center" if centered else "w")
        self.tree.tag_configure("ok", foreground=COLORS["ok"])
        self.tree.tag_configure("warn", foreground=COLORS["warn"])
        self.tree.tag_configure("error", foreground=COLORS["error"])
        self.tree.grid(row=0, column=0, sticky="nsew")

        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        # Меню строки: всё, что делается с конкретным файлом.
        self.row_menu = tk.Menu(self.tree, tearoff=0)
        self.row_menu.add_command(label="Изменить имя…   F2", command=self._edit_selected_name)
        self.row_menu.add_command(label="Пересканировать   F5", command=self._rescan_selected)
        self.row_menu.add_separator()
        self.row_menu.add_command(label="Считать одним документом…", command=self._merge_selected)
        self.row_menu.add_command(label="Очистить метаданные…", command=self._scrub_selected)
        self.row_menu.add_separator()
        self.row_menu.add_command(
            label="Отметить или снять   Пробел", command=self._toggle_selected
        )
        self.tree.bind("<Button-3>", self._show_row_menu)
        self.tree.bind("<F5>", lambda _event: self._rescan_selected())

        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<F2>", lambda _event: self._edit_selected_name())
        # Одиночный щелчок по колонке с галочкой переключает строку сразу.
        self.tree.bind("<Button-1>", self._on_click, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        Tooltip(self.tree, TOOLTIPS["table"])

        right = ttk.Frame(workspace, width=RIGHT_MIN_WIDTH)
        right.columnconfigure(0, weight=1)
        # Правая колонка читается сверху вниз: как файл выглядит, что о нём
        # известно, и лишь затем ход работы.
        right.rowconfigure(1, weight=4, minsize=PREVIEW_MIN_HEIGHT)
        right.rowconfigure(3, weight=3, minsize=DETAILS_MIN_HEIGHT)
        right.rowconfigure(5, weight=2, minsize=LOG_MIN_HEIGHT)
        workspace.add(right, weight=2)

        ttk.Label(right, text="ПРЕДПРОСМОТР ФАЙЛА", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, PAD_S)
        )
        preview = ttk.Frame(right, style="Card.TFrame", padding=PAD_S)
        preview.grid(row=1, column=0, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)

        self.preview_image = ttk.Label(preview, anchor="center", style="Preview.TLabel")
        self.preview_image.grid(row=0, column=0, sticky="nsew")
        self.preview_image.grid_remove()
        self.preview_photo: tk.PhotoImage | None = None

        self.preview_text = tk.Text(
            preview,
            wrap="word",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=FONT_MONO,
            relief="flat",
            highlightthickness=0,
            padx=PAD_S,
            pady=PAD_S,
            state="disabled",
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        Tooltip(self.preview_image, TOOLTIPS["preview_pane"])
        Tooltip(self.preview_text, TOOLTIPS["preview_pane"])
        self._set_preview_text("Выберите файл в списке — здесь будет его содержимое.")

        ttk.Label(right, text="СВЕДЕНИЯ О ФАЙЛЕ", style="Section.TLabel").grid(
            row=2, column=0, sticky="w", pady=(PAD_M, PAD_S)
        )
        details = ttk.Frame(right, style="Card.TFrame", padding=PAD_S)
        details.grid(row=3, column=0, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.details = tk.Text(
            details,
            height=DETAILS_HEIGHT,
            wrap="word",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=FONT_MONO,
            relief="flat",
            highlightthickness=0,
            padx=PAD_S,
            pady=PAD_S,
            state="disabled",
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(details, orient="vertical", command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        Tooltip(self.details, TOOLTIPS["details"])
        self._set_details("Выберите файл в списке, чтобы увидеть сведения о нём.")

        ttk.Label(right, text="ЖУРНАЛ РАБОТЫ", style="Section.TLabel").grid(
            row=4, column=0, sticky="w", pady=(PAD_M, PAD_S)
        )
        log_frame = ttk.Frame(right)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=FONT_MONO,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            padx=PAD_M,
            pady=PAD_S,
            state="disabled",
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        Tooltip(self.log, TOOLTIPS["log"])
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _build_status(self) -> None:
        status = ttk.Frame(self.root, padding=(PAD_L, PAD_S, PAD_L, 0))
        status.grid(row=4, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=0, column=0, sticky="e"
        )

    def _build_actions(self) -> None:
        """Ряд кнопок: слева действия над файлами, справа служебные."""
        actions = ttk.Frame(self.root, padding=(PAD_L, PAD_S, PAD_L, PAD_L))
        actions.grid(row=5, column=0, sticky="ew")
        actions.columnconfigure(6, weight=1)

        self.scan_button = ttk.Button(
            actions, text="Сканировать", width=BUTTON_WIDTH, command=self._scan
        )
        self.scan_button.grid(row=0, column=0, sticky="w")
        Tooltip(self.scan_button, TOOLTIPS["scan"])
        self.preview_button = ttk.Button(
            actions, text="Предпросмотр", width=BUTTON_WIDTH, command=self._preview
        )
        self.preview_button.grid(row=0, column=1, sticky="w", padx=(PAD_M, 0))
        Tooltip(self.preview_button, TOOLTIPS["preview"])
        self.apply_button = ttk.Button(
            actions,
            text="Переименовать",
            width=BUTTON_WIDTH,
            style="Accent.TButton",
            command=self._apply,
        )
        self.apply_button.grid(row=0, column=2, sticky="w", padx=(PAD_M, 0))
        Tooltip(self.apply_button, TOOLTIPS["apply"])
        self.undo_button = ttk.Button(
            actions, text="Отменить", width=BUTTON_WIDTH, command=self._undo
        )
        self.undo_button.grid(row=0, column=3, sticky="w", padx=(PAD_M, 0))
        Tooltip(self.undo_button, TOOLTIPS["undo"])
        self.stop_button = ttk.Button(
            actions, text="Стоп", width=BUTTON_WIDTH, command=self._stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=4, sticky="w", padx=(PAD_M, 0))
        Tooltip(self.stop_button, TOOLTIPS["stop"])

        # Объединение страниц — частая работа, а не редкая настройка: у него
        # своя кнопка в ряду, хотя оно есть и в меню строки.
        self.merge_button = ttk.Button(
            actions, text="Объединить", width=BUTTON_WIDTH, command=self._merge_selected
        )
        self.merge_button.grid(row=0, column=5, sticky="w", padx=(PAD_M, 0))
        Tooltip(self.merge_button, TOOLTIPS["merge"])

        # Служебное — под одной кнопкой: в ряду остаётся только ход работы.
        more = ttk.Menubutton(actions, text="Ещё", width=BUTTON_WIDTH)
        menu = tk.Menu(more, tearoff=0)
        menu.add_command(label="Самопроверка", command=self._selftest)
        menu.add_command(label="Журнал работы", command=self._open_logs)
        menu.add_command(label="Отчёт об именах", command=self._send_feedback)
        menu.add_separator()
        menu.add_command(label="Настройки", command=self._open_settings)
        if self.config.update.enabled:
            menu.add_command(label="Проверить обновления", command=self._check_updates)
        more.configure(menu=menu)
        more.grid(row=0, column=7, sticky="e", padx=(PAD_M, 0))
        Tooltip(more, TOOLTIPS["more"])
        self.more_menu = menu

    def _set_details(self, text: str) -> None:
        """Показать подробности выбранного файла."""
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _preview_size(self) -> tuple[int, int]:
        """Размер картинки под текущую ширину панели предпросмотра."""
        frame = self.preview_image.master
        width = frame.winfo_width() or RIGHT_MIN_WIDTH
        height = frame.winfo_height() or PREVIEW_MIN_HEIGHT
        return (max(220, width - 2 * PAD_M), max(160, height - 2 * PAD_M))

    def _set_preview_text(self, text: str) -> None:
        """Показать текстовый предпросмотр вместо картинки."""
        self.preview_image.grid_remove()
        self.preview_photo = None
        self.preview_text.grid()
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    def _show_preview(self, item: PlanItem) -> None:
        """Показать содержимое выбранного файла.

        Снимок и первая страница PDF показываются картинкой, всё остальное —
        началом прочитанного текста: именно по нему строилось имя, поэтому по
        нему же видно, справедливо ли оно.
        """
        data = None if item.is_folder else thumbnail_png(item.source_path, self._preview_size())
        if data is None:
            self._set_preview_text(text_preview(item))
            return
        try:
            # Tk принимает картинку строкой base64: так работает в любой сборке,
            # тогда как двоичные данные поддерживаются не везде.
            photo = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
        except tk.TclError:
            self._set_preview_text(text_preview(item))
            return
        # Ссылку надо держать: без неё Tk выбрасывает картинку сборщиком.
        self.preview_photo = photo
        self.preview_text.grid_remove()
        self.preview_image.configure(image=photo, text="")
        self.preview_image.grid()

    def _show_details(self, _event: object = None) -> None:
        """Полные имена выбранного файла — без обрезки по ширине колонки."""
        if self.plan is None:
            return
        selection = self.tree.selection()
        if not selection:
            return
        try:
            item = self.plan.items[int(selection[0])]
        except (ValueError, IndexError):
            # Строка-группа: своей строки плана у неё нет.
            self._set_details("Папка показана для наглядности — переименование не предложено.")
            self._set_preview_text(folder_preview(Path(selection[0].removeprefix("dir:"))))
            return
        self._set_details(file_card(item, self.plan.root if self.plan else None))
        self._show_preview(item)

    # --- журнал и события --------------------------------------------------

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_events(self) -> None:
        """Перенести события рабочего потока в интерфейс (раздел 82 ТЗ)."""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "progress":
                    done, total, stage = payload
                    self.progress.set(done, total)
                    self.status_var.set(progress_label(done, total, stage))
                elif kind == "files":
                    self._show_files(payload)
                elif kind == "plan":
                    self._show_plan(payload)
                elif kind == "rows":
                    self._refresh_rows(list(payload))
                elif kind == "plan_cleared":
                    self._clear_plan(str(payload))
                elif kind == "done":
                    self._finish(str(payload))
                elif kind == "readiness":
                    self._show_readiness(payload)
                elif kind == "update":
                    self._handle_update_answer(payload)
                elif kind == "error":
                    self._finish("Ошибка")
                    messagebox.showerror("DocRenamer", str(payload))
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _busy(self, busy: bool) -> None:
        if busy:
            self.progress.start_pulse()
        else:
            self.progress.clear()
        state = "disabled" if busy else "normal"
        for button in (
            self.scan_button,
            self.preview_button,
            self.apply_button,
            self.undo_button,
            self.merge_button,
        ):
            button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")

    def _finish(self, message: str) -> None:
        self._busy(False)
        self.status_var.set(message)

    def _run_async(self, work: Callable[[], None]) -> None:
        """Запустить работу в фоновом потоке."""
        if self.worker is not None and self.worker.is_alive():
            messagebox.showinfo("DocRenamer", "Операция уже выполняется.")
            return
        self.app.cancel_event.clear()
        self._busy(True)

        def wrapper() -> None:
            try:
                work()
            except Cancelled:
                self.events.put(("log", "Остановлено пользователем."))
                self.events.put(("done", "Остановлено"))
            except Exception as exc:  # интерфейс не должен падать от ошибки анализа
                self.events.put(("error", exc))

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    # --- действия ----------------------------------------------------------

    def _choose_directory(self) -> None:
        selected = filedialog.askdirectory(title="Выберите папку с документами")
        if selected:
            self.directory = Path(selected)
            self.directory_var.set(selected)

    def _current_directory(self) -> Path | None:
        text = self.directory_var.get().strip()
        if not text:
            messagebox.showwarning("DocRenamer", "Сначала выберите папку.")
            return None
        path = Path(text)
        if not path.is_dir():
            messagebox.showerror("DocRenamer", f"Каталог не найден:\n{path}")
            return None
        self.directory = path
        return path

    def _scan(self) -> None:
        directory = self._current_directory()
        if directory is None:
            return
        self.config.recursive = self.recursive_var.get()

        def work() -> None:
            files = self.app.scan(directory)
            # Список показывается сразу: человек видит, с чем предстоит работа,
            # ещё до разбора содержимого.
            self.events.put(("files", files))
            self.events.put(("done", f"Найдено файлов: {len(files)}"))

        self._run_async(work)

    def _preview(self) -> None:
        directory = self._current_directory()
        if directory is None:
            return
        self.config.recursive = self.recursive_var.get()

        def work() -> None:
            files = self.app.scan(directory)
            self.events.put(("files", files))
            analyses = self.app.analyze(files)
            plan = build_plan(
                analyses,
                config=self.config,
                root=directory,
                app_version=__version__,
            )
            self.events.put(("plan", plan))
            self.events.put(("done", "Предпросмотр готов"))

        self._run_async(work)

    def _apply(self) -> None:
        if self.plan is None:
            messagebox.showinfo("DocRenamer", "Сначала выполните предпросмотр.")
            return
        selected = self.plan.selected_items
        if not selected:
            messagebox.showinfo("DocRenamer", "Нет файлов, выбранных для переименования.")
            return
        confirmed = messagebox.askyesno(
            "Подтверждение",
            f"Переименовать файлов: {len(selected)}?\n\n"
            "Содержимое файлов не изменяется. Операцию можно отменить кнопкой "
            "«Отменить последнее».",
        )
        if not confirmed:
            return

        plan = self.plan

        def work() -> None:
            report = self.app.apply(plan)
            summary = f"Переименовано: {report.renamed}, пропущено: {report.skipped}"
            if report.critical:
                self.events.put(("error", report.critical))
            self.events.put(
                (
                    "plan_cleared",
                    "Файлы переименованы. Нажмите «Предпросмотр», чтобы увидеть папку заново.",
                )
            )
            self.events.put(("done", summary))

        self._run_async(work)

    def _undo(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите manifest сессии",
            initialdir=str(self.paths.manifests_dir),
            filetypes=[("Manifest JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if not selected:
            return

        def work() -> None:
            report = self.app.undo(Path(selected))
            self.events.put(
                (
                    "plan_cleared",
                    "Прежние имена восстановлены. Нажмите «Предпросмотр», "
                    "чтобы начать заново.",
                )
            )
            self.events.put(
                ("done", f"Восстановлено: {report.restored}, пропущено: {report.skipped}")
            )

        self._run_async(work)

    def _stop(self) -> None:
        self.app.cancel()
        self._log("Остановка: новые задачи не запускаются.")

    def _open_logs(self) -> None:
        """Открыть каталог журналов средствами системы."""
        import shutil
        import subprocess

        directory = self.paths.logs_dir
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                # Открытие собственного каталога журналов средствами системы.
                os.startfile(str(directory))  # type: ignore[attr-defined] # noqa: S606
            else:
                opener = shutil.which("xdg-open") or shutil.which("open")
                if not opener:
                    raise OSError("Не найдена системная программа открытия папок")
                subprocess.run(  # noqa: S603 — абсолютный путь, список аргументов
                    [opener, str(directory)],
                    shell=False,
                    check=False,
                    timeout=10,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            messagebox.showinfo("DocRenamer", f"Журналы находятся в:\n{directory}\n\n{exc}")

    def _open_settings(self) -> None:
        SettingsDialog(self.root, self.config, self.paths)

    # --- отчёт об именах ---------------------------------------------------

    def _send_feedback(self) -> None:
        """Показать обезличенный отчёт и, с согласия человека, отправить его.

        Отчёт — это статистика о работе алгоритма имён: сколько файлов какого
        вида разобрано, где не хватило уверенности, какие имена пришлось
        править руками. Ни имён файлов, ни фамилий, ни текста документов в нём
        нет, и человек видит его целиком до отправки.
        """
        import subprocess

        report = self.learning.build_report()
        if not report.get("records"):
            messagebox.showinfo(
                "Отчёт об именах",
                "Пока нечего отправлять: переименуйте файлы или исправьте\n"
                "предложенные имена, и программа запомнит, где ошиблась.",
            )
            return
        path = self.learning.save_report()
        text = self.learning.report_text()
        preview = text if len(text) <= 2000 else text[:2000] + "\n…"
        agreed = messagebox.askyesno(
            "Отчёт об именах",
            "Будет открыта страница отправки отчёта в браузере.\n"
            "Отправляется только это:\n\n"
            f"{preview}\n\n"
            f"Отчёт сохранён: {path}\n\nОткрыть страницу отправки?",
        )
        if not agreed:
            self._log(f"Отчёт сохранён, отправка отменена: {path}")
            return
        command = self._updater_command(
            ["--feedback", str(path), "--repository", self.config.update.repository]
        )
        if command is None:
            messagebox.showinfo(
                "Отчёт об именах",
                f"Отчёт сохранён:\n{path}\n\nПриложите его к обращению вручную.",
            )
            return
        try:
            subprocess.Popen(  # noqa: S603 — список аргументов, без оболочки
                command, **hidden_process_options()
            )
            self._log("Открыта страница отправки отчёта об именах.")
        except (OSError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Отчёт об именах", f"Не удалось открыть страницу: {exc}")

    # --- обновления --------------------------------------------------------

    def _updater_command(self, arguments: list[str]) -> list[str] | None:
        """Команда запуска отдельной программы обновления.

        Обновление вынесено в самостоятельный исполняемый файл: сама программа
        обработки документов не содержит сетевого кода (раздел 3 ТЗ).
        """
        import sys

        candidates = [
            self.paths.root / ("DocRenamerUpdate.exe" if os.name == "nt" else "DocRenamerUpdate"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate), *arguments]
        if not getattr(sys, "frozen", False):
            return [sys.executable, "-m", "docrenamer_updater", *arguments]
        return None

    def _check_updates(self) -> None:
        """Проверить наличие новой версии по команде пользователя."""
        import json
        import subprocess

        command = self._updater_command(
            ["--check", "--json", "--current", __version__,
             "--repository", self.config.update.repository]
        )
        if command is None:
            messagebox.showinfo(
                "Обновления",
                "Программа обновления не найдена рядом с приложением.\n"
                "Скачайте новую версию со страницы релизов вручную.",
            )
            return

        def work() -> None:
            try:
                completed = subprocess.run(  # noqa: S603 — список аргументов, без оболочки
                    command,
                    shell=False,
                    capture_output=True,
                    timeout=120,
                    check=False,
                    **hidden_process_options(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.events.put(("error", f"Проверка обновлений не выполнена: {exc}"))
                return
            output = completed.stdout.decode("utf-8", errors="replace").strip()
            try:
                payload = json.loads(output.splitlines()[-1]) if output else {}
            except (json.JSONDecodeError, IndexError):
                payload = {}
            self.events.put(("update", payload))
            self.events.put(("done", "Проверка обновлений завершена"))

        self._run_async(work)

    def _handle_update_answer(self, payload: dict[str, Any]) -> None:
        """Показать результат проверки и, при согласии, установить обновление."""
        if payload.get("error"):
            messagebox.showwarning("Обновления", str(payload["error"]))
            return
        if not payload.get("update"):
            self._log("Установлена последняя версия.")
            messagebox.showinfo("Обновления", "У вас последняя версия.")
            return

        version = str(payload.get("version", ""))
        self._log(f"Доступна версия {version}.")
        if not messagebox.askyesno(
            "Доступно обновление",
            f"Доступна версия {version} (установлена {__version__}).\n\n"
            "Скачать и установить сейчас? Программа закроется и запустится заново.",
        ):
            return

        import subprocess
        import sys

        restart = str(self.paths.root / "DocRenamer.exe") if os.name == "nt" else sys.executable
        command = self._updater_command(
            ["--install", "--current", __version__,
             "--repository", self.config.update.repository, "--restart", restart]
        )
        if command is None:
            return
        try:
            subprocess.Popen(  # noqa: S603
                command, shell=False, close_fds=True, **hidden_process_options()
            )
        except (OSError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Обновления", f"Не удалось запустить обновление: {exc}")
            return
        self.app.cleanup()
        self.root.destroy()

    # --- готовность комплекта ---------------------------------------------

    def _selftest(self, *, probe_model: bool = True, quiet: bool = False) -> None:
        """Проверить, что всё необходимое на месте и разбор работает."""
        from docrenamer.selftest import run_selftest

        def work() -> None:
            report = run_selftest(self.config, self.paths, probe_model=probe_model)
            self.events.put(("readiness", report))
            if not quiet:
                for line in report.format_text().splitlines():
                    self.events.put(("log", line))
            self.events.put(("done", report.verdict))

        if quiet:
            threading.Thread(target=work, daemon=True).start()
            return
        self._run_async(work)

    def _show_readiness(self, report: Any) -> None:
        """Обновить значок готовности в заголовке окна."""
        self.readiness_var.set(report.badge)
        if report.failed:
            style = "Error.TLabel"
        elif report.warnings:
            style = "Warn.TLabel"
        else:
            style = "Local.TLabel"
        self.readiness_label.configure(style=style)
        details = "\n".join(
            f"{check.icon} {check.name}: {check.detail}" for check in report.checks
        )
        Tooltip(self.readiness_label, details)

    # --- план --------------------------------------------------------------

    def _show_files(self, files: list[Any]) -> None:
        """Показать найденные файлы сразу после сканирования."""
        self.plan = None
        self.nodes = {}
        self.tree.delete(*self.tree.get_children())
        self.tree.heading("confidence", text="Размер")
        root = self.directory or (files[0].path.parent if files else Path("."))
        for index, scanned in enumerate(files):
            size = scanned.size / 1024
            parent = self._folder_node(scanned.path.parent, root)
            self.tree.insert(
                parent,
                "end",
                iid=str(index),
                text=scanned.path.name,
                values=(
                    "",
                    "—",
                    f"{size:.0f} КБ" if size < 1024 else f"{size / 1024:.1f} МБ",
                    "Найден",
                ),
                tags=("warn",),
            )
        self._set_details(
            f"Найдено файлов: {len(files)}.\n"
            "Нажмите «Предпросмотр», чтобы разобрать их и увидеть предлагаемые имена."
        )

    def _show_plan(self, plan: RenamePlan) -> None:
        self.plan = plan
        self.nodes = {}
        self.tree.heading("confidence", text="Уверенность")
        self.tree.delete(*self.tree.get_children())

        # Порядок показа: сначала файлы корня, затем папка и всё, что в ней.
        # Дерево повторяет то, что человек видит в проводнике, и границу между
        # корнем и вложенной папкой видно сразу.
        root = _resolved(plan.root)
        files_by_directory: dict[Path, list[tuple[int, PlanItem]]] = {}
        folder_rows: dict[Path, str] = {}
        for index, item in enumerate(plan.items):
            if item.is_folder:
                folder_rows[_resolved(item.source_path)] = str(index)
                continue
            directory = _resolved(item.source_path.parent)
            files_by_directory.setdefault(directory, []).append((index, item))

        children: dict[Path, set[Path]] = {}
        for directory in set(files_by_directory) | set(folder_rows):
            current = directory
            while current != root and root in current.parents:
                children.setdefault(current.parent, set()).add(current)
                current = current.parent

        def build(directory: Path) -> None:
            parent = self._folder_node(directory, root, folder_rows)
            for index, item in sorted(
                files_by_directory.get(directory, []),
                key=lambda pair: pair[1].source_path.name.casefold(),
            ):
                self.tree.insert(
                    parent,
                    "end",
                    iid=str(index),
                    text=plan_row_label(item),
                    values=plan_row_values(item),
                    tags=(row_tag(item),),
                )
            for subdirectory in sorted(
                children.get(directory, ()), key=lambda path: path.name.casefold()
            ):
                build(subdirectory)

        build(root)
        for node in self.nodes.values():
            self.tree.item(node, open=True)
        self._update_select_all_label()
        for key, value in plan.counters().items():
            self._log(f"{key}: {value}")

    def _folder_node(
        self,
        directory: Path,
        root: Path,
        folder_rows: dict[Path, str] | None = None,
    ) -> str:
        """Узел дерева для папки; при необходимости создаётся вместе с верхними.

        Папка, для которой есть строка плана, сама и служит узлом: её галочка
        распространяется на всё содержимое. Для остальных создаётся простая
        группа — она ничего не переименовывает, но показывает вложенность.
        """
        directory = _resolved(directory)
        root = _resolved(root)
        if directory == root or root not in directory.parents:
            return ""
        known = self.nodes.get(directory)
        if known is not None:
            return known
        parent = self._folder_node(directory.parent, root, folder_rows)
        row = (folder_rows or {}).get(directory)
        if row is not None and self.plan is not None:
            item = self.plan.items[int(row)]
            self.tree.insert(
                parent,
                "end",
                iid=row,
                text=plan_row_label(item),
                values=plan_row_values(item),
                tags=(row_tag(item),),
                open=True,
            )
            node = row
        else:
            node = f"dir:{directory}"
            self.tree.insert(
                parent,
                "end",
                iid=node,
                text=f"📁 {directory.name}",
                values=("", "—", "", "папка"),
                tags=("warn",),
                open=True,
            )
        self.nodes[directory] = node
        return node

    def _clear_plan(self, reason: str) -> None:
        """Убрать список после операции: имена файлов уже изменились.

        Иначе на экране остаётся план, который больше не соответствует
        содержимому папки.
        """
        self.plan = None
        self.nodes = {}
        self.tree.delete(*self.tree.get_children())
        self._set_details(reason)
        self._log(reason)

    def _on_click(self, event: tk.Event) -> str | None:
        """Щелчок по колонке с галочкой — сразу переключает строку.

        С Shift или Ctrl щелчок не перехватывается: тогда человек выделяет
        несколько строк, а не отмечает одну.
        """
        if self.plan is None:
            return None
        state = int(event.state) if str(event.state).isdigit() else 0
        if state & 0x0001 or state & 0x0004:  # Shift или Ctrl
            return None
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tree.identify_column(event.x) != "#1":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self._set_row_selected(row, toggle=True)
        return "break"

    def _on_double_click(self, event: tk.Event) -> str:
        """Двойной щелчок: по имени — правка, в остальном — отметка."""
        if self.plan is None:
            return "break"
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if row and column == "#2":
            self._edit_name(row)
            return "break"
        self._toggle_selected()
        return "break"

    def _edit_selected_name(self) -> str:
        """Изменить имя выбранной строки (кнопка и клавиша F2)."""
        selection = self.tree.selection()
        if selection:
            self._edit_name(selection[0])
        elif self.plan is not None:
            messagebox.showinfo(
                "Изменение имени", "Выберите строку, имя которой нужно изменить."
            )
        return "break"

    def _merge_selected(self) -> None:
        """Объединить файлы в один документ по решению человека.

        Программа не всегда может понять, что перед ней страницы: сканы без
        распознавания ничем не отличаются от отдельных снимков. Тогда решает
        человек — и выбирает страницы прямо в открывшемся окне.
        """
        if self.plan is None:
            messagebox.showinfo("Один документ", "Сначала нажмите «Предпросмотр».")
            return

        preselected = [item for item in self._selected_plan_items() if not item.is_folder]
        folders = {item.source_path.parent for item in preselected}
        candidates = [
            item
            for item in self.plan.items
            if not item.is_folder
            and (not folders or item.source_path.parent in folders)
        ]
        if len(candidates) < 2:
            messagebox.showinfo(
                "Один документ",
                "Объединять нечего: нужно хотя бы два файла в одной папке.",
            )
            return

        dialog = MergeDialog(
            self.root,
            candidates,
            preselected=preselected,
            suggestion=self._merge_suggestion(preselected or candidates),
            root=self.plan.root,
            on_add=self._plan_item_for,
        )
        answer = dialog.show()
        if answer is None:
            return
        pages, name = answer
        # Файлы, добавленные в окне вручную, становятся частью плана: иначе
        # переименовать их будет нечем.
        plan = self.plan
        for item in dialog.added:
            if item in pages:
                plan.items.append(item)
        accepted, message = merge_as_document(plan, pages, name)
        if not accepted:
            # Объединение не состоялось — добавленные строки в плане не нужны.
            plan.items = [item for item in plan.items if item not in dialog.added]
            messagebox.showwarning("Один документ", message)
            return
        if dialog.added:
            # Список получил новые строки — проще перерисовать его целиком.
            self._show_plan(plan)
        else:
            self._refresh_rows(pages)
        self._update_select_all_label()
        self._log(message)
        for item in pages:
            self.learning.record_plan_item(item, event="merged")

    def _plan_item_for(self, path: Path) -> PlanItem | None:
        """Строка плана для файла, добавленного человеком вручную."""
        if self.plan is None:
            return None
        for item in self.plan.items:
            if item.source_path == path:
                return item
        return make_plan_item(path, config=self.config)

    def _show_row_menu(self, event: tk.Event) -> str | None:
        """Показать меню для строки под указателем."""
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self.tree.focus(row)
        try:
            self.row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.row_menu.grab_release()
        return "break"

    def _rescan_selected(self) -> str:
        """Разобрать выбранные файлы заново.

        Обстановка меняется: поставили распознавание, дополнили справочник
        видов документов — и файл, который вчера не поддался, сегодня получит
        имя. Пересобирать ради этого весь план не нужно.
        """
        if self.plan is None:
            messagebox.showinfo("Пересканирование", "Сначала нажмите «Предпросмотр».")
            return "break"
        items = [item for item in self._selected_plan_items() if not item.is_folder]
        if not items:
            messagebox.showinfo("Пересканирование", "Выберите файл в списке.")
            return "break"
        paths = [item.source_path for item in items]
        plan = self.plan

        def work() -> None:
            updated = self.app.reanalyze(plan, paths)
            self.events.put(("rows", updated))
            self.events.put(("done", f"Разобрано заново: {len(updated)}"))

        self._run_async(work)
        return "break"

    def _scrub_selected(self) -> None:
        """Снять метаданные с выбранных файлов.

        Единственная операция программы, которая меняет сам файл, поэтому
        человеку прямо сказано, что именно будет удалено, чего очистка не
        делает и что замена исходных файлов необратима.
        """
        items = [item for item in self._selected_plan_items() if not item.is_folder]
        if not items:
            messagebox.showinfo(
                "Очистка метаданных",
                "Отметьте файлы, с которых нужно снять метаданные.\n"
                "Несколько строк выбираются мышью с Ctrl или Shift.",
            )
            return
        supported = [item for item in items if can_scrub(item.source_path)]
        if not supported:
            messagebox.showinfo(
                "Очистка метаданных",
                "Для выбранных форматов очистка не поддержана.\n"
                "Поддерживаются JPEG, PNG, TIFF, WEBP, PDF, DOCX, XLSX, PPTX.",
            )
            return

        skipped = len(items) - len(supported)
        question = (
            f"Будет очищено файлов: {len(supported)}."
            + (f"\nПропущено (формат не поддержан): {skipped}." if skipped else "")
            + "\n\nЧто снимается:\n"
            "• у снимков — EXIF, GPS, модель камеры, миниатюра;\n"
            "• у PDF — автор, программа, даты, XMP;\n"
            "• у Office — автор, кем изменён, организация, время правки.\n\n"
            "Чего очистка не делает:\n"
            "• не меняет сам текст: подпись и фамилия внутри документа остаются;\n"
            "• не убирает исправления и примечания Word — это содержимое;\n"
            "• не отменяет копий файла, сохранённых в другом месте.\n\n"
            "Очищенные копии будут сложены в подпапку «Без метаданных».\n"
            "Заменить вместо этого исходные файлы?\n"
            "«Нет» — сохранить копии, исходные не трогать."
        )
        answer = messagebox.askyesnocancel("Очистка метаданных", question)
        if answer is None:
            return
        replace = bool(answer)
        if replace and not messagebox.askyesno(
            "Замена исходных файлов",
            "Исходные файлы будут заменены очищенными.\n"
            "Вернуть удалённые метаданные будет нельзя — отмены у этой\n"
            "операции нет.\n\nПродолжить?",
        ):
            return

        paths = [item.source_path for item in supported]

        def work() -> None:
            report = self.app.scrub(paths, replace=replace)
            self.events.put(("log", f"Отчёт об очистке: {report.report_path}"))
            self.events.put(
                (
                    "done",
                    f"Очистка: обработано {report.cleaned} из {report.total}"
                    + (f", ошибок {report.failed}" if report.failed else ""),
                )
            )
            if replace:
                self.events.put(
                    ("plan_cleared", "Файлы очищены — список обновите предпросмотром.")
                )

        self._run_async(work)

    def _selected_plan_items(self) -> list[PlanItem]:
        """Строки плана под выделением, включая содержимое выбранных папок."""
        if self.plan is None:
            return []
        collected: list[PlanItem] = []
        seen: set[int] = set()

        def add(row: str) -> None:
            try:
                index = int(row)
            except ValueError:
                index = -1
            if index >= 0 and index not in seen:
                seen.add(index)
                collected.append(self.plan.items[index])  # type: ignore[union-attr]
            for child in self.tree.get_children(row):
                add(child)

        for row in self.tree.selection():
            add(row)
        return collected

    def _merge_suggestion(self, pages: list[PlanItem]) -> str:
        """Имя, предлагаемое для объединённого документа."""
        for item in pages:
            analysis = item.analysis
            if analysis is None:
                continue
            value = analysis.document_type.value if analysis.document_type else ""
            if value and not analysis.metadata.get("category_label_type"):
                people = [person.name.split()[0] for person in analysis.main_persons[:1]]
                return "_".join([str(value), *people])
        return pages[0].source_path.parent.name

    def _refresh_rows(self, items: list[PlanItem]) -> None:
        """Перерисовать строки, изменённые вне обычного хода работы."""
        if self.plan is None:
            return
        for item in items:
            row = str(self.plan.items.index(item))
            if self.tree.exists(row):
                self.tree.item(
                    row,
                    text=plan_row_label(item),
                    values=plan_row_values(item),
                    tags=(row_tag(item),),
                )

    def _edit_name(self, row: str) -> None:
        """Заменить предложенное имя на введённое человеком (раздел 79 ТЗ).

        Программа предлагает, решает человек. Введённое имя проходит те же
        проверки: запрещённые символы, длина, расширение, занятость имени.
        """
        from tkinter import simpledialog

        if self.plan is None:
            return
        try:
            item = self.plan.items[int(row)]
        except (ValueError, IndexError):
            return
        current = item.proposed_filename or item.source_path.name
        answer = simpledialog.askstring(
            "Изменение имени",
            f"Сейчас:  {item.source_path.name}\n\nНовое имя:",
            initialvalue=current,
            parent=self.root,
        )
        if answer is None:
            return
        before = item.proposed_filename
        accepted, message = set_manual_name(self.plan, item, answer)
        if not accepted:
            messagebox.showwarning("Изменение имени", message)
            return
        self.tree.item(
            row,
            text=plan_row_label(item),
            values=plan_row_values(item),
            tags=(row_tag(item),),
        )
        self._update_select_all_label()
        self._show_details()
        self._log(f"{item.source_path.name}: {message}")
        # Правка руками — самый ценный отзыв об алгоритме: программа
        # запоминает обезличенную суть исправления (раздел 63 ТЗ).
        self.learning.record_edit(item, proposed=before, chosen=item.proposed_filename)

    def _toggle_selected(self, _event: object = None) -> str:
        """Включить или исключить строку плана (раздел 79 ТЗ)."""
        if self.plan is None:
            return "break"
        selection = self.tree.selection()
        if selection:
            self._set_row_selected(selection[0], toggle=True)
        return "break"

    def _set_row_selected(self, row: str, *, toggle: bool = False, value: bool = False) -> None:
        """Обновить отметку строки и её вид.

        Отметка на папке распространяется на всё, что внутри: одним нажатием
        можно и взять целиком, и исключить целиком, чтобы заняться папкой
        отдельно.
        """
        if self.plan is None:
            return
        children = self.tree.get_children(row)
        try:
            item = self.plan.items[int(row)]
        except (ValueError, IndexError):
            # Строка-группа: своего переименования нет, но содержимое отметить
            # всё равно нужно.
            if children:
                target = value if not toggle else not self._subtree_selected(row)
                for child in children:
                    self._set_row_selected(child, value=target)
                self._update_select_all_label()
            return
        if not item.is_rename and not children:
            return
        if item.is_rename:
            item.selected = (not item.selected) if toggle else value
        if children:
            target = item.selected
            if not item.is_rename:
                target = (not self._subtree_selected(row)) if toggle else value
            for child in children:
                self._set_row_selected(child, value=target)
        if not item.is_rename:
            self._update_select_all_label()
            return
        self.tree.item(
            row,
            text=plan_row_label(item),
            values=plan_row_values(item),
            tags=(row_tag(item),),
        )
        self._update_select_all_label()

    def _subtree_selected(self, row: str) -> bool:
        """Отмечено ли всё внутри строки-группы."""
        if self.plan is None:
            return False
        marked: list[bool] = []
        for child in self.tree.get_children(row):
            try:
                item = self.plan.items[int(child)]
            except (ValueError, IndexError):
                marked.append(self._subtree_selected(child))
                continue
            if item.is_rename:
                marked.append(item.selected)
        return bool(marked) and all(marked)

    def _toggle_all(self) -> None:
        """Отметить или снять все строки, которые можно переименовать."""
        if self.plan is None:
            return
        renameable = [
            (str(index), item)
            for index, item in enumerate(self.plan.items)
            if item.is_rename
        ]
        if not renameable:
            return
        select = not all(item.selected for _, item in renameable)
        for row, _item in renameable:
            self._set_row_selected(row, value=select)
        self._update_select_all_label()
        self._log(
            f"Отмечено файлов: {sum(1 for _, i in renameable if i.selected)} из {len(renameable)}"
        )

    def _update_select_all_label(self) -> None:
        """Кнопка называется по тому, что она сделает при нажатии."""
        if self.plan is None:
            self.select_all_var.set("Выбрать все")
            return
        renameable = [item for item in self.plan.items if item.is_rename]
        all_selected = bool(renameable) and all(item.selected for item in renameable)
        self.select_all_var.set("Снять все" if all_selected else "Выбрать все")

    # --- восстановление и закрытие -----------------------------------------

    def _check_recovery(self) -> None:
        """Предложить действия по незавершённой сессии (раздел 83 ТЗ)."""
        incomplete = find_incomplete_sessions(self.paths.manifests_dir)
        if not incomplete:
            return
        manifest = incomplete[-1]
        self._log(f"Обнаружена незавершённая сессия: {manifest.name}")
        if messagebox.askyesno(
            "Незавершённая сессия",
            f"Обнаружена незавершённая сессия:\n{manifest.name}\n\n"
            "Откатить выполненные переименования?",
        ):
            def work() -> None:
                report = self.app.undo(manifest)
                self.events.put(
                    ("plan_cleared", "Прежние имена восстановлены после незавершённой сессии.")
                )
                self.events.put(("done", f"Откат: восстановлено {report.restored}"))

            self._run_async(work)

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno("DocRenamer", "Операция выполняется. Закрыть окно?"):
                return
            self.app.cancel()
        self.app.cleanup()
        self.root.destroy()

    def run(self) -> int:
        self.app.startup_maintenance()
        self.root.mainloop()
        return 0


class SettingsDialog:
    """Диалог настроек (раздел 57 ТЗ)."""

    def __init__(self, parent: tk.Tk, config: Config, paths: AppPaths) -> None:
        self.config = config
        self.paths = paths
        self.window = tk.Toplevel(parent)
        self.window.title("Настройки")
        self.window.configure(bg=COLORS["bg"])
        self.window.transient(parent)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)

        self.recursive = tk.BooleanVar(value=config.recursive)
        self.use_ai = tk.BooleanVar(value=config.ai.enabled)
        self.use_ocr = tk.BooleanVar(value=config.ocr.enabled)
        self.use_exif = tk.BooleanVar(value=config.media.use_exif)
        self.use_ffprobe = tk.BooleanVar(value=config.media.use_ffprobe)
        self.inspect_archives = tk.BooleanVar(value=True)
        self.include_gps = tk.BooleanVar(value=config.media.include_gps_coordinates)

        for text, variable, key in (
            ("Включая подпапки", self.recursive, "set_recursive"),
            ("Использовать локальную модель", self.use_ai, "set_ai"),
            ("Распознавать сканы", self.use_ocr, "set_ocr"),
            ("Читать метаданные фотографий", self.use_exif, "set_exif"),
            ("Читать метаданные видео и аудио", self.use_ffprobe, "set_media"),
            ("Читать список содержимого архивов", self.inspect_archives, "set_archives"),
            ("Добавлять координаты в имя фотографии", self.include_gps, "set_gps"),
        ):
            box = ttk.Checkbutton(frame, text=text, variable=variable)
            box.pack(anchor="w", pady=PAD_XS)
            Tooltip(box, TOOLTIPS[key])

        grid = ttk.Frame(frame)
        grid.pack(fill="x", pady=(10, 4))
        ttk.Label(grid, text="Порог уверенности:").grid(row=0, column=0, sticky="w")
        self.threshold = tk.StringVar(value=f"{config.naming.confidence_threshold:.2f}")
        threshold_entry = ttk.Entry(grid, textvariable=self.threshold, width=8)
        threshold_entry.grid(row=0, column=1, padx=PAD_M)
        Tooltip(threshold_entry, TOOLTIPS["set_threshold"])
        ttk.Label(grid, text="Максимальная длина имени:").grid(row=1, column=0, sticky="w")
        self.max_length = tk.StringVar(value=str(config.naming.max_filename_length))
        length_entry = ttk.Entry(grid, textvariable=self.max_length, width=8)
        length_entry.grid(row=1, column=1, padx=PAD_M)
        Tooltip(length_entry, TOOLTIPS["set_length"])

        model = self.paths.models_dir / Path(config.ai.model_path).name
        ttk.Label(frame, text="Модель:", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(
            frame,
            text=f"{model}  {'— найдена' if model.is_file() else '— не найдена'}",
            style="Muted.TLabel",
        ).pack(anchor="w")
        ttk.Label(frame, text="OCR:", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(frame, text=config.ocr.language_spec, style="Muted.TLabel").pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Сохранить", style="Accent.TButton", command=self._save).pack(
            side="right"
        )
        ttk.Button(buttons, text="Отмена", command=self.window.destroy).pack(
            side="right", padx=6
        )

    def _save(self) -> None:
        try:
            threshold = float(self.threshold.get().replace(",", "."))
            max_length = int(self.max_length.get())
        except ValueError:
            messagebox.showerror("Настройки", "Порог и длина имени должны быть числами.")
            return
        self.config.recursive = self.recursive.get()
        self.config.ai.enabled = self.use_ai.get()
        self.config.ocr.enabled = self.use_ocr.get()
        self.config.media.use_exif = self.use_exif.get()
        self.config.media.use_ffprobe = self.use_ffprobe.get()
        self.config.media.include_gps_coordinates = self.include_gps.get()
        self.config.naming.confidence_threshold = max(0.0, min(1.0, threshold))
        self.config.naming.max_filename_length = max(24, min(240, max_length))
        try:
            self.config.save(self.paths.config_file)
        except OSError as exc:
            messagebox.showerror("Настройки", f"Не удалось сохранить настройки:\n{exc}")
            return
        self.window.destroy()


def run_gui(
    config: Config | None = None,
    paths: AppPaths | None = None,
    initial_directory: Path | None = None,
) -> int:
    """Запустить графический интерфейс."""
    app_paths = paths or default_paths()
    app_config = config or load_config(paths=app_paths)
    gui = DocRenamerGUI(app_config, app_paths, initial_directory)
    return gui.run()
