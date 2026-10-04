"""Снимки окон программы для проверки внешнего вида (запускается в CI на Windows; на своём компьютере: python tests/windows_shots.py).
Результат — PNG-файлы в папке shots/."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DEBTORS_HOME", tempfile.mkdtemp())

from datetime import date, timedelta  # noqa: E402

from PIL import ImageGrab, ImageStat  # noqa: E402

import app  # noqa: E402
import claimlog  # noqa: E402
import core  # noqa: E402
import orgs  # noqa: E402
import owners  # noqa: E402

OUT = Path("shots")
OUT.mkdir(exist_ok=True)
PROBLEMS: list[str] = []                                         # автоматические замечания: проверяются в конце, снимки сохраняются всегда


def check_theme(name: str, win, dark: bool) -> None:
    """Грубая проверка темы: клиентская область окна в тёмной теме должна быть тёмной, в светлой — светлой.
    Ловит «светлое окно в тёмной теме» и обратное; тонкие отличия по-прежнему смотрятся глазами по снимкам."""
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    mean = ImageStat.Stat(ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("L")).mean[0]
    ok = mean < 110 if dark else mean > 150
    print(f"яркость {name}: {mean:.0f} ({'тёмная' if dark else 'светлая'} тема){'' if ok else ' — ОШИБКА'}")
    if not ok:
        PROBLEMS.append(f"{name}: средняя яркость {mean:.0f} не соответствует {'тёмной' if dark else 'светлой'} теме")


def settle(root, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)


def shot(win, name, dark=None):
    win.lift()
    settle(win)
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(max(0, x - 8), max(0, y - 40), x + w + 8, y + h + 8), all_screens=True)
    img.save(OUT / f"{name}.png")
    if dark is not None:
        check_theme(name, win, dark)
    print("снимок", name, (x, y, w, h), "экран", win.winfo_screenwidth(), win.winfo_screenheight(), "scaling", win.tk.call("tk", "scaling"))


def main():
    app.FIRST_RUN = False                                        # без окна приветствия на снимках
    app.save_settings = lambda s: None
    app.App.restore_last_state = lambda self: None
    app.App.save_state = lambda self: None
    mode = sys.argv[1] if len(sys.argv) > 1 else "light"
    dark = {"light": False, "dark": True}.get(mode)
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
    shot(a, f"{mode_tag}-01-main-empty", dark)
    a.open_path(Path(__file__).resolve().parent.parent / "sample.xlsx")
    settle(a)
    shot(a, f"{mode_tag}-02-main-data", dark)
    org = orgs.Organization(name="ООО УО «Тестовая»", match="Тест", houses=[
        {"address": f"Тестовая ул {n}", "since": "01.06.2015", "until": "01.11.2020" if n % 3 == 0 else "", "left": n % 4 == 1, "court": ""}
        for n in range(1, 9)])
    a.orgs = [org] + a.orgs
    sd = app.SettingsDialog(a)
    settle(sd)
    for i, tab in enumerate(sd.tabs.labels):                       # каждая вкладка настроек отдельным снимком
        sd.tabs.select(i)
        settle(sd, 0.3)
        shot(sd, f"{mode_tag}-03-settings-{i + 1}", dark)
    sd.destroy()
    od = app.OrgDialog(a, a.orgs, org.name, on_close=lambda n: None)
    settle(od)
    shot(od, f"{mode_tag}-04-orgs-houses", dark)
    od.destroy()
    ow = app.OwnerDialog(a, {"address": "Тестовая ул 1", "flat": "5", "report_fio": "Иванов Иван Иванович", "debt": 125000.0}, org)
    settle(ow)
    shot(ow, f"{mode_tag}-05-owner", dark)
    ow.destroy()
    app.datepicker.USE_NATIVE = False
    a.settings.addr_col, a.settings.flat_col, a.settings.name_col, a.settings.debt_col = "Адрес", "Кв", "ФИО", "Долг"
    headers, rows = ["ФИО", "Адрес", "Кв", "Долг"], [[f"Иванов {i} Иван", "Тестовая ул 1", str(i), 1000.0 * i] for i in range(1, 14)]
    owners.save_card(owners.Card(address="Тестовая ул 1", flat="1", owners=[owners.Owner(
        birth_date="01.01.1980", birth_place="г. Город", passport="0000 000000", reg_address="ул. Тестовая, 1")]))   # ✓
    owners.save_card(owners.Card(address="Тестовая ул 1", flat="2", owners=[owners.Owner(passport="0000 000000")]))   # ⚠
    claimlog.mark_sent([("Тестовая ул 1", "1")], date.today() - timedelta(days=5))                    # ✉ ждём ответа
    claimlog.mark_sent([("Тестовая ул 1", "2"), ("Тестовая ул 1", "3")], date.today() - timedelta(days=50))   # ⚠ срок истёк
    a.result = core.Result(headers, rows, [r[3] for r in rows], {})
    a.show_rows(headers, rows, numbered=True)
    settle(a)
    shot(a, f"{mode_tag}-06-main-result", dark)
    # открытое меню «Файл»: рисуется самим Tk, поэтому снимок делаем обычным способом
    menu = a.menus["Файл"]
    btn = [b for b in a.menubar_frame.winfo_children()][0]
    menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
    settle(a, 0.5)
    x, y, w = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width()
    ImageGrab.grab(bbox=(max(0, x - 8), max(0, y - 40), x + w + 8, y + 330), all_screens=True).save(OUT / f"{mode_tag}-07-menu-file.png")
    menu.unpost()
    a.destroy()
    if PROBLEMS:
        print("\n".join(PROBLEMS))
        sys.exit(1)


if __name__ == "__main__":
    main()
