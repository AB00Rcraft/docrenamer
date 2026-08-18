"""Сохранение осмысленных имён и многотомные документы.

Два правила, сформулированные при приёмке:

* если человек уже назвал файл по-русски и по делу — это имя не ломается,
  максимум дополняется датой по единому образцу;
* файлы, отличающиеся только номером, — это части одного документа, и номер
  части обязан сохраниться.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.extractors.series import detect_series, split_part
from docrenamer.naming.builder import is_meaningful_stem
from docrenamer.paths import AppPaths
from docrenamer.types import Status

DOCUMENT = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)

UNDATED = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)


def analyses_by_name(app: Application, directory: Path) -> dict[str, object]:
    return {a.source_path.name: a for a in app.analyze(app.scan(directory))}


# --- какие имена считаются осмысленными ------------------------------------


@pytest.mark.parametrize(
    "stem",
    [
        "Договор займа №17 от 18 августа 2026 года",
        "Постановление Иванова И.И.",
        "Акт сверки с ООО Альфа",
        "отчет за 2026 год",
        "Дело Петрова 1",
        "Постановление",
    ],
)
def test_human_names_are_recognized(stem: str) -> None:
    assert is_meaningful_stem(stem)


@pytest.mark.parametrize(
    "stem",
    [
        "IMG_0032",
        "scan0007",
        "DSC_1234",
        "VID_3871",
        "20260818_142203",
        "8f3a91c2e4b7",
        "Новый документ",
        "Новый документ 2",
        "Untitled document",
        "Документ1",
        "1",
        "",
    ],
)
def test_machine_names_are_not_protected(stem: str) -> None:
    assert not is_meaningful_stem(stem)


# --- сохранение хорошего имени ---------------------------------------------


def test_good_name_is_not_renamed_by_default(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Хорошее имя само не меняется, но вариант всё равно предлагается.

    Требование приёмки: галочка не стоит, решение принимает человек.
    """
    name = "Постановление от 27 июля 2026 года.txt"
    (workdir / name).write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert not item.selected, "хорошее имя не переименовывается само"
    assert item.status == Status.GOOD_NAME_KEPT.value
    assert item.proposed_filename != name, "вариант должен быть предложен"
    assert item.proposed_filename.startswith("Постановление_СПИ_")


def test_good_name_gets_a_proposal_in_our_style(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Для хорошего имени предлагается аккуратный вариант в общем стиле."""
    (workdir / "Постановление по делу Иванова.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("Постановление_СПИ_")
    assert item.proposed_filename.endswith("_27.07.2026.txt")
    assert not item.selected
    assert item.status == Status.GOOD_NAME_KEPT.value


def test_original_name_is_kept_verbatim_when_nothing_better_exists(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Если предложить нечего, прежнее имя сохраняется дословно."""
    (workdir / "Договор займа №17 «Альфа».txt").write_bytes(
        "Текст без реквизитов, дат и наименований.".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "Договор займа №17 «Альфа»" in item.proposed_filename or not item.proposed_filename
    assert not item.selected


def test_technical_name_is_fully_rebuilt(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Техническое имя заменяется полноценным, как и раньше."""
    (workdir / "scan0007.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("Постановление_СПИ_")
    assert "652102_26_77028-ИП" in item.proposed_filename


def test_preservation_can_be_disabled(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    config.naming.preserve_good_names = False
    (workdir / "Постановление по делу Иванова.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "Постановление_СПИ" in item.proposed_filename


def test_filesystem_date_does_not_touch_good_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата из файловой системы — не повод дополнять хорошее имя."""
    (workdir / "Заметки по встрече с подрядчиком.txt").write_bytes(
        "Обсудили сроки и смету, дата не указана".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename in ("", "Заметки по встрече с подрядчиком.txt")
    assert not item.selected


# --- многотомные документы --------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("Дело Петрова 1", ("Дело Петрова", 1, "")),
        ("Договор том 2", ("Договор", 2, "том")),
        ("Отчёт часть 3", ("Отчёт", 3, "часть")),
        ("Приложение (2)", ("Приложение", 2, "")),
        ("Акт part 2", ("Акт", 2, "часть")),
        ("Постановление", None),
        ("2", None),
    ],
)
def test_part_number_parsing(stem: str, expected: tuple[str, int, str] | None) -> None:
    assert split_part(stem) == expected


def test_series_requires_at_least_two_parts(tmp_path: Path) -> None:
    single = [tmp_path / "Дело Петрова 1.pdf"]
    assert detect_series(single) == {}


def test_volumes_keep_their_numbers(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Тома не сливаются в одно имя и не перенумеровываются заново."""
    for index in (1, 2, 3):
        (workdir / f"scan_{index}.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    names = {item.source_path.name: item.proposed_filename for item in plan.items}

    assert "_1_из_3_" in names["scan_1.txt"]
    assert "_2_из_3_" in names["scan_2.txt"]
    assert "_3_из_3_" in names["scan_3.txt"]
    # Числовой суффикс разрешения коллизий не появляется: имена и так разные.
    assert not any("__02" in name for name in names.values())


def test_explicit_volume_label_is_kept(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Слово «том» из исходного имени сохраняется, а не заменяется догадкой."""
    (workdir / "scan том 1.txt").write_bytes(DOCUMENT.encode())
    (workdir / "scan том 2.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert any("_том_1_" in item.proposed_filename for item in plan.items)
    assert any("_том_2_" in item.proposed_filename for item in plan.items)


def test_second_volume_inherits_missing_date_with_visible_source(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Том без шапки берёт дату у соседнего тома — с указанием источника."""
    (workdir / "scan_1.txt").write_bytes(DOCUMENT.encode())
    (workdir / "scan_2.txt").write_bytes(UNDATED.encode())

    app = Application(config, paths=app_paths)
    found = analyses_by_name(app, workdir)
    second = found["scan_2.txt"]

    assert second.document_date is not None
    assert second.document_date.value == "2026-07-27"
    assert "из файла «scan_1.txt»" in second.document_date.evidence
    assert second.document_date.confidence < found["scan_1.txt"].document_date.confidence
    assert second.has_status(Status.SERIES_PART_DETECTED)


def test_volumes_survive_apply_and_undo(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Полный цикл: тома переименованы по порядку и корректно откатываются."""
    for index in (1, 2):
        (workdir / f"scan_{index}.txt").write_bytes(f"{DOCUMENT}\nтом {index}".encode())

    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    renamed = sorted(p.name for p in workdir.iterdir())

    assert report.renamed == 2
    assert "_1_из_2_" in renamed[0]
    assert "_2_из_2_" in renamed[1]

    assert report.manifest_path is not None
    app.undo(report.manifest_path)
    assert sorted(p.name for p in workdir.iterdir()) == ["scan_1.txt", "scan_2.txt"]


# --- аккуратное имя против небрежной пометки --------------------------------


@pytest.mark.parametrize(
    ("stem", "preserve"),
    [
        ("Постановление по делу Иванова", True),
        ("Договор займа №17 от 18 августа 2026 года", True),
        ("Заметки по встрече с подрядчиком", True),
        ("седой дом газ", False),
        ("газ дом", False),
        ("копия скана", False),
        ("IMG_0032", False),
    ],
)
def test_only_well_formed_names_are_preserved(stem: str, preserve: bool) -> None:
    """Небрежная пометка для себя — не повод отказаться от переименования."""
    from docrenamer.config import load_document_types
    from docrenamer.naming.builder import is_well_formed_name
    from docrenamer.textquality import comparison_key

    type_words = frozenset(
        comparison_key(entry["canonical_name"]) for entry in load_document_types()
    )
    assert is_well_formed_name(stem, type_words) is preserve


def test_sloppy_name_is_rebuilt_but_its_words_survive(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Слова прежнего имени не теряются: в них бывает суть, которой нет в тексте."""
    (workdir / "седой дом газ.txt").write_bytes(
        (
            "СПРАВКА\n"
            "об отключении газоснабжения\n"
            "от 15 марта 2026 года\n"
            "Выдана в том, что подача газа приостановлена.\n"
            "АО «Мосгаз»\n"
        ).encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("Справка_")
    assert "седой_дом_газ" in item.proposed_filename
    assert item.proposed_filename.endswith("_15.03.2026.txt")
    assert item.selected


def test_unreadable_file_is_not_renamed_by_its_own_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """У нечитаемого файла собственное имя ничего не подтверждает."""
    (workdir / "прошивка станка.bin").write_bytes(bytes(range(256)) * 8)

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename in ("", "прошивка станка.bin")
    assert not item.selected


def test_initials_are_attached_to_surname(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Инициалы пишутся вплотную: ИвановИИ."""
    (workdir / "scan0007.txt").write_bytes(
        (
            "ПОСТАНОВЛЕНИЕ\n"
            "о возбуждении исполнительного производства\n"
            "от 27 июля 2026 года\n"
            "Должник: Иванов И.И.\n"
        ).encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "ИвановИИ" in item.proposed_filename
    assert "Иванов_ИИ" not in item.proposed_filename


def test_long_human_name_is_rebuilt_using_its_own_data(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Слишком длинное имя пересобирается, а номер дела из него сохраняется."""
    name = "Дело № А40-123456-2026 определение суда обезличенная копия от 15 марта 2026 года.txt"
    (workdir / name).write_bytes(
        "ОПРЕДЕЛЕНИЕ\nо принятии искового заявления к производству\n"
        "Арбитражный суд города Москвы\n".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("Определение_суда_")
    assert "А40-123456-2026" in item.proposed_filename
    assert "15.03.2026" in item.proposed_filename
    assert len(item.proposed_filename) < len(name)
