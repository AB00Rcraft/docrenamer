"""Справка по человеку — не паспорт (разделы 63, 92 ТЗ).

В справке паспорт лишь одна строка среди даты рождения, ИНН, адреса и
имущества. Называть по ней весь документ нельзя: файл перестанет находиться и
будет выглядеть тем, чем не является.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths

DOSSIER = (
    "ОТЧЁТ ПО РЕЗУЛЬТАТАМ ПРОВЕРКИ ФИЗИЧЕСКОГО ЛИЦА\n"
    "Фамилия, имя, отчество: Шахманова Мария Петровна\n"
    "Дата рождения: 14.03.1985\n"
    "Паспорт: серия 45 12 номер 345678, выдан 20.04.2010\n"
    "ИНН: 771234567890\n"
    "СНИЛС: 123-456-789 00\n"
    "Адрес регистрации: город Москва, улица Тверская, дом 5\n"
    "Телефон: +7 900 123-45-67\n"
    "Транспортные средства: автомобиль Toyota Camry\n"
    "Недвижимость: квартира 68 кв. м\n"
    "Место работы: ООО «Альфа»\n"
    "Родственники и связи: супруг Шахманов Пётр Иванович\n"
)
PASSPORT = (
    "РОССИЙСКАЯ ФЕДЕРАЦИЯ\nПАСПОРТ\n"
    "выдан отделом УФМС России по городу Москве\n"
    "код подразделения 770-001\nШАХМАНОВА МАРИЯ ПЕТРОВНА\n"
    "место рождения гор. Москва\n"
)


def preview_names(config: Config, app_paths: AppPaths, workdir: Path) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    return {a.source_path.name: a.proposed_filename for a in app.analyze(app.scan(workdir))}


def test_report_about_person_is_not_a_passport(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Общий отчёт по человеку называется справкой, а не паспортом."""
    (workdir / "report.txt").write_text(DOSSIER, encoding="utf-8")

    name = preview_names(config, app_paths, workdir)["report.txt"]

    assert name.startswith("Справка_установочная"), name
    assert "Паспорт" not in name, name
    assert "ШахмановаМП" in name, name


def test_passport_scan_stays_a_passport(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Сам паспорт по-прежнему называется паспортом."""
    (workdir / "скан.txt").write_text(PASSPORT, encoding="utf-8")

    name = preview_names(config, app_paths, workdir)["скан.txt"]

    assert name.startswith("Паспорт"), name


def test_birth_date_is_not_the_document_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата рождения — не дата документа, и в имя она не идёт."""
    (workdir / "report.txt").write_text(
        DOSSIER + "Справка составлена 12 мая 2026 года.\n", encoding="utf-8"
    )

    name = preview_names(config, app_paths, workdir)["report.txt"]

    assert "12.05.2026" in name, name
    assert "14.03.1985" not in name, name
    assert "20.04.2010" not in name, name


def test_report_keeps_only_its_subject_person(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Справка составлена об одном человеке, родственники в имя не идут."""
    (workdir / "report.txt").write_text(DOSSIER, encoding="utf-8")

    name = preview_names(config, app_paths, workdir)["report.txt"]

    assert "ШахмановПИ" not in name, name
