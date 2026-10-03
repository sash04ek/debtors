"""Организации: реквизиты, дома, текст претензии. Хранятся в ~/.debtors/orgs.json."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from dataclasses import asdict, dataclass, field, fields

import storage

ORGS_PATH = storage.ORGS_PATH

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
COURT_FIELDS = ("applicant_address", "region", "city_in", "license_text", "poa_text")

@dataclass
class Organization:
    name: str                          # в претензии: ООО УО «ДомСервис»
    match: str = ""                    # слово для авто-определения по заголовку файла: «ДомСервис»
    header: str = ""                   # шапка слева (реквизиты), по строке на строку
    houses: list = field(default_factory=list)       # дома: [{"address": «Калинина ул 113», "since": «01.11.2021», "until": «01.09.2024» (дата ухода),
                                                     #         "left": дом ушёл, а дата ухода неизвестна, "court": код участка}]
    agent: str = ""                    # платёжный агент, напр. ООО «ЕИРЦ» (необязательно)
    agent_address: str = ""
    days: str = "10 (десяти) дней"
    body: str = ""                     # пусто → стандартный текст
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
    license_text: str = ""             # «№ 679 от 18.05.2021» — уведомление о предоставлении лицензии
    poa_text: str = ""                 # «23.08.2022г.» — дата доверенности представителя
    # --- доверенности на представителя, который отправляет документы (файлы docx в ~/.debtors/poa) ---
    poa_mail: str = ""                 # имя файла доверенности для почты (письмо в ЕИРЦ)
    poa_court: str = ""                # имя файла доверенности для суда (заявления о судебном приказе)

    def __post_init__(self):
        # совместимость: раньше дома были просто строками-адресами
        self.houses = [normalize_house(h) for h in self.houses if (h if isinstance(h, str) else h.get("address"))]

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
        data = storage.load_json(ORGS_PATH, "orgs")
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


POA_KINDS = {"mail": "для почты", "court": "для суда"}


def poa_path(name: str) -> Path | None:
    """Путь к сохранённому файлу доверенности; None, если не задан или файл пропал."""
    if not name or Path(name).name != name:
        return None
    p = storage.POA_DIR / name
    return p if p.is_file() else None


def import_poa(src, kind: str, old: str = "") -> str:
    """Копирует docx доверенности в папку данных программы и возвращает сохранённое имя (прежний файл заменяется)."""
    src = Path(src)
    if src.suffix.lower() != ".docx":
        raise ValueError("Доверенность должна быть файлом Word (.docx).")
    storage.POA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}-{kind}.docx"
    shutil.copyfile(src, storage.POA_DIR / name)
    remove_poa(old)
    return name


def remove_poa(name: str) -> None:
    p = poa_path(name)
    if p:
        p.unlink(missing_ok=True)


def copy_poa(org: "Organization", kind: str, out_dir) -> Path | None:
    """Кладёт доверенность организации (kind: mail/court) в папку с документами. None — доверенность не задана."""
    p = poa_path(getattr(org, f"poa_{kind}"))
    if p is None:
        return None
    label = re.sub(r'[\\/:*?"<>|«»]', "", org.name).strip()
    dest = Path(out_dir) / f"Доверенность {POA_KINDS[kind]} {label}.docx"
    shutil.copyfile(p, dest)
    return dest


def save_orgs(orgs: list[Organization]) -> None:
    storage.save_json(ORGS_PATH, "orgs", [asdict(o) for o in orgs])


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


_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)")
_LEFT_WORDS = ("ушел", "ушёл", "ушла", "выбыл", "расторг", "не в управлении")


def _dates_in(text: str) -> list:
    from datetime import date
    out = []
    for d, m, y in _DATE_RE.findall(text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            out.append(date(y, int(m), int(d)))
        except ValueError:
            pass
    return out


def _fmt(d) -> str:
    return f"{d:%d.%m.%Y}"


def split_since(text: str) -> tuple[str, str, bool]:
    """Прежняя запись «В управлении с» одной строкой -> (дата прихода, дата ухода, ушёл без даты).
    «01.06.2015г» -> («01.06.2015», «», False); «01.12.2019г-01.11.2020гг» -> («01.12.2019», «01.11.2020», False);
    «01.06.2015г ушел» -> («01.06.2015», «», True); текст без даты остаётся в «с» как есть."""
    text = (text or "").strip()
    if not text:
        return "", "", False
    left = any(w in text.lower() for w in _LEFT_WORDS)
    dates = _dates_in(text)
    if len(dates) >= 2:
        return _fmt(min(dates)), _fmt(max(dates)), False
    if len(dates) == 1:
        return _fmt(dates[0]), "", left
    return ("" if left else text), "", left


def normalize_house(h) -> dict:
    """Дом в едином виде: адрес, дата прихода, дата ухода, признак «ушёл», участок. Прежние записи (только «since»
    строкой с периодом или словом «ушел») разбираются на отдельные поля."""
    if isinstance(h, str):
        h = {"address": h}
    if "until" in h or "left" in h:
        since, until, left = str(h.get("since", "")).strip(), str(h.get("until", "")).strip(), bool(h.get("left"))
    else:
        since, until, left = split_since(str(h.get("since", "")))
    return {"address": str(h.get("address", "")).strip(), "since": since, "until": until, "left": left,
            "court": str(h.get("court", "")).strip()}


def _migrate_houses(data):
    """Схема организаций 1 -> 2: у домов появились отдельные поля «until» и «left»."""
    if isinstance(data, list):
        for org in data:
            if isinstance(org, dict) and "houses" in org:
                org["houses"] = [normalize_house(h) for h in org["houses"] if (h if isinstance(h, str) else h.get("address"))]
    return data


storage.MIGRATIONS[("orgs", 1)] = _migrate_houses


def is_managed_house(h: dict, today=None) -> bool:
    """Находится ли дом в управлении сейчас.
    Нет даты прихода — нет. Дата прихода в будущем — ещё нет. Дом ушёл (стоит признак «ушёл» без даты ухода, либо дата ухода
    уже прошла) — нет. Непустой текст в «с» без распознаваемой даты считается заполненным (дом в управлении)."""
    from datetime import date
    from datepicker import parse_date
    today = today or date.today()
    since = (h.get("since") or "").strip()
    until = parse_date(h.get("until") or "")
    if h.get("left") and not until:
        return False
    if not since:
        return False
    start = parse_date(since)
    if start and start > today:
        return False
    if until and today > until:
        return False
    return True


def house_period_text(h: dict) -> str:
    """Подпись периода для окон: «с 01.06.2015», «с 01.12.2019 по 01.11.2020», «с 01.06.2015, ушёл (дата неизвестна)»."""
    since, until, left = h.get("since", ""), h.get("until", ""), h.get("left")
    text = f"с {since}" if since else ""
    if until:
        text += f" по {until}"
    elif left:
        text += (", " if text else "") + "ушёл (дата ухода неизвестна)"
    return text


def find_house(org: Organization, address: str) -> dict | None:
    """Запись дома в списке домов организации (или None)."""
    a = norm_addr(address)
    return next((h for h in org.houses if norm_addr(h["address"]) == a), None)


def house_since(org: Organization, address: str) -> str:
    """Дата, с которой дом находится в управлении организации (пусто, если дома нет в списке или дата не задана)."""
    a = norm_addr(address)
    for h in org.houses:
        if norm_addr(h["address"]) == a:
            return h["since"]
    return ""
