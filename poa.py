"""Чтение доверенностей (.docx и .doc): из текста достаются дата доверенности и представитель (В. Е. Павличенко)."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}

_NAME = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_PATR_F = r"[А-ЯЁ][а-яё]*(?:вн|чн)(?:а|ы|е|у|ой)"
_PATR_M = r"[А-ЯЁ][а-яё]*ич(?:а|у|ем|е)?"
_TRIPLE = re.compile(rf"({_NAME})\s+([А-ЯЁ][а-яё]+)\s+((?:{_PATR_F})|(?:{_PATR_M}))(?![а-яё])")
_TRIGGER = re.compile(r"(?:доверя\w+|уполномоч\w+|поруча\w+)", re.IGNORECASE)
_SURNAME_INITIALS = re.compile(rf"({_NAME})\s+([А-ЯЁ])\.\s*([А-ЯЁ])\.")
_INITIALS_SURNAME = re.compile(rf"([А-ЯЁ])\.\s*([А-ЯЁ])\.\s*({_NAME})")
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})(?!\d)")
_DATE_WORD = re.compile(r"(?<!\d)[«\"“]?\s*(\d{1,2})\s*[»\"”]?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.IGNORECASE)
_NOT_ISSUE_DATE = re.compile(r"(выдан|паспорт|рожд|зарегистр|проживает|серия)", re.IGNORECASE)


def read_text(path) -> str:
    """Текст файла Word. Пустая строка — прочитать не удалось."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            xml = re.sub(r"<w:(?:tab|br)\b[^>]*/>", " ", xml)
            xml = xml.replace("</w:p>", "\n")
            return html.unescape(re.sub(r"<[^>]+>", "", xml))
        if shutil.which("textutil"):                              # macOS читает .doc сам
            out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", errors="ignore")
        return _read_doc_raw(path.read_bytes())
    except Exception:
        return ""


def _read_doc_raw(data: bytes) -> str:
    """Запасной способ для .doc: текст в нём лежит в UTF-16 или в cp1251 — декодируем оба варианта и оставляем читаемое."""
    parts = []
    for text in (data.decode("utf-16-le", errors="ignore"), data[1:].decode("utf-16-le", errors="ignore"),
                 data.decode("cp1251", errors="ignore")):
        parts.append(re.sub(r"[^\w\s.,:;«»\"'()/№-]", " ", text, flags=re.UNICODE))
    return "\n".join(parts)


def parse_date(text: str) -> str:
    """Первая дата, похожая на дату доверенности (не паспортная и не дата рождения): «23.08.2022г.»."""
    found = []
    for m in _DATE_NUM.finditer(text):
        found.append((m.start(), m.end(), int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DATE_WORD.finditer(text):
        found.append((m.start(), m.end(), int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))))
    prev_end = 0
    for pos, end, d, mo, y in sorted(found):
        before, prev_end = text[max(prev_end, pos - 40):pos], end         # слова считаем только после предыдущей даты
        if not (1 <= d <= 31 and 1 <= mo <= 12 and 1990 <= y <= 2100):
            continue
        if _NOT_ISSUE_DATE.search(before):
            continue
        return f"{d:02d}.{mo:02d}.{y}г."
    return ""


def _nominative(surname: str, female: bool) -> str:
    """Фамилия из дательного/винительного падежа в именительный — только для явных окончаний, иначе без изменений."""
    s = surname
    if female:
        for tail, new in (("овой", "ова"), ("евой", "ева"), ("иной", "ина"), ("ыной", "ына"), ("ской", "ская"), ("цкой", "цкая"),
                          ("ову", "ова"), ("еву", "ева"), ("ину", "ина"), ("ыну", "ына"), ("скую", "ская"), ("цкую", "цкая")):
            if s.endswith(tail):
                return s[:-len(tail)] + new
        return s
    for tail, new in (("скому", "ский"), ("цкому", "цкий"), ("ому", "ой"), ("ову", "ов"), ("еву", "ев"), ("ину", "ин"),
                      ("ыну", "ын"), ("ова", "ов"), ("ева", "ев"), ("ина", "ин"), ("ына", "ын")):
        if s.endswith(tail):
            return s[:-len(tail)] + new
    return s


def parse_representative(text: str) -> str:
    """Представитель: «В. Е. Павличенко». ФИО берётся после слов «доверяет/уполномочивает», фамилия уточняется по подписи."""
    flat = re.sub(r"\s+", " ", text)
    start = _TRIGGER.search(flat)
    if not start:
        return ""
    m = _TRIPLE.search(flat, start.end(), start.end() + 400)
    if not m:
        return ""
    surname, first, patr = m.groups()
    ini = (first[0], patr[0])
    female = bool(re.fullmatch(_PATR_F, patr))
    stem = surname[:4].lower()
    for rx, order in ((_SURNAME_INITIALS, "sfp"), (_INITIALS_SURNAME, "fps")):
        for c in rx.finditer(flat):
            cs, c1, c2 = (c.group(1), c.group(2), c.group(3)) if order == "sfp" else (c.group(3), c.group(1), c.group(2))
            if (c1, c2) == ini and cs[:4].lower() == stem:
                return f"{ini[0]}. {ini[1]}. {cs}"
    return f"{ini[0]}. {ini[1]}. {_nominative(surname, female)}"


def parse(path) -> dict:
    """{"date": "23.08.2022г.", "name": "В. Е. Павличенко"} — только то, что удалось определить."""
    text = read_text(path)
    out = {"date": parse_date(text), "name": parse_representative(text)}
    return {k: v for k, v in out.items() if v}
