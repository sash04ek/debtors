"""Организации: реквизиты, дома, текст претензии. Хранятся в ~/.debtors_orgs.json."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ORGS_PATH = Path.home() / ".debtors_orgs.json"

# Плейсхолдеры: {org} {agent} {agent_address} {date} {debt} {days}; **текст** — жирный.
BODY_WITH_AGENT = """В соответствии с представленной {agent} по состоянию на **{date} г.** перед {org} за Вами числится задолженность за предоставленные жилищно-коммунальные услуги в размере **{debt}** рублей.
Напоминаем Вам, что согласно п. 1 ст. 153 ЖК РФ граждане обязаны своевременно вносить плату за жилое помещение и коммунальные услуги.
Плата за жилое помещение и коммунальные услуги вносится ежемесячно до десятого числа месяца, следующего за истекшим месяцем.
Предлагаем Вам в течение **{days}** со дня получения настоящей претензии оплатить имеющийся у Вас долг перед {org} по квитанциям {agent}. В случае несогласия с суммой задолженности просим Вас обратиться в {agent} ({agent_address}).
{org} готово рассмотреть предоставление рассрочки погашения задолженности за предоставленные жилищно-коммунальные услуги.
В противном случае {org} будет вынуждено ограничить предоставление Вам коммунальных услуг (электроснабжение, водоотведение) в соответствии с Разделом 11 «Правил предоставления коммунальных услуг собственникам» № 354 от 06.05.2011 г. и обратиться в судебные органы для взыскания с Вас задолженности в принудительном порядке. При этом на Вас будет возложена обязанность по оплате судебных расходов, включая оплату государственной пошлины за подачу иска, оплату услуг юридического агентства, а так же возможность применения ограничительных мер.
**Поэтому просим Вас погасить задолженность в добровольном порядке.**"""

BODY_NO_AGENT = """По состоянию на **{date} г.** перед {org} за Вами числится задолженность за предоставленные жилищно-коммунальные услуги в размере **{debt}** рублей.
Напоминаем Вам, что согласно п. 1 ст. 153 ЖК РФ граждане обязаны своевременно вносить плату за жилое помещение и коммунальные услуги.
Плата за жилое помещение и коммунальные услуги вносится ежемесячно до десятого числа месяца, следующего за истекшим месяцем.
Предлагаем Вам в течение **{days}** со дня получения настоящей претензии оплатить имеющийся у Вас долг перед {org}. В случае несогласия с суммой задолженности просим Вас обратиться в {org}.
{org} готово рассмотреть предоставление рассрочки погашения задолженности за предоставленные жилищно-коммунальные услуги.
В противном случае {org} будет вынуждено ограничить предоставление Вам коммунальных услуг (электроснабжение, водоотведение) в соответствии с Разделом 11 «Правил предоставления коммунальных услуг собственникам» № 354 от 06.05.2011 г. и обратиться в судебные органы для взыскания с Вас задолженности в принудительном порядке. При этом на Вас будет возложена обязанность по оплате судебных расходов, включая оплату государственной пошлины за подачу иска, оплату услуг юридического агентства, а так же возможность применения ограничительных мер.
**Поэтому просим Вас погасить задолженность в добровольном порядке.**"""


LETTER_BODY = "\tПрошу Вас в срок до {date} предоставить сведения по начислению и оплате предоставляемых услуг для направления в суд, по адресам:"
LETTER_TO = "**Директору ООО «ЕИРЦ»**\n**Полиенко С. А.**\n347900, г. Таганрог, пер. Комсомольский 21"
LETTER_FIELDS = ("letter_header", "letter_to", "letter_body", "sign_role", "sign_name", "city", "letter_days")
COURT_FIELDS = ("applicant_address", "region", "city_in", "duty_default", "license_text", "poa_text")

@dataclass
class Organization:
    name: str                          # в претензии: ООО УО «ДомСервис»
    match: str = ""                    # слово для авто-определения по заголовку файла: «ДомСервис»
    header: str = ""                   # шапка слева (реквизиты), по строке на строку
    houses: list = field(default_factory=list)       # дома: [{"address": «Калинина ул 113», "since": «01.11.2021», "court": код участка}]
    agent: str = ""                    # платёжный агент, напр. ООО «ЕИРЦ» (необязательно)
    agent_address: str = ""
    days: str = "10 (десяти) дней"
    body: str = ""                     # пусто → стандартный текст
    claim_no_prefix: str = ""          # необязательно, зарезервировано
    # --- письмо в ЕИРЦ (запрос выписок по должникам) ---
    letter_header: str = ""            # шапка письма; строки с «# » — крупно (14 пт), все строки жирные
    letter_to: str = ""                # кому (справа); **жирный**
    letter_body: str = ""              # пусто → стандартный; поле {date}
    sign_role: str = "Представитель по доверенности"
    sign_name: str = ""
    city: str = "г. Таганрог"
    letter_days: int = 10              # срок предоставления сведений, дней
    # --- заявление о выдаче судебного приказа ---
    applicant_address: str = ""        # адрес заявителя в заявлении
    region: str = "Ростовская область"
    city_in: str = "г. Таганроге"      # «в г. Таганроге» (для текста заявления)
    duty_default: str = "200"          # госпошлина по умолчанию, руб.
    license_text: str = ""             # «№ 679 от 18.05.2021» — уведомление о предоставлении лицензии
    poa_text: str = ""                 # «23.08.2022г.» — дата доверенности представителя

    def __post_init__(self):
        # совместимость: раньше дома были просто строками-адресами
        self.houses = [{"address": h.strip(), "since": "", "court": ""} if isinstance(h, str) else
                       {"address": str(h.get("address", "")).strip(), "since": str(h.get("since", "")).strip(),
                        "court": str(h.get("court", "")).strip()}
                       for h in self.houses if (h if isinstance(h, str) else h.get("address"))]

    def body_template(self) -> str:
        if self.body.strip():
            return self.body
        return BODY_WITH_AGENT if self.agent.strip() else BODY_NO_AGENT


def default_orgs() -> list[Organization]:
    return [
        Organization(
            name="ООО УО «ДомСервис»", match="ДомСервис",
            header=("Российская Федерация\nРостовская область\nОбщество с ограниченной ответственностью\n"
                    "Управляющая организация «ДомСервис»\n347900 Ростовская область\n"
                    "г. Таганрог, ул. Котлостроительная, 37/19, офис № 5; тел: 341-199.\n"
                    "Эл. почта: ooo.uo.domservis@mail.ru,\nИНН/КПП: 6154159722/615401001\nОГРН: 1216100002766"),
            agent="ООО «ЕИРЦ»", agent_address="347935, РО, г. Таганрог, пер. Комсомольский, д. 21",
            letter_header=("# Общество с ограниченной ответственностью\n# Управляющая организация «ДомСервис»\n\n"
                           "347913, Ростовская область, г. Таганрог, ул. Котлостроительная, 37/19, оф.33\n"
                           "р/с: 40702810028050000261 в Банк ВТБ (ПАО) ИНН/КПП: 6154159722/615401001,\n"
                           "ОГРН: 1216100002766, эл. почта: ooo.uo.domservis@mail.ru\n"
                           "Тел: +7(918)-586-34-87"),
            letter_to=LETTER_TO, sign_name="В. Е. Павличенко",
            applicant_address="347910, Ростовская область. г. Таганрог, ул. Котлостроительная, 37/19, оф.33",
            license_text="№ 679 от 18.05.2021", poa_text="23.08.2022г.",
        ),
        Organization(
            name="ООО УО «ТаганСервис»", match="ТаганСервис",
            header=("Российская Федерация\nРостовская область\nОбщество с ограниченной ответственностью\n"
                    "Управляющая организация «ТаганСервис»\n347910 Ростовская область\n"
                    "г. Таганрог, ул. Котлостроительная, 37/19, каб. 19; тел: 8(8634)341-015.\n"
                    "Сайт: taganservis.ru\nИНН/КПП: 6154136429/615401001\nОГРН: 1146154036203"),
            agent="ООО «ЕИРЦ»", agent_address="347935, РО, г. Таганрог, пер. Комсомольский, д. 21",
            letter_header=("# Общество с ограниченной ответственностью\n# Управляющая организация «ТаганСервис»\n\n"
                           "347910, Ростовская область, г. Таганрог, ул. Котлостроительная, 37/19, каб. 19\n"
                           "р/с: 40702810852090010135 в ЮГО-ЗАПАДНЫЙ БАНК ПАО СБЕРБАНК, БИК 046015602\n"
                           "ИНН/КПП: 6154136429/615401001, ОГРН: 1146154036203\n"
                           "Тел: 8(8634)341-015"),
            letter_to=LETTER_TO,
            applicant_address="347910, Ростовская область, г. Таганрог, ул. Котлостроительная, 37/19, каб. 19",
        ),
    ]


def load_orgs() -> list[Organization]:
    try:
        data = json.loads(ORGS_PATH.read_text(encoding="utf-8"))
        names = {f.name for f in fields(Organization)}
        orgs = [Organization(**{k: v for k, v in d.items() if k in names}) for d in data]
        if orgs:
            defaults = {d.name: d for d in default_orgs()}
            for o in orgs:  # сохранённые до появления письма организации: подставить стандартные поля
                d = defaults.get(o.name)
                if d and not o.letter_header.strip():
                    for f in LETTER_FIELDS:
                        setattr(o, f, getattr(d, f))
                    o.sign_name = o.sign_name or d.sign_name
                if d and not o.applicant_address.strip():
                    for f in COURT_FIELDS:
                        setattr(o, f, getattr(d, f))
            return orgs
    except Exception:
        pass
    return default_orgs()


def save_orgs(orgs: list[Organization]) -> None:
    ORGS_PATH.write_text(json.dumps([asdict(o) for o in orgs], ensure_ascii=False, indent=2), encoding="utf-8")


_FLAT_TAIL = re.compile(r"[\s,;]+(?:кв|квартира|пом|помещение)\b\.?\s*[\w/\-.,\s]*$", re.IGNORECASE)


# «к.1», «-к.2», « к 3» в конце адреса после номера дома — номер квартиры (так записано в отчётах)
_K_FLAT = re.compile(r"(?<=\d)[\s,;-]*к\.?\s*(\d+[а-яa-z]?)\s*$", re.IGNORECASE)
_FLAT_NUM = re.compile(r"[\s,;]+(?:кв|квартира|пом|помещение)\b\.?\s*([\w/\-]+)", re.IGNORECASE)


def extract_flat(addr) -> str:
    """Номер квартиры, записанный в адресе: «Новый пер 100-5-к.1» → «1», «Калинина ул 113, кв. 5» → «5»."""
    s = re.sub(r"\([^)]*\)", " ", str(addr or "")).strip(" .,;")
    m = _FLAT_NUM.search(s) or _K_FLAT.search(s)
    return m.group(1) if m else ""


def addr_flat(address, flat) -> tuple[str, str]:
    """(адрес дома без квартиры, квартира): квартира из колонки, а если она пуста — из адреса."""
    f = str(flat if flat is not None else "").strip()
    return clean_house_address(address), (f or extract_flat(address))


def clean_house_address(addr) -> str:
    """Адрес дома без квартиры и пометок: «Калинина ул 113, кв. 5» → «Калинина ул 113»,
    «Инструментальная ул 19-3 (нежилые)» → «Инструментальная ул 19-3», «Чехова ул 337,» → «Чехова ул 337»."""
    s = re.sub(r"\([^)]*\)", " ", str(addr or ""))          # пометки в скобках: (жилые), (нежилые)
    s = _FLAT_TAIL.sub("", s.strip())                          # «, кв. 34», « пом 5»
    s = _K_FLAT.sub("", s.strip(" .,;"))                       # «-к.1», « к2» после номера дома
    s = re.sub(r"\s+", " ", s).strip(" .,;")
    return s


def norm_addr(a: str) -> str:
    return re.sub(r"[\s.,]+", " ", clean_house_address(a)).strip().lower().replace("ё", "е")


def find_by_title(orgs: list[Organization], title: str) -> Organization | None:
    t = (title or "").lower()
    for o in orgs:
        if o.match and o.match.lower() in t:
            return o
    return None


def find_by_house(orgs: list[Organization], address: str) -> Organization | None:
    a = norm_addr(address)
    for o in orgs:
        if any(norm_addr(h["address"]) == a for h in o.houses):
            return o
    return None


def house_addresses(org: Organization) -> set[str]:
    """Нормализованные адреса домов организации."""
    return {norm_addr(h["address"]) for h in org.houses}


def house_court(org: Organization, address: str) -> str:
    """Код судебного участка, закреплённого за домом в списке домов организации (пусто, если не задан)."""
    a = norm_addr(address)
    for h in org.houses:
        if norm_addr(h["address"]) == a:
            return h.get("court", "")
    return ""


def house_since(org: Organization, address: str) -> str:
    """Дата, с которой дом находится в управлении организации (пусто, если дома нет в списке или дата не задана)."""
    a = norm_addr(address)
    for h in org.houses:
        if norm_addr(h["address"]) == a:
            return h["since"]
    return ""
