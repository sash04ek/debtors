"""Логика: чтение Excel, отбор физических лиц, сортировка по сумме долга, выгрузка."""

from __future__ import annotations

import json
import re
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# Признаки юридических лиц / организаций в наименовании (регистр не важен).
DEFAULT_ORG_MARKERS = [
    "ООО", "ОАО", "ЗАО", "ПАО", "АО", "НАО", "МУП", "ГУП", "ФГУП", "МКУ", "МБУ",
    "ГБУ", "ГКУ", "ФГБУ", "АНО", "НКО", "ТСЖ", "ТСН", "СНТ", "ЖСК", "ГСК", "КФХ",
    "ПК", "ОДО", "ТОО", "LLC", "LTD", "INC",
    "общество", "предприятие", "учреждение", "компания", "корпорация",
    "фонд", "товарищество", "кооператив", "администрация", "управление",
    "холдинг", "группа", "завод", "банк", "агентство", "центр",
    "сервис", "условка", "магазин", "сауна", "парикмахерская", "кафе", "аптека", "салон",
]
IP_MARKERS = ["ИП", "индивидуальный предприниматель"]


# Версия списка по умолчанию: при её росте новые слова добавляются в сохранённые настройки.
MARKERS_VERSION = 2


@dataclass
class Settings:
    top_n: int = 20
    name_col: str | None = None
    debt_col: str | None = None
    inn_col: str | None = None          # необязательно
    addr_col: str | None = None         # адрес дома (для претензий и фильтра по домам)
    house_col: str | None = None        # номер дома, если он в отдельной колонке от улицы («Улица» + «Дом»)
    flat_col: str | None = None         # квартира
    type_col: str | None = None         # необязательно: колонка «Тип лица»
    type_value: str = "физ"             # подстрока, означающая физлицо в type_col
    ip_as_person: bool = False          # считать ИП физлицами
    skip_nonresidential: bool = True    # пропускать нежилые: «Кв» вида н/п, н/п2, н/п доп…
    restore_state: bool = True          # при запуске восстанавливать файл, отфильтрованный список и отметки
    sort_col: str | None = None         # по какой колонке сортировать перед отбором N; None = по сумме долга
    sort_desc: bool = True              # True — по убыванию (от большего к меньшему)
    page_size: int = 50                 # строк таблицы на одной странице
    col_widths: dict = field(default_factory=dict)       # ширина колонок таблицы, заданная мышью: заголовок -> пиксели
    hidden_cols: list[str] = field(default_factory=list)  # скрытые колонки таблицы (по заголовку)
    courts_query: str = ""              # текст в поиске окна «Судьи и адреса участков» — запоминается между открытиями
    out_dir: str = ""                   # папка, куда создаются документы (запоминается)
    recent_files: list[str] = field(default_factory=list)   # последние открытые файлы (новые первыми)
    welcomed: bool = False              # приветствие первого запуска уже показано
    geometry: str = ""                  # размер и положение главного окна («980x700+120+60»)
    table_font: str = "normal"          # размер шрифта таблицы: normal / large / xlarge
    only_managed: bool = False          # в отбор попадают только дома, которые сейчас в управлении (по дате в списке домов)
    duty_auto: bool = True              # госпошлину в заявлении считать по ст. 333.19 НК РФ (ручное значение в карточке главнее)
    duty_scale: list = field(default_factory=list)      # таблица ставок; пусто — встроенная (duty.DEFAULT_SCALE)
    duty_share: float = 50.0            # судебный приказ: % от пошлины по иску
    theme: str = "system"               # оформление: system — как в системе, light — светлое, dark — тёмное
    org_markers: list[str] = field(default_factory=lambda: list(DEFAULT_ORG_MARKERS))
    markers_version: int = MARKERS_VERSION   # для дозаписи новых слов в сохранённый список


@dataclass
class Sheet:
    headers: list[str]
    rows: list[list]                    # значения строк под заголовком
    title: str = ""                     # текст над таблицей (название отчёта, организация)


def _is_xls(path) -> bool:
    return str(path).lower().endswith(".xls")


def _xls_rows(path, sheet_name):
    import xlrd
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_name(sheet_name) if sheet_name else wb.sheet_by_index(0)
    return [[(None if v == "" else v) for v in ws.row_values(i)] for i in range(ws.nrows)]


def list_sheets(path: str | Path) -> list[str]:
    if _is_xls(path):
        import xlrd
        return xlrd.open_workbook(str(path), on_demand=True).sheet_names()
    wb = load_workbook(path, read_only=True)
    try:
        return wb.sheetnames
    finally:
        wb.close()


def read_sheet(path: str | Path, sheet_name: str | None = None) -> Sheet:
    """Читает лист; строкой заголовка считается первая строка, где заполнено ≥2 ячеек текстом."""
    if _is_xls(path):
        all_rows = _xls_rows(path, sheet_name)
    else:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name] if sheet_name else wb.active
            all_rows = [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()

    header_idx = 0
    title = ""
    for i, r in enumerate(all_rows[:50]):
        if sum(1 for v in r if isinstance(v, str) and v.strip()) >= 2:
            header_idx = i
            break
    title = " ".join(str(v) for r in all_rows[:header_idx] for v in r if v not in (None, ""))
    if not all_rows:
        return Sheet([], [])

    raw = all_rows[header_idx]
    headers, seen = [], {}
    for i, v in enumerate(raw):
        h = str(v).strip() if v not in (None, "") else f"Колонка {get_column_letter(i + 1)}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        headers.append(h)

    rows = []
    for r in all_rows[header_idx + 1:]:
        if all(v in (None, "") for v in r):
            continue
        r = list(r) + [None] * (len(headers) - len(r))
        rows.append(r[:len(headers)])
    return Sheet(headers, rows, title)


def guess_columns(headers: list[str]) -> dict[str, str | None]:
    """Пытается угадать нужные колонки по названиям."""
    def find(*keys, exclude=()):
        for h in headers:
            low = h.lower()
            if any(k in low for k in keys) and not any(e in low for e in exclude):
                return h
        return None

    return {
        "name_col": find("фио", "должник", "наименован", "контрагент", "абонент", "клиент", "ф.и.о"),
        "debt_col": find("сумма долга", "задолж", "долг", "сальдо", "сумма", "к оплате",
                         exclude=("дата", "пени", "договор")),
        "inn_col": find("инн"),
        "addr_col": find("адрес", "улиц") or find("дом"),
        "house_col": next((h for h in headers if re.fullmatch(r"\s*(дом|№ дома|номер дома|д\.?)\s*", h.lower())), None),
        "flat_col": find("кв", "помещен"),
        "type_col": find("тип лица", "вид лица", "тип контрагента", "категория", "тип"),
    }


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))                                    # 114.0 → «114»
    return str(v).strip()


def row_address(row: list, idx: dict, addr_col: str | None, house_col: str | None = None) -> str:
    """Адрес дома строки: колонка «Адрес» или «Улица» + отдельная колонка с номером дома («10-й пер» + «114»)."""
    addr = _cell_text(row[idx[addr_col]]) if addr_col and addr_col in idx else ""
    house = _cell_text(row[idx[house_col]]) if house_col and house_col in idx and house_col != addr_col else ""
    if house and house not in addr:
        return f"{addr} {house}".strip()
    return addr


_NUM_CLEAN = re.compile(r"[^\d,.\-]")


def parse_amount(v) -> float | None:
    """Разбирает сумму: 1234.5, '1 234,50', '1 234,50 руб.', '-' и т.п."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    # strip(".,") убирает точку от «руб.» и прочие хвосты
    s = _NUM_CLEAN.sub("", str(v).replace(" ", "")).strip(".,")
    if not s or s == "-":
        return None
    if "," in s and "." in s:
        # последний разделитель — десятичный
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
        if s.count(".") > 1:
            head, _, tail = s.rpartition(".")
            s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def _has_marker(text: str, markers: list[str]) -> bool:
    for m in markers:
        m = m.strip()
        if not m:
            continue
        # Короткие аббревиатуры ищем целым словом, чтобы «АО» не срабатывало внутри фамилий.
        pattern = r"(?<![\w])" + re.escape(m) + r"(?![\w])" if len(m) <= 5 else re.escape(m)
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def classify(name, inn, type_value, s: Settings) -> tuple[bool, str]:
    """Возвращает (является_физлицом, причина)."""
    name = str(name or "").strip()

    if s.type_col:
        t = str(type_value or "").lower()
        ok = s.type_value.lower() in t
        return ok, f"тип лица: «{type_value}»"

    is_ip = _has_marker(name, IP_MARKERS)
    if is_ip:
        return s.ip_as_person, "ИП"

    if s.inn_col and inn not in (None, "") and looks_like_fio(name):
        digits = re.sub(r"\D", "", str(inn))
        if isinstance(inn, (int, float)) and len(digits) == 11:
            digits = "0" + digits  # ведущий ноль потерян в числовой ячейке
        if len(digits) == 10:
            return False, "ИНН 10 цифр (юрлицо)"
        if len(digits) == 12:
            return (not _has_marker(name, s.org_markers)), "ИНН 12 цифр"

    if not name:
        return False, "пустое наименование"
    if not looks_like_fio(name):
        return False, "не похоже на ФИО"
    if _has_marker(name, s.org_markers):
        return False, "признак организации в наименовании"
    if re.search(r"[«»\"]", name):
        return False, "кавычки в наименовании (похоже на организацию)"
    return True, "похоже на ФИО"


@dataclass
class Result:
    headers: list[str]
    top: list[list]            # отобранные строки (исходные значения)
    amounts: list[float]
    stats: dict


_RESIDENT_FLAT = re.compile(r"^\s*['’`]?\d")


def is_nonresidential(flat) -> bool:
    """Жилая квартира — номер начинается с цифры («14», «46доп», «234,235», «19\'»).
    Всё остальное — нежилое: н/п, н/п2, магазин, сауна, подвал, парикмахерская, пусто…"""
    if str(flat if flat is not None else "").strip() == "":
        return False                                       # квартира не указана — не считаем помещение нежилым
    return not _RESIDENT_FLAT.match(str(flat))


_FIO_WORD = re.compile(r"^[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)*\.?$")


def looks_like_fio(name: str) -> bool:
    """«Фамилия Имя [Отчество]» или «Фамилия И. О.»: 2–5 слов кириллицей, без цифр и кавычек;
    фамилия — не короче 2 букв, остальные слова — имя/отчество или инициалы."""
    parts = re.sub(r"[.,]+", " ", name).split()
    if not 2 <= len(parts) <= 5:
        return False
    if len(parts[0]) < 2 or not all(_FIO_WORD.match(p) for p in parts):
        return False
    return True


_DATE = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\s*$")
_NUMBER = re.compile(r"^[-+]?\d[\d\s\u00a0]*([.,]\d+)?$")


def _parse_cell(v, kind: str):
    """Значение ячейки как ключ сортировки нужного вида; None — пусто (такие строки всегда в конце)."""
    if v is None or str(v).strip() == "":
        return None
    if kind == "date":
        if hasattr(v, "toordinal"):
            return v.toordinal()
        m = _DATE.match(str(v))
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y + 2000 if y < 100 else y) * 10000 + mo * 100 + d
    if kind == "num":
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        t = str(v).replace("\u00a0", "").replace(" ", "").replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None
    # текст: «натуральная» сортировка, чтобы «2» шло перед «10», а регистр не влиял
    parts = re.split(r"(\d+)", str(v).casefold().replace("ё", "е"))
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def sort_by_values(items: list, get, desc: bool) -> list:
    """Сортирует items по значению get(item): даты, числа и текст определяются автоматически.
    Пустые значения всегда идут в конец; равные значения сохраняют прежний порядок."""
    vals = [get(x) for x in items]
    filled = [v for v in vals if v is not None and str(v).strip() != ""]
    kind = "text"
    if filled:
        if sum(1 for v in filled if hasattr(v, "toordinal") or _DATE.match(str(v))) >= 0.9 * len(filled):
            kind = "date"
        elif sum(1 for v in filled if isinstance(v, (int, float)) or _NUMBER.match(str(v))) >= 0.9 * len(filled):
            kind = "num"
    keyed, empty = [], []
    for it, v in zip(items, vals):
        k = _parse_cell(v, kind)
        (empty if k is None else keyed).append((k, it))
    keyed.sort(key=lambda t: t[0], reverse=desc)
    return [it for _, it in keyed] + [it for _, it in empty]


def process(sheet: Sheet, s: Settings, org=None) -> Result:
    """org — организация: если у неё заданы дома, берутся только строки этих домов."""
    if not s.name_col or not s.debt_col:
        raise ValueError("Выберите колонки «ФИО / Наименование» и «Сумма долга».")
    idx = {h: i for i, h in enumerate(sheet.headers)}
    ni, di = idx[s.name_col], idx[s.debt_col]
    ii = idx.get(s.inn_col) if s.inn_col else None
    ti = idx.get(s.type_col) if s.type_col else None

    houses = None
    managed = None                                        # дома в управлении сейчас; задаётся при «Только дома в управлении»
    if org is not None and getattr(org, "houses", None):
        if not s.addr_col:
            raise ValueError("У организации заданы дома — выберите колонку «Адрес».")
        from orgs import is_managed, norm_addr
        houses = {norm_addr(h["address"]) for h in org.houses}
        if s.only_managed:
            managed = {norm_addr(h["address"]) for h in org.houses if is_managed(h.get("since", ""))}
    ai = idx[s.addr_col] if s.addr_col else None
    addr_of = lambda r: row_address(r, idx, s.addr_col, s.house_col)
    fi = idx[s.flat_col] if (s.flat_col and s.skip_nonresidential) else None

    persons, skipped_org, skipped_amount, other_org, nonres, not_managed = [], 0, 0, 0, 0, 0
    for r in sheet.rows:
        if houses is not None and norm_addr(addr_of(r)) not in houses:
            other_org += 1
            continue
        if managed is not None and norm_addr(addr_of(r)) not in managed:
            not_managed += 1                              # дом из списка организации, но сейчас не в управлении
            continue
        flat = None
        if fi is not None:
            flat = r[fi]
            if flat in (None, "") and ai is not None:
                from orgs import extract_flat
                flat = extract_flat(addr_of(r))           # квартира могла быть записана в адресе: «…-к.1»
        if fi is not None and is_nonresidential(flat):
            nonres += 1
            continue
        is_person, _ = classify(r[ni], r[ii] if ii is not None else None,
                                r[ti] if ti is not None else None, s)
        if not is_person:
            skipped_org += 1
            continue
        amt = parse_amount(r[di])
        if amt is None or amt <= 0:
            skipped_amount += 1
            continue
        persons.append((amt, r))

    persons.sort(key=lambda x: x[0], reverse=True)          # сначала по долгу: при равных значениях крупнее долг выше
    if s.sort_col and s.sort_col != s.debt_col and s.sort_col in idx:
        ci = idx[s.sort_col]
        persons = sort_by_values(persons, lambda p: p[1][ci], s.sort_desc)
    elif not s.sort_desc:
        persons.sort(key=lambda x: x[0])                        # по сумме долга по возрастанию
    top = persons[:max(1, int(s.top_n))]
    return Result(
        headers=sheet.headers,
        top=[r for _, r in top],
        amounts=[a for a, _ in top],
        stats={
            "всего строк": len(sheet.rows),
            "дома других организаций": other_org,
            "дома не в управлении": not_managed,
            "нежилые помещения": nonres,
            "не физлица": skipped_org,
            "без долга / сумма не распознана": skipped_amount,
            "физлиц с долгом": len(persons),
            "отобрано": len(top),
            "сумма долга отобранных": sum(a for a, _ in top),
        },
    )


META_SHEET = "_debtors_meta"          # скрытый служебный лист: по нему программа узнаёт свой отфильтрованный файл
STATS_SHEET = "Статистика"


def export(result: Result, path: str | Path, debt_col: str, meta: dict | None = None) -> None:
    """Сохраняет отфильтрованный список в Excel. В файл добавляется скрытый лист с меткой и настройками колонок,
    чтобы программа могла открыть его позже как отфильтрованный (detect_file_kind / read_filtered)."""
    wb = Workbook()
    ws = wb.active
    ws.title = f"Топ-{len(result.top)} должников"
    di = result.headers.index(debt_col)
    ws.append(["№"] + result.headers)
    for n, (row, amt) in enumerate(zip(result.top, result.amounts), 1):
        row = list(row)
        row[di] = amt
        ws.append([n] + row)

    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="DDEBF7")
    for c in ws[1]:
        c.font, c.fill = bold, fill
    for row in ws.iter_rows(min_row=2, min_col=di + 2, max_col=di + 2):
        for c in row:
            c.number_format = "#,##0.00"
    ws.append([])
    ws.append(["", "Итого"] + [None] * (di - 1) + [sum(result.amounts)])
    ws.cell(ws.max_row, di + 2).number_format = "#,##0.00"
    ws.cell(ws.max_row, 2).font = bold

    for i, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 6), 60)
    ws.freeze_panes = "A2"

    st = wb.create_sheet(STATS_SHEET)
    for k, v in result.stats.items():
        st.append([k, v])
    st.column_dimensions["A"].width = 36
    st.column_dimensions["B"].width = 18

    info = {"app": "debtors", "format": 1, "kind": "filtered", "debt_col": debt_col,
            "headers": result.headers, "stats": result.stats, "created": date.today().isoformat()}
    info.update(meta or {})
    ms = wb.create_sheet(META_SHEET)
    ms["A1"] = json.dumps(info, ensure_ascii=False)
    ms["A2"] = "Служебный лист программы «Должники»: по нему программа узнаёт отфильтрованный файл. Не удаляйте."
    ms.sheet_state = "hidden"
    wb.save(path)


def detect_file_kind(path: str | Path) -> tuple[str, dict]:
    """('filtered', метаданные) для файла, сохранённого этой программой («Сохранить в Excel»),
    иначе ('original', {}). Понимает и файлы старых версий без служебного листа (по структуре)."""
    if not str(path).lower().endswith((".xlsx", ".xlsm")):
        return "original", {}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return "original", {}
    try:
        names = wb.sheetnames
        if META_SHEET in names:
            try:
                meta = json.loads(str(wb[META_SHEET]["A1"].value))
                if isinstance(meta, dict) and meta.get("kind") == "filtered":
                    return "filtered", meta
            except (ValueError, TypeError):
                pass
        if STATS_SHEET in names and names and names[0].startswith("Топ-"):        # файл более ранней версии
            first = next(wb[names[0]].iter_rows(min_row=1, max_row=1, values_only=True), ())
            if first and str(first[0]).strip() == "№":
                return "filtered", {"legacy": True}
        return "original", {}
    finally:
        wb.close()


def read_filtered(path: str | Path) -> dict:
    """Читает отфильтрованный файл: {"headers", "rows", "amounts", "stats", "meta", "sheet"}.
    Колонка «№» и строка «Итого» отбрасываются."""
    kind, meta = detect_file_kind(path)
    if kind != "filtered":
        raise ValueError("Это не отфильтрованный файл программы.")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        names = wb.sheetnames
        sheet = next(n for n in names if n not in (META_SHEET, STATS_SHEET))
        rows = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
        headers = [str(h) for h in rows[0][1:] if h is not None]
        data = []
        for r in rows[1:]:
            if not (isinstance(r[0], (int, float)) and not isinstance(r[0], bool)):
                break                                            # пустая строка и «Итого» — конец списка
            row = list(r[1:1 + len(headers)])
            data.append(row + [None] * (len(headers) - len(row)))
        stats = {}
        if STATS_SHEET in names:
            for k, v in wb[STATS_SHEET].iter_rows(values_only=True):
                if k:
                    stats[str(k)] = v
        debt_col = meta.get("debt_col") or guess_columns(headers).get("debt_col")
        di = headers.index(debt_col) if debt_col in headers else None
        amounts = [(parse_amount(row[di]) or 0.0) if di is not None else 0.0 for row in data]
        return {"headers": headers, "rows": data, "amounts": amounts, "stats": stats or meta.get("stats", {}),
                "meta": {**meta, "debt_col": debt_col}, "sheet": sheet}
    finally:
        wb.close()
