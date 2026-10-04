"""Проверка перед созданием документов: чего не хватает у организации и у отдельных адресов."""

from __future__ import annotations

import orgs as orgmod

KINDS = ("claims", "letter", "court")


def org_issues(kind: str, org: orgmod.Organization) -> list[str]:
    """Проблемы организации для этого вида документов (общие для всех адресов). Подсказка — где это исправить."""
    out: list[str] = []

    def need(value: str, what: str, where: str) -> None:
        if not (value or "").strip():
            out.append(f"не заполнено: {what} ({where})")

    if kind == "claims":
        need(org.header, "шапка претензии", "Организации → Шапка")
    elif kind == "letter":
        need(org.letter_header, "шапка письма", "Организации → Шапка")
        need(org.letter_to, "кому адресовано письмо", "Организации → Письмо в ЕИРЦ")
        need(org.sign_name, "подписант", "Организации → Письмо в ЕИРЦ")
        if orgmod.poa_path(org.poa_mail) is None:
            out.append("не добавлена доверенность для почты (Организации → Доверенности)")
    elif kind == "court":
        need(org.letter_header, "шапка заявления", "Организации → Шапка")
        need(org.applicant_address, "адрес заявителя", "Организации → Судебный приказ")
        need(org.license_text, "уведомление о лицензии", "Организации → Судебный приказ")
        need(org.sign_name, "подписант", "Организации → Письмо в ЕИРЦ")
        need(org.poa_text, "дата доверенности", "Организации → Судебный приказ")
        if orgmod.poa_path(org.poa_court) is None:
            out.append("не добавлена доверенность для суда (Организации → Доверенности)")
    return out


def row_issues(kind: str, org: orgmod.Organization, address: str, card_ok: bool = True, court_ok: bool = True,
               today=None, card_full: bool = True, claim_sent: str = "") -> list[str]:
    """Проблемы одного адреса. Дома проверяются, только если у организации ведётся список домов."""
    miss: list[str] = []
    if kind == "court":
        if not card_ok:
            miss.append("нет персональных данных")
        elif not card_full:
            miss.append("карточка заполнена не полностью")
        if not court_ok:
            miss.append("нет участка")
    if claim_sent and kind in ("claims", "court"):
        miss.append(f"претензия уже отправлена {claim_sent}" if kind == "claims" else f"приказ уже подан в суд {claim_sent}")
    if org.houses:
        house = orgmod.find_house(org, address)
        if house is None:
            miss.append("дома нет в списке организации")
        elif not orgmod.is_managed_house(house, today):
            miss.append(f"дом не в управлении ({orgmod.house_period_text(house) or 'нет даты прихода'})")
    return miss
