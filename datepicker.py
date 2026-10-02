"""Выбор даты: поле ввода с кнопкой, открывающей календарь (DateEntry), и разбор/форматирование дат.
Дату можно и набрать руками: «01.06.2015», «1.6.15», «2015-06-01»; произвольный текст остаётся как есть."""
from __future__ import annotations

import calendar
import re
import time
import tkinter as tk
from datetime import date
from tkinter import ttk

import native_date
import widgets

USE_NATIVE = True          # показывать системный календарь ОС (если он есть); приложение переключает из настроек
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

    def select(self, d: date) -> None:
        """Перейти на дату d (например, набранную в поле)."""
        self.selected = d
        self.year, self.month = d.year, d.month
        self.render()

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


class DateEntry(ttk.Frame):
    """Поле даты: клик по полю (или ↓ / F4) показывает календарь, если он ещё не показан; фокус остаётся в поле, поэтому дату
    можно набирать с клавиатуры, а календарь следует за введённым значением. Календарь закрывается выбором дня, кликом вне поля,
    Esc, Enter или уходом фокуса. suffix — что дописывать к выбранной дате (например «г.»)."""

    def __init__(self, parent, textvariable: tk.StringVar | None = None, suffix: str = "", width: int = 12, command=None):
        super().__init__(parent)
        self.var = textvariable if textvariable is not None else tk.StringVar()
        self.suffix, self.command = suffix, command
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left")
        self._popup: CalendarPopup | None = None
        self._native: native_date.Pending | None = None
        self._away_bind: tuple | None = None                  # (окно, id привязки) клика вне поля, пока календарь открыт
        self._opened_at = 0.0
        self.entry.bind("<Button-1>", self._clicked, add="+")
        self.entry.bind("<Down>", lambda e: (self.open_calendar(), "break")[1])
        self.entry.bind("<F4>", lambda e: (self.open_calendar(), "break")[1])
        self.entry.bind("<KeyRelease>", lambda e: self._sync_typed(), add="+")
        self.entry.bind("<Escape>", self._escape)
        self.entry.bind("<Return>", self._return)
        self.entry.bind("<FocusOut>", self._focus_out, add="+")
        self.bind("<Destroy>", lambda e: self.close_calendar() if e.widget is self else None, add="+")

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
        self.entry.state(["!disabled"] if enabled else ["disabled"])
        if not enabled:
            self.close_calendar()

    # --- показ и закрытие календаря ---
    def is_open(self) -> bool:
        return self._native is not None or (self._popup is not None and self._popup.winfo_exists())

    def _clicked(self, _event=None) -> None:
        """Клик по полю: сначала поле получает фокус и курсор, потом (если календарь не показан) он открывается."""
        self.after_idle(self.open_calendar)

    def open_calendar(self) -> None:
        if self.entry.instate(["disabled"]) or self.is_open():
            return
        self.tidy()
        self._opened_at = time.monotonic()
        self._arm_away()
        if USE_NATIVE and native_date.available():
            self._native = native_date.ask(self, self.date(), True, self._native_result,
                                           x=self.entry.winfo_rootx(), y=self.entry.winfo_rooty() + self.entry.winfo_height() + 4,
                                           y_above=self.entry.winfo_rooty(), look=self._look())
        else:
            self.open_builtin()

    def open_builtin(self) -> None:
        """Календарь самой программы (если системного нет или он не открылся)."""
        if self._popup is not None and self._popup.winfo_exists():
            return
        self._arm_away()
        self._popup = CalendarPopup(self, self.date(), self._picked, on_clear=self._cleared)
        self._popup.show_below(self.entry)
        self.entry.focus_force()                               # новое окно не должно уносить фокус из поля

    def close_calendar(self) -> None:
        if self._native is not None:
            self._native.cancel()
            self._native = None
        if self._popup is not None:
            if self._popup.winfo_exists():
                self._popup.destroy()
            self._popup = None
        self._disarm_away()

    def _arm_away(self) -> None:
        """Пока календарь открыт, клик в любом другом месте окна закрывает его."""
        if self._away_bind is not None:
            return
        top = self.winfo_toplevel()
        self._away_bind = (top, top.bind("<Button-1>", self._away_click, add="+"))

    def _disarm_away(self) -> None:
        if self._away_bind is not None:
            top, funcid = self._away_bind
            self._away_bind = None
            try:
                top.unbind("<Button-1>", funcid)
            except tk.TclError:
                pass

    def _away_click(self, event) -> None:
        if event.widget is self.entry or self._popup is not None and str(event.widget).startswith(str(self._popup)):
            return
        self.close_calendar()

    def _focus_out(self, _event=None) -> None:
        self.tidy()
        if time.monotonic() - self._opened_at > 0.4:           # сразу после показа окно календаря может на миг отнять фокус
            self.close_calendar()

    def _escape(self, _event=None):
        if self.is_open():
            self.close_calendar()
            return "break"                                    # Esc закрывает только календарь, а не диалог

    def _return(self, _event=None):
        self.tidy()
        if self.is_open():
            self.close_calendar()
            return "break"

    def _look(self) -> str:
        """Тема программы для системного календаря: «dark» или «light» (по яркости фона окна)."""
        try:
            main = self.nametowidget(".")
            bg = main.winfo_rgb(widgets.palette(self)["bg"])
            return "dark" if sum(bg) < 3 * 32768 else "light"
        except tk.TclError:
            return ""

    # --- следование за набранной датой ---
    def _sync_typed(self) -> None:
        """Пока календарь открыт, он переходит на дату, набранную в поле (когда набрана полностью: дд.мм.гггг)."""
        if not self.is_open():
            return
        text = self.var.get()
        m = _DMY.fullmatch(text.strip().rstrip("гГ.").strip())
        d = parse_date(text) if (m and len(m.group(3)) == 4) or _YMD.fullmatch(text.strip()) else None
        if d is None:
            return
        if self._native is not None:
            self._native.sync(d)
        elif self._popup is not None and self._popup.winfo_exists():
            self._popup.select(d)

    # --- результат ---
    def _native_result(self, kind: str, d: date | None) -> None:
        self._native = None
        self._disarm_away()
        if not self.winfo_exists():
            return
        if kind == "pick" and d:
            self._picked(d)
        elif kind == "clear":
            self._cleared()
        elif kind == "error":
            self.open_builtin()                                  # системный календарь не открылся — свой

    def _picked(self, d: date) -> None:
        self.var.set(format_date(d, self.suffix))
        self.close_calendar()
        self.entry.focus_set()
        self.entry.icursor("end")
        if self.command:
            self.command()

    def _cleared(self) -> None:
        self.var.set("")
        self.close_calendar()
        self.entry.focus_set()
        if self.command:
            self.command()
