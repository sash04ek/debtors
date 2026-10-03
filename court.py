"""Заявление о выдаче судебного приказа: два шаблона — собственник известен / неизвестен."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

import owners
from claim import _runs, clean_flat, split_address
from core import parse_amount
from numwords import money_plain, rubles_words
import courts as courtsmod
from orgs import Organization, house_since
from owners import Card, Owner

BLANK = "____________"
# Суд (участок мирового судьи) в заявлении не определяется программой: пользователь ищет его сам и вписывает в Word.
COURT_PLACEHOLDER = ("**Мировому судье ______________________________**\n"
                     "**на судебном участке № ______**\n"
                     "______________________________ (адрес суда)")


def _v(x, blank=BLANK) -> str:
    x = str(x or "").strip()
    return x if x else blank


def _amount(s, default=None):
    a = parse_amount(s) if str(s or "").strip() else None
    return default if a is None else a


def _words(a) -> str:
    return rubles_words(a) if a is not None else "________ (________________) рублей __ коп."


def _plain(a) -> str:
    return money_plain(a).replace(" ", " ") if a is not None else "________"


def _surname_first(name: str) -> str:
    """«А. А. Иванов» → «Иванов А. А.»."""
    parts = name.split()
    if len(parts) >= 2 and all(re.fullmatch(r"[А-ЯЁA-Z]\.?", p) for p in parts[:-1]):
        return " ".join([parts[-1]] + parts[:-1])
    return name


def court_request_title(court: str) -> str:
    """Жирные строки суда → «Мирового судью в … районе на судебном участке №…» (винительный падеж)."""
    bold = [ln.replace("**", "").strip() for ln in court.splitlines() if "**" in ln]
    text = " ".join(bold) if bold else "суд"
    return re.sub(r"^Мировому судье", "Мирового судью", text)


def property_address(org: Organization, card: Card, with_flat: bool = True) -> str:
    """Адрес помещения: «Ростовская область, г. Таганрог, ул. Панфилова, д. 109-1, кв. 58»."""
    street, house = split_address(card.address)
    base = f"{org.region}, {org.city}, {street}, д. {house}"
    return f"{base}, кв. {clean_flat(card.flat)}" if with_flat else base


@dataclass
class Case:
    """Одно заявление: на одного собственника (owner) или на неизвестного (owner=None)."""
    owner: Owner | None
    co_owners: list = field(default_factory=list)     # все собственники помещения
    debt: float | None = None                         # сумма долга по помещению (в каждом заявлении полная)
    penalty: float | None = None


def plan_cases(card: Card, report_fio: str, report_debt: float | None) -> list[Case]:
    """Заявления по помещению: по одному на каждого собственника. Суммы не делятся: в каждое заявление идёт
    полный долг и пени по помещению."""
    total_debt = _amount(card.debt, report_debt)
    total_pen = _amount(card.penalty)
    people = card.people(report_fio)
    if not people:
        return [Case(None, [], total_debt, total_pen)]
    return [Case(p, people, total_debt, total_pen) for p in people]


def _owner_label(o: Owner) -> str:
    return f"{o.fio} (доля в праве {o.share.strip()})" if o.share.strip() else o.fio


def build_court_application(org: Organization, card: Card, case: Case, *, path: str | Path,
                            court_obj: "courtsmod.Court | None" = None, duty: float | None = None) -> bool:
    """Формирует заявление на одного собственника. Возвращает True, если использован шаблон «собственник известен»."""
    owner = case.owner
    known = owner is not None
    fio = owner.fio if known else ""
    street, house = split_address(card.address)
    flat = clean_flat(card.flat)
    prop_addr = property_address(org, card)
    # выбранный участок или пустое место, которое заполняют вручную
    court = courtsmod.header_text(court_obj) if court_obj else COURT_PLACEHOLDER
    debt_a, pen_a = case.debt, case.penalty
    duty_a = _amount(card.duty, duty)      # значение в карточке > расчёт по НК РФ > пустое место (заполняется в Word)
    fio_gen = (owner.fio_gen.strip() or owners.decline_fio(fio, "gen")) if known else ""
    fio_ins = (owner.fio_ins.strip() or owners.decline_fio(fio, "ins")) if known else ""
    several = len(case.co_owners) > 1
    others = [o for o in case.co_owners if o is not owner and o.fio != fio]

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin, sec.right_margin, sec.top_margin, sec.bottom_margin = Cm(3), Cm(1.5), Cm(2), Cm(2)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    st.font.size = Pt(11)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0

    J, R, C = WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.CENTER

    def para(text="", align=None, size=11, indent=None, after=0):
        p = doc.add_paragraph()
        if align is not None:
            p.alignment = align
        if indent is not None:
            p.paragraph_format.first_line_indent = Cm(indent)
        p.paragraph_format.space_after = Pt(after)
        _runs(p, text, Pt(size))
        return p

    def body(text):
        return para(text, J, 11, indent=1.25, after=6)

    # шапка организации
    for line in org.letter_header.splitlines():
        big = line.startswith("# ")
        t = line[2:] if big else line
        if t.strip():
            para(f"**{t}**", C, 13 if big else 9)
    para("_" * 78, None, 10, after=6)

    # суд, заявитель
    for line in court.splitlines():
        para(line, R, 12)
    para("", R)
    para(f"**ЗАЯВИТЕЛЬ: {org.name}**", R)
    para(f"**адрес:** {org.applicant_address}", R)
    para("", R)

    # должник
    if known:
        para(f"**ДОЛЖНИК: {fio}**", R)
        if owner.share.strip():
            para(f"**Доля в праве:** {owner.share.strip()}", R)
        para(f"**Дата рождения:** {_v(owner.birth_date)} г.", R)
        para(f"**Паспорт:** {_v(owner.passport)}", R)
        para(f"**Место рождения:** {_v(owner.birth_place)}", R)
        para(f"**Адрес регистрации:** {_v(owner.reg_address)}", R)
        para(f"**Адрес проживания:** {owner.live_address.strip() or prop_addr}", R)
        if others:
            para("**Сособственники:** " + "; ".join(_owner_label(o) for o in others), R)
    else:
        para("**ДОЛЖНИК: Физическое лицо**", R)
        para("**(фамилия, имя и отчество, которого не известно)**", R)
        para("**Идентификатор неизвестен**", R)
        para(f"**Адрес:** {prop_addr}", R)
        para(f"**Кадастровый номер:** {_v(card.cadastral)}", R)
    para(f"**Сумма задолженности:** {_plain(debt_a)} руб.", R)
    para(f"**Сумма пеней:** {_plain(pen_a)} руб.", R)
    duty_txt = _plain(duty_a).replace(",00", "")
    para(f"**Сумма госпошлины:** {duty_txt} руб.", R, after=14)

    para("**ЗАЯВЛЕНИЕ**", C, 12)
    para("**о выдаче судебного приказа**", C, 12, after=8)

    # текст заявления
    since = house_since(org, card.address)   # дата из списка домов организации
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", since or ""):
        since += "г."                          # «01.06.2015г.» — так принято в тексте заявления
    body(f"Многоквартирный дом {house} по {street} с {_v(since)} находится в управлении "
         f"{org.name} Заявитель управляет и обеспечивает содержание и ремонт имущества указанного жилого дома.")
    tariffs = ("Порядок расчёта, цены, ставки и тарифы на жилищно-коммунальные услуги для населения ежегодно "
               "утверждаются органом местного самоуправления, которое являлось основанием для начислений оплаты "
               f"жилищно-коммунальных услуг в многоквартирном доме по адресу: {street}, д. {house}.")
    if known and several:
        body(f"Согласно выписке из ЕГРН, полученной в кв. {flat} МКД {house} по {street}, в {org.city_in}, "
             "собственниками вышеуказанного помещения являются: "
             + "; ".join(_owner_label(o) for o in case.co_owners) + f". {tariffs}")
        body(f"Настоящее заявление подаётся в отношении {fio_gen}"
             + (f" (доля в праве {owner.share.strip()})" if owner.share.strip() else "")
             + "; в отношении остальных собственников помещения заявления подаются отдельно.")
    elif known:
        body(f"Согласно выписке из ЕГРН, полученной в кв. {flat} МКД {house} по {street}, в {org.city_in}, "
             f"должник является собственником вышеуказанного помещения. {tariffs}")
    else:
        body("Физическое лицо (фамилия, имя и отчество, которого не известно), проживающий по адресу: "
             f"**{prop_addr},** является собственником жилого помещения по указанному адресу.")
        body(tariffs)
    for t in (
        "В соответствии с ч. 3 ст. 30 Жилищного кодекса РФ собственник жилого помещения несет бремя содержания данного помещения. Данная норма базируется на положениях ст. 210 Гражданского кодекса РФ, которой установлено, что собственник несет бремя содержания, принадлежащего ему имущества.",
        "Статьей 158 ЖК РФ предусмотрено, что собственник жилого помещения в многоквартирном доме обязан нести расходы на содержание принадлежащего ему помещения, а также участвовать в расходах на содержание общего имущества в многоквартирном доме соразмерно своей доле в праве общей собственности на это имущество путем внесения платы за содержание и ремонт жилого помещения.",
        "С учетом рассмотренных положений собственник жилого помещения в многоквартирном доме полностью несет бремя содержания принадлежащего ему жилого помещения, а также соразмерную доле участия в общей собственности долю бремени содержания общего имущества дома.",
        "По правилам ст. 154 ЖК РФ плата за жилое помещение и коммунальные услуги для собственника помещения в многоквартирном доме включает в себя: плату за содержание и ремонт жилого помещения, с включением платы за услуги и работы по управлению многоквартирным домом, содержанию, текущему и капитальному ремонту имущества в многоквартирном доме и плату за коммунальные услуги.",
        "В течение длительного времени Должник не выполняет обязательства по оплате жилой площади.",
    ):
        body(t)
    acc = f", по лицевому счету №{card.account.strip()}" if card.account.strip() else ""
    body(f"Общая задолженность по жилищным и коммунальным платежам{acc} за период с {_v(card.debt_from)} "
         f"по {_v(card.debt_to)} составляет {_words(debt_a)}, кроме того, за период с {_v(card.pen_from)} "
         f"по {_v(card.pen_to)} на задолженность образовалась пеня в размере {_words(pen_a)}")
    body("В соответствии со статьями 153, 155 ЖК РФ собственник жилого помещения обязан ежемесячно до десятого числа месяца, следующего за истекшим месяцем, вносить плату за жилое помещение и коммунальные услуги.")
    body("Согласно ст. 309 ГК РФ обязательства должны исполняться надлежащим образом в соответствии с условиями обязательства и требованиями закона. Указанные требования Ответчик не исполняет.")
    who = fio_ins if known else f"собственником жилого помещения по указанному адресу: {prop_addr},"
    body(f"Досудебный порядок урегулирования спора с {who} соблюдён {org.name} "
         "ежемесячными выставлениями квитанций в адрес Должника.")
    body("До настоящего момента Должником не предприняты меры по погашению образовавшейся задолженности в полном объеме.")

    # просительная часть
    para("На основании вышеизложенного, в соответствии с долями должников, а также на основании "
         "ст.154, п. 14 ст. 155, ст. 158 Жилищного кодекса РФ, ст. 309 Гражданского кодекса РФ, ст. 121-123 ГПК РФ "
         f"просим **{court_request_title(court)}:**", J, 11, indent=1.0, after=6)
    dot = "" if known else "● "
    debtor = fio_gen if known else "Физическое лицо (фамилия, имя и отчество, которого не известно)"
    if not known:
        para("● **Запросить персональные данные должника, который является собственником жилого помещения "
             f"с кадастровым номером: {_v(card.cadastral)} (ФИО, дата и место рождения, место жительства, ИНН) "
             "у уполномоченных органов.**", J, 11, indent=1.25, after=6)
    para(f"{dot}Взыскать с {debtor} в пользу {org.name} задолженность за жилищные и коммунальные услуги за период "
         f"с {_v(card.debt_from)} по {_v(card.debt_to)} в размере {_words(debt_a)},", J, 11, indent=1.25, after=6)
    para(f"{dot}Взыскать с {debtor} в пользу {org.name} образовавшуюся на задолженность пеню в размере "
         f"{_words(pen_a)} с {_v(card.pen_from)} по {_v(card.pen_to)}.", J, 11, indent=1.25, after=6)
    para(f"{dot}Взыскать с {debtor} в пользу {org.name} расходы за оплату государственной пошлины в размере "
         f"{duty_txt} рублей.", J, 11, indent=1.25, after=14)

    # подпись и приложения
    para("**Представитель по доверенности**" if not org.sign_role.strip() else f"**{org.sign_role}**", J, 11)
    para(f"{org.name}\t\t\t\t_____________{_surname_first(org.sign_name)}", J, 11, after=10)
    para("**Приложение:**", J, 11)
    attachments = [
        "Копия заявления о выдаче судебного приказа для должника;",
        f"Платежное поручение об оплате государственной пошлины {_v(card.payment_order)};",
        f"Копия уведомления о предоставлении лицензии {_v(org.license_text)};",
        "Копия Протокола;",
        f"Лицевой счет №{_v(card.account)};",
        "Копия Истории начислений и платежей по управляющей компании;",
        f"Копия Счет-извещения за {_v(card.invoice_month)};",
        "Расчет пени по оплате коммунальных услуг;",
    ]
    if known:
        attachments.append(f"Выписка из ЕГРН об объекте недвижимости {flat} МКД {house} по {street};")
    attachments.append(f"Доверенность от {_v(org.poa_text)}")
    for a in attachments:
        para(a, J, 11)
    doc.save(str(path))
    return known
