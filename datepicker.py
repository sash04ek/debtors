"""Выбор даты: поле ввода с кнопкой, открывающей календарь (DateEntry), и разбор/форматирование дат.
Дату можно и набрать руками: «01.06.2015», «1.6.15», «2015-06-01»; произвольный текст остаётся как есть."""
from __future__ import annotations

import calendar
import re
import tkinter as tk
from datetime import date
from tkinter import ttk

import widgets

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_DMY = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)")
_YMD = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
# вся строка — одна дата с необязательным «г.» (так записаны даты в карточках: «23.08.2022г.»)
_WHOLE = re.compile(r"^\s*(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})\s*(?:г\.?|гг\.?)?\s*$", re.IGNORECASE)


def parse_date(text: str) -> date | None:
    """Первая дата в тексте («01.06.2015г», «с 1.6.15») или None."""
    text = text or ""
    m = _YMD.search(text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _DMY.search(text)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def format_date(d: date, suffix: str = "") -> str:
    return f"{d:%d.%m.%Y}{suffix}"


def normalize(text: str, suffix: str = "") -> str:
    """Если вся строка — дата, приводит её к виду «дд.мм.гггг» (+ суффикс); иной текст возвращает без изменений."""
    if text and _WHOLE.match(text):
        d = parse_date(text)
        if d:
            return format_date(d, suffix)
    return text


def month_grid(year: int, month: int) -> list[list[date]]:
    """Недели (с понедельника) для календаря: 6 строк по 7 дней, с днями соседних месяцев."""
    first = date(year, month, 1)
    start = first.toordinal() - first.weekday()
    return [[date.fromordinal(start + w * 7 + i) for i in range(7)] for w in range(6)]


class CalendarPopup(tk.Toplevel):
    """Календарь под полем ввода. Выбор дня закрывает его; клик вне календаря тоже."""

    def __init__(self, anchor: tk.Misc, current: date | None, on_pick, on_clear=None):
        super().__init__(anchor)
        self.withdraw()
        self.on_pick, self.on_clear = on_pick, on_clear
        self.selected = current
        base = current or date.today()
        self.year, self.month = base.year, base.month
        main = anchor.nametowidget(".")

        def hexcolor(c: str) -> str:                           # системные цвета («systemWindowBackgroundColor») -> #rrggbb по главному окну
            r, g, b = main.winfo_rgb(c)
            return "#%02x%02x%02x" % (r // 257, g // 257, b // 257)
        self.pal = {k: hexcolor(v) for k, v in widgets.palette(self).items()}
        p = self.pal
        dark = sum(main.winfo_rgb(p["bg"])) < 3 * 32768
        try:
            if self.tk.call("tk", "windowingsystem") == "aqua":
                self.tk.call("::tk::unsupported::MacWindowStyle", "style", self._w, "help", "noActivates")
            else:
                self.wm_overrideredirect(True)
            self.wm_attributes("-topmost", True)
        except tk.TclError:
            self.wm_overrideredirect(True)
        if self.tk.call("tk", "windowingsystem") == "aqua":    # кнопки календаря — в той же теме, что и главное окно
            try:
                self.update_idletasks()
                self.tk.call("::tk::unsupported::MacWindowStyle", "appearance", self, "darkaqua" if dark else "aqua")
            except tk.TclError:
                pass
        body = tk.Frame(self, bg=p["bg"], highlightthickness=1, highlightbackground=p["line"], padx=8, pady=8)
        body.pack()
        head = tk.Frame(body, bg=p["bg"])
        head.pack(fill="x")
        for text, cmd in (("«", lambda: self.shift(-12)), ("‹", lambda: self.shift(-1))):
            self._nav(head, text, cmd).pack(side="left")
        for text, cmd in (("»", lambda: self.shift(12)), ("›", lambda: self.shift(1))):
            self._nav(head, text, cmd).pack(side="right")
        self.title_lbl = tk.Label(head, bg=p["bg"], fg=p["fg"], font=widgets.bold_font(self))
        self.title_lbl.pack(expand=True)
        grid = tk.Frame(body, bg=p["bg"])
        grid.pack(pady=(6, 4))
        for i, name in enumerate(WEEKDAYS):
            tk.Label(grid, text=name, bg=p["bg"], fg=p["muted"], width=3).grid(row=0, column=i)
        self.cells: list[list[tk.Label]] = []
        for r in range(6):
            row = []
            for c in range(7):
                lbl = tk.Label(grid, width=3, bg=p["bg"], fg=p["fg"], cursor="arrow", highlightthickness=1,
                               highlightbackground=p["bg"])
                lbl.grid(row=r + 1, column=c, padx=1, pady=1)
                row.append(lbl)
            self.cells.append(row)
        foot = tk.Frame(body, bg=p["bg"])
        foot.pack(fill="x", pady=(4, 0))
        ttk.Button(foot, text="Сегодня", command=lambda: self.pick(date.today())).pack(side="left")
        if on_clear:
            ttk.Button(foot, text="Очистить", command=self.clear).pack(side="right")
        self.render()
        self.bind("<Button-1>", self._maybe_close, add="+")
        self.bind("<Escape>", lambda e: self.destroy())

    def _nav(self, parent, text, cmd):
        p = self.pal
        lbl = tk.Label(parent, text=text, bg=p["bg"], fg=p["fg"], width=2, cursor="arrow")
        lbl.bind("<Button-1>", lambda e: (cmd(), "break")[1])
        return lbl

    def shift(self, months: int):
        total = self.year * 12 + (self.month - 1) + months
        self.year, self.month = total // 12, total % 12 + 1
        self.render()

    def render(self):
        p, today = self.pal, date.today()
        self.title_lbl.config(text=f"{MONTHS[self.month - 1]} {self.year}")
        for r, week in enumerate(month_grid(self.year, self.month)):
            for c, d in enumerate(week):
                lbl = self.cells[r][c]
                inside = d.month == self.month
                chosen = self.selected == d
                lbl.config(text=str(d.day), bg=p["accent"] if chosen else p["bg"],
                           fg="#ffffff" if chosen else (p["fg"] if inside else p["muted"]),
                           highlightbackground=p["accent"] if d == today and not chosen else (p["accent"] if chosen else p["bg"]))
                lbl.bind("<Button-1>", lambda e, d=d: (self.pick(d), "break")[1])
                lbl.bind("<Enter>", lambda e, l=lbl, d=d: None if self.selected == d else l.config(bg=p["line"]))
                lbl.bind("<Leave>", lambda e, l=lbl, d=d: None if self.selected == d else l.config(bg=p["bg"]))

    def pick(self, d: date):
        self.on_pick(d)
        self.destroy()

    def clear(self):
        if self.on_clear:
            self.on_clear()
        self.destroy()

    def _maybe_close(self, event):
        x, y = self.winfo_rootx(), self.winfo_rooty()
        if not (x <= event.x_root <= x + self.winfo_width() and y <= event.y_root <= y + self.winfo_height()):
            self.destroy()

    def show_below(self, widget: tk.Misc):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 2
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if y + h > sh - 40:                                    # не помещается снизу — открываем над полем
            y = max(0, widget.winfo_rooty() - h - 2)
        x = max(0, min(x, sw - w))
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        try:
            self.grab_set()                                    # клик вне календаря приходит сюда и закрывает его
        except tk.TclError:
            pass
        try:
            self.focus_force()
        except tk.TclError:
            pass


class DateEntry(ttk.Frame):
    """Поле даты с кнопкой «▾» (календарь). suffix — что дописывать к выбранной дате (например «г.»)."""

    def __init__(self, parent, textvariable: tk.StringVar | None = None, suffix: str = "", width: int = 12, command=None):
        super().__init__(parent)
        self.var = textvariable if textvariable is not None else tk.StringVar()
        self.suffix, self.command = suffix, command
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left")
        self.button = ttk.Button(self, text="▾", width=2, style="Toolbutton", takefocus=False, command=self.open_calendar)
        self.button.pack(side="left", padx=(3, 0))
        self.entry.bind("<FocusOut>", lambda e: self.tidy(), add="+")
        self.entry.bind("<Return>", lambda e: self.tidy(), add="+")
        self._popup: CalendarPopup | None = None

    def get(self) -> str:
        return self.var.get()

    def set(self, text: str) -> None:
        self.var.set(text)

    def date(self) -> date | None:
        return parse_date(self.var.get())

    def tidy(self) -> None:
        """Набранную дату приводит к единому виду; обычный текст не трогает."""
        text = self.var.get()
        fixed = normalize(text, self.suffix)
        if fixed != text:
            self.var.set(fixed)

    def set_enabled(self, enabled: bool) -> None:
        for w in (self.entry, self.button):
            w.state(["!disabled"] if enabled else ["disabled"])

    def open_calendar(self) -> None:
        if str(self.button.cget("state")) == "disabled":
            return
        self.tidy()
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.destroy()
            return
        self._popup = CalendarPopup(self, self.date(), self._picked, on_clear=self._cleared)
        self._popup.show_below(self.entry)

    def _picked(self, d: date) -> None:
        self.var.set(format_date(d, self.suffix))
        if self.command:
            self.command()

    def _cleared(self) -> None:
        self.var.set("")
        if self.command:
            self.command()
