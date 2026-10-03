"""Снимки окон программы для проверки внешнего вида (запускается в CI на Windows; на своём компьютере: python tests/windows_shots.py).
Результат — PNG-файлы в папке shots/."""
import os
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DEBTORS_HOME", tempfile.mkdtemp())

from PIL import ImageGrab  # noqa: E402

import app  # noqa: E402
import core  # noqa: E402
import orgs  # noqa: E402

OUT = Path("shots")
OUT.mkdir(exist_ok=True)


def settle(root, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)


def shot(win, name):
    win.lift()
    settle(win)
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(max(0, x - 8), max(0, y - 40), x + w + 8, y + h + 8), all_screens=True)
    img.save(OUT / f"{name}.png")
    print("снимок", name, (x, y, w, h), "экран", win.winfo_screenwidth(), win.winfo_screenheight(), "scaling", win.tk.call("tk", "scaling"))


def main():
    app.save_settings = lambda s: None
    app.App.restore_last_state = lambda self: None
    app.App.save_state = lambda self: None
    mode = sys.argv[1] if len(sys.argv) > 1 else "light"
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0       # 2.0 ~ экран Windows с масштабом 150 % (шрифты крупнее, пиксели те же)
    a = app.App()
    if scale:
        a.tk.call("tk", "scaling", scale)
        mode_tag = f"{mode}-x{scale:g}"
    else:
        mode_tag = mode
    a.settings.theme = mode
    a.theme_var.set({"light": "Светлая", "dark": "Тёмная"}.get(mode, "Как в системе"))
    app.apply_theme(a, mode)
    a.geometry("1100x700+10+10")
    settle(a)
    print("Tk", a.tk.call("info", "patchlevel"), a.tk.call("tk", "windowingsystem"), "тема", mode)
    shot(a, f"{mode_tag}-01-main-empty")
    a.open_path(Path(__file__).resolve().parent.parent / "sample.xlsx")
    settle(a)
    shot(a, f"{mode_tag}-02-main-data")
    org = orgs.Organization(name="ООО УО «Тестовая»", match="Тест", houses=[
        {"address": f"Тестовая ул {n}", "since": "01.06.2015", "until": "01.11.2020" if n % 3 == 0 else "", "left": n % 4 == 1, "court": ""}
        for n in range(1, 9)])
    a.orgs = [org] + a.orgs
    sd = app.SettingsDialog(a)
    settle(sd)
    shot(sd, f"{mode_tag}-03-settings")
    sd.destroy()
    od = app.OrgDialog(a, a.orgs, org.name, on_close=lambda n: None)
    settle(od)
    shot(od, f"{mode_tag}-04-orgs-houses")
    od.destroy()
    ow = app.OwnerDialog(a, {"address": "Тестовая ул 1", "flat": "5", "report_fio": "Иванов Иван Иванович", "debt": 125000.0}, org)
    settle(ow)
    shot(ow, f"{mode_tag}-05-owner")
    ow.destroy()
    app.datepicker.USE_NATIVE = False
    a.settings.addr_col, a.settings.flat_col, a.settings.name_col, a.settings.debt_col = "Адрес", "Кв", "ФИО", "Долг"
    headers, rows = ["ФИО", "Адрес", "Кв", "Долг"], [[f"Иванов {i} Иван", "Тестовая ул 1", str(i), 1000.0 * i] for i in range(1, 14)]
    a.result = core.Result(headers, rows, [r[3] for r in rows], {})
    a.show_rows(headers, rows, numbered=True)
    settle(a)
    shot(a, f"{mode_tag}-06-main-result")
    a.destroy()


if __name__ == "__main__":
    main()
