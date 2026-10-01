"""Папка с данными программы: все настройки и данные лежат в одном месте — ~/.debtors/.

Раньше файлы лежали в домашней папке россыпью (~/.debtors_*.json); при первом запуске
новой версии они переносятся в папку. Другое место можно задать переменной DEBTORS_HOME."""
import json
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
TRASH_PATH = DATA_DIR / "trash.json"                 # удалённые карточки собственников (хранятся 30 дней)

# что переносится при экспорте/импорте (состояние окна state.json не переносим)
TRANSFER_FILES = ("settings.json", "orgs.json", "courts.json", "owners.json", "trash.json")


def export_data(zip_path, directory: Path | None = None) -> list[str]:
    """Упаковывает настройки и данные в один zip-файл (для переноса на другой компьютер). Возвращает имена файлов."""
    d = Path(directory or DATA_DIR)
    names = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in TRANSFER_FILES:
            if (d / name).exists():
                z.write(d / name, name)
                names.append(name)
    return names


def import_data(zip_path, directory: Path | None = None) -> list[str]:
    """Загружает данные из zip. Прежние файлы сначала сохраняются в папке backups. Возвращает загруженные имена.
    Принимаются только известные имена файлов с корректным JSON — архив проверяется целиком до замены."""
    d = Path(directory or DATA_DIR)
    with zipfile.ZipFile(zip_path) as z:
        found = {n: z.read(n) for n in z.namelist() if n in TRANSFER_FILES}
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
    for name, raw in found.items():
        (d / name).write_bytes(raw)
        if name in ("owners.json", "trash.json"):
            try:
                os.chmod(d / name, 0o600)
            except OSError:
                pass
    return sorted(found)
