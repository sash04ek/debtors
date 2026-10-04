"""Папка с данными программы: все настройки и данные лежат в одном месте — ~/.debtors/.

Раньше файлы лежали в домашней папке россыпью (~/.debtors_*.json); при первом запуске
новой версии они переносятся в папку. Другое место можно задать переменной DEBTORS_HOME."""
import json
import re
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

LEGACY = {
    "settings.json": ".debtors_finder.json",
    "orgs.json": ".debtors_orgs.json",
    "courts.json": ".debtors_courts.json",
    "owners.json": ".debtors_owners.json",
    "state.json": ".debtors_state.json",
}


def data_dir() -> Path:
    d = Path(os.environ.get("DEBTORS_HOME") or Path.home() / ".debtors")
    try:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)                       # внутри персональные данные — только владельцу
    except OSError:
        pass
    return d


def _migrate(d: Path) -> None:
    home = Path.home()
    for new, old in LEGACY.items():
        src, dst = home / old, d / new
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
            except OSError:
                pass


DATA_DIR = data_dir()
if not os.environ.get("DEBTORS_HOME"):
    _migrate(DATA_DIR)

SETTINGS_PATH = DATA_DIR / "settings.json"
ORGS_PATH = DATA_DIR / "orgs.json"
COURTS_PATH = DATA_DIR / "courts.json"
OWNERS_PATH = DATA_DIR / "owners.json"
STATE_PATH = DATA_DIR / "state.json"
POA_DIR = DATA_DIR / "poa"                           # файлы доверенностей организаций (docx)
CLAIMS_PATH = DATA_DIR / "claims.json"               # отметки об отправленных претензиях
TRASH_PATH = DATA_DIR / "trash.json"                 # удалённые карточки собственников (хранятся 30 дней)

# ---------- надёжная запись и версия схемы ----------
# Версия схемы хранится в самом файле («schema_version»). Файлы без версии — прежние (версия 0): они читаются и при
# следующем сохранении записываются в новом формате. Новую версию формата вводят так: увеличить номер здесь и добавить
# функцию в MIGRATIONS — она переводит данные с версии N на N+1.
SCHEMA_VERSION = {"settings": 1, "orgs": 2, "courts": 1, "owners": 1, "trash": 1, "state": 1, "claims": 1}
# Файлы, у которых данные — список или словарь «ключ -> запись»: версия лежит рядом, а данные — под этим ключом.
# У остальных (словарь полей) версия — просто ещё одно поле.
CONTAINER_KEY = {"orgs": "organizations", "owners": "cards", "trash": "items", "claims": "records"}
MIGRATIONS: dict = {}                                 # (вид файла, версия N) -> функция(данные) -> данные версии N+1


def write_atomic(path, text: str, private: bool = False) -> None:
    """Пишет файл целиком или не пишет совсем: данные идут во временный файл рядом, и только после записи на диск он
    переименовывается поверх старого. Сбой или выключение питания посреди записи не оставляют половину файла."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _split(kind: str, raw):
    """(версия, данные) из содержимого файла; файл без версии — версия 0."""
    key = CONTAINER_KEY.get(kind)
    if key:
        if isinstance(raw, dict) and "schema_version" in raw and key in raw:
            return int(raw["schema_version"]), raw[key]
        return 0, raw
    if isinstance(raw, dict):
        raw = dict(raw)
        return int(raw.pop("schema_version", 0) or 0), raw
    return 0, raw


def migrate(kind: str, payload, version: int):
    """Переводит данные с их версии на текущую (версия новее текущей — данные как есть)."""
    while version < SCHEMA_VERSION[kind]:
        payload = MIGRATIONS.get((kind, version), lambda p: p)(payload)
        version += 1
    return payload


def load_json(path, kind: str, default=None):
    """Данные файла (уже без служебной версии и приведённые к текущей схеме); нет файла или он повреждён — default."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default
    version, payload = _split(kind, raw)
    return migrate(kind, payload, version)


def save_json(path, kind: str, payload, private: bool = False) -> None:
    """Сохраняет данные атомарно и с версией схемы. Если на диске файл более новой версии (его записала новая версия
    программы), он сначала копируется рядом под именем «….vN.bak»: старая программа его не затрёт без следа."""
    path = Path(path)
    try:
        old_version, _ = _split(kind, json.loads(path.read_text(encoding="utf-8")))
        if old_version > SCHEMA_VERSION[kind]:
            shutil.copy2(path, path.with_name(f"{path.name}.v{old_version}.bak"))
    except Exception:
        pass
    key = CONTAINER_KEY.get(kind)
    doc = {"schema_version": SCHEMA_VERSION[kind], key: payload} if key else {"schema_version": SCHEMA_VERSION[kind], **payload}
    write_atomic(path, json.dumps(doc, ensure_ascii=False, indent=2), private)


# что переносится при экспорте/импорте (состояние окна state.json не переносим)
TRANSFER_FILES = ("settings.json", "orgs.json", "courts.json", "owners.json", "trash.json", "claims.json")


def export_data(zip_path, directory: Path | None = None) -> list[str]:
    """Упаковывает настройки и данные в один zip-файл (для переноса на другой компьютер). Возвращает имена файлов."""
    d = Path(directory or DATA_DIR)
    names = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in TRANSFER_FILES:
            if (d / name).exists():
                z.write(d / name, name)
                names.append(name)
        for f in sorted((d / "poa").glob("*.doc*")) if (d / "poa").is_dir() else []:
            z.write(f, f"poa/{f.name}")
            names.append(f"poa/{f.name}")
    return names


def import_data(zip_path, directory: Path | None = None) -> list[str]:
    """Загружает данные из zip. Прежние файлы сначала сохраняются в папке backups. Возвращает загруженные имена.
    Принимаются только известные имена файлов с корректным JSON — архив проверяется целиком до замены."""
    d = Path(directory or DATA_DIR)
    with zipfile.ZipFile(zip_path) as z:
        found = {n: z.read(n) for n in z.namelist() if n in TRANSFER_FILES}
        poa = {n[4:]: z.read(n) for n in z.namelist() if re.fullmatch(r"poa/[0-9a-f]{32}-(?:mail|court)\.docx?", n)}
        if not found:
            raise ValueError("В архиве нет данных программы «Должники».")
        for name, raw in found.items():
            try:
                json.loads(raw.decode("utf-8"))
            except Exception:
                raise ValueError(f"Файл {name} в архиве повреждён.")
    backups = d / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_data(backups / f"до-импорта-{stamp}.zip", d)
    if poa:
        (d / "poa").mkdir(parents=True, exist_ok=True)
        for name, raw in poa.items():
            (d / "poa" / name).write_bytes(raw)
    for name, raw in found.items():
        (d / name).write_bytes(raw)
        if name in ("owners.json", "trash.json"):
            try:
                os.chmod(d / name, 0o600)
            except OSError:
                pass
    return sorted(found)
