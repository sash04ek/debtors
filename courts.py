"""Список судебных участков мировых судей: загружается с sudrf.ru (публичные данные ГАС «Правосудие»),
хранится в ~/.debtors/courts.json; из него в заявлении выбирается нужный участок."""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

import storage

COURTS_PATH = storage.COURTS_PATH
# Тот же адрес использует карта на странице «Участки мировых судей» sudrf.ru: код, название, адрес и координаты участков
LIST_URL = "https://sudrf.ru/index.php?id=300&act=ya_coords&type_suds=mir"
DEFAULT_REGIONS = "61"          # Ростовская область


@dataclass
class Court:
    code: str = ""           # классификационный код: 61MS0203
    name: str = ""           # «Судебный участок № 10 Таганрогского судебного района Ростовской области»
    address: str = ""        # адрес суда: из sudrf.ru или исправленный пользователем
    judge: str = ""          # мировой судья участка — вводится вручную и запоминается
    base_address: str = ""   # адрес из sudrf.ru (address может быть исправлен вручную)


class DownloadError(Exception):
    """Не удалось загрузить список (текст можно показывать пользователю)."""


def _ssl_context() -> ssl.SSLContext:
    """Сертификаты берём из certifi: у Python с python.org на macOS нет корневых сертификатов."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _default_urlopen(url, timeout: float = 90):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


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
    """Загружает участки и оставляет только выбранные регионы (коды через запятую, например «61» или «61, 23»)."""
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
        courts = [c for c in courts if c.code[:2] in wanted]
    if not courts:
        raise DownloadError("Для указанных регионов участков не найдено. Проверьте коды регионов (61 — Ростовская область).")
    return sorted(courts, key=lambda c: (c.code[:2], _sort_key(c.name)))


def _sort_key(name: str):
    m = re.search(r"№\s*(\d+)", name)
    return (re.sub(r"№\s*\d+", "", name).strip(), int(m.group(1)) if m else 0)


def _read_file() -> dict:
    try:
        data = json.loads(COURTS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
    COURTS_PATH.write_text(json.dumps(
        {"regions": regions, "updated": updated if updated is not None else date.today().isoformat(),
         "courts": [{"code": c.code, "name": c.name, "address": c.base_address or c.address} for c in courts],
         "last": last, "overrides": overrides}, ensure_ascii=False, indent=2), encoding="utf-8")


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
    COURTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
