"""Проверка запуска: главное окно и основные диалоги строятся без ошибок. Запускается и в CI на Windows и macOS (Tk 8.6),
где поведение Tk отличается от Tk 9 на разработческом компьютере: python tests/smoke.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os

os.environ.setdefault("DEBTORS_HOME", tempfile.mkdtemp())          # не трогаем настоящие данные программы

import app  # noqa: E402
import core  # noqa: E402
import orgs  # noqa: E402


def main() -> None:
    import tkinter as tk
    app.save_settings = lambda s: None
    app.App.restore_last_state = lambda self: None
    a = app.App()
    a.update()
    print("Tk", a.tk.call("info", "patchlevel"), a.tk.call("tk", "windowingsystem"))
    org = a.current_org()
    sd = app.SettingsDialog(a)
    sd.update()
    for dlg in (app.RegionsDialog(sd), app.DutyScaleDialog(sd)):
        dlg.update()
        dlg.destroy()
    sd.destroy()
    od = app.OrgDialog(a, a.orgs, org.name, on_close=lambda n: None)
    od.update()
    od.destroy()
    ow = app.OwnerDialog(a, {"address": "ул. Тестовая, д. 1", "flat": "5", "report_fio": "Иванов Иван", "debt": 1000.0}, org)
    ow.update()
    ow.destroy()
    # таблица, поиск, сортировка, меню
    headers, rows = ["ФИО", "Адрес", "Кв", "Долг"], [[f"Иванов {i}", "ул. Тестовая, д. 1", str(i), 1000.0 + i] for i in range(30)]
    a.settings.addr_col, a.settings.flat_col, a.settings.name_col, a.settings.debt_col = "Адрес", "Кв", "ФИО", "Долг"
    a.result = core.Result(headers, rows, [r[3] for r in rows], {})
    a.show_rows(headers, rows, numbered=True)
    a.update()
    a.sort_view("c5")
    a.search_var.set("Иванов 1")
    a.apply_search()
    a.update()
    for mode in ("dark", "light", "system"):
        a.settings.theme = mode
        app.apply_theme(a, mode)
        a.update()
    de = app.datepicker.DateEntry(a, tk.StringVar(value="01.06.2015"))
    de.pack()
    app.datepicker.USE_NATIVE = False
    de.open_calendar()
    a.update()
    de.close_calendar()
    a.destroy()
    print("OK")


if __name__ == "__main__":
    main()
