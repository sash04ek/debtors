"""Журнал отправленных претензий: по адресу и квартире — дата отправки; через заданное число дней программа напоминает,
что срок ответа истёк. Хранится в ~/.debtors/claims.json (ключ — как у карточек собственников)."""

from __future__ import annotations

from datetime import date, timedelta

import orgs
import owners
import storage

DEFAULT_DAYS = 40

# статусы записи
SENT, OVERDUE, CLOSED = "sent", "overdue", "closed"


def _load() -> dict[str, dict]:
    data = storage.load_json(storage.CLAIMS_PATH, "claims", {})
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    storage.save_json(storage.CLAIMS_PATH, "claims", data)


def key_of(address, flat) -> str:
    return owners.make_key(address, flat)


def mark_sent(items: list[tuple[str, str]], sent: date, org: str = "") -> int:
    """Отмечает претензии отправленными: items — [(адрес, квартира)]. Повторная отметка заменяет дату и снимает «ответ получен»."""
    data = _load()
    for address, flat in items:
        data[key_of(address, flat)] = {"address": address, "flat": flat, "org": org, "sent": sent.isoformat(), "closed": ""}
    _save(data)
    return len(items)


def unmark(items: list[tuple[str, str]]) -> int:
    """Убирает отметку об отправке."""
    data = _load()
    n = sum(1 for address, flat in items if data.pop(key_of(address, flat), None) is not None)
    _save(data)
    return n


def close(items: list[tuple[str, str]], on: date | None = None) -> int:
    """«Ответ получен»: напоминание по этим адресам больше не показывается (отметка об отправке остаётся)."""
    data, n = _load(), 0
    for address, flat in items:
        rec = data.get(key_of(address, flat))
        if rec:
            rec["closed"] = (on or date.today()).isoformat()
            n += 1
    _save(data)
    return n


def get(address, flat, data: dict | None = None) -> dict | None:
    return (data if data is not None else _load()).get(key_of(address, flat))


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def due_date(rec: dict, days: int) -> date | None:
    sent = _day(rec.get("sent", ""))
    return sent + timedelta(days=days) if sent else None


def status(rec: dict | None, days: int, today: date | None = None) -> str:
    """"" — претензия не отправлялась; sent — ждём ответа; overdue — срок ответа истёк; closed — ответ получен."""
    if not rec or not _day(rec.get("sent", "")):
        return ""
    if rec.get("closed"):
        return CLOSED
    return OVERDUE if (today or date.today()) >= due_date(rec, days) else SENT


def overdue(days: int, today: date | None = None) -> list[dict]:
    """Записи с истёкшим сроком ответа, самые давние первыми; в запись добавлены due (срок) и late (дней просрочки)."""
    today = today or date.today()
    out = []
    for rec in _load().values():
        if status(rec, days, today) == OVERDUE:
            due = due_date(rec, days)
            out.append(rec | {"due": due.isoformat(), "late": (today - due).days})
    return sorted(out, key=lambda r: (r["sent"], orgs.norm_addr(r.get("address", "")), str(r.get("flat", ""))))


def short(text: str) -> str:
    """«2026-10-04» → «04.10.26» для узкой колонки таблицы."""
    d = _day(text)
    return f"{d:%d.%m.%y}" if d else ""


def long(text: str) -> str:
    d = _day(text)
    return f"{d:%d.%m.%Y}" if d else ""
