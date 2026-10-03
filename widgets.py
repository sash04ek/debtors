"""Элементы оформления: переключатель, выпадающий список, блок-карточка со строками.
На macOS это элементы в стиле системных настроек (переключатель-«таблетка», список со стрелками вверх/вниз,
скруглённая карточка), на Windows и Linux — стандартные: флажок ttk.Checkbutton и ttk.Combobox, карточка с почти
прямыми углами. Цвета берутся от текущей темы (светлой/тёмной) и обновляются через retheme()."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


def is_aqua(root: tk.Misc) -> bool:
    """Работаем на macOS (Aqua)?"""
    return root.tk.call("tk", "windowingsystem") == "aqua"


def mix(root: tk.Misc, a: str, b: str, k: float) -> str:
    """Цвет между a (k=0) и b (k=1). Системные цвета считаются по главному окну: у нового диалога оформление
    (светлое/тёмное) ещё не выставлено и могло бы дать цвет другой темы."""
    main = root.nametowidget(".")
    (r1, g1, b1), (r2, g2, b2) = main.winfo_rgb(a), main.winfo_rgb(b)
    return "#%02x%02x%02x" % tuple(int((x + (y - x) * k) / 257) for x, y in ((r1, r2), (g1, g2), (b1, b2)))


def bold_font(root: tk.Misc) -> tkfont.Font:
    """Системный шрифт того же размера, что и обычный текст, но жирный — как заголовки блоков в настройках macOS."""
    main = root.nametowidget(".")
    f = getattr(main, "_bold_font", None)
    if f is None:
        f = tkfont.nametofont("TkDefaultFont").copy()
        f.configure(weight="bold")
        main._bold_font = f
    return f


def base_colors(root: tk.Misc) -> tuple[str, str, str]:
    """(цвет текста, фон окна, фон полей/таблицы) текущей темы. У темы Sun Valley (Windows) цвета не читаются через ttk.Style,
    поэтому приложение запоминает их при выборе темы (theme_colors у главного окна); иначе берутся из стиля."""
    main = root.nametowidget(".")
    given = getattr(main, "theme_colors", None)
    if given:
        return given
    st = ttk.Style(root)
    fg = st.lookup("TLabel", "foreground") or "black"
    bg = st.lookup("TFrame", "background") or st.lookup("TLabel", "background") or "white"
    field = "systemTextBackgroundColor" if root.tk.call("tk", "windowingsystem") == "aqua" else (
        st.lookup("Treeview", "fieldbackground") or "white")
    return fg, bg, field


def palette(root: tk.Misc) -> dict:
    fg, bg, field = base_colors(root)
    try:
        card = bg                                   # фон карточки как у окна: иначе вокруг ttk-кнопок видны светлые «заплатки»
        pal = {"bg": bg, "fg": fg, "card": card, "line": mix(root, bg, fg, 0.16),
               "muted": mix(root, fg, bg, 0.45), "chip": mix(root, card, fg, 0.12),
               "off": mix(root, card, fg, 0.30)}
    except tk.TclError:
        pal = {"bg": "#ececec", "fg": "#000000", "card": "#f5f5f5", "line": "#d0d0d0", "muted": "#808080",
               "chip": "#e0e0e0", "off": "#b0b0b0"}
    try:
        root.nametowidget(".").winfo_rgb(field)
        pal["field"] = field
    except tk.TclError:
        pal["field"] = pal["bg"]
    try:
        root.winfo_rgb("systemControlAccentColor")
        pal["accent"] = "systemControlAccentColor"
    except tk.TclError:
        pal["accent"] = "#0a84ff"
    return pal


class _AquaSwitch(tk.Canvas):
    """Переключатель вместо флажка (macOS); связан с BooleanVar. Управляется и с клавиатуры: Tab — фокус, пробел — переключить."""
    W, H, M = 28, 16, 2                                    # размер «таблетки» и поле вокруг неё (под кольцо фокуса)

    def __init__(self, parent, variable: tk.BooleanVar, command=None, surface: str = "card"):
        super().__init__(parent, width=self.W + 2 * self.M, height=self.H + 2 * self.M, highlightthickness=0, bd=0)
        self.var, self.command, self.role, self.surface = variable, command, "switch", surface
        self.focused = False
        self.pal = palette(self)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.bind("<FocusOut>", lambda e: self._set_focus(False))
        self.configure(takefocus=1)
        variable.trace_add("write", lambda *a: self.redraw())
        self.redraw()

    def _set_focus(self, value: bool):
        self.focused = value
        self.redraw()

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _pill(self, x0, y0, x1, y1, color):
        """«Таблетка»: два круга и прямоугольник между ними (штатные овалы Tk сглажены, многоугольники и толстые линии — нет)."""
        h = y1 - y0
        self.create_oval(x0, y0, x0 + h, y1, fill=color, outline="")
        self.create_oval(x1 - h, y0, x1, y1, fill=color, outline="")
        self.create_rectangle(x0 + h / 2, y0, x1 - h / 2, y1, fill=color, outline="")

    def redraw(self, pal: dict | None = None):
        self.pal = pal or self.pal
        p, on = self.pal, bool(self.var.get())
        self.configure(bg=p["card"] if self.surface == "card" else p["bg"])
        self.delete("all")
        m, w, h = self.M, self.W, self.H
        color = p["accent"] if on else p["off"]
        if self.focused:                                                       # кольцо фокуса при навигации Tab
            self._pill(0, 0, w + 2 * m, h + 2 * m, p["accent"])
            self._pill(m - 1, m - 1, m + w + 1, m + h + 1, self.cget("bg"))
        self._pill(m, m, m + w, m + h, color)
        d = h - 4                                                              # диаметр кнопки; поля вокруг по 2 пикселя
        x = m + w - 2 - d if on else m + 2
        y = m + 2
        try:
            shadow = mix(self, color, "#000000", 0.35)
        except tk.TclError:
            shadow = "#555555"
        self.create_oval(x - 0.5, y + 0.5, x + d + 0.5, y + d + 1.5, fill=shadow, outline="")      # мягкая тень под кнопкой
        self.create_oval(x, y, x + d, y + d, fill="#ffffff", outline="")


class _AquaPopupSelect(tk.Frame):
    """Выпадающий список как в настройках macOS (значение и кнопка со стрелками вверх/вниз). С клавиатуры: Tab — фокус, пробел/Enter/↓ — открыть."""

    def __init__(self, parent, variable: tk.StringVar | None, values, command=None, width: int = 0):
        super().__init__(parent, bd=0, highlightthickness=2, takefocus=1)
        self.var = variable if variable is not None else tk.StringVar()
        self.values, self.command, self.role = list(values), command, "select"
        self.pal = palette(self)
        # width > 0: подпись фиксированной ширины (в символах) и прижата влево — для панелей инструментов
        self.lbl = tk.Label(self, textvariable=self.var, bd=0, padx=0, **({"width": width, "anchor": "w"} if width else {}))
        self.lbl.pack(side="left", padx=(0, 6))
        self.chip = tk.Canvas(self, width=16, height=16, highlightthickness=0, bd=0)
        self.chip.pack(side="left")
        for w in (self, self.lbl, self.chip):
            w.bind("<Button-1>", self.open)
        for seq in ("<space>", "<Return>", "<Down>"):
            self.bind(seq, self.open)
        self.redraw()

    def redraw(self, pal: dict | None = None):
        self.pal = pal or self.pal
        p = self.pal
        self.configure(bg=p["card"], highlightbackground=p["card"], highlightcolor=p["accent"])
        self.lbl.configure(bg=p["card"], fg=p["fg"])
        c = self.chip
        c.configure(bg=p["card"])
        c.delete("all")
        c.create_rectangle(0, 0, 16, 16, fill=p["chip"], outline=p["chip"])
        c.create_line(5, 6.5, 8, 3.5, 11, 6.5, fill=p["fg"], width=1.6, capstyle="round", joinstyle="round")      # вверх
        c.create_line(5, 9.5, 8, 12.5, 11, 9.5, fill=p["fg"], width=1.6, capstyle="round", joinstyle="round")     # вниз

    # совместимость с ttk.Combobox, чтобы заменять его без переписывания кода вокруг
    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def __setitem__(self, key, value):
        if key == "values":
            self.values = list(value)
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        return self.values if key == "values" else super().__getitem__(key)

    def open(self, _e=None):
        menu = tk.Menu(self, tearoff=0)
        for v in self.values:
            menu.add_radiobutton(label=v, variable=self.var, value=v, command=self._chosen)
        menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _chosen(self):
        if self.command:
            self.command()


def Switch(parent, variable: tk.BooleanVar, command=None, surface: str = "card"):
    """Переключатель: «таблетка» на macOS, стандартный флажок на Windows/Linux (подпись стоит слева, в строке карточки)."""
    if is_aqua(parent):
        return _AquaSwitch(parent, variable, command, surface)
    style = ttk.Style(parent)
    if style.theme_use().startswith("sun-valley"):                # в теме Windows 11 есть настоящий переключатель
        return ttk.Checkbutton(parent, variable=variable, command=command, style="Switch.TCheckbutton")
    return ttk.Checkbutton(parent, variable=variable, command=command)


def PopupSelect(parent, variable: tk.StringVar | None, values, command=None, width: int = 0, chars: int = 0):
    """Выпадающий список: в стиле настроек macOS или стандартный ttk.Combobox (Windows/Linux).
    width — ширина подписи в символах на macOS; chars — ширина поля в символах на Windows/Linux (0 — по самому длинному значению)."""
    if is_aqua(parent):
        return _AquaPopupSelect(parent, variable, values, command, width)
    values = list(values)
    var = variable if variable is not None else tk.StringVar()
    size = chars or min(max([len(v) for v in values] + [8]) + 2, 48)
    cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=size)
    if command:
        cb.bind("<<ComboboxSelected>>", lambda e: command())
    return cb


class Card(tk.Canvas):
    """Блок со строками «название — элемент справа», разделёнными тонкими линиями; рамка со скруглёнными углами."""
    PAD_X, PAD_Y = 2, 5

    def __init__(self, parent):
        super().__init__(parent, bd=0, highlightthickness=0, height=20)
        self.RADIUS = 10 if is_aqua(parent) else 3                        # macOS — крупное скругление, Windows — почти прямые углы
        self.role, self._rows = "card-rounded", 0
        self.pal = palette(self)
        self.body = tk.Frame(self, bd=0)
        self.body.role = "card"
        self._win = self.create_window(self.PAD_X, self.PAD_Y, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.bind("<Configure>", self._on_size)

    def _on_body(self, _e=None):
        self.configure(height=self.body.winfo_reqheight() + 2 * self.PAD_Y)

    def _on_size(self, e):
        self.itemconfigure(self._win, width=max(10, e.width - 2 * self.PAD_X))
        self.redraw()

    def redraw(self, pal: dict | None = None):
        self.pal = pal or self.pal
        p = self.pal
        self.configure(bg=p["bg"])
        self.delete("border")
        w, h, r = self.winfo_width() - 1, self.winfo_height() - 1, self.RADIUS
        if w < 2 * r or h < 2 * r:
            return
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, splinesteps=12, fill=p["card"], outline=p["line"], width=1, tags="border")
        self.tag_lower("border")

    def row(self, label: str = "", muted: bool = False) -> tk.Frame:
        """Добавляет строку; возвращает контейнер справа, куда кладётся элемент управления."""
        if self._rows:
            line = tk.Frame(self.body, height=1, bd=0)
            line.role = "line"
            line.pack(fill="x", padx=12)
        self._rows += 1
        row = tk.Frame(self.body, bd=0)
        row.role = "card"
        row.pack(fill="x", padx=12, pady=7)
        if label:
            lbl = tk.Label(row, text=label, bd=0, anchor="w", justify="left")
            lbl.role = "muted" if muted else "label"
            lbl.pack(side="left")
        right = tk.Frame(row, bd=0)
        right.role = "card"
        right.pack(side="right")
        return right


def section(parent: tk.Misc, title: str, pady: tuple = (14, 0)) -> Card:
    """Заголовок блока (жирным над карточкой) и сама карточка."""
    head = ttk.Label(parent, text=title, font=bold_font(parent))
    head.pack(anchor="w", pady=(pady[0], 5), padx=2)
    card = Card(parent)
    card.pack(fill="x")
    return card


class Badge(tk.Canvas):
    """Круглый значок с номером шага."""

    def __init__(self, parent, number: int, surface: str = "field", size: int = 22):
        super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0)
        self.number, self.size, self.surface, self.role = number, size, surface, "badge"
        self.redraw(palette(self))

    def redraw(self, pal: dict):
        s = self.size
        self.configure(bg=pal["field"] if self.surface == "field" else pal["bg"])
        self.delete("all")
        self.create_oval(1, 1, s - 1, s - 1, fill=pal["accent"], outline=pal["accent"])
        self.create_text(s / 2, s / 2 + 0.5, text=str(self.number), fill="#ffffff", font=bold_font(self))


def steps_list(parent: tk.Misc, steps, surface: str = "field", wrap: int = 470) -> tk.Frame:
    """Нумерованный список шагов: значок с номером, жирное название и пояснение под ним."""
    box = tk.Frame(parent, bd=0)
    box.role = surface
    for i, (title, detail) in enumerate(steps, 1):
        row = tk.Frame(box, bd=0)
        row.role = surface
        row.pack(fill="x", pady=5)
        Badge(row, i, surface).pack(side="left", anchor="n", padx=(0, 12))
        col = tk.Frame(row, bd=0)
        col.role = surface
        col.pack(side="left", fill="x")
        t = tk.Label(col, text=title, bd=0, anchor="w", font=bold_font(parent), justify="left")
        t.role = f"{surface}-label"
        t.pack(anchor="w")
        d = tk.Label(col, text=detail, bd=0, anchor="w", justify="left", wraplength=wrap)
        d.role = f"{surface}-muted"
        d.pack(anchor="w")
    return box


def retheme(widget: tk.Misc) -> None:
    """Перекрашивает все элементы этого модуля внутри widget по текущей теме."""
    pal = palette(widget)

    def walk(w: tk.Misc):
        role = getattr(w, "role", None)
        try:
            if role == "card":
                w.configure(bg=pal["card"])
            elif role == "card-rounded":
                w.redraw(pal)
            elif role == "line":
                w.configure(bg=pal["line"])
            elif role == "label":
                w.configure(bg=pal["card"], fg=pal["fg"])
            elif role == "muted":
                w.configure(bg=pal["card"], fg=pal["muted"])
            elif role in ("field", "window"):
                w.configure(bg=pal["field"] if role == "field" else pal["bg"])
            elif role in ("field-label", "window-label"):
                w.configure(bg=pal["field" if role.startswith("field") else "bg"], fg=pal["fg"])
            elif role in ("field-muted", "window-muted"):
                w.configure(bg=pal["field" if role.startswith("field") else "bg"], fg=pal["muted"])
            elif role in ("switch", "select", "badge"):
                w.redraw(pal)
        except tk.TclError:
            pass
        for c in w.winfo_children():
            walk(c)
    walk(widget)


class PopupMenu:
    """Всплывающее меню, нарисованное самим Tk (Windows/Linux): системное меню Windows не поддаётся тёмной теме — светлые
    рамка, разделители и фон. Набор методов — как у tk.Menu (add_command, add_checkbutton, add_separator, add_cascade, delete,
    entryconfig, tk_popup, unpost), поэтому остальной код не отличает одно от другого. Цвета берутся у темы в момент показа."""

    def __init__(self, parent: tk.Misc, postcommand=None):
        self.parent, self.postcommand = parent, postcommand
        self.entries: list[dict] = []
        self._win: tk.Toplevel | None = None
        self._child: "PopupMenu | None" = None
        self._owner: "PopupMenu | None" = None
        self._prev_grab = None

    # --- описание пунктов ---
    def add_command(self, label: str = "", command=None, accelerator: str = "", state: str = "normal", **_ignored) -> None:
        self.entries.append({"type": "command", "label": label, "command": command, "accelerator": accelerator, "state": state})

    def add_checkbutton(self, label: str = "", variable: tk.Variable | None = None, command=None, accelerator: str = "",
                        state: str = "normal", **_ignored) -> None:
        self.entries.append({"type": "checkbutton", "label": label, "variable": variable, "command": command,
                             "accelerator": accelerator, "state": state})

    def add_separator(self) -> None:
        self.entries.append({"type": "separator"})

    def add_cascade(self, label: str = "", menu: "PopupMenu | None" = None, state: str = "normal", **_ignored) -> None:
        self.entries.append({"type": "cascade", "label": label, "menu": menu, "state": state})

    def delete(self, first, last=None) -> None:
        if first == 0 and last in (None, "end"):
            self.entries.clear()
        else:
            end = len(self.entries) if last in (None, "end") else int(last) + 1
            del self.entries[int(first):end]

    def index(self, what):
        return len(self.entries) - 1 if what == "end" and self.entries else None

    def type(self, i: int) -> str:
        return self.entries[i]["type"]

    def entryconfig(self, i: int, **kw) -> None:
        self.entries[i].update(kw)

    entryconfigure = entryconfig

    def entrycget(self, i: int, key: str):
        return self.entries[i].get(key)

    # --- показ ---
    def is_open(self) -> bool:
        return self._win is not None and self._win.winfo_exists()

    def _root(self) -> "PopupMenu":
        return self._owner._root() if self._owner else self

    def tk_popup(self, x: int, y: int) -> None:
        self.unpost()
        if self.postcommand:
            self.postcommand()
        if not self.entries:
            return
        top = self._owner is None
        pal = palette(self.parent)
        bg, fg, line = pal["bg"], pal["fg"], pal["line"]
        hover, muted = mix(self.parent, bg, fg, 0.14), pal["muted"]
        win = self._win = tk.Toplevel(self.parent)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        outer = tk.Frame(win, bg=line, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=bg, pady=4)
        inner.pack()
        widgets_by_row: list[tuple[tk.Frame, list[tk.Label]]] = []
        for i, e in enumerate(self.entries):
            if e["type"] == "separator":
                tk.Frame(inner, height=1, bg=line).pack(fill="x", padx=8, pady=4)
                continue
            enabled = e.get("state", "normal") != "disabled"
            color = fg if enabled else muted
            row = tk.Frame(inner, bg=bg, padx=6)
            row.pack(fill="x", padx=4)
            mark = "✓" if e["type"] == "checkbutton" and e["variable"] is not None and e["variable"].get() else ""
            labels = [tk.Label(row, text=mark, bg=bg, fg=color, width=2, anchor="w")]
            labels.append(tk.Label(row, text=e["label"], bg=bg, fg=color, anchor="w"))
            labels[0].pack(side="left")
            labels[1].pack(side="left", fill="x", expand=True, padx=(0, 28))
            tail = "›" if e["type"] == "cascade" else e.get("accelerator", "")
            if tail:
                labels.append(tk.Label(row, text=tail, bg=bg, fg=muted if e["type"] != "cascade" else color, anchor="e"))
                labels[-1].pack(side="right")
            widgets_by_row.append((row, labels))
            if not enabled:
                continue
            for w in [row] + labels:
                w.bind("<Enter>", lambda ev, r=row, ls=labels, e=e: self._hover(r, ls, hover, e), add="+")
                w.bind("<Leave>", lambda ev, r=row, ls=labels: self._unhover(r, ls, bg), add="+")
                w.bind("<ButtonRelease-1>", lambda ev, e=e, r=row: self._invoke(e, r), add="+")
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h - 40)) if y + h > sh - 40 else y
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.lift()
        if top:
            self._prev_grab = self.parent.grab_current()
            try:
                win.grab_set()                                  # клик вне меню приходит сюда и закрывает его
            except tk.TclError:
                pass
            win.bind("<Button-1>", self._click_outside, add="+")
            win.bind("<Escape>", lambda e: self.unpost())
            try:
                win.focus_force()
            except tk.TclError:
                pass

    @staticmethod
    def _hover(row, labels, color, entry=None) -> None:
        row.configure(bg=color)
        for lbl in labels:
            lbl.configure(bg=color)

    @staticmethod
    def _unhover(row, labels, color) -> None:
        row.configure(bg=color)
        for lbl in labels:
            lbl.configure(bg=color)

    def _click_outside(self, event) -> None:
        for m in (self, self._child):
            if m is not None and m.is_open():
                x, y = m._win.winfo_rootx(), m._win.winfo_rooty()
                if x <= event.x_root <= x + m._win.winfo_width() and y <= event.y_root <= y + m._win.winfo_height():
                    return
        self.unpost()

    def _invoke(self, entry: dict, row: tk.Frame) -> None:
        if entry["type"] == "cascade":
            sub = entry["menu"]
            if sub is not None:
                if self._child is not None and self._child is not sub:
                    self._child.unpost()
                self._child = sub
                sub._owner = self
                sub.tk_popup(row.winfo_rootx() + row.winfo_width() - 4, row.winfo_rooty() - 4)
            return
        if entry["type"] == "checkbutton" and entry.get("variable") is not None:
            entry["variable"].set(not entry["variable"].get())
        command = entry.get("command")
        self._root().unpost()
        if command:
            self.parent.after_idle(command)                     # команда выполняется уже после закрытия меню

    def unpost(self) -> None:
        if self._child is not None:
            self._child.unpost()
            self._child = None
        if self._win is not None:
            try:
                if self._owner is None:
                    self._win.grab_release()
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None
            if self._owner is None and self._prev_grab is not None:
                try:
                    self._prev_grab.grab_set()                  # диалогу возвращается его модальность
                except tk.TclError:
                    pass
                self._prev_grab = None
