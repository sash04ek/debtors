"""Колонки программы для «Сохранить в Excel»: флаги и персональные данные собственников по каждому адресу.
Данных нет — ячейка пустая; колонки в файле есть всегда. В отчётные колонки они не входят: при повторном открытии файла
отбрасываются (core.export пишет их число в служебный лист) и при следующем сохранении считаются заново."""

from __future__ import annotations

from datetime import date

import claimlog
import owners

HEADERS = ["Данные собственника", "Судебный участок", "Претензия отправлена", "Ответ на претензию", "Приказ подан в суд",
           "Собственник", "Доля в праве", "Дата рождения", "Место рождения", "Паспорт", "Адрес регистрации",
           "Адрес проживания", "Кадастровый номер"]

PERSONAL_FROM = 5                                  # с этой колонки HEADERS — персональные данные (до неё — флаги)
_CARD = {"full": "заполнены", "partial": "заполнены не полностью", "none": ""}
_CLAIM = {claimlog.SENT: "ждём ответа", claimlog.OVERDUE: "срок ответа истёк", claimlog.CLOSED: "ответ получен", "": ""}
_OWNER_FIELDS = ("fio", "share", "birth_date", "birth_place", "passport", "reg_address", "live_address")


def unique_headers(existing: list[str]) -> list[str]:
    """Заголовки программы, не совпадающие с колонками отчёта (при совпадении — с пометкой)."""
    taken = {str(h).strip().lower() for h in existing}
    return [h if h.lower() not in taken else f"{h} (программа)" for h in HEADERS]


def _join(values: list[str]) -> str:
    """Значение одной колонки по всем собственникам: один — как есть, несколько — «1) …; 2) …»; все пусты — пусто."""
    if not any(values):
        return ""
    if len(values) == 1:
        return values[0]
    return "; ".join(f"{i}) {v or '—'}" for i, v in enumerate(values, 1))


def row(info: dict, card: dict | None, rec: dict | None, days: int, court_name: str = "", today: date | None = None) -> list:
    """Значения колонок HEADERS для одного адреса. card — запись из owners.json (dict) или None, rec — запись журнала претензий."""
    c = owners._from_dict(card) if card else None
    people = c.owners if c else []
    status = owners.card_status(c, info.get("report_fio", ""))
    state = claimlog.status(rec, days, today)
    own = [_join([str(getattr(o, f) or "").strip() for o in people]) for f in _OWNER_FIELDS]
    return [_CARD[status], court_name,
            claimlog.long((rec or {}).get("sent", "")), _CLAIM[state], claimlog.long((rec or {}).get("court", "")),
            *own, (c.cadastral.strip() if c else "")]
