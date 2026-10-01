"""Элементы оформления в стиле системных настроек macOS: переключатель, выпадающий список со стрелками,
блок-карточка со строками. Цвета берутся от текущей темы (светлой/тёмной) и обновляются через retheme()."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


def _mix(root: tk.Misc, a: str, b: str, k: float) -> str:
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


def palette(root: tk.Misc) -> dict:
    st = ttk.Style(root)
    fg = st.lookup("TLabel", "foreground") or "black"
    bg = st.lookup("TFrame", "background") or st.lookup("TLabel", "background") or "white"
    try:
        card = bg                                   # фон карточки как у окна: иначе вокруг ttk-кнопок видны светлые «заплатки»
        pal = {"bg": bg, "fg": fg, "card": card, "line": _mix(root, bg, fg, 0.16),
               "muted": _mix(root, fg, bg, 0.45), "chip": _mix(root, card, fg, 0.12),
               "off": _mix(root, card, fg, 0.30)}
    except tk.TclError:
        pal = {"bg": "#ececec", "fg": "#000000", "card": "#f5f5f5", "line": "#d0d0d0", "muted": "#808080",
               "chip": "#e0e0e0", "off": "#b0b0b0"}
    field = "systemTextBackgroundColor" if root.tk.call("tk", "windowingsystem") == "aqua" else (
        st.lookup("Treeview", "fieldbackground") or "white")
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


class Switch(tk.Canvas):
    """Переключатель вместо флажка; связан с BooleanVar."""
    W, H = 28, 16

    def __init__(self, parent, variable: tk.BooleanVar, command=None, surface: str = "card"):
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0, bd=0)
        self.var, self.command, self.role, self.surface = variable, command, "switch", surface
        self.pal = palette(self)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.configure(takefocus=1)
        self._trace = variable.trace_add("write", lambda *a: self.redraw())
        self.redraw()

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def redraw(self, pal: dict | None = None):
        self.pal = pal or self.pal
        p, on = self.pal, bool(self.var.get())
        self.configure(bg=p["card"] if self.surface == "card" else p["bg"])
        self.delete("all")
        h = self.H
        color = p["accent"] if on else p["off"]
        self.create_oval(1, 1, h - 1, h - 1, fill=color, outline=color)
        self.create_oval(self.W - h + 1, 1, self.W - 1, h - 1, fill=color, outline=color)
        self.create_rectangle(h // 2, 1, self.W - h // 2, h - 1, fill=color, outline=color)
        x = self.W - h + 2 if on else 2
        self.create_oval(x, 2, x + h - 4, h - 2, fill="#ffffff", outline="#ffffff")


class PopupSelect(tk.Frame):
    """Выпадающий список как в настройках macOS: значение справа и кнопка со стрелками вверх/вниз."""

    def __init__(self, parent, variable: tk.StringVar, values, command=None):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.var, self.values, self.command, self.role = variable, list(values), command, "select"
        self.pal = palette(self)
        self.lbl = tk.Label(self, textvariable=variable, bd=0, padx=0)
        self.lbl.pack(side="left", padx=(0, 6))
        self.chip = tk.Canvas(self, width=16, height=16, highlightthickness=0, bd=0)
        self.chip.pack(side="left")
        for w in (self, self.lbl, self.chip):
            w.bind("<Button-1>", self.open)
        self.redraw()

    def redraw(self, pal: dict | None = None):
        self.pal = pal or self.pal
        p = self.pal
        self.configure(bg=p["card"])
        self.lbl.configure(bg=p["card"], fg=p["fg"])
        c = self.chip
        c.configure(bg=p["card"])
        c.delete("all")
        c.create_rectangle(0, 0, 16, 16, fill=p["chip"], outline=p["chip"])
        c.create_line(5, 6.5, 8, 3.5, 11, 6.5, fill=p["fg"], width=1.6, capstyle="round", joinstyle="round")      # вверх
        c.create_line(5, 9.5, 8, 12.5, 11, 9.5, fill=p["fg"], width=1.6, capstyle="round", joinstyle="round")     # вниз

    def open(self, _e=None):
        menu = tk.Menu(self, tearoff=0)
        for v in self.values:
            menu.add_radiobutton(label=v, variable=self.var, value=v, command=self._chosen)
        menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _chosen(self):
        if self.command:
            self.command()


class Card(tk.Canvas):
    """Блок со строками «название — элемент справа», разделёнными тонкими линиями; рамка со скруглёнными углами."""
    RADIUS, PAD_X, PAD_Y = 10, 2, 5

    def __init__(self, parent):
        super().__init__(parent, bd=0, highlightthickness=0, height=20)
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
