"""Список судебных участков мировых судей: загружается с sudrf.ru (публичные данные ГАС «Правосудие»),
хранится в ~/.debtors/courts.json; из него в заявлении выбирается нужный участок."""

from __future__ import annotations

import re
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import date

import storage

COURTS_PATH = storage.COURTS_PATH
# Тот же адрес использует карта на странице «Участки мировых судей» sudrf.ru: код, название, адрес и координаты участков
LIST_URL = "https://sudrf.ru/index.php?id=300&act=ya_coords&type_suds=mir"
DEFAULT_REGIONS = "61"          # Ростовская область

# Регионы, для которых на sudrf.ru есть участки мировых судей: код (первые две цифры кода участка) -> название.
REGIONS = {
    "01": "Республика Адыгея", "02": "Республика Башкортостан", "03": "Республика Бурятия", "04": "Республика Алтай",
    "05": "Республика Дагестан", "06": "Республика Ингушетия", "07": "Кабардино-Балкарская Республика",
    "08": "Республика Калмыкия", "09": "Карачаево-Черкесская Республика", "10": "Республика Карелия",
    "11": "Республика Коми", "12": "Республика Марий Эл", "13": "Республика Мордовия",
    "14": "Республика Саха (Якутия)", "15": "Республика Северная Осетия — Алания", "16": "Республика Татарстан",
    "17": "Республика Тыва", "18": "Удмуртская Республика", "19": "Республика Хакасия", "20": "Чеченская Республика",
    "21": "Чувашская Республика", "22": "Алтайский край", "23": "Краснодарский край", "25": "Приморский край",
    "26": "Ставропольский край", "27": "Хабаровский край", "28": "Амурская область", "29": "Архангельская область",
    "30": "Астраханская область", "31": "Белгородская область", "32": "Брянская область", "33": "Владимирская область",
    "34": "Волгоградская область", "35": "Вологодская область", "36": "Воронежская область", "37": "Ивановская область",
    "38": "Иркутская область", "39": "Калининградская область", "40": "Калужская область", "41": "Камчатский край",
    "42": "Кемеровская область", "43": "Кировская область", "44": "Костромская область", "45": "Курганская область",
    "46": "Курская область", "47": "Ленинградская область", "48": "Липецкая область", "49": "Магаданская область",
    "50": "Московская область", "51": "Мурманская область", "52": "Нижегородская область", "53": "Новгородская область",
    "54": "Новосибирская область", "55": "Омская область", "56": "Оренбургская область", "57": "Орловская область",
    "58": "Пензенская область", "59": "Пермский край", "60": "Псковская область", "61": "Ростовская область",
    "62": "Рязанская область", "63": "Самарская область", "64": "Саратовская область", "65": "Сахалинская область",
    "66": "Свердловская область", "67": "Смоленская область", "68": "Тамбовская область", "69": "Тверская область",
    "70": "Томская область", "71": "Тульская область", "72": "Тюменская область", "73": "Ульяновская область",
    "74": "Челябинская область", "75": "Забайкальский край", "76": "Ярославская область", "77": "Москва",
    "79": "Еврейская автономная область", "86": "Ханты-Мансийский автономный округ — Югра",
    "87": "Чукотский автономный округ", "89": "Ямало-Ненецкий автономный округ",
    # Новые регионы. В публичном списке sudrf.ru участков этих регионов нет (см. missing_regions)
    "82": "Республика Крым", "92": "Севастополь", "80": "Донецкая Народная Республика",
    "81": "Луганская Народная Республика", "84": "Херсонская область", "85": "Запорожская область",
}


def region_label(code: str) -> str:
    """«61» -> «Ростовская область (61)»; неизвестный код показывается как есть."""
    code = code.strip().zfill(2)
    return f"{REGIONS[code]} ({code})" if code in REGIONS else code


def _prefix(code: str) -> str:
    """Числовая часть кода участка до букв: «61MS0203» -> «61»."""
    m = re.match(r"\d+", code)
    return m.group(0) if m else code[:2]


def missing_regions(courts: list, regions: str) -> list[str]:
    """Выбранные регионы, для которых в загруженном списке нет ни одного участка (подписи «Название (код)»)."""
    have = {_prefix(c.code) for c in courts}
    out = []
    for c in region_codes(regions):
        if c not in REGIONS:
            continue                                   # неизвестные коды отдельно не проверяем
        if c not in have:
            out.append(region_label(c))
    return out


def region_codes(regions: str) -> list[str]:
    """Коды из сохранённого значения («61» или «61, 23») по порядку, без повторов."""
    out = []
    for c in re.split(r"[,\s;]+", regions or ""):
        c = c.strip().zfill(2) if c.strip() else ""
        if c and c not in out:
            out.append(c)
    return out


def regions_summary(regions: str) -> str:
    """Короткая подпись для строки настроек: один регион — «Название (код)», несколько — «Название (код) и ещё N»."""
    codes = region_codes(regions)
    codes = codes or [DEFAULT_REGIONS]
    first = region_label(codes[0])
    return first if len(codes) == 1 else f"{first} и ещё {len(codes) - 1}"


def set_regions(regions: str) -> None:
    """Запоминает выбранный регион сразу (не дожидаясь загрузки списка участков); остальные данные файла не трогает."""
    data = _read_file()
    data["regions"] = regions
    storage.save_json(COURTS_PATH, "courts", data)


@dataclass
class Court:
    code: str = ""           # классификационный код: 61MS0203
    name: str = ""           # «Судебный участок № 10 Таганрогского судебного района Ростовской области»
    address: str = ""        # адрес суда: из sudrf.ru или исправленный пользователем
    judge: str = ""          # мировой судья участка — вводится вручную и запоминается
    base_address: str = ""   # адрес из sudrf.ru (address может быть исправлен вручную)


class DownloadError(Exception):
    """Не удалось загрузить список (текст можно показывать пользователю)."""


def ssl_context() -> ssl.SSLContext:
    """Сертификаты берём из certifi: у Python с python.org на macOS нет корневых сертификатов."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _default_urlopen(url, timeout: float = 90):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


_ENTRY = re.compile(r"\{type:'mir',name:'((?:[^'\\]|\\.)*)',adress:'((?:[^'\\]|\\.)*)',coord:")
_CODE = re.compile(r"balloons_user\['(\w+)'\]\[balloons_user\['\1'\]\.length\]=$")


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s).strip()


def parse(text: str) -> list[Court]:
    """Разбирает ответ sudrf.ru (JavaScript с записями balloons_user['61MS0203'][...]={…})."""
    out: dict[str, Court] = {}
    for m in _ENTRY.finditer(text):
        head = text[max(0, m.start() - 120):m.start()]
        cm = _CODE.search(head)
        if not cm:
            continue
        code = cm.group(1)
        out.setdefault(code, Court(code, _unescape(m.group(1)), _unescape(m.group(2))))
    return list(out.values())


def download(regions: str = DEFAULT_REGIONS, urlopen=_default_urlopen) -> list[Court]:
    """Загружает участки и оставляет только выбранные регионы (код региона; для старых настроек — несколько через запятую)."""
    try:
        with urlopen(LIST_URL) as resp:
            raw = resp.read()
    except Exception as e:
        raise DownloadError(f"Не удалось загрузить список участков с sudrf.ru: {getattr(e, 'reason', e)}") from None
    courts = parse(raw.decode("cp1251", "replace"))
    if not courts:
        raise DownloadError("Сайт sudrf.ru ответил в неожиданном формате — список участков не удалось разобрать.")
    wanted = {r.strip().zfill(2) for r in re.split(r"[,\s;]+", regions) if r.strip()}
    if wanted:
        courts = [c for c in courts if _prefix(c.code) in wanted]
    if not courts:
        raise DownloadError("В списке sudrf.ru нет участков для выбранных регионов: "
                            + "; ".join(region_label(c) for c in region_codes(regions) if c in REGIONS) + ".")
    return sorted(courts, key=lambda c: (_prefix(c.code).zfill(3), _sort_key(c.name)))


def _sort_key(name: str):
    m = re.search(r"№\s*(\d+)", name)
    return (re.sub(r"№\s*\d+", "", name).strip(), int(m.group(1)) if m else 0)


def _read_file() -> dict:
    data = storage.load_json(COURTS_PATH, "courts", {})
    return data if isinstance(data, dict) else {}


def load() -> dict:
    """{"regions", "updated", "courts": [Court, …], "last": код последнего выбранного участка}.
    К участкам применены ручные правки (судья, исправленный адрес суда) — они хранятся отдельно и не теряются
    при повторной загрузке списка."""
    data = _read_file()
    names = {"code", "name", "address"}
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    courts = []
    for d in data.get("courts", []):
        c = Court(**{k: v for k, v in d.items() if k in names})
        ov = overrides.get(c.code) or {}
        c.base_address = c.address
        c.address = ov.get("address") or c.address
        c.judge = ov.get("judge", "")
        courts.append(c)
    return {"regions": data.get("regions", DEFAULT_REGIONS), "updated": data.get("updated", ""),
            "courts": courts, "last": data.get("last", "")}


def save(regions: str, courts: list[Court], last: str = "", updated: str | None = None,
         overrides: dict | None = None) -> None:
    """Сохраняет список. Ручные правки (overrides) сохраняются как были, если не переданы явно."""
    if overrides is None:
        overrides = _read_file().get("overrides") or {}
    storage.save_json(COURTS_PATH, "courts", {
        "regions": regions, "updated": updated if updated is not None else date.today().isoformat(),
        "courts": [{"code": c.code, "name": c.name, "address": c.base_address or c.address} for c in courts],
        "last": last, "overrides": overrides})


def save_last(code: str) -> None:
    d = load()
    save(d["regions"], d["courts"], code, d["updated"])


def set_override(code: str, judge: str, address: str) -> None:
    """Запоминает судью и/или исправленный адрес суда для участка (пустые значения — правка снимается)."""
    data = _read_file()
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    base = next((d.get("address", "") for d in data.get("courts", []) if d.get("code") == code), "")
    ov = {}
    if judge.strip():
        ov["judge"] = judge.strip()
    if address.strip() and address.strip() != base:
        ov["address"] = address.strip()
    if ov:
        overrides[code] = ov
    else:
        overrides.pop(code, None)
    data["overrides"] = overrides
    storage.save_json(COURTS_PATH, "courts", data)


def short_name(court: Court | None) -> str:
    """«Судебный участок № 10 Таганрогского судебного района Ростовской области» → «№ 10 Таганрогского р-на»."""
    if court is None:
        return ""
    m = re.match(r"\s*Судебный участок\s*№\s*(\d+)\s+(\S+)", court.name, re.IGNORECASE)
    return f"№ {m.group(1)} {m.group(2)}" if m else court.name


def find_by_code(courts: list[Court], code: str) -> Court | None:
    return next((c for c in courts if c.code == code), None) if code else None


def search(courts: list[Court], query: str) -> list[Court]:
    """Фильтр по словам запроса (регистр не важен): «таганрог 10» → участок № 10 Таганрогского района."""
    words = [w for w in re.split(r"\s+", query.lower().replace("ё", "е").strip()) if w]
    def hay(c: Court) -> str:
        return f"{c.name} {c.code} {c.judge}".lower().replace("ё", "е")   # название, код, судья; адрес суда даёт шум
    res = []
    for c in courts:
        h = hay(c)
        if all(re.search(r"(?<!\d)" + re.escape(w) + r"(?!\d)" if w.isdigit() else re.escape(w), h) for w in words):
            res.append(c)
    return res


def _prepositional(rest: str) -> str:
    """«Таганрогского судебного района Ростовской области» → «в Таганрогском судебном районе Ростовской области»."""
    def fix(m):
        adj = m.group(1)
        adj = re.sub(r"ого$", "ом", adj)
        return f"{adj} судебном районе"
    out = re.sub(r"(\S+) судебного района", fix, rest, count=1)
    return f"в {out}" if out != rest else rest


def header_text(court: Court) -> str:
    """Три строки шапки заявления: «Мировому судье в … районе / на судебном участке № N / адрес суда»."""
    m = re.match(r"\s*Судебный участок\s*№\s*(\d+)\s*(.*)$", court.name, re.IGNORECASE)
    if m:
        num, rest = m.group(1), m.group(2).strip()
        lines = [f"**Мировому судье {_prepositional(rest)}**".replace("  ", " ").rstrip(),
                 f"**на судебном участке № {num}**"]
    else:                                                         # необычное название — печатаем как есть
        lines = ["**Мировому судье**", f"**{court.name}**"]
    if court.judge.strip():
        lines.append(f"Судья: {court.judge.strip()}")
    if court.address:
        lines.append(court.address)
    return "\n".join(lines)
