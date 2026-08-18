"""Промпт локальной модели (разделы 38, 14A.8 ТЗ).

Инструкции по извлечению русских юридических реквизитов формулируются на
русском языке. Документ не переводится: модель получает исходный Unicode-текст,
и канонический ответ для русскоязычного документа остаётся русскоязычным.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a local document metadata classifier.

You do not have permission to invent information.
Use only facts explicitly present in INPUT.
If a value is uncertain or absent, return null.

Your task is not to summarize the whole document.
Select only metadata useful for identifying the file:
- document type
- document date
- document number
- major persons/parties
- major organizations
- case/contract identifiers
- short subject

For every non-null value provide evidence from INPUT.
Return valid JSON only.

Документ русскоязычный. Работай с русским текстом как есть, не переводи его.

Требования к значениям:
- document_type — вид документа по-русски, как он назван в тексте
  (например: «Постановление судебного пристава», «Договор займа»,
  «Протокол допроса», «Решение суда»);
- document_date — дата самого документа в формате ГГГГ-ММ-ДД;
- document_number — номер документа так, как он напечатан;
- case_numbers — номера дел и исполнительных производств;
- main_persons — фамилии и инициалы ключевых лиц с их процессуальной ролью
  (должник, взыскатель, истец, ответчик, обвиняемый, сторона договора);
- main_organizations — наименования организаций и государственных органов;
- subject — краткий предмет документа, 2–5 слов по-русски.

evidence — дословный фрагмент из INPUT, подтверждающий значение.
Значение без дословного подтверждения в INPUT возвращать запрещено.
"""

#: Требуемая форма ответа. Показывается модели как образец.
RESPONSE_SCHEMA_EXAMPLE = """{
  "document_type": {"value": null, "confidence": 0.0, "evidence": ""},
  "document_date": {"value": null, "confidence": 0.0, "evidence": ""},
  "document_number": {"value": null, "confidence": 0.0, "evidence": ""},
  "case_numbers": [],
  "main_persons": [],
  "main_organizations": [],
  "subject": {"value": null, "confidence": 0.0, "evidence": ""}
}"""


def build_prompt(context_block: str) -> str:
    """Собрать полный запрос к локальной модели."""
    return (
        f"{SYSTEM_PROMPT}\n"
        "Ответ строго в таком виде (JSON без пояснений):\n"
        f"{RESPONSE_SCHEMA_EXAMPLE}\n\n"
        "INPUT:\n"
        f"{context_block}\n\n"
        "JSON:\n"
    )
