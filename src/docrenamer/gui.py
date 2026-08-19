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
    merge_as_document,
    set_manual_name,
)
from docrenamer.paths import AppPaths, default_paths
from docrenamer.presentation import (
    plan_row_label,
    plan_row_values,
    progress_label,
    row_tag,
)
from docrenamer.preview import (
    folder_preview,
    format_stamp,
    metadata_summary,
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
BUTTON_WIDTH = 15
ROW_HEIGHT = 26
DETAILS_HEIGHT = 3
PROGRESS_HEIGHT = 6
LEFT_MIN_WIDTH = 620
RIGHT_MIN_WIDTH = 360
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 720
WINDOW_MIN_WIDTH = 940
WINDOW_MIN_HEIGHT = 600

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
    "merge": "Считать выбранные файлы страницами одного документа.\n"
             "Отметьте их мышью с Ctrl или Shift — или выберите папку целиком.\n"
             "Программа даст им общее имя с номерами страниц.",
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
             "Двойной щелчок по имени — правка вручную, пробел — отметка.",
    "select_all": "Отметить все файлы, для которых есть предложение.\n"
                  "Повторное нажатие снимает отметки.",
    "details": "Полные имена выбранного файла, причина решения и метаданные:\n"
               "размер, время изменения, контрольная сумма. При переименовании\n"
               "они не меняются — программа сверяет их до и после.",
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
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
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
        self.root.rowconfigure(2, weight=1)

        self._build_header()
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
        workspace.grid(row=2, column=0, sticky="nsew", padx=PAD_L)

        left = ttk.Frame(workspace, width=LEFT_MIN_WIDTH)
        left.columnconfigure(0, weight=1)
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
            columns=("mark", "proposed", "confidence", "status", "meta"),
            show="tree headings",
            # Несколько строк выбираются мышью с Ctrl или Shift: так
            # отмечаются страницы, которые надо объединить в один документ.
            selectmode="extended",
        )
        # Колонка дерева показывает вложенность: сначала файлы корня, затем
        # папка и её содержимое под ней — структуру видно без догадок.
        self.tree.heading("#0", text="Файл или папка")
        self.tree.column("#0", width=260, minwidth=140, stretch=False, anchor="w")
        columns: tuple[tuple[str, str, int, bool, bool], ...] = (
            ("mark", "✓", 40, True, False),
            ("proposed", "Предлагаемое имя", 420, False, True),
            ("confidence", "Уверенность", 110, True, False),
            ("status", "Состояние", 150, False, False),
            ("meta", "Метаданные", 170, False, False),
        )
        for column, title, width, centered, stretch in columns:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=36 if column == "mark" else 90,
                             stretch=stretch)
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

        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<F2>", lambda _event: self._edit_selected_name())
        # Одиночный щелчок по колонке с галочкой переключает строку сразу.
        self.tree.bind("<Button-1>", self._on_click, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        Tooltip(self.tree, TOOLTIPS["table"])

        # Подробности выбранной строки: длинные имена показываются целиком,
        # с переносом, а не обрезаются шириной колонки.
        details = ttk.Frame(left, style="Card.TFrame", padding=PAD_M)
        details.grid(row=2, column=0, sticky="ew", pady=(PAD_M, 0))
        details.columnconfigure(0, weight=1)
        self.details = tk.Text(
            details,
            height=DETAILS_HEIGHT,
            wrap="word",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=FONT_MONO,
            relief="flat",
            highlightthickness=0,
            state="disabled",
        )
        self.details.grid(row=0, column=0, sticky="ew")
        Tooltip(self.details, TOOLTIPS["details"])
        self._set_details("Выберите файл в списке, чтобы увидеть подробности.")

        right = ttk.Frame(workspace, width=RIGHT_MIN_WIDTH)
        right.columnconfigure(0, weight=1)
        # Предпросмотр занимает верх правой колонки, журнал — низ: содержимое
        # файла важнее хода работы, по нему и видно, верно ли имя.
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=2)
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

        ttk.Label(right, text="ЖУРНАЛ РАБОТЫ", style="Section.TLabel").grid(
            row=2, column=0, sticky="w", pady=(PAD_M, PAD_S)
        )
        log_frame = ttk.Frame(right)
        log_frame.grid(row=3, column=0, sticky="nsew")
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
        status = ttk.Frame(self.root, padding=(PAD_L, PAD_M, PAD_L, PAD_S))
        status.grid(row=3, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(status, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e", padx=(PAD_M, 0)
        )

    def _build_actions(self) -> None:
        """Ряд кнопок: слева действия над файлами, справа служебные."""
        actions = ttk.Frame(self.root, padding=(PAD_L, PAD_S, PAD_L, PAD_L))
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)

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

        service = (
            ("Изменить имя", self._edit_selected_name, "edit_name", 5),
            ("Один документ", self._merge_selected, "merge", 6),
            ("Самопроверка", self._selftest, "selftest", 7),
            ("Журнал", self._open_logs, "logs", 8),
            ("Улучшение", self._send_feedback, "feedback", 9),
            ("Настройки", self._open_settings, "settings", 10),
        )
        for text, command, key, column in service:
            button = ttk.Button(actions, text=text, width=BUTTON_WIDTH, command=command)
            button.grid(row=0, column=column, sticky="e", padx=(PAD_M, 0))
            Tooltip(button, TOOLTIPS[key])
        if self.config.update.enabled:
            updates = ttk.Button(
                actions, text="Обновления", width=BUTTON_WIDTH, command=self._check_updates
            )
            updates.grid(row=0, column=11, sticky="e", padx=(PAD_M, 0))
            Tooltip(updates, TOOLTIPS["updates"])

    def _set_details(self, text: str) -> None:
        """Показать подробности выбранного файла."""
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

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
        data = None if item.is_folder else thumbnail_png(item.source_path)
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
        lines = [f"Сейчас:  {item.source_path.name}"]
        if item.is_rename:
            lines.append(f"Станет:  {item.proposed_filename}")
        lines.append(
            f"Уверенность: {item.confidence * 100:.0f}%    Состояние: {item.status}"
        )
        if item.message:
            lines.append(item.message)
        lines.append(metadata_summary(item))
        self._set_details("\n".join(lines))
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
                    self.progress.configure(maximum=max(1, total), value=done)
                    self.status_var.set(progress_label(done, total, stage))
                elif kind == "files":
                    self._show_files(payload)
                elif kind == "plan":
                    self._show_plan(payload)
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
        state = "disabled" if busy else "normal"
        for button in (
            self.scan_button,
            self.preview_button,
            self.apply_button,
            self.undo_button,
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
                    format_stamp(scanned.mtime),
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
                values=("", "—", "", "папка", ""),
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
        """Щелчок по колонке с галочкой — сразу переключает строку."""
        if self.plan is None:
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
        """Объединить выбранные файлы в один документ по решению человека.

        Программа не всегда может понять, что перед ней страницы: сканы без
        распознавания ничем не отличаются от отдельных снимков. Тогда решает
        человек, и его решение важнее любой догадки.
        """
        from tkinter import simpledialog

        if self.plan is None:
            messagebox.showinfo("Один документ", "Сначала нажмите «Предпросмотр».")
            return
        items = self._selected_plan_items()
        pages = [item for item in items if not item.is_folder]
        if len(pages) < 2:
            messagebox.showinfo(
                "Один документ",
                "Отметьте страницы одного документа: несколько файлов мышью\n"
                "с Ctrl или Shift — либо папку, в которой они лежат.",
            )
            return
        suggestion = self._merge_suggestion(pages)
        answer = simpledialog.askstring(
            "Один документ",
            f"Страниц выбрано: {len(pages)}.\n\nОбщее имя документа:",
            initialvalue=suggestion,
            parent=self.root,
        )
        if answer is None:
            return
        accepted, message = merge_as_document(self.plan, pages, answer)
        if not accepted:
            messagebox.showwarning("Один документ", message)
            return
        self._refresh_rows(pages)
        self._update_select_all_label()
        self._log(message)
        for item in pages:
            self.learning.record_plan_item(item, event="merged")

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
