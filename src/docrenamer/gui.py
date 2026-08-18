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
    "bg": "#1e2126",
    "panel": "#262a31",
    "field": "#1a1d22",
    "text": "#d8dee9",
    "muted": "#8b93a1",
    "accent": "#4fa3ff",
    "ok": "#6fcf7f",
    "warn": "#e2b344",
    "error": "#e06c75",
}

MONOSPACE = ("Consolas", 10) if tk.TkVersion else ("Courier", 10)

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
        self.root.geometry("1000x680")
        self.root.minsize(820, 560)
        self.root.configure(bg=COLORS["bg"])
        self._build_style()
        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)
        self.root.after(200, self._check_recovery)

    # --- построение интерфейса --------------------------------------------

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:  # pragma: no cover — тема зависит от системы
            pass
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure(
            "TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 10)
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Local.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["ok"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TButton", background=COLORS["panel"], foreground=COLORS["text"], padding=6
        )
        style.map(
            "TButton",
            background=[("active", COLORS["accent"]), ("disabled", COLORS["panel"])],
            foreground=[("disabled", COLORS["muted"])],
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#10141a",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TRadiobutton", background=COLORS["bg"], foreground=COLORS["text"]
        )
        style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure(
            "TEntry", fieldbackground=COLORS["field"], foreground=COLORS["text"]
        )
        style.configure(
            "Treeview",
            background=COLORS["field"],
            fieldbackground=COLORS["field"],
            foreground=COLORS["text"],
            rowheight=22,
        )
        style.configure("Treeview.Heading", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure(
            "TProgressbar", background=COLORS["accent"], troughcolor=COLORS["field"]
        )

    def _build_widgets(self) -> None:
        header = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text="DocRenamer Offline", font=("Segoe UI", 13, "bold")).pack(
            side="left"
        )
        badge = ttk.Label(header, text="● LOCAL ONLY", style="Local.TLabel")
        badge.pack(side="right")
        Tooltip(badge, LOCAL_ONLY_TOOLTIP)

        chooser = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        chooser.pack(fill="x")
        ttk.Label(chooser, text="Папка:").pack(side="left")
        self.directory_var = tk.StringVar(value=str(self.directory or ""))
        entry = ttk.Entry(chooser, textvariable=self.directory_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(chooser, text="Выбрать", command=self._choose_directory).pack(side="left")

        modes = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        modes.pack(fill="x")
        self.mode_var = tk.StringVar(value="preview")
        for value, label in (
            ("analyze", "Анализ"),
            ("preview", "Предпросмотр"),
            ("apply", "Применить"),
        ):
            ttk.Radiobutton(modes, text=label, value=value, variable=self.mode_var).pack(
                side="left", padx=(0, 14)
            )
        self.recursive_var = tk.BooleanVar(value=self.config.recursive)
        ttk.Checkbutton(modes, text="Рекурсивно", variable=self.recursive_var).pack(side="left")

        panes = ttk.PanedWindow(self.root, orient="vertical")
        panes.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        preview_frame = ttk.Frame(panes)
        self.tree = ttk.Treeview(
            preview_frame,
            columns=("current", "proposed", "confidence", "status"),
            show="headings",
            selectmode="browse",
        )
        for column, title, width in (
            ("current", "Текущее имя", 240),
            ("proposed", "Предлагаемое имя", 420),
            ("confidence", "Уверенность", 100),
            ("status", "Состояние", 180),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        self.tree.tag_configure("ok", foreground=COLORS["ok"])
        self.tree.tag_configure("warn", foreground=COLORS["warn"])
        self.tree.tag_configure("error", foreground=COLORS["error"])
        scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._toggle_selected)
        panes.add(preview_frame, weight=3)

        log_frame = ttk.Frame(panes)
        self.log = tk.Text(
            log_frame,
            height=10,
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=MONOSPACE,
            relief="flat",
            wrap="none",
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        panes.add(log_frame, weight=2)

        status = ttk.Frame(self.root, padding=(12, 0, 12, 4))
        status.pack(fill="x")
        self.progress = ttk.Progressbar(status, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="right", padx=(10, 0)
        )

        buttons = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        self.scan_button = ttk.Button(buttons, text="Сканировать", command=self._scan)
        self.scan_button.pack(side="left")
        self.preview_button = ttk.Button(buttons, text="Предпросмотр", command=self._preview)
        self.preview_button.pack(side="left", padx=6)
        self.apply_button = ttk.Button(
            buttons, text="Переименовать", style="Accent.TButton", command=self._apply
        )
        self.apply_button.pack(side="left", padx=6)
        self.undo_button = ttk.Button(buttons, text="Отменить последнее", command=self._undo)
        self.undo_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(buttons, text="Стоп", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Открыть лог", command=self._open_logs).pack(side="right")
        ttk.Button(buttons, text="⚙ Настройки", command=self._open_settings).pack(
            side="right", padx=6
        )

        self._log(f"DocRenamer Offline {__version__}. Все данные обрабатываются локально.")

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
