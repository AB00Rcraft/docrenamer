"""Графический интерфейс на Tkinter + ttk (разделы 6, 57, 78–82 ТЗ).

Ни Electron, ни Chromium, ни встроенного веб-сервера. Интерфейс компактный,
тёмный, с моноширинным журналом и постоянным индикатором ``● LOCAL ONLY``.

Вся тяжёлая работа выполняется в рабочем потоке; виджеты обновляются только из
потока интерфейса через очередь событий (раздел 82 ТЗ).
"""

from __future__ import annotations

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
from docrenamer.logging.manifest import find_incomplete_sessions
from docrenamer.operations.planner import RenamePlan
from docrenamer.paths import AppPaths, default_paths
from docrenamer.presentation import format_plan_row, progress_label, row_tag

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
DETAILS_HEIGHT = 4
PROGRESS_HEIGHT = 6
LEFT_MIN_WIDTH = 620
RIGHT_MIN_WIDTH = 360
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 720
WINDOW_MIN_WIDTH = 940
WINDOW_MIN_HEIGHT = 600

LOCAL_ONLY_TOOLTIP = (
    "Все документы обрабатываются локально.\nСетевые AI API не используются."
)


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
        self.root.title(f"DocRenamer Offline {__version__}")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.root.configure(bg=COLORS["bg"])
        self._build_style()
        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)
        self.root.after(200, self._check_recovery)
        # Быстрая проверка готовности при запуске: без обращения к модели,
        # чтобы окно открывалось сразу.
        self.root.after(300, lambda: self._selftest(probe_model=False, quiet=True))

    # --- построение интерфейса --------------------------------------------

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

        self._log(f"DocRenamer Offline {__version__}. Все данные обрабатываются локально.")

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(PAD_L, PAD_M, PAD_L, PAD_S))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="DocRenamer Offline", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.readiness_var = tk.StringVar(value="… проверка готовности")
        self.readiness_label = ttk.Label(
            header, textvariable=self.readiness_var, style="Muted.TLabel"
        )
        self.readiness_label.grid(row=0, column=1, sticky="e", padx=(PAD_M, PAD_L))
        Tooltip(self.readiness_label, "Нажмите «Самопроверка», чтобы увидеть подробности.")

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
        ttk.Button(
            toolbar, text="Выбрать", width=BUTTON_WIDTH, command=self._choose_directory
        ).grid(row=0, column=2, sticky="e", padx=(PAD_M, 0))

        modes = ttk.Frame(toolbar)
        modes.grid(row=1, column=0, columnspan=3, sticky="w", pady=(PAD_M, 0))
        self.mode_var = tk.StringVar(value="preview")
        for index, (value, label) in enumerate(
            (("analyze", "Анализ"), ("preview", "Предпросмотр"), ("apply", "Применить"))
        ):
            ttk.Radiobutton(modes, text=label, value=value, variable=self.mode_var).grid(
                row=0, column=index, sticky="w", padx=(0, PAD_L)
            )
        self.recursive_var = tk.BooleanVar(value=self.config.recursive)
        ttk.Checkbutton(modes, text="Включая подпапки", variable=self.recursive_var).grid(
            row=0, column=3, sticky="w"
        )

    def _build_workspace(self) -> None:
        """Две колонки: список файлов и журнал."""
        workspace = ttk.PanedWindow(self.root, orient="horizontal")
        workspace.grid(row=2, column=0, sticky="nsew", padx=PAD_L)

        left = ttk.Frame(workspace, width=LEFT_MIN_WIDTH)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        workspace.add(left, weight=3)

        ttk.Label(left, text="ЧТО БУДЕТ ПЕРЕИМЕНОВАНО", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, PAD_S)
        )

        table = ttk.Frame(left)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table,
            columns=("current", "proposed", "confidence", "status"),
            show="headings",
            selectmode="browse",
        )
        for column, title, width, anchor, stretch in (
            ("current", "Текущее имя", 220, "w", False),
            ("proposed", "Предлагаемое имя", 420, "w", True),
            ("confidence", "Уверенность", 110, "center", False),
            ("status", "Состояние", 170, "w", False),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor, stretch=stretch, minwidth=90)
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
        self.tree.bind("<Double-1>", self._toggle_selected)
        self.tree.bind("<<TreeviewSelect>>", self._show_details)

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
        self._set_details("Выберите файл в списке, чтобы увидеть подробности.")

        right = ttk.Frame(workspace, width=RIGHT_MIN_WIDTH)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        workspace.add(right, weight=2)

        ttk.Label(right, text="ЖУРНАЛ РАБОТЫ", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, PAD_S)
        )
        log_frame = ttk.Frame(right)
        log_frame.grid(row=1, column=0, sticky="nsew")
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
        self.preview_button = ttk.Button(
            actions, text="Предпросмотр", width=BUTTON_WIDTH, command=self._preview
        )
        self.preview_button.grid(row=0, column=1, sticky="w", padx=(PAD_M, 0))
        self.apply_button = ttk.Button(
            actions,
            text="Переименовать",
            width=BUTTON_WIDTH,
            style="Accent.TButton",
            command=self._apply,
        )
        self.apply_button.grid(row=0, column=2, sticky="w", padx=(PAD_M, 0))
        self.undo_button = ttk.Button(
            actions, text="Отменить", width=BUTTON_WIDTH, command=self._undo
        )
        self.undo_button.grid(row=0, column=3, sticky="w", padx=(PAD_M, 0))
        self.stop_button = ttk.Button(
            actions, text="Стоп", width=BUTTON_WIDTH, command=self._stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=4, sticky="w", padx=(PAD_M, 0))

        ttk.Button(
            actions, text="Самопроверка", width=BUTTON_WIDTH, command=self._selftest
        ).grid(row=0, column=5, sticky="e", padx=(PAD_M, 0))
        ttk.Button(
            actions, text="Журнал", width=BUTTON_WIDTH, command=self._open_logs
        ).grid(row=0, column=6, sticky="e", padx=(PAD_M, 0))
        ttk.Button(
            actions, text="Настройки", width=BUTTON_WIDTH, command=self._open_settings
        ).grid(row=0, column=7, sticky="e", padx=(PAD_M, 0))

    def _set_details(self, text: str) -> None:
        """Показать подробности выбранного файла."""
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _show_details(self, _event: object = None) -> None:
        """Полные имена выбранного файла — без обрезки по ширине колонки."""
        if self.plan is None:
            return
        selection = self.tree.selection()
        if not selection:
            return
        item = self.plan.items[int(selection[0])]
        lines = [f"Сейчас:  {item.source_path.name}"]
        if item.is_rename:
            lines.append(f"Станет:  {item.proposed_filename}")
        lines.append(
            f"Уверенность: {item.confidence * 100:.0f}%    Состояние: {item.status}"
        )
        if item.message:
            lines.append(item.message)
        self._set_details("\n".join(lines))

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
                elif kind == "plan":
                    self._show_plan(payload)
                elif kind == "done":
                    self._finish(str(payload))
                elif kind == "readiness":
                    self._show_readiness(payload)
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
            self.events.put(("done", f"Найдено файлов: {len(files)}"))

        self._run_async(work)

    def _preview(self) -> None:
        directory = self._current_directory()
        if directory is None:
            return
        self.config.recursive = self.recursive_var.get()

        def work() -> None:
            plan = self.app.preview(directory)
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
                ("done", f"Восстановлено: {report.restored}, пропущено: {report.skipped}")
            )

        self._run_async(work)

    def _stop(self) -> None:
        self.app.cancel()
        self._log("Остановка: новые задачи не запускаются.")

    def _open_logs(self) -> None:
        """Открыть каталог журналов средствами системы."""
        import os
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

    def _show_plan(self, plan: RenamePlan) -> None:
        self.plan = plan
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(plan.items):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=format_plan_row(item),
                tags=(row_tag(item),),
            )
        for key, value in plan.counters().items():
            self._log(f"{key}: {value}")

    def _toggle_selected(self, _event: object = None) -> str:
        """Включить или исключить строку плана (раздел 79 ТЗ)."""
        if self.plan is None:
            return "break"
        selection = self.tree.selection()
        if not selection:
            return "break"
        index = int(selection[0])
        item = self.plan.items[index]
        if not item.is_rename:
            return "break"
        item.selected = not item.selected
        self.tree.item(selection[0], values=format_plan_row(item), tags=(row_tag(item),))
        return "break"

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

        for text, variable in (
            ("Рекурсивно", self.recursive),
            ("Использовать локальный ИИ", self.use_ai),
            ("OCR для сканов", self.use_ocr),
            ("Обрабатывать фото", self.use_exif),
            ("Обрабатывать видео/аудио", self.use_ffprobe),
            ("Анализировать архивы без распаковки", self.inspect_archives),
            ("Включать координаты GPS в имя", self.include_gps),
        ):
            ttk.Checkbutton(frame, text=text, variable=variable).pack(anchor="w", pady=2)

        grid = ttk.Frame(frame)
        grid.pack(fill="x", pady=(10, 4))
        ttk.Label(grid, text="Порог уверенности:").grid(row=0, column=0, sticky="w")
        self.threshold = tk.StringVar(value=f"{config.naming.confidence_threshold:.2f}")
        ttk.Entry(grid, textvariable=self.threshold, width=8).grid(row=0, column=1, padx=8)
        ttk.Label(grid, text="Максимальная длина имени:").grid(row=1, column=0, sticky="w")
        self.max_length = tk.StringVar(value=str(config.naming.max_filename_length))
        ttk.Entry(grid, textvariable=self.max_length, width=8).grid(row=1, column=1, padx=8)

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
