"""Подсказки не должны загораживать кнопки.

Подсказка, выскакивающая мгновенно, закрывает соседние кнопки как раз тогда,
когда человек ведёт к ним мышь. Поэтому она появляется только после
задержки, исчезает сама и убирается по нажатию.

Запускается там, где доступна графическая подсистема.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def widget():  # type: ignore[no-untyped-def]
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover — нет дисплея
        pytest.skip("графическая подсистема недоступна")
    root.withdraw()
    button = tk.Button(root, text="Сканировать")
    button.pack()
    yield button
    root.destroy()


def make_tip(widget, delay: int = 30, show: int = 10_000):  # type: ignore[no-untyped-def]
    from docrenamer.gui import Tooltip

    return Tooltip(widget, "Посмотреть, какие файлы есть в папке.", delay=delay, show=show)


def wait(widget, milliseconds: int) -> None:  # type: ignore[no-untyped-def]
    """Дать окну прожить заданное время, обрабатывая отложенные задачи."""
    widget.after(milliseconds, widget.quit)
    widget.mainloop()


def test_not_shown_at_once(widget) -> None:  # type: ignore[no-untyped-def]
    """Пока мышь только прошла над кнопкой, подсказки нет."""
    tip = make_tip(widget, delay=500)

    tip._schedule()

    assert tip.window is None


def test_shown_after_delay(widget) -> None:  # type: ignore[no-untyped-def]
    """Задержался на кнопке — подсказка появилась."""
    tip = make_tip(widget, delay=30)

    tip._schedule()
    wait(widget, 120)

    assert tip.window is not None


def test_hidden_by_itself(widget) -> None:  # type: ignore[no-untyped-def]
    """Подсказка держится недолго и уходит сама."""
    tip = make_tip(widget, delay=10, show=40)

    tip._schedule()
    wait(widget, 200)

    assert tip.window is None


def test_click_removes_tooltip(widget) -> None:  # type: ignore[no-untyped-def]
    """Нажали — подсказка не нужна."""
    tip = make_tip(widget, delay=10)
    tip._schedule()
    wait(widget, 80)
    assert tip.window is not None

    tip._hide()

    assert tip.window is None


def test_leaving_cancels_pending(widget) -> None:  # type: ignore[no-untyped-def]
    """Мышь ушла до срока — подсказка так и не появится."""
    tip = make_tip(widget, delay=60)

    tip._schedule()
    tip._hide()
    wait(widget, 150)

    assert tip.window is None


def test_text_is_replaced_not_doubled(widget) -> None:  # type: ignore[no-untyped-def]
    """Готовность обновляется в той же подсказке, а не заводит вторую."""
    tip = make_tip(widget, delay=10)

    tip.set_text("✓ OCR: найден")
    tip._schedule()
    wait(widget, 80)

    assert tip.text == "✓ OCR: найден"
    assert tip.window is not None
