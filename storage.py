"""Папка с данными программы: все настройки и данные лежат в одном месте — ~/.debtors/.

Раньше файлы лежали в домашней папке россыпью (~/.debtors_*.json); при первом запуске
новой версии они переносятся в папку. Другое место можно задать переменной DEBTORS_HOME."""
import os
import shutil
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
