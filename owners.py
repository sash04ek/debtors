"""Карточки помещений с собственниками (персональные данные для заявления о судебном приказе).

Хранятся локально в ~/.debtors/owners.json (права 600). Ключ — адрес дома + квартира из отчёта.
У помещения может быть несколько собственников: заявление подаётся на каждого.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

import storage

OWNERS_PATH = storage.OWNERS_PATH

# Поля, общие для всего дома: подставляются в новую карточку из любой уже заполненной карточки этого дома.
HOUSE_FIELDS: tuple = ()   # суд определяется по справочнику, дата управления — по списку домов организации


@dataclass
class Owner:
    """Один собственник помещения."""
    fio: str = ""                  # у первого собственника пусто = взять ФИО из отчёта
    fio_gen: str = ""              # в родительном: «с Ивановой Анны Петровны» (пусто = склонить автоматически)
    fio_ins: str = ""              # в творительном: «спор с Ивановой Анной Петровной»
    share: str = ""                # доля в праве (1/2, 1/3, 50%) — только указывается в заявлении, на суммы не влияет
    birth_date: str = ""
    birth_place: str = ""
    passport: str = ""             # серия и номер, кем и когда выдан
    reg_address: str = ""
    live_address: str = ""         # пусто = адрес помещения


OWNER_FIELDS = tuple(f.name for f in fields(Owner))


@dataclass
class Card:
    address: str = ""              # адрес дома как в отчёте, напр. «Водопроводная ул 13»
    flat: str = ""                 # квартира как в отчёте
    unknown: bool = False          # собственники неизвестны: шаблон «собственник неизвестен»
    owners: list = field(default_factory=list)   # собственники помещения (список Owner)
    # --- собственник неизвестен ---
    cadastral: str = ""
    # --- по делу ---
    account: str = ""              # лицевой счёт
    debt: str = ""                 # пусто = сумма из отчёта
    penalty: str = ""
    debt_from: str = ""
    debt_to: str = ""
    pen_from: str = ""
    pen_to: str = ""
    duty: str = ""                 # госпошлина; пусто = значение по умолчанию организации
    payment_order: str = ""        # платёжное поручение: «№6462 от 28.09.2023»
    invoice_month: str = ""        # счёт-извещение за: «март 2023 года»
    # --- по дому ---
    managed_since: str = ""        # дом в управлении с: «01.11.2021»
    court_code: str = ""           # судебный участок из списка (код, напр. 61MS0203); пусто = выбрать при формировании

    def __post_init__(self):
        self.owners = [o if isinstance(o, Owner) else Owner(**{k: v for k, v in dict(o).items() if k in OWNER_FIELDS})
                       for o in self.owners]

    def people(self, report_fio: str = "") -> list[Owner]:
        """Собственники, на которых подаются заявления (ФИО приведены к обычному регистру).
        Нет собственников в карточке — один собственник по ФИО из отчёта; «неизвестны» — пусто."""
        if self.unknown:
            return []
        report = str(report_fio or "").strip()
        out = []
        for i, o in enumerate(self.owners):
            fio = normalize_fio(o.fio.strip() or (report if i == 0 else ""))   # пустое ФИО первого — из отчёта
            if fio:
                out.append(replace(o, fio=fio))
        if not self.owners and report:
            out = [Owner(fio=normalize_fio(report))]
        return out


def make_key(address, flat) -> str:
    from orgs import norm_addr
    a = norm_addr(address)
    # апостроф («19\'») сохраняем: это отдельная запись отчёта, а не та же квартира «19»
    f = re.sub(r"\s+", "", str(flat if flat is not None else "")).lower().replace("’", "'").replace("`", "'")
    return f"{a}|{f}"


def _load_all() -> dict[str, dict]:
    try:
        data = json.loads(OWNERS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_all(data: dict[str, dict]) -> None:
    OWNERS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(OWNERS_PATH, 0o600)  # персональные данные — только владельцу
    except OSError:
        pass


_LEGACY_OWNER_KEYS = ("fio", "fio_gen", "fio_ins", "birth_date", "birth_place", "passport", "reg_address", "live_address")


def _from_dict(d: dict) -> Card:
    d = dict(d)
    if "owners" not in d:                        # старая карточка: данные одного собственника лежали в самой карточке
        legacy = {k: d[k] for k in _LEGACY_OWNER_KEYS if d.get(k)}
        d["owners"] = [legacy] if legacy else []
    names = {f.name for f in fields(Card)}
    return Card(**{k: v for k, v in d.items() if k in names})


def get_card(address, flat) -> Card | None:
    d = _load_all().get(make_key(address, flat))
    return _from_dict(d) if d else None


def get_or_new(address, flat) -> Card:
    """Сохранённая карточка либо новая, в которую подставлены данные по дому из соседних карточек."""
    card = get_card(address, flat)
    if card:
        return card
    card = Card(address=str(address or "").strip(), flat=re.sub(r"['’`]+", "", str(flat or "")).strip())
    prefix = make_key(address, "").split("|")[0] + "|"
    for key, d in _load_all().items():
        if key.startswith(prefix):
            for f in HOUSE_FIELDS:
                if d.get(f) and not getattr(card, f):
                    setattr(card, f, d[f])
    return card


def save_card(card: Card) -> None:
    data = _load_all()
    data[make_key(card.address, card.flat)] = asdict(card)
    _save_all(data)


TRASH_PATH = storage.TRASH_PATH
TRASH_DAYS = 30                                   # сколько дней удалённая карточка лежит в корзине


def _load_trash() -> dict[str, dict]:
    try:
        data = json.loads(TRASH_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_trash(data: dict[str, dict]) -> None:
    TRASH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TRASH_PATH, 0o600)
    except OSError:
        pass


def delete_card(address, flat) -> None:
    """Удаляет карточку в корзину: её можно восстановить в течение TRASH_DAYS дней."""
    from datetime import date, timedelta
    key = make_key(address, flat)
    data = _load_all()
    card = data.pop(key, None)
    if card is None:
        return
    trash = _load_trash()
    limit = (date.today() - timedelta(days=TRASH_DAYS)).isoformat()
    trash = {k: v for k, v in trash.items() if str(v.get("deleted", "")) >= limit}      # старое из корзины убираем
    trash[key] = {"card": card, "deleted": date.today().isoformat()}
    _save_trash(trash)
    _save_all(data)


def has_trashed(address, flat) -> bool:
    return make_key(address, flat) in _load_trash()


def restore_card(address, flat) -> Card | None:
    """Возвращает удалённую карточку из корзины (если на её месте нет новой). None — в корзине её нет."""
    key = make_key(address, flat)
    trash = _load_trash()
    item = trash.get(key)
    if not item:
        return None
    data = _load_all()
    if key not in data:
        data[key] = item["card"]
        _save_all(data)
    trash.pop(key)
    _save_trash(trash)
    return _from_dict(data[key])


_LOWER_PARTS = {"оглы", "кызы", "улы", "кизи", "гызы"}


def normalize_fio(fio: str) -> str:
    """«КЛАДЧЕНКО ВЕРА ИВАНОВНА» → «Кладченко Вера Ивановна»; инициалы («Л. И.») не трогает."""
    def fix(word: str) -> str:
        if re.fullmatch(r"(?:[А-Яа-яЁёA-Za-z]\.)+", word):
            return word.upper()                               # инициалы «В.Н.» остаются заглавными
        if len(word.rstrip(".")) <= 1:
            return word.upper()
        low = word.lower()
        if low in _LOWER_PARTS:
            return low if word.isupper() or word.islower() else word
        if word.isupper() or word.islower():
            return "-".join(p[:1].upper() + p[1:].lower() for p in word.split("-"))
        return word
    return " ".join(fix(w) for w in re.sub(r"\s+", " ", fio).strip().split(" "))


def gender_by_fio(fio: str) -> str:
    """'f' или 'm': по отчеству, затем по фамилии, затем по имени."""
    parts = fio.lower().split()
    tail = " ".join(parts[2:]) if len(parts) > 2 else ""
    if re.search(r"(вна|чна|кызы|кизи|гызы)\b", tail):
        return "f"
    if re.search(r"(ич|оглы|улы)\b", tail):
        return "m"
    surname = parts[0] if parts else ""
    if re.search(r"(ова|ева|ёва|ина|ына|ская|цкая|ная|ая|яя|ская)$", surname):
        return "f"
    if re.search(r"(ов|ев|ёв|ин|ын|ский|цкий|ной|ой|ий|ый)$", surname):
        return "m"
    first = parts[1] if len(parts) > 1 else ""
    if len(first.rstrip(".")) > 1 and first.endswith(("а", "я")) and first not in ("илья", "никита", "лёва", "сава"):
        return "f"
    return "m"


# Отчества, у которых в творительном падеже ударное окончание «-ом»: Ильичом, Кузьмичом…
_STRESSED_PATR = {"ильич", "кузьмич", "лукич", "фомич"}
# Фамилии с беглой гласной, которые библиотека склоняет неверно
_SURNAME_EXCEPTIONS = {"заяц": ("Зайца", "Зайцем")}


def _decl_a_name(name: str, case: str) -> str:
    """Мужское имя на -а/-я (Никита, Кузьма, Фома, Лука, Данила, Саша): склоняется как 1-е склонение."""
    low = name.lower()
    stem, end = name[:-1], low[-1]
    if case == "gen":
        if end == "я":
            return stem + ("и" if stem[-1:].lower() != "и" else "и")
        return stem + ("и" if stem[-1:].lower() in "гкхжчшщ" else "ы")
    if end == "я":
        return stem + ("ией" if stem[-1:].lower() == "и" else "ей")
    return stem + ("ей" if stem[-1:].lower() in "жчшщц" else "ой")


def _ortho(word_out: str, word_src: str) -> str:
    """Орфография изменённых слов: после г, к, х, ж, ч, ш, щ вместо «ы» пишется «и» (Ольги, Анжелики)."""
    if word_out != word_src:
        return re.sub(r"([гкхжчшщ])ы$", r"\1и", word_out)
    return word_out


def decline_fio(fio: str, case: str) -> str:
    """Склонение «Фамилия Имя Отчество» в 'gen' (кого) или 'ins' (кем). При сбое вернёт ФИО как есть."""
    fio = normalize_fio(fio)
    parts = fio.split()
    if len(parts) < 2:
        return fio
    try:
        from petrovich.enums import Case, Gender
        from petrovich.main import Petrovich
        p = Petrovich()
        c = Case.GENITIVE if case == "gen" else Case.INSTRUMENTAL
        female = gender_by_fio(fio) == "f"
        g = Gender.FEMALE if female else Gender.MALE
        surname, first = parts[0], parts[1]
        patr = " ".join(parts[2:])

        # фамилия
        low = surname.lower()
        if low in _SURNAME_EXCEPTIONS and not female:
            sn = _SURNAME_EXCEPTIONS[low][0 if case == "gen" else 1]
        elif low.endswith(("ых", "их")):
            sn = surname                                    # Белых, Черных, Долгих — не склоняются
        else:
            sn = _ortho(p.lastname(surname, c, g), surname)
            if case == "ins" and not female and low.endswith("ач"):
                sn = surname + "ом"                         # Ткач → Ткачом, Богач → Богачом
        # имя
        fn = _ortho(p.firstname(first, c, g), first)
        if not female and fn == first and first.lower().endswith(("а", "я")) and len(first) > 2:
            fn = _decl_a_name(first, case)
        out = [sn, fn]
        # отчество
        if patr:
            if len(parts) == 3:
                pt = _ortho(p.middlename(patr, c, g), patr)
                if case == "ins" and patr.lower() in _STRESSED_PATR:
                    pt = patr + "ом"
            else:
                pt = patr
            out.append(pt)
        return " ".join(out)
    except Exception:
        return fio
