"""Окно приложения «Должники» (Tkinter — работает на Windows и macOS)."""

from __future__ import annotations

import json
import sys
import tkinter as tk
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import claim
import core
import court
import courts as courtsmod
import orgs as orgmod
import owners
from datetime import date

CONFIG_PATH = Path.home() / ".debtors_finder.json"
STATE_PATH = Path.home() / ".debtors_state.json"     # состояние приложения между запусками
NONE = "— нет —"
SORT_DEBT_LABEL = "Сумма долга"
DESC_LABEL = "по убыванию (от большего к меньшему)"
ASC_LABEL = "по возрастанию (от меньшего к большему)"


def load_settings() -> core.Settings:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        s = core.Settings(**{k: v for k, v in data.items() if k in core.Settings.__dataclass_fields__})
        if data.get("markers_version", 1) < core.MARKERS_VERSION:
            have = {m.lower() for m in s.org_markers}
            s.org_markers += [m for m in core.DEFAULT_ORG_MARKERS if m.lower() not in have]
            s.markers_version = core.MARKERS_VERSION
        return s
    except Exception:
        return core.Settings()


def save_settings(s: core.Settings) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class Tooltip:
    """Всплывающая подсказка при наведении на виджет."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 450):
        self.widget, self.text, self.delay = widget, text, delay
        self._job, self._tip = None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self._job = self.widget.after(self.delay, self._show)

    def _show(self):
        self._job = None
        tip = self._tip = tk.Toplevel(self.widget)
        try:
            if tip.tk.call("tk", "windowingsystem") == "aqua":
                # на macOS обычное безрамочное окно не рисуется — берём системный стиль подсказки
                tip.tk.call("::tk::unsupported::MacWindowStyle", "style", tip._w, "help", "noActivates")
            else:
                tip.wm_overrideredirect(True)
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            tip.wm_overrideredirect(True)
        tk.Label(tip, text=self.text, background="#ffffe0", foreground="#202020", relief="solid",
                 borderwidth=1, padx=6, pady=2).pack()
        tip.update_idletasks()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() - tip.winfo_reqwidth()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip.wm_geometry(f"+{max(0, x)}+{y}")

    def _hide(self, _event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def resource_path(rel: str) -> Path:
    """Путь к ресурсу и из исходников, и из собранного PyInstaller-приложения."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / rel


NATIVE_SCROLL = ("Treeview", "Text", "Listbox")   # свои виджеты прокручиваем сами, остальное — форма-«холст»


def _wheel_units(delta: int) -> int:
    """Число «строк» прокрутки по дельте колеса (знак важен, величина зависит от ОС)."""
    if delta == 0:
        return 0
    mag = max(1, min(5, round(abs(delta) / 40))) if abs(delta) >= 40 else 1
    return -mag if delta > 0 else mag


def _scroll_target(widget):
    """Ближайший вверх по дереву виджет, который умеет прокручиваться (холст формы, таблица, текст)."""
    w = widget
    while w is not None:
        if getattr(w, "_wheel_scrollable", False) or w.winfo_class() in NATIVE_SCROLL:
            return w
        w = getattr(w, "master", None)
    return None


def install_wheel(root: tk.Tk) -> None:
    """Колесо мыши, Shift+колесо (по горизонтали) и жесты трекпада — во всех окнах и над любыми полями."""
    def scroll(w, dx: int, dy: int):
        try:
            if dy and hasattr(w, "yview_scroll"):
                w.yview_scroll(dy, "units")
            if dx and hasattr(w, "xview_scroll"):
                w.xview_scroll(dx, "units")
        except tk.TclError:
            pass

    def on_wheel(event, horizontal=False):
        target = _scroll_target(event.widget) if not isinstance(event.widget, str) else None
        if target is None:
            return
        u = _wheel_units(event.delta)
        scroll(target, u if horizontal else 0, 0 if horizontal else u)
        return "break"

    def on_touchpad(event):
        target = _scroll_target(event.widget) if not isinstance(event.widget, str) else None
        if target is None:
            return
        try:
            dx, dy = (int(float(v)) for v in root.tk.call("tk::PreciseScrollDeltas", event.delta))
        except tk.TclError:
            return
        scroll(target, -dx, -dy)
        return "break"

    for seq, h in (("<MouseWheel>", False), ("<Shift-MouseWheel>", True)):
        root.bind_all(seq, lambda e, h=h: on_wheel(e, h))
    root.bind_all("<TouchpadScroll>", on_touchpad)
    # родные обработчики этих классов заменяем нашими, чтобы не было двойной прокрутки
    for cls in NATIVE_SCROLL:
        for seq, h in (("<MouseWheel>", False), ("<Shift-MouseWheel>", True)):
            root.bind_class(cls, seq, lambda e, h=h: on_wheel(e, h))
        root.bind_class(cls, "<TouchpadScroll>", on_touchpad)
    # Linux (X11): колесо приходит кнопками 4/5
    for btn, d in (("<Button-4>", 120), ("<Button-5>", -120)):
        root.bind_all(btn, lambda e, d=d: on_wheel(type("E", (), {"widget": e.widget, "delta": d})()))


EDIT_CLASSES = ("Entry", "TEntry", "TSpinbox", "TCombobox", "Text")
# Физические коды клавиш A, X, C, V (не зависят от раскладки): macOS / Windows / X11
_KEYCODES = {"aqua": {0: "SelectAll", 7: "Cut", 8: "Copy", 9: "Paste"},
             "win32": {65: "SelectAll", 88: "Cut", 67: "Copy", 86: "Paste"},
             "x11": {38: "SelectAll", 53: "Cut", 54: "Copy", 55: "Paste"}}


def _select_all(w) -> None:
    if w.winfo_class() == "Text":
        w.tag_add("sel", "1.0", "end-1c")
    else:
        w.select_range(0, "end")
        w.icursor("end")


def install_clipboard(root: tk.Tk) -> None:
    """Копировать/вставить работают при любой раскладке (Tk привязывает их к латинским буквам, поэтому
    при русской раскладке Cmd+V / Ctrl+V молчали) и есть контекстное меню по правой кнопке."""
    ws = root.tk.call("tk", "windowingsystem")
    codes = _KEYCODES.get(ws, _KEYCODES["x11"])
    mod = "Command" if ws == "aqua" else "Control"

    def on_key(event):
        # на macOS Tk кодирует keycode как (код физической клавиши << 24) | символ; в остальных ОС код «сырой»
        hw = (event.keycode >> 24) if ws == "aqua" else event.keycode
        action = codes.get(hw)
        if not action:
            return
        w = event.widget
        if action == "SelectAll":
            _select_all(w)
        else:
            w.event_generate(f"<<{action}>>")
        return "break"

    def popup(event):
        w = event.widget
        w.focus_set()
        editable = str(w.cget("state")) not in ("readonly", "disabled")
        m = tk.Menu(w, tearoff=0)
        for label, ev, need_edit in (("Вырезать", "<<Cut>>", True), ("Копировать", "<<Copy>>", False),
                                     ("Вставить", "<<Paste>>", True)):
            m.add_command(label=label, command=lambda ev=ev: w.event_generate(ev),
                          state="normal" if (editable or not need_edit) else "disabled")
        m.add_separator()
        m.add_command(label="Выделить всё", command=lambda: _select_all(w))
        m.tk_popup(event.x_root, event.y_root)
        return "break"

    right = ("<Button-2>", "<Control-Button-1>") if ws == "aqua" else ("<Button-3>",)
    for cls in EDIT_CLASSES:
        # более специфичные привязки Tk (латинские Cmd+V и т. п.) сохраняются и имеют приоритет
        root.bind_class(cls, f"<{mod}-Key>", on_key)
        for seq in right:
            root.bind_class(cls, seq, popup)


def center_on_screen(win: tk.Tk, width: int, height: int) -> None:
    """Первое положение главного окна — по центру экрана."""
    win.update_idletasks()
    # на небольших экранах окно не должно выходить за экран (запас под заголовок окна, меню и Dock)
    width = min(width, win.winfo_screenwidth() - 40)
    height = min(height, win.winfo_screenheight() - 140)
    x = max(0, (win.winfo_screenwidth() - width) // 2)
    y = max(0, (win.winfo_screenheight() - height) // 2 - 20)   # чуть выше центра: учитываем меню/Dock
    win.geometry(f"{width}x{height}+{x}+{y}")


def center_over(win: tk.Misc, parent: tk.Misc) -> None:
    """Ставит дочернее окно по центру родительского (и не даёт уйти за край экрана)."""
    win.update_idletasks()
    parent.update_idletasks()
    w = max(win.winfo_width(), win.winfo_reqwidth())
    h = max(win.winfo_height(), win.winfo_reqheight())
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    x = max(0, min(x, win.winfo_screenwidth() - w))
    y = max(0, min(y, win.winfo_screenheight() - h))
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.update_idletasks()
    # geometry задаёт положение с рамкой окна: компенсируем высоту заголовка
    dy = win.winfo_rooty() - win.winfo_y()
    if 0 < dy < 100:
        win.geometry(f"{w}x{h}+{x}+{max(0, y - dy)}")


def col_width(header: str) -> int:
    h = header.lower()
    if "фио" in h or "должник" in h:
        return 280
    if "адрес" in h:
        return 210
    if h in ("кв", "квартира"):
        return 80
    return 130


def fmt_money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _mix(root: tk.Misc, fg: str, bg: str, k: float) -> str:
    """Цвет между текстом и фоном: k=0 — цвет текста, k=1 — цвет фона."""
    (r1, g1, b1), (r2, g2, b2) = root.winfo_rgb(fg), root.winfo_rgb(bg)
    return "#%02x%02x%02x" % tuple(int((a + (b - a) * k) / 257) for a, b in ((r1, r2), (g1, g2), (b1, b2)))


THEME_LABELS = {"system": "Как в системе", "light": "Светлая", "dark": "Тёмная"}
DARK_COLORS = {"bg": "#2b2b2b", "fg": "#e6e6e6", "field": "#1e1e1e", "select": "#0a5cc7"}


def _is_mac(root: tk.Misc) -> bool:
    return root.tk.call("tk", "windowingsystem") == "aqua"


def _system_dark_windows() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def set_window_appearance(root: tk.Misc, win: tk.Misc, mode: str) -> None:
    """macOS: светлое/тёмное оформление окна (auto — как в системе)."""
    try:
        root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win,
                     {"light": "aqua", "dark": "darkaqua"}.get(mode, "auto"))
    except tk.TclError:
        pass


def apply_theme(root: tk.Tk, mode: str) -> None:
    """Применяет тему оформления. На macOS оформление даёт сама система (окна и диалоги);
    на Windows/Linux светлая — стандартная, тёмная — палитра поверх темы clam."""
    if _is_mac(root):
        for w in [root] + [c for c in root.winfo_children() if isinstance(c, tk.Toplevel)]:
            set_window_appearance(root, w, mode)
        root.update_idletasks()
    else:
        st = ttk.Style(root)
        dark = mode == "dark" or (mode == "system" and _system_dark_windows())
        if dark:
            c = DARK_COLORS
            st.theme_use("clam")
            st.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                         troughcolor=c["field"], bordercolor="#444444", lightcolor=c["bg"], darkcolor=c["bg"])
            st.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"])
            st.configure("Treeview.Heading", background="#3a3a3a", foreground=c["fg"])
            st.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", "#ffffff")])
            st.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["fg"])])
            root.configure(background=c["bg"])
            for pat, opts in (("Text", {"background": c["field"], "foreground": c["fg"]}),
                              ("Listbox", {"background": c["field"], "foreground": c["fg"]}),
                              ("Menu", {"background": c["bg"], "foreground": c["fg"]})):
                for k, v in opts.items():
                    root.option_add(f"*{pat}.{k}", v)
        else:
            st.theme_use("vista" if "vista" in st.theme_names() else "default")
            st.map("Treeview", background=[("selected", "#0078d7")], foreground=[("selected", "#ffffff")])
            root.configure(background=st.lookup("TFrame", "background") or "SystemButtonFace")
    apply_palette(root)


def apply_palette(root: tk.Misc) -> None:
    """Приглушённый, зелёный и оранжевый цвета подписей и цвет чередования строк берутся от системной темы
    (светлой или тёмной), а не задаются жёстко, — поэтому читаются и в тёмном режиме."""
    st = ttk.Style(root)
    fg = st.lookup("TLabel", "foreground") or "black"
    bg = st.lookup("TLabel", "background") or "white"
    field = "systemTextBackgroundColor" if _is_mac(root) else (st.lookup("Treeview", "fieldbackground") or "white")
    try:
        dark = sum(root.winfo_rgb(bg)) < 3 * 32768
        muted = _mix(root, fg, bg, 0.45)
        stripe = _mix(root, field, fg, 0.07 if dark else 0.04)
    except tk.TclError:
        dark, muted, stripe = False, "gray", "#f4f5f5"
    st.configure("Muted.TLabel", foreground=muted)
    st.configure("Ok.TLabel", foreground="#5fc27e" if dark else "#2e7d32")
    st.configure("Warn.TLabel", foreground="#f0a93c" if dark else "#b26a00")
    st.configure("Status.TLabel", foreground=muted, font="TkSmallCaptionFont")
    root.stripe_color = stripe
    tree = getattr(root, "tree", None)
    if tree is not None:
        tree.tag_configure("odd", background=stripe)              # чередование строк, как в Finder


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Должники")
        try:
            self._icon = tk.PhotoImage(file=str(resource_path("assets/icon.png")))
            self.iconphoto(True, self._icon)
        except Exception:
            pass
        center_on_screen(self, 980, 700)
        install_wheel(self)
        install_clipboard(self)
        self.minsize(min(900, self.winfo_screenwidth() - 40), 420)

        self.settings = load_settings()
        apply_theme(self, self.settings.theme)
        self.bind("<<ThemeChanged>>", lambda e: e.widget is self and apply_palette(self), add="+")
        if _is_mac(self):                                  # новые окна (диалоги) получают то же оформление
            self.bind_class("Toplevel", "<Map>", lambda e: isinstance(e.widget, tk.Toplevel)
                            and set_window_appearance(self, e.widget, self.settings.theme), add="+")
        self.path: Path | None = None
        self.sheet: core.Sheet | None = None
        self.result: core.Result | None = None

        self._restoring = False
        self.kind = "original"                          # тип открытого файла: original — исходный отчёт, filtered — отфильтрованный список
        self.file_meta: dict = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self.restore_last_state)          # прошлое состояние восстанавливаем, когда окно уже показано

    # ---------- интерфейс ----------
    def _build(self):
        pad = {"padx": 6, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Открыть Excel…", command=self.open_file).pack(side="left")
        self.file_lbl = ttk.Label(top, text="Файл не выбран", style="Muted.TLabel")
        self.file_lbl.pack(side="left", padx=(8, 2))
        self.kind_lbl = ttk.Label(top, text="", style="Muted.TLabel")
        self.kind_lbl.pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Лист:").pack(side="left", padx=(16, 2))
        self.sheet_cb = ttk.Combobox(top, state="readonly", width=24)
        self.sheet_cb.pack(side="left")
        self.sheet_cb.bind("<<ComboboxSelected>>", lambda e: self.kind == "original" and self.load_sheet(self.sheet_cb.get()))
        # кнопка «Настройки» — шестерёнка в правом верхнем углу
        try:
            self._gear = tk.PhotoImage(file=str(resource_path("assets/gear.png")))
            self._gear_hover = tk.PhotoImage(file=str(resource_path("assets/gear_hover.png")))
            gear = ttk.Label(top, image=self._gear, cursor="pointinghand" if self.tk.call("tk", "windowingsystem") == "aqua" else "hand2")
            gear.bind("<Enter>", lambda e: gear.configure(image=self._gear_hover), add="+")
            gear.bind("<Leave>", lambda e: gear.configure(image=self._gear), add="+")
        except tk.TclError:
            gear = ttk.Label(top, text="⚙", font=("", 18), cursor="hand2")
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.pack(side="right", padx=(0, 4))
        Tooltip(gear, "Настройки")

        orow = ttk.Frame(self)
        orow.pack(fill="x", **pad)
        ttk.Label(orow, text="Организация:").pack(side="left")
        self.org_cb = ttk.Combobox(orow, state="readonly", width=34)
        self.org_cb.pack(side="left", padx=6)
        self.org_hint = ttk.Label(orow, text="", style="Muted.TLabel")
        self.org_hint.pack(side="left", padx=10)
        self.refresh_orgs()
        self.org_cb.bind("<<ComboboxSelected>>", lambda e: self.save_state())

        # значения настроек живут в переменных; окно «Настройки» лишь показывает их
        self.col_vars = {k: tk.StringVar() for k in COLUMN_FIELDS}
        self.col_options = {k: [] for k in COLUMN_FIELDS}
        self.top_n = tk.IntVar(value=self.settings.top_n)
        self.ip_as_person = tk.BooleanVar(value=self.settings.ip_as_person)
        self.skip_nonres = tk.BooleanVar(value=self.settings.skip_nonresidential)
        self.restore_var = tk.BooleanVar(value=self.settings.restore_state)
        self.theme_var = tk.StringVar(value=THEME_LABELS.get(self.settings.theme, THEME_LABELS["system"]))
        self.sort_options = [SORT_DEBT_LABEL]                       # «Сумма долга» + колонки файла (заполняется при загрузке листа)
        self.page_size_var = tk.StringVar(value=str(self.settings.page_size))
        self.sort_var = tk.StringVar(value=self.settings.sort_col or SORT_DEBT_LABEL)
        self.sort_dir_var = tk.StringVar(value=DESC_LABEL if self.settings.sort_desc else ASC_LABEL)
        self.item_index: dict[str, int] = {}                        # строка таблицы -> номер в результате (после сортировки по клику)
        self.view_sort: tuple[str, bool] | None = None              # сортировка таблицы кликом по заголовку: (колонка, по убыванию)

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.filter_btn = ttk.Button(actions, text="Фильтровать", command=self.on_filter_button)
        self.filter_btn.pack(side="left")
        self.export_btn = ttk.Button(actions, text="Сохранить в Excel…", command=self.export, state="disabled")
        self.export_btn.pack(side="left", padx=6)

        docs = ttk.Frame(self)
        docs.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(docs, text="Документы для отмеченных:").pack(side="left", padx=(0, 6))
        self.claim_btn = ttk.Button(docs, text="Претензии…", command=self.make_claims, state="disabled")
        self.claim_btn.pack(side="left")
        self.letter_btn = ttk.Button(docs, text="Письмо в ЕИРЦ…", command=self.make_letter, state="disabled")
        self.letter_btn.pack(side="left", padx=6)
        self.court_btn = ttk.Button(docs, text="Судебный приказ…", command=self.make_court, state="disabled")
        self.court_btn.pack(side="left")
        self.owner_btn = ttk.Button(docs, text="Собственники помещения…", command=self.edit_owner, state="disabled")
        self.owner_btn.pack(side="right")

        # строка состояния внизу окна, как в Finder: тонкая линия сверху и мелкий приглушённый текст по центру
        status = ttk.Frame(self)
        status.pack(side="bottom", fill="x")
        ttk.Separator(status, orient="horizontal").pack(fill="x")
        self.stats_lbl = ttk.Label(status, text="Откройте Excel-файл", style="Status.TLabel", justify="center", anchor="center")
        self.stats_lbl.pack(fill="x", padx=10, pady=4)
        status.bind("<Configure>", lambda e: self.stats_lbl.config(wraplength=max(200, e.width - 24)))

        pick_bar = ttk.Frame(self)
        pick_bar.pack(fill="x", padx=8)
        self.all_var = tk.BooleanVar(value=True)
        self.all_cb = ttk.Checkbutton(pick_bar, text="Выделить / снять всех", variable=self.all_var,
                                      command=self.toggle_all, state="disabled")
        self.all_cb.pack(side="left")
        self.pick_lbl = ttk.Label(pick_bar, text="", style="Muted.TLabel")
        self.pick_lbl.pack(side="left", padx=12)
        self.bind("<FocusIn>", lambda e: e.widget is self and self.item_index and self.refresh_card_flags())

        # пагинация — отдельная строка под таблицей: в одной строке с отметками она не помещалась в окно
        pager_bar = ttk.Frame(self)
        pager_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 2))
        self.rows_lbl = ttk.Label(pager_bar, text="", style="Muted.TLabel")
        self.rows_lbl.pack(side="left")
        pager = ttk.Frame(pager_bar)
        pager.pack(side="right")
        self.first_btn = ttk.Button(pager, text="⏮", width=3, command=lambda: self.goto(0))
        self.prev_btn = ttk.Button(pager, text="◀", width=3, command=lambda: self.goto(self.page - 1))
        self.page_lbl = ttk.Label(pager, text="Стр. 1 из 1", width=12, anchor="center")
        self.next_btn = ttk.Button(pager, text="▶", width=3, command=lambda: self.goto(self.page + 1))
        self.last_btn = ttk.Button(pager, text="⏭", width=3, command=lambda: self.goto(10 ** 9))
        for w in (self.first_btn, self.prev_btn, self.page_lbl, self.next_btn, self.last_btn):
            w.pack(side="left")
        ttk.Label(pager, text="  на странице:").pack(side="left")
        size_cb = ttk.Combobox(pager, textvariable=self.page_size_var, values=("20", "50", "100", "200", "500"),
                               state="readonly", width=5)
        size_cb.pack(side="left", padx=(4, 0))
        size_cb.bind("<<ComboboxSelected>>", lambda e: self.change_page_size())

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(table, show="headings")
        ys = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        # данные таблицы хранятся отдельно от экрана: страницы, сортировка и отметки работают по всему списку
        self.has_checks = False
        self.cols: list[str] = []
        self.data_rows: list[list] = []                  # значения колонок данных для каждой строки
        self.check_state: list[bool] = []                # отметки по номеру строки результата
        self.order: list[int] = []                       # порядок показа (после сортировки кликом)
        self.page = 0
        self._page_first = 0
        self.tree.bind("<Configure>", lambda e: self.fit_columns())
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", self.on_tree_space)
        self.tree.bind("<Double-Button-1>", self.on_tree_double)
        self._build_context_menu()
        self._bind_shortcuts()
        apply_palette(self)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="we")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

    # ---------- горячие клавиши и контекстное меню ----------
    def _bind_shortcuts(self):
        mod = "Command" if self.tk.call("tk", "windowingsystem") == "aqua" else "Control"

        def guarded(fn):
            def handler(event=None):
                # в полях ввода клавиши работают как обычно
                if isinstance(getattr(event, "widget", None), (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox)):
                    return None
                fn()
                return "break"
            return handler

        self.bind_all(f"<{mod}-o>", lambda e: (self.open_file(), "break")[1])
        self.bind_all(f"<{mod}-comma>", lambda e: (self.open_settings(), "break")[1])
        self.bind_all(f"<{mod}-a>", guarded(self._select_all_rows), add="+")
        self.bind_all("<F5>", lambda e: (self.on_filter_button(), "break")[1])
        self.bind_all(f"<{mod}-Return>", lambda e: (self.on_filter_button(), "break")[1])
        self.tree.bind(f"<{mod}-c>", lambda e: (self.copy_rows(), "break")[1])
        Tooltip(self.filter_btn, f"Применить или сбросить фильтр (F5, {'⌘' if mod == 'Command' else 'Ctrl+'}Enter)")

    def _select_all_rows(self):
        if self.focus_get() is self.tree:
            self.tree.selection_set(self.tree.get_children())

    def _build_context_menu(self):
        self.ctx = tk.Menu(self, tearoff=0)
        self.ctx.add_command(label="Собственники помещения…", command=self.edit_owner)
        self.ctx.add_command(label="Отметить / снять отметку", command=self._toggle_selected)
        self.ctx.add_separator()
        self.ctx.add_command(label="Копировать строки", command=self.copy_rows)
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.tree.bind(seq, self.show_context_menu, add="+")

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item not in self.tree.selection():
            self.tree.selection_set(item)
        owner_ok = bool(self.result and self.result.top and self.has_checks)
        self.ctx.entryconfig(0, state="normal" if owner_ok else "disabled")
        self.ctx.entryconfig(1, state="normal" if self.has_checks else "disabled")
        self.ctx.tk_popup(event.x_root, event.y_root)
        return "break"

    def _toggle_selected(self):
        for item in self.tree.selection():
            self._toggle_item(item)
        self.refresh_pick_state()

    def copy_rows(self):
        rows = ["\t".join(str(v) for v in self.tree.item(i, "values")[3 if self.has_checks else 0:])
                for i in self.tree.selection()]
        if rows:
            self.clipboard_clear()
            self.clipboard_append("\n".join(rows))

    # ---------- действия ----------
    def open_file(self):
        p = filedialog.askopenfilename(
            title="Выберите файл с должниками",
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Все файлы", "*.*")],
        )
        if p:
            self.open_path(Path(p))

    def open_path(self, path: Path, sheet: str | None = None, quiet: bool = False) -> bool:
        """Открывает файл отчёта (и лист, если он есть в файле). quiet — без окон с ошибками (восстановление при запуске)."""
        kind, meta = core.detect_file_kind(path)
        if kind == "filtered":
            return self.open_filtered(path, quiet)              # файл, сохранённый этой программой («Сохранить в Excel»)
        try:
            names = core.list_sheets(path)
        except Exception as e:
            if not quiet:
                messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}\n\n"
                                               "Поддерживаются форматы .xlsx и .xls.")
            return False
        self.path = path
        self.file_lbl.config(text=self.path.name, style="TLabel")
        self.sheet_cb["values"] = names
        chosen = sheet if sheet in names else names[0]
        self.sheet_cb.set(chosen)
        self.load_sheet(chosen)
        return True

    def open_filtered(self, path: Path, quiet: bool = False) -> bool:
        """Открывает отфильтрованный список, сохранённый программой: он сразу становится результатом
        (без повторной фильтрации), колонки и организация берутся из служебного листа файла."""
        try:
            data = core.read_filtered(path)
        except Exception as e:
            if not quiet:
                messagebox.showerror("Ошибка", f"Не удалось открыть отфильтрованный файл:\n{e}")
            return False
        meta, headers = data["meta"], data["headers"]
        self.path, self.kind, self.file_meta = path, "filtered", meta
        self.file_lbl.config(text=path.name, style="TLabel")
        self.sheet_cb["values"] = [data["sheet"]]
        self.sheet_cb.set(data["sheet"])
        self.sheet = core.Sheet(headers, data["rows"], meta.get("title", ""))
        saved_cols, guess = meta.get("columns") or {}, core.guess_columns(headers)
        for key, var in self.col_vars.items():
            optional = key in OPTIONAL_COLUMNS
            self.col_options[key] = ([NONE] if optional else []) + headers
            value = saved_cols.get(key) if saved_cols.get(key) in headers else guess.get(key)
            var.set(value if value else (NONE if optional else ""))
        if meta.get("debt_col") in headers:
            self.col_vars["debt_col"].set(meta["debt_col"])
        debt_name = self.col_vars["debt_col"].get()
        self.sort_options = [SORT_DEBT_LABEL] + [h for h in headers if h != debt_name]
        if self.sort_var.get() not in self.sort_options:
            self.sort_var.set(SORT_DEBT_LABEL)
        org = next((o for o in self.orgs if o.name == meta.get("org")), None) or orgmod.find_by_title(self.orgs, meta.get("title", ""))
        if org:
            self.org_cb.set(org.name)
            self.org_hint.config(text="взята из отфильтрованного файла")
        self.result = core.Result(headers, data["rows"], data["amounts"], data["stats"])
        # порядок в файле — порядок, в котором он был сохранён; если в файле есть метка сортировки, показываем её,
        # иначе (файл прежней версии) список идёт по номерам
        self._display_result(meta.get("sort_col") or (debt_name if "sort_desc" in meta else None),
                             bool(meta.get("sort_desc", False)))
        st = data["stats"]
        src = meta.get("source_file")
        self.stats_lbl.config(text=(
            f"Отфильтрованный список: записей {len(self.result.top)} · сумма: {fmt_money(sum(self.result.amounts))}"
            + (f" · исходный файл: {src}" if src else "")
            + (f" · строк в исходном: {st['всего строк']}" if st.get("всего строк") else "")))
        self.kind_lbl.config(text="· отфильтрованный список", style="Ok.TLabel")
        self.filter_btn.config(text="Уже отфильтрован", state="disabled")
        self.save_state()
        return True

    def load_sheet(self, name: str):
        try:
            self.sheet = core.read_sheet(self.path, name)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать лист:\n{e}")
            return
        self.kind, self.file_meta = "original", {}
        self.kind_lbl.config(text="· исходный файл", style="Muted.TLabel")
        self.filter_btn.config(state="normal")
        headers = self.sheet.headers
        guess = core.guess_columns(headers)
        for key, var in self.col_vars.items():
            optional = key in OPTIONAL_COLUMNS
            self.col_options[key] = ([NONE] if optional else []) + headers
            saved = getattr(self.settings, key)
            value = saved if saved in headers else guess.get(key)
            var.set(value if value else (NONE if optional else ""))
        debt_name = self.col_vars["debt_col"].get()
        self.sort_options = [SORT_DEBT_LABEL] + [h for h in headers if h != debt_name]
        if self.sort_var.get() not in self.sort_options:
            self.sort_var.set(SORT_DEBT_LABEL)                       # прежняя колонка сортировки в этом файле отсутствует
        self.show_rows(headers, self.sheet.rows)
        self.stats_lbl.config(text=f"Загружено строк: {len(self.sheet.rows)}")
        self.filter_btn.config(text="Фильтровать")
        self.result = None
        self.export_btn.config(state="disabled")
        self.claim_btn.config(state="disabled")
        self.letter_btn.config(state="disabled")
        self.court_btn.config(state="disabled")
        self.owner_btn.config(state="disabled")
        org = orgmod.find_by_title(self.orgs, self.sheet.title)
        if org:
            self.org_cb.set(org.name)
            self.org_hint.config(text="определена по заголовку файла")
        elif (uk := self._org_from_uk_column()):
            self.org_cb.set(uk.name)
            self.org_hint.config(text="определена по колонке «УК»")
        else:
            cover = self.org_coverage()
            if cover and cover[0][1] > 0:                              # заголовка нет — смотрим, чьи это дома
                self.org_cb.set(cover[0][0].name)
                self.org_hint.config(text="определена по домам из списка организации")
            else:
                self.org_hint.config(text="не удалось определить по файлу — выберите вручную")
        self.save_state()

    # ---------- состояние между запусками ----------
    def _state_key(self, k: int) -> str:
        """Ключ строки списка (ФИО, адрес, квартира) — устойчив к изменению порядка строк в файле."""
        s, h, row = self.settings, self.result.headers, self.result.top[k]
        idx = {c: i for i, c in enumerate(h)}
        parts = [str(row[idx[s.name_col]] or "") if s.name_col in idx else "",
                 core.row_address(row, idx, s.addr_col, s.house_col),
                 str(row[idx[s.flat_col]] or "") if s.flat_col in idx else ""]
        return "|".join(parts).lower()

    def save_state(self):
        """Запоминает открытый файл, лист, организацию, факт фильтрации и снятые галочки."""
        if getattr(self, "_restoring", False):
            return
        try:
            if not self.restore_var.get():
                STATE_PATH.unlink(missing_ok=True)                 # запоминание выключено — прошлое состояние не храним
                return
            unchecked = []
            if self.result and self.has_checks:
                unchecked = [self._state_key(i) for i, on in enumerate(self.check_state) if not on]
            STATE_PATH.write_text(json.dumps({
                "file": str(self.path) if self.path else "", "sheet": self.sheet_cb.get(), "org": self.org_cb.get(),
                "filtered": bool(self.result), "unchecked": unchecked}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def restore_last_state(self):
        """При запуске: открыть прошлый файл, заново отфильтровать список и вернуть снятые галочки."""
        if not self.settings.restore_state:
            return
        try:
            st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        path = st.get("file") or ""
        if not path:
            return
        if not Path(path).exists():
            self.stats_lbl.config(text=f"Файл прошлого сеанса не найден: {path}")
            return
        self._restoring = True
        try:
            if not self.open_path(Path(path), st.get("sheet"), quiet=True):
                self.stats_lbl.config(text=f"Не удалось открыть файл прошлого сеанса: {path}")
                return
            if st.get("org") in [o.name for o in self.orgs]:
                self.org_cb.set(st["org"])
                self.org_hint.config(text="восстановлена с прошлого сеанса")
            if self.kind == "original" and st.get("filtered"):
                self.run(quiet=True)                             # исходный файл: список строится заново
            if self.result:                                      # и для исходного, и для отфильтрованного файла
                unchecked = set(st.get("unchecked") or [])
                for i in range(len(self.check_state)):
                    if self._state_key(i) in unchecked:
                        self.check_state[i] = False
                self.render_page()
        finally:
            self._restoring = False
            self.save_state()

    def on_close(self):
        self.save_state()
        self.destroy()

    def _org_from_uk_column(self):
        """Организация по значению колонки «УК» / «Управляющая компания» (в отчётах без заголовка)."""
        if not self.sheet:
            return None
        h = self.sheet.headers
        col = next((c for c in h if c.strip().lower() in ("ук", "управляющая компания", "управляющая организация")), None)
        if col is None:
            return None
        i = h.index(col)
        value = next((str(r[i]) for r in self.sheet.rows if r[i] not in (None, "")), "")
        return orgmod.find_by_title(self.orgs, value)

    def org_coverage(self) -> list[tuple]:
        """[(организация, число строк отчёта по её домам)] по убыванию; только организации со списком домов."""
        addr_col = self.col_vars["addr_col"].get()
        if not self.sheet or addr_col not in self.sheet.headers:
            return []
        idx = {c: i for i, c in enumerate(self.sheet.headers)}
        house_col = self.col_vars["house_col"].get()
        house_col = None if house_col in ("", NONE) else house_col
        keys = [orgmod.norm_addr(a) for a in (core.row_address(r, idx, addr_col, house_col) for r in self.sheet.rows) if a]
        out = []
        for o in self.orgs:
            if o.houses:
                houses = orgmod.house_addresses(o)
                out.append((o, sum(1 for k in keys if k in houses)))
        return sorted(out, key=lambda t: -t[1])

    def explain_empty_result(self, s) -> None:
        """Список получился пустым — объясняем почему и, если возможно, предлагаем выход."""
        st, org = self.result.stats, self.current_org()
        total = st.get("всего строк", 0)
        if org.houses and st.get("дома других организаций", 0) >= total > 0:
            best = next(((o, n) for o, n in self.org_coverage() if n > 0 and o.name != org.name), None)
            msg = (f"В списке домов организации «{org.name}» нет ни одного дома из этого отчёта: все строки отчёта "
                   f"({total}) относятся к другим домам. В списке организации домов: {len(org.houses)}.")
            if best:
                msg += (f"\n\nБольше всего совпадений у «{best[0].name}» ({best[1]} строк). "
                        "Переключиться на неё и отфильтровать заново?")
                if messagebox.askyesno("Пустой список", msg):
                    self.org_cb.set(best[0].name)
                    self.org_hint.config(text="выбрана по домам")
                    self.result = None
                    self.run()
                return
            msg += ("\n\nПроверьте выбранную организацию и её дома (Настройки → Организации → Дома; "
                    "пустой список домов означает «все дома файла»).")
            messagebox.showinfo("Пустой список", msg)
            return
        parts = [f"{k}: {st[k]}" for k in ("не физлица", "нежилые помещения", "без долга / сумма не распознана") if st.get(k)]
        messagebox.showinfo("Пустой список", "Под условия отбора не подошла ни одна строка.\n\n"
                            + (("Пропущено: " + "; ".join(parts) + ".\n\n") if parts else "")
                            + "Проверьте колонки в настройках (ФИО, «Сумма долга», «Адрес дома», «Квартира») и галочки отбора.")

    # ---------- организации ----------
    def refresh_orgs(self, keep=None):
        self.orgs = orgmod.load_orgs()
        names = [o.name for o in self.orgs]
        self.org_cb["values"] = names
        self.org_cb.set(keep if keep in names else (self.settings_org if getattr(self, "settings_org", None) in names else names[0]))

    def current_org(self) -> orgmod.Organization:
        return next((o for o in self.orgs if o.name == self.org_cb.get()), self.orgs[0])

    def open_settings(self):
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = SettingsDialog(self)

    def edit_orgs(self):
        OrgDialog(self, self.orgs, self.org_cb.get(), on_close=lambda name: self.refresh_orgs(name))

    def make_claims(self):
        if not self.result or not self.result.top:
            return
        s, org = self.settings, self.current_org()
        h = self.result.headers
        if not (s.addr_col and s.flat_col):
            messagebox.showinfo("Нет колонок", "Для претензий выберите колонки «Адрес дома» и «Квартира».")
            return
        pick = self.checked_indexes()
        if not pick:
            messagebox.showinfo("Претензии", "Не отмечено ни одного адреса.")
            return
        folder = filedialog.askdirectory(title=f"Папка для претензий ({org.name})")
        if not folder:
            return
        fi, ni = h.index(s.flat_col), h.index(s.name_col)
        today, made = date.today(), 0
        out = Path(folder)
        try:
            for k in pick:
                row = self.result.top[k]
                addr, flat = orgmod.addr_flat(self.row_addr(row), row[fi])
                fn = f"{k + 1:02d} " + claim.file_name(row[ni], addr, flat)
                claim.build_claim(org, address=addr, flat=flat, debt=self.result.amounts[k],
                                  on_date=today, path=out / fn)
                made += 1
        except Exception as e:
            messagebox.showerror("Ошибка", f"Сформировано {made}, затем ошибка:\n{e}")
            return
        messagebox.showinfo("Готово", f"Претензий: {made}\nОрганизация: {org.name}\nПапка: {folder}")

    # ---------- отметки в таблице результата ----------
    def checked_indexes(self) -> list[int]:
        """Номера отмеченных строк результата — по всему списку, а не только на текущей странице."""
        return [i for i, on in enumerate(self.check_state) if on]

    def set_check(self, item, value: bool):
        idx = self.item_index.get(item)
        if idx is None or idx >= len(self.check_state):
            return
        self.check_state[idx] = value
        vals = list(self.tree.item(item, "values"))
        vals[0] = "☑" if value else "☐"
        self.tree.item(item, values=vals)

    def refresh_pick_state(self):
        n, total = sum(self.check_state), len(self.check_state)
        self.all_var.set(total > 0 and n == total)
        text = ""
        if self.has_checks:
            text = f"Отмечено адресов: {n} из {total}"
            if self.result and len(self.result.amounts) == total:
                text += f" · долг отмеченных: {fmt_money(sum(a for a, on in zip(self.result.amounts, self.check_state) if on))}"
        self.pick_lbl.config(text=text)
        self.save_state()

    def toggle_all(self):
        if not self.has_checks:
            return
        self.check_state = [self.all_var.get()] * len(self.check_state)      # все страницы сразу
        for item in self.tree.get_children():
            self.set_check(item, self.check_state[self.item_index[item]])
        self.refresh_pick_state()

    def _toggle_item(self, item):
        idx = self.item_index.get(item)
        if idx is not None:
            self.set_check(item, not self.check_state[idx])

    def on_tree_click(self, event):
        if not self.has_checks:
            return
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_column(event.x) == "#1":
            item = self.tree.identify_row(event.y)
            if item:
                self._toggle_item(item)
                self.refresh_pick_state()
                return "break"

    def on_tree_space(self, event):
        if not self.has_checks:
            return
        for item in self.tree.selection():
            self._toggle_item(item)
        self.refresh_pick_state()
        return "break"

    # ---------- фильтр: применить / сбросить ----------
    def on_filter_button(self):
        if self.result:
            self.reset_filter()
        else:
            self.run()

    def reset_filter(self):
        """Снимает фильтр: снова показывается весь загруженный файл (постранично)."""
        if not self.sheet or self.kind == "filtered":
            return
        self.result = None
        self.show_rows(self.sheet.headers, self.sheet.rows)
        self.stats_lbl.config(text=f"Загружено строк: {len(self.sheet.rows)}")
        for b in (self.export_btn, self.claim_btn, self.letter_btn, self.court_btn, self.owner_btn):
            b.config(state="disabled")
        self.filter_btn.config(text="Фильтровать")
        self.save_state()

    def make_letter(self):
        if not self.result or not self.result.top:
            return
        s, org = self.settings, self.current_org()
        if not (s.addr_col and s.flat_col):
            messagebox.showinfo("Нет колонок", "Для письма выберите колонки «Адрес дома» и «Квартира».")
            return
        if not org.letter_header.strip():
            messagebox.showinfo("Нет шапки", "Заполните вкладку «Письмо в ЕИРЦ» в настройках → «Организации…».")
            return
        pick = self.checked_indexes()
        if not pick:
            messagebox.showinfo("Письмо в ЕИРЦ", "Не отмечено ни одного адреса.")
            return
        h = self.result.headers
        fi = h.index(s.flat_col)
        default = f"Письмо в ЕИРЦ {org.name}.docx".replace("«", "").replace("»", "").replace('"', "")
        p = filedialog.asksaveasfilename(defaultextension=".docx", initialfile=default,
                                         filetypes=[("Word", "*.docx")])
        if not p:
            return
        try:
            n = claim.build_letter(org, items=[orgmod.addr_flat(self.row_addr(self.result.top[k]), self.result.top[k][fi])
                                               for k in pick],
                                   on_date=date.today(), path=p)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сформировать письмо:\n{e}")
            return
        messagebox.showinfo("Готово", f"Адресов в письме: {n}\nОрганизация: {org.name}\n{p}")

    # ---------- собственники и судебный приказ ----------
    def row_addr(self, row: list) -> str:
        """Адрес дома строки результата (с учётом отдельной колонки «Номер дома»)."""
        s = self.settings
        return core.row_address(row, {c: i for i, c in enumerate(self.result.headers)}, s.addr_col, s.house_col)

    def row_info(self, k: int) -> dict:
        """Данные строки топа: адрес, квартира, ФИО из отчёта, долг."""
        s, h, row = self.settings, self.result.headers, self.result.top[k]
        addr, flat = orgmod.addr_flat(self.row_addr(row) if s.addr_col else "",
                                      row[h.index(s.flat_col)] if s.flat_col else "")
        return {
            "address": addr,
            "flat": flat,
            "report_fio": str(row[h.index(s.name_col)] or ""),
            "debt": self.result.amounts[k],
        }

    def _need_addr_cols(self, what: str) -> bool:
        s = self.settings
        if not (s.addr_col and s.flat_col):
            messagebox.showinfo("Нет колонок", f"Для {what} выберите колонки «Адрес дома» и «Квартира» в настройках.")
            return False
        return True

    def edit_owner(self):
        if not self.result or not self.result.top or not self._need_addr_cols("карточки собственника"):
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Данные собственника", "Выберите строку в таблице (клик по адресу или ФИО).")
            return
        OwnerDialog(self, self.row_info(self.item_index[sel[0]]), self.current_org())

    def on_tree_double(self, event):
        if not self.has_checks or self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) == "#1":
            return
        item = self.tree.identify_row(event.y)
        if item and self._need_addr_cols("карточки собственника"):
            OwnerDialog(self, self.row_info(self.item_index[item]), self.current_org())
            return "break"

    def make_court(self):
        if not self.result or not self.result.top or not self._need_addr_cols("заявления"):
            return
        org = self.current_org()
        pick = self.checked_indexes()
        if not pick:
            messagebox.showinfo("Судебный приказ", "Не отмечено ни одного адреса.")
            return
        data = courtsmod.load()
        courts_list, batch_code = data["courts"], ""

        def own_court_code(info: dict, card) -> str:
            """Участок, уже известный для помещения: выбран в карточке или закреплён за домом в списке домов."""
            return (card.court_code if card else "") or orgmod.house_court(org, info["address"])
        lacking = 0
        for k in pick:
            info = self.row_info(k)
            if not own_court_code(info, owners.get_card(info["address"], info["flat"])):
                lacking += 1
        if courts_list and lacking:
            dlg = CourtChoiceDialog(self, courts_list, data["last"], lacking, len(pick))
            self.wait_window(dlg)
            if dlg.result is None:
                return
            batch_code = dlg.result
            if batch_code:
                courtsmod.save_last(batch_code)
        elif courts_list:
            pass                                         # у всех адресов участок уже задан — общий выбор не нужен
        else:
            messagebox.showinfo("Судебные участки", "Список участков не загружен: в заявлениях поле суда останется пустым. "
                                "Загрузить список можно в настройках (шестерёнка → «Судебные участки»).")
        folder = filedialog.askdirectory(title=f"Папка для заявлений ({org.name})")
        if not folder:
            return
        out, n_known, n_unknown, no_card, no_court, multi = Path(folder), 0, 0, 0, 0, 0
        try:
            for k in pick:
                info = self.row_info(k)
                card = owners.get_card(info["address"], info["flat"])
                if card is None:
                    no_card += 1
                    card = owners.get_or_new(info["address"], info["flat"])
                court_obj = (courtsmod.find_by_code(courts_list, card.court_code)
                             or courtsmod.find_by_code(courts_list, orgmod.house_court(org, info["address"]))
                             or courtsmod.find_by_code(courts_list, batch_code))
                cases = court.plan_cases(card, info["report_fio"], info["debt"])     # по одному на каждого собственника
                if len(cases) > 1:
                    multi += 1
                for j, case in enumerate(cases, 1):
                    who = case.owner.fio if case.owner else "собственник не известен"
                    num = f"{k + 1:02d}" + (f"-{j}" if len(cases) > 1 else "")
                    fn = f"{num} " + claim.safe_name(
                        f"Заявление о судебном приказе {who} {info['address']} кв {claim.clean_flat(info['flat'])}") + ".docx"
                    no_court += 0 if court_obj else 1
                    if court.build_court_application(org, card, case, path=out / fn, court_obj=court_obj):
                        n_known += 1
                    else:
                        n_unknown += 1
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сформировать заявление:\n{e}")
            return
        note = (f"\n\nДля {no_card} адресов карточка собственника не заполнена: ФИО взято из отчёта, а дата и место "
                "рождения, паспорт, пени, периоды остались пустыми (____). Заполните их в «Данные собственника…» "
                "или в Word.") if no_card else ""
        if multi:
            note += (f"\n\nПомещений с несколькими собственниками: {multi} — на каждого собственника сформировано "
                     "отдельное заявление (номера вида 05-1, 05-2).")
        if no_court:
            note += f"\n\nБез судебного участка (поле суда пустое): {no_court}."
        messagebox.showinfo("Готово", f"Заявлений: {n_known + n_unknown}\n"
                                      f"• с ФИО собственника: {n_known}\n• собственник неизвестен: {n_unknown}\n"
                                      f"Организация: {org.name}\nПапка: {folder}{note}")

    def edit_markers(self):
        win = tk.Toplevel(self)
        win.title("Признаки организаций")
        win.geometry("420x460")
        win.transient(self)
        ttk.Label(win, text="Если наименование содержит одно из этих слов,\n"
                            "запись считается организацией (по одному на строку):",
                  justify="left").pack(anchor="w", padx=8, pady=6)
        txt = tk.Text(win, wrap="none")
        txt.pack(fill="both", expand=True, padx=8)
        txt.insert("1.0", "\n".join(self.settings.org_markers))

        def save():
            self.settings.org_markers = [l.strip() for l in txt.get("1.0", "end").splitlines() if l.strip()]
            save_settings(self.settings)
            win.destroy()

        def reset():
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(core.DEFAULT_ORG_MARKERS))

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)
        ttk.Button(btns, text="Сохранить", command=save).pack(side="right")
        ttk.Button(btns, text="По умолчанию", command=reset).pack(side="right", padx=6)
        center_over(win, getattr(self, "_settings_win", None) if getattr(self, "_settings_win", None)
                    and self._settings_win.winfo_exists() else self)

    def collect_settings(self) -> core.Settings:
        s = self.settings
        for key, var in self.col_vars.items():
            v = var.get()
            setattr(s, key, None if v in ("", NONE) else v)
        try:
            s.top_n = max(1, int(self.top_n.get()))
        except (tk.TclError, ValueError):
            s.top_n = 20
        s.inn_col = s.type_col = None
        s.ip_as_person = self.ip_as_person.get()
        s.skip_nonresidential = self.skip_nonres.get()
        s.restore_state = self.restore_var.get()
        s.theme = next((k for k, v in THEME_LABELS.items() if v == self.theme_var.get()), "system")
        s.sort_col = None if self.sort_var.get() in ("", SORT_DEBT_LABEL) else self.sort_var.get()
        s.sort_desc = self.sort_dir_var.get() != ASC_LABEL
        try:
            s.page_size = max(1, int(self.page_size_var.get()))
        except ValueError:
            s.page_size = 50
        return s

    def run(self, quiet: bool = False) -> bool:
        """Фильтрует загруженный отчёт. quiet — без окон (восстановление при запуске). Возвращает True при успехе."""
        if not self.sheet:
            if not quiet:
                messagebox.showinfo("Нет данных", "Сначала откройте Excel-файл.")
            return False
        if self.kind == "filtered":
            if not quiet:
                messagebox.showinfo("Фильтр", "Открыт уже отфильтрованный список. Чтобы отфильтровать заново, "
                                              "откройте исходный файл отчёта.")
            return False
        s = self.collect_settings()
        if not (s.name_col and s.debt_col):
            if not quiet:
                messagebox.showinfo("Настройки", "Укажите колонки «ФИО» и «Сумма долга».")
                self.open_settings()
            return False
        try:
            self.result = core.process(self.sheet, s, self.current_org())
        except Exception as e:
            if not quiet:
                messagebox.showerror("Ошибка", str(e))
            return False
        save_settings(s)
        self._display_result(s.sort_col or s.debt_col, s.sort_desc)
        if not self.result.top and not quiet:
            self.filter_btn.config(text="Сбросить фильтр")
            self.save_state()
            self.explain_empty_result(s)
            return True

        st = self.result.stats
        self.stats_lbl.config(text=(
            f"Организация: {self.current_org().name} · строк: {st['всего строк']} · физлиц с долгом: {st['физлиц с долгом']} · "
            f"отобрано: {st['отобрано']} · сумма: {fmt_money(st['сумма долга отобранных'])}"
        ))
        self.filter_btn.config(text="Сбросить фильтр")
        self.save_state()
        return True

    def _display_result(self, sort_col: str | None = None, sort_desc: bool = False):
        """Показывает self.result в таблице (с отметками) и включает кнопки документов.
        sort_col/sort_desc — по какой колонке список уже отсортирован: она помечается стрелкой в заголовке
        (▲ по возрастанию, ▼ по убыванию); без колонки помечается «№»."""
        di = self.result.headers.index(self.col_vars["debt_col"].get())
        rows = []
        for row, amt in zip(self.result.top, self.result.amounts):
            row = list(row)
            row[di] = fmt_money(amt)
            rows.append(row)
        self.show_rows(self.result.headers, rows, numbered=True)
        if sort_col and sort_col in self.result.headers:
            self._mark_sort(f"c{self.result.headers.index(sort_col) + 2}", sort_desc)      # +2: колонки «✓» и «№»
        else:
            self._mark_sort("c1", False)
        state = "normal" if self.result.top else "disabled"
        for b in (self.export_btn, self.claim_btn, self.letter_btn, self.court_btn, self.owner_btn):
            b.config(state=state)

    def export(self):
        if not self.result:
            return
        default = f"{self.path.stem}_топ{len(self.result.top)}.xlsx" if self.path else "должники.xlsx"
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=default,
                                         filetypes=[("Excel", "*.xlsx")])
        if not p:
            return
        try:
            s = self.collect_settings()
            meta = {
                "columns": {k: (None if v.get() in ("", NONE) else v.get()) for k, v in self.col_vars.items()},
                "org": self.current_org().name,
                "source_file": (self.file_meta.get("source_file") if self.kind == "filtered" else None)
                               or (self.path.name if self.path else ""),
                "source_sheet": self.file_meta.get("source_sheet") if self.kind == "filtered" else self.sheet_cb.get(),
                "title": self.sheet.title if self.sheet else "",
                "sort_col": s.sort_col, "sort_desc": s.sort_desc,
            }
            core.export(self.result, p, s.debt_col, meta)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")
            return
        messagebox.showinfo("Готово", f"Сохранено:\n{p}")

    def show_rows(self, headers, rows, numbered=False):
        """Загружает данные в таблицу и показывает первую страницу. numbered — режим результата (✓, №, отметки)."""
        self.cols = (["✓", "№", "Данные"] if numbered else []) + list(headers)
        self.has_checks = numbered
        self.data_rows = [["" if v is None else v for v in r] for r in rows]
        self.check_state = [True] * len(rows) if numbered else []
        self.order = list(range(len(rows)))
        self.view_sort = None
        self.page = 0
        self.compute_card_flags()
        self.col_titles = {f"c{i}": h for i, h in enumerate(self.cols)}
        self.tree["columns"] = [f"c{i}" for i in range(len(self.cols))]
        for i, h in enumerate(self.cols):
            self.tree.heading(f"c{i}", text=h, command=lambda c=f"c{i}": self.sort_view(c))
            small = numbered and h in SERVICE_COLS
            self.tree.column(f"c{i}", width=SERVICE_COLS[h] if small else col_width(h),
                             minwidth=36 if small else 50, stretch=False, anchor="center" if small else "w")
        self.col_weights = {f"c{i}": SERVICE_COLS[h] if (numbered and h in SERVICE_COLS) else col_width(h)
                            for i, h in enumerate(self.cols)}
        self.fixed_cols = {f"c{i}" for i, h in enumerate(self.cols) if numbered and h in SERVICE_COLS}
        self.all_cb.config(state="normal" if numbered and rows else "disabled")
        self.fit_columns()
        self.render_page()

    def fit_columns(self):
        """Ширина колонок подгоняется под ширину окна пропорционально их «весу», поэтому таблица
        помещается без горизонтальной прокрутки (узкие служебные колонки ✓ и № не сжимаются)."""
        weights = getattr(self, "col_weights", None)
        if not weights:
            return
        avail = self.tree.winfo_width() - 6
        if avail < 200:                                         # окно ещё не показано
            return
        fixed = sum(w for c, w in weights.items() if c in self.fixed_cols)
        flex = {c: w for c, w in weights.items() if c not in self.fixed_cols}
        total = sum(flex.values()) or 1
        room = max(avail - fixed, 50 * len(flex))
        for c, w in flex.items():
            self.tree.column(c, width=max(50, int(room * w / total)))

    # --- страницы ---
    def _page_size(self) -> int:
        try:
            return max(1, int(self.page_size_var.get()))
        except ValueError:
            return 50

    def total_pages(self) -> int:
        return max(1, -(-len(self.order) // self._page_size()))

    def goto(self, page: int):
        self.page = min(max(page, 0), self.total_pages() - 1)
        self.render_page()

    def change_page_size(self):
        self.page = self._page_first // self._page_size()        # остаёмся на той же строке, а не на прежнем номере страницы
        self.render_page()
        self.save_settings_now()

    def change_theme(self):
        """Тема выбрана в настройках: применяется сразу и запоминается."""
        self.settings.theme = self.collect_settings().theme
        apply_theme(self, self.settings.theme)
        self.save_settings_now()

    def save_settings_now(self):
        try:
            save_settings(self.collect_settings())
        except Exception:
            pass

    def render_page(self):
        """Рисует текущую страницу; отметки и порядок берутся из данных, поэтому не теряются при переходах."""
        size = self._page_size()
        self.page = min(self.page, self.total_pages() - 1)
        start = self.page * size
        self._page_first = start
        self.tree.delete(*self.tree.get_children())
        self.item_index = {}
        for pos in range(start, min(start + size, len(self.order))):
            idx = self.order[pos]
            vals = ([("☑" if self.check_state[idx] else "☐"), idx + 1, "✓" if self.card_flags[idx] else ""] if self.has_checks else []) + self.data_rows[idx]
            self.item_index[self.tree.insert("", "end", values=vals, tags=("odd",) if pos % 2 else ())] = idx
        total, tp = len(self.order), self.total_pages()
        self.page_lbl.config(text=f"Стр. {self.page + 1} из {tp}")
        self.rows_lbl.config(text=f"строки {start + 1 if total else 0}–{min(start + size, total)} из {total}")
        back, fwd = ("!disabled" if self.page > 0 else "disabled"), ("!disabled" if self.page < tp - 1 else "disabled")
        for b in (self.first_btn, self.prev_btn):
            b.state([back])
        for b in (self.next_btn, self.last_btn):
            b.state([fwd])
        self.refresh_pick_state()

    def compute_card_flags(self):
        """Для каждой строки результата: есть ли карточка с персональными данными собственника."""
        n = len(self.data_rows) if self.has_checks else 0
        self.card_flags = [False] * n
        if not (n and self.result and self.result.top and self.settings.addr_col and self.settings.flat_col):
            return
        cards = owners._load_all()
        for idx in range(min(n, len(self.result.top))):
            info = self.row_info(idx)
            d = cards.get(owners.make_key(info["address"], info["flat"]))
            if d:
                self.card_flags[idx] = any(getattr(o, k).strip() for o in owners._from_dict(d).owners
                                           for k in owners.OWNER_FIELDS)

    def refresh_card_flags(self):
        """Карточки могли измениться в диалоге — обновляем колонку «Данные» на видимой странице."""
        if not self.has_checks:
            return
        self.compute_card_flags()
        for item, idx in self.item_index.items():
            vals = list(self.tree.item(item, "values"))
            vals[2] = "✓" if self.card_flags[idx] else ""
            self.tree.item(item, values=vals)

    def sort_view(self, colid: str):
        """Сортировка таблицы кликом по заголовку — по всему списку, а не только по видимой странице.
        Первый клик — по возрастанию, повторный — по убыванию. Меняет только порядок показа;
        какие должники отобраны — определяет «Сортировать по» в настройках."""
        if not self.order:
            return
        ci = int(colid[1:])
        j = ci - (3 if self.has_checks else 0)                    # позиция в data_rows
        if self.has_checks and ci == 0:
            getter = lambda idx: 1 if self.check_state[idx] else 0
        elif self.has_checks and ci == 1:
            getter = lambda idx: idx + 1
        elif self.has_checks and ci == 2:
            getter = lambda idx: 1 if self.card_flags[idx] else 0
        else:
            getter = lambda idx: self.data_rows[idx][j]
        desc = bool(self.view_sort and self.view_sort[0] == colid and not self.view_sort[1])
        self.order = core.sort_by_values(list(self.order), getter, desc)
        self.page = 0
        self.render_page()
        self._mark_sort(colid, desc)

    def _mark_sort(self, colid: str, desc: bool):
        """Стрелка в заголовке колонки, по которой отсортирован список (▲ по возрастанию, ▼ по убыванию)."""
        self.view_sort = (colid, desc)
        for cid, title in self.col_titles.items():
            self.tree.heading(cid, text=title + (("  ▼" if desc else "  ▲") if cid == colid else ""))


SERVICE_COLS = {"✓": 36, "№": 46, "Данные": 64}      # служебные колонки таблицы результата и их ширина

COLUMN_FIELDS = {
    "name_col": "ФИО *",
    "debt_col": "Сумма долга *",
    "addr_col": "Адрес дома (или улица)",
    "house_col": "Номер дома (если в отдельной колонке)",
    "flat_col": "Квартира",
}
OPTIONAL_COLUMNS = ("addr_col", "house_col", "flat_col")


class SettingsDialog(tk.Toplevel):
    """Экран настроек: колонки файла, число должников, правила отбора."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Настройки")
        self.transient(app)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        cols = ttk.LabelFrame(body, text="Колонки файла", padding=8)
        cols.pack(fill="x")
        for row, (key, text) in enumerate(COLUMN_FIELDS.items()):
            ttk.Label(cols, text=text).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Combobox(cols, state="readonly", width=34, textvariable=app.col_vars[key],
                         values=app.col_options[key]).grid(row=row, column=1, sticky="we", padx=(10, 0), pady=3)
        cols.columnconfigure(1, weight=1)
        if not app.sheet:
            ttk.Label(cols, text="Колонки появятся после открытия файла.", style="Muted.TLabel").grid(
                row=len(COLUMN_FIELDS), column=0, columnspan=2, sticky="w", pady=(6, 0))

        rules = ttk.LabelFrame(body, text="Отбор", padding=8)
        rules.pack(fill="x", pady=(10, 0))
        line = ttk.Frame(rules)
        line.pack(fill="x")
        ttk.Label(line, text="Показать должников:").pack(side="left")
        ttk.Spinbox(line, from_=1, to=100000, textvariable=app.top_n, width=7).pack(side="left", padx=8)
        ttk.Checkbutton(rules, text="ИП считать физлицами", variable=app.ip_as_person).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(rules, text="Пропускать нежилые помещения (н/п, магазины и т. п.)",
                        variable=app.skip_nonres).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(rules, text="Запоминать состояние при запуске (файл, список, отметки)",
                        variable=app.restore_var).pack(anchor="w", pady=(2, 0))
        srow = ttk.Frame(rules)
        srow.pack(fill="x", pady=(8, 0))
        ttk.Label(srow, text="Сортировать по:").pack(side="left")
        ttk.Combobox(srow, textvariable=app.sort_var, values=app.sort_options, state="readonly", width=26).pack(
            side="left", padx=(8, 6))
        ttk.Combobox(srow, textvariable=app.sort_dir_var, values=[DESC_LABEL, ASC_LABEL], state="readonly",
                     width=34).pack(side="left")
        ttk.Label(rules, text="Сортировка применяется до отбора: в список попадают первые N должников в этом порядке.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Button(rules, text="Признаки организаций…", command=app.edit_markers).pack(anchor="w", pady=(8, 0))

        look = ttk.LabelFrame(body, text="Внешний вид", padding=8)
        look.pack(fill="x", pady=(10, 0))
        lrow = ttk.Frame(look)
        lrow.pack(fill="x")
        ttk.Label(lrow, text="Тема:").pack(side="left")
        theme_cb = ttk.Combobox(lrow, textvariable=app.theme_var, values=list(THEME_LABELS.values()),
                                state="readonly", width=18)
        theme_cb.pack(side="left", padx=8)
        theme_cb.bind("<<ComboboxSelected>>", lambda e: app.change_theme())

        orgs = ttk.LabelFrame(body, text="Организации", padding=8)
        orgs.pack(fill="x", pady=(10, 0))
        ttk.Label(orgs, text="Реквизиты, дома, тексты претензий, письма и заявлений для каждой организации.",
                  style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w")
        ttk.Button(orgs, text="Организации…", command=app.edit_orgs).pack(anchor="w", pady=(6, 0))

        cf = ttk.LabelFrame(body, text="Судебные участки", padding=8)
        cf.pack(fill="x", pady=(10, 0))
        line2 = ttk.Frame(cf)
        line2.pack(fill="x")
        ttk.Label(line2, text="Коды регионов:").pack(side="left")
        self.regions = tk.StringVar(value=courtsmod.load()["regions"])
        ttk.Entry(line2, textvariable=self.regions, width=14).pack(side="left", padx=6)
        ttk.Label(line2, text="(61 — Ростовская обл.; несколько — через запятую)", style="Muted.TLabel").pack(side="left")
        self.courts_lbl = ttk.Label(cf, text="", wraplength=420, justify="left")
        self.courts_lbl.pack(anchor="w", pady=(6, 0))
        brow = ttk.Frame(cf)
        brow.pack(anchor="w", pady=(6, 0))
        ttk.Button(brow, text="Загрузить список участков с sudrf.ru", command=self.load_courts).pack(side="left")
        ttk.Button(brow, text="Судьи и адреса участков…", command=self.edit_courts).pack(side="left", padx=(6, 0))
        self.show_courts_info()

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Готово", command=self.close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Return>", lambda e: self.close())
        self.bind("<Escape>", lambda e: self.close())
        center_over(self, app)

    def show_courts_info(self):
        d = courtsmod.load()
        self.courts_lbl.config(text=(f"Загружено участков: {len(d['courts'])} (обновлено {d['updated']})"
                                     if d["courts"] else "Список участков не загружен."))

    def edit_courts(self):
        if not courtsmod.load()["courts"]:
            messagebox.showinfo("Судебные участки", "Сначала загрузите список участков кнопкой слева.", parent=self)
            return
        CourtsEditorDialog(self)

    def load_courts(self):
        """Загружает публичный список участков мировых судей с sudrf.ru (без ваших данных)."""
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            courts_list = courtsmod.download(self.regions.get())
        except courtsmod.DownloadError as e:
            messagebox.showerror("Судебные участки", str(e), parent=self)
            return
        finally:
            self.config(cursor="")
        courtsmod.save(self.regions.get().strip(), courts_list, courtsmod.load()["last"])
        self.show_courts_info()
        messagebox.showinfo("Судебные участки", f"Загружено участков: {len(courts_list)}.", parent=self)

    def close(self):
        save_settings(self.app.collect_settings())
        self.destroy()


class AutoCombo(ttk.Frame):
    """Выпадающий список с поиском по вхождению: пока вы печатаете, в списке остаются только подходящие варианты.
    source(запрос) -> [(подпись, ключ)]; on_pick(ключ) вызывается при выборе (пустая строка — выбор сброшен)."""

    def __init__(self, master, source, on_pick, width: int = 60, max_rows: int = 10):
        super().__init__(master)
        self.source, self.on_pick, self.max_rows = source, on_pick, max_rows
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="▾", width=2, command=self.toggle).pack(side="left", padx=(4, 0))
        self._pop = self._lb = None
        self._items: list = []
        self._inside = False
        self._chosen_label = ""
        for seq, fn in (("<KeyRelease>", self._on_key), ("<Down>", self._down), ("<Up>", self._up),
                        ("<Return>", self._return), ("<Escape>", lambda e: self.hide()),
                        ("<FocusOut>", self._focus_out), ("<Button-1>", self._on_click_entry)):
            self.entry.bind(seq, fn, add="+")

    # --- поведение ---
    def set_text(self, label: str) -> None:
        self._chosen_label = label
        self.var.set(label)

    def _query(self) -> str:
        text = self.var.get()
        return "" if text == self._chosen_label else text        # после выбора показываем весь список

    def _on_click_entry(self, _e):
        self.entry.focus_set()                    # клик в поле всегда возвращает ему фокус
        self.after_idle(self.show)

    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R", "Left", "Right"):
            return
        if not self.var.get().strip() and self._chosen_label:
            self._chosen_label = ""
            self.on_pick("")                                       # поле очищено — выбор снят
        self.show()

    def toggle(self):
        if self._pop is not None:
            self.hide()
            self.entry.focus_set()
        else:
            self.entry.focus_set()
            self.show(all_items=True)

    def show(self, all_items: bool = False):
        self._items = self.source("" if all_items else self._query())
        if not self._items:
            self.hide()
            return
        if self._pop is None:
            self._build_popup()
        self._lb.delete(0, "end")
        for label, _key in self._items:
            self._lb.insert("end", label)
        self._lb.configure(height=min(len(self._items), self.max_rows))
        self._lb.selection_clear(0, "end")
        self._place()

    def _build_popup(self):
        pop = self._pop = tk.Toplevel(self)
        try:
            if pop.tk.call("tk", "windowingsystem") == "aqua":
                # системный стиль «подсказка без активации»: окно не отбирает фокус у поля ввода
                pop.tk.call("::tk::unsupported::MacWindowStyle", "style", pop._w, "help", "noActivates")
            else:
                pop.wm_overrideredirect(True)
            pop.wm_attributes("-topmost", True)
        except tk.TclError:
            pop.wm_overrideredirect(True)
        frame = ttk.Frame(pop, borderwidth=1, relief="solid")
        frame.pack(fill="both", expand=True)
        self._lb = tk.Listbox(frame, exportselection=False, activestyle="none", height=self.max_rows, takefocus=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=sb.set)
        self._lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self._lb.bind("<Motion>", self._hover)
        # штатная обработка нажатия у Listbox переносит на него фокус ввода, а после закрытия списка фокус терялся
        # (поле поиска переставало принимать текст). Нажатие гасим, выбор делаем по отпусканию кнопки.
        for seq in ("<Button-1>", "<B1-Motion>", "<Double-Button-1>", "<Shift-Button-1>"):
            self._lb.bind(seq, lambda e: "break")
        self._lb.bind("<ButtonRelease-1>", self._click)
        self._lb.bind("<Enter>", lambda e: setattr(self, "_inside", True))
        self._lb.bind("<Leave>", lambda e: setattr(self, "_inside", False))

    def _place(self):
        self.update_idletasks()
        x, y = self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        w = self.winfo_width()
        self._pop.update_idletasks()
        h = self._lb.winfo_reqheight() + 4
        self._pop.wm_geometry(f"{max(w, 200)}x{h}+{x}+{y}")
        self._pop.lift()

    def hide(self):
        if self._pop is not None:
            self._pop.destroy()
            self._pop = self._lb = None
            self._inside = False

    def _focus_out(self, _e):
        self.after(250, lambda: None if self._inside else self.hide())

    def _hover(self, e):
        i = self._lb.nearest(e.y)
        self._lb.selection_clear(0, "end")
        self._lb.selection_set(i)

    def _click(self, e):
        self._choose(self._lb.nearest(e.y))

    def _move(self, delta: int):
        if self._pop is None:
            self.show(all_items=not self.var.get().strip() or self.var.get() == self._chosen_label)
            return
        cur = self._lb.curselection()
        i = min(max((cur[0] if cur else -1) + delta, 0), self._lb.size() - 1)
        self._lb.selection_clear(0, "end")
        self._lb.selection_set(i)
        self._lb.see(i)

    def _down(self, _e):
        self._move(1)
        return "break"

    def _up(self, _e):
        self._move(-1)
        return "break"

    def _return(self, _e):
        if self._pop is not None:
            cur = self._lb.curselection()
            self._choose(cur[0] if cur else 0)
            return "break"

    def _choose(self, i: int):
        if not 0 <= i < len(self._items):
            return
        label, key = self._items[i]
        self.set_text(label)
        self.hide()
        self.entry.focus_set()                    # фокус остаётся в поле — можно сразу искать снова
        self.entry.icursor("end")
        self.on_pick(key)


class CourtEditDialog(tk.Toplevel):
    """Данные участка, которых нет в списке sudrf.ru: мировой судья и (при необходимости) исправленный адрес суда."""

    def __init__(self, parent, court, on_done):
        super().__init__(parent)
        self.court, self.on_done = court, on_done
        self.title("Данные участка")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=court.name, wraplength=520, justify="left", font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(body, text="Мировой судья (ФИО) — выводится в шапке заявления строкой «Судья: …»").pack(anchor="w", pady=(10, 0))
        self.judge = tk.StringVar(value=court.judge)
        ttk.Entry(body, textvariable=self.judge, width=64).pack(fill="x")
        ttk.Label(body, text="Адрес суда").pack(anchor="w", pady=(8, 0))
        self.address = tk.StringVar(value=court.address)
        ttk.Entry(body, textvariable=self.address, width=64).pack(fill="x")
        ttk.Label(body, text=f"Адрес в списке sudrf.ru: {court.base_address or court.address}", style="Muted.TLabel",
                  wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Label(body, text="Правки запоминаются и не пропадают при обновлении списка участков.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Сохранить", command=self.save).pack(side="right")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        center_over(self, parent.winfo_toplevel())

    def save(self):
        courtsmod.set_override(self.court.code, self.judge.get(), self.address.get())
        self.destroy()
        self.on_done()


class CourtsEditorDialog(tk.Toplevel):
    """Правка судьи и адреса суда у загруженных участков. Можно выделить несколько участков и задать им общий адрес."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Судьи и адреса участков")
        self.transient(parent)
        self.geometry("1120x640")
        self.courts = courtsmod.load()["courts"]
        self.shown: list = []

        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Поиск:").pack(side="left")
        self.query = tk.StringVar()
        ttk.Entry(top, textvariable=self.query).pack(side="left", fill="x", expand=True, padx=6)
        self.query.trace_add("write", lambda *a: self.refresh())
        ttk.Label(top, text="✎ — данные изменены вручную", style="Muted.TLabel").pack(side="left")

        box = ttk.Frame(self, padding=(12, 8, 12, 0))
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=("mark", "name", "judge", "address"), show="headings", selectmode="extended")
        for c, text, w, anchor in (("mark", "", 26, "center"), ("name", "Участок", 500, "w"),
                                   ("judge", "Мировой судья", 200, "w"), ("address", "Адрес суда", 330, "w")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=c != "mark")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())
        for seq in ("<Command-a>", "<Control-a>"):
            self.tree.bind(seq, lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        form = ttk.LabelFrame(self, text="Правка", padding=10)
        form.pack(fill="x", padx=12, pady=10)
        self.sel_lbl = ttk.Label(form, text="Выберите участок в списке (можно несколько: Shift/Cmd-клик, Cmd+A — все)",
                                 style="Muted.TLabel")
        self.sel_lbl.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(form, text="Мировой судья (ФИО)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.judge = tk.StringVar()
        self.judge_entry = ttk.Entry(form, textvariable=self.judge)
        self.judge_entry.grid(row=2, column=0, columnspan=2, sticky="we")
        ttk.Label(form, text="Адрес суда").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.address = tk.StringVar()
        ttk.Entry(form, textvariable=self.address).grid(row=4, column=0, columnspan=2, sticky="we")
        form.columnconfigure(0, weight=1)
        row = ttk.Frame(form)
        row.grid(row=5, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Button(row, text="Сохранить", command=self.apply).pack(side="left")
        ttk.Button(row, text="Сбросить правки у выбранных", command=self.reset).pack(side="left", padx=6)
        self.hint = ttk.Label(row, text="", style="Muted.TLabel")
        self.hint.pack(side="left", padx=8)
        ttk.Button(row, text="Закрыть", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        center_over(self, parent)

    def refresh(self, keep: set | None = None):
        keep = keep if keep is not None else {self.shown[self.tree.index(i)].code for i in self.tree.selection()
                                              if self.tree.index(i) < len(self.shown)}
        self.shown = courtsmod.search(self.courts, self.query.get())
        self.tree.delete(*self.tree.get_children())
        for c in self.shown:
            edited = bool(c.judge) or (c.base_address and c.address != c.base_address)
            item = self.tree.insert("", "end", values=("✎" if edited else "", c.name, c.judge, c.address))
            if c.code in keep:
                self.tree.selection_add(item)

    def _selected(self) -> list:
        return [self.shown[self.tree.index(i)] for i in self.tree.selection()]

    def load_selected(self):
        sel = self._selected()
        if len(sel) == 1:
            self.judge_entry.state(["!disabled"])
            self.judge.set(sel[0].judge)
            self.address.set(sel[0].address)
            self.sel_lbl.config(text=sel[0].name, style="TLabel")
            self.hint.config(text="")
        elif len(sel) > 1:
            self.judge.set("")
            self.judge_entry.state(["disabled"])                 # ФИО судьи у каждого участка своё
            addrs = {c.address for c in sel}
            self.address.set(addrs.pop() if len(addrs) == 1 else "")
            self.sel_lbl.config(text=f"Выбрано участков: {len(sel)} — адрес будет задан всем сразу", style="TLabel")
            self.hint.config(text="судью задают по одному участку")
        else:
            self.judge_entry.state(["!disabled"])
            self.sel_lbl.config(text="Выберите участок в списке (можно несколько: Shift/Cmd-клик, Cmd+A — все)",
                                style="Muted.TLabel")

    def apply(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Участки", "Выберите участок в списке.", parent=self)
            return
        address = self.address.get().strip()
        for c in sel:
            judge = self.judge.get().strip() if len(sel) == 1 else c.judge       # при множественном выборе судью не трогаем
            courtsmod.set_override(c.code, judge, address if address else c.base_address)
        self._reload(sel)
        self.hint.config(text=f"Сохранено: {len(sel)}")

    def reset(self):
        sel = self._selected()
        if not sel:
            return
        if not messagebox.askyesno("Сбросить правки", f"Вернуть данные из списка sudrf.ru для выбранных участков ({len(sel)})? "
                                   "ФИО судей и изменённые адреса будут удалены.", parent=self):
            return
        for c in sel:
            courtsmod.set_override(c.code, "", c.base_address)
        self._reload(sel)
        self.hint.config(text="Правки сброшены")

    def _reload(self, sel: list):
        self.courts = courtsmod.load()["courts"]
        self.refresh({c.code for c in sel})
        self.load_selected()


class CourtPicker(ttk.Frame):
    """Выбор судебного участка: выпадающий список с поиском по вхождению (по названию, коду и ФИО судьи)."""

    def __init__(self, master, courts: list, selected: str = "", height: int = 6):
        super().__init__(master)
        self.courts, self.code = courts, selected
        self.combo = AutoCombo(self, self._source, self._on_pick, width=64)
        self.combo.pack(fill="x")
        self.info = ttk.Label(self, text="", wraplength=560, justify="left")
        self.info.pack(anchor="w", pady=(4, 0))
        self.edit_btn = ttk.Button(self, text="Судья и адрес суда…", command=self._edit)
        self.edit_btn.pack(anchor="w", pady=(4, 0))
        self._refresh_selected()

    def _source(self, query: str):
        return [(c.name + (f" — {c.judge}" if c.judge else ""), c.code) for c in courtsmod.search(self.courts, query)]

    def _on_pick(self, code: str):
        self.code = code
        self._show_info()

    def _refresh_selected(self):
        c = courtsmod.find_by_code(self.courts, self.code)
        self.combo.set_text(c.name + (f" — {c.judge}" if c.judge else "") if c else "")
        self._show_info()

    def _show_info(self):
        c = courtsmod.find_by_code(self.courts, self.code)
        if c:
            self.info.config(text=f"{c.name}\nСудья: {c.judge or 'не указан'}\n{c.address}", style="Ok.TLabel")
        else:
            self.info.config(text="Участок не выбран", style="Muted.TLabel")
        self.edit_btn.state(["!disabled"] if c else ["disabled"])

    def _edit(self):
        c = courtsmod.find_by_code(self.courts, self.code)
        if c:
            CourtEditDialog(self, c, self._after_edit)

    def _after_edit(self):
        self.courts[:] = courtsmod.load()["courts"]                  # подхватываем сохранённые правки
        self._refresh_selected()

    def get(self) -> str:
        return self.code

    def clear(self):
        self.code = ""
        self.combo.set_text("")
        self._show_info()


class CourtChoiceDialog(tk.Toplevel):
    """Перед формированием заявлений: какой судебный участок подставить (для карточек без своего участка)."""

    def __init__(self, app: "App", courts: list, last: str, n: int, total: int | None = None):
        super().__init__(app)
        self.title("Судебный участок")
        self.transient(app)
        self.geometry("680x300")
        self.result = None                      # код участка, "" — без участка, None — отмена
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        extra = f" из {total}" if total and total != n else ""
        ttk.Label(body, text=f"Выберите судебный участок для адресов без своего участка ({n}{extra}). Если участок выбран "
                             "в карточке помещения или закреплён за домом в настройках организации, используется он.",
                  wraplength=640, justify="left").pack(anchor="w")
        self.picker = CourtPicker(body, courts, last)
        self.picker.pack(fill="x", pady=(8, 0))
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Сформировать", command=self.ok).pack(side="right")
        ttk.Button(btns, text="Без участка (впишу в Word)", command=self.blank).pack(side="right", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_over(self, app)
        self.grab_set()

    def ok(self):
        if not self.picker.get():
            messagebox.showinfo("Судебный участок", "Выберите участок в списке или нажмите «Без участка».", parent=self)
            return
        self.result = self.picker.get()
        self.destroy()

    def blank(self):
        self.result = ""
        self.destroy()


class OwnerDialog(tk.Toplevel):
    """Карточка помещения: собственники (у помещения их может быть несколько) и данные по делу.
    Заявление о судебном приказе формируется на каждого собственника."""

    OWNER_ROWS = [
        ("fio", "ФИО (у первого собственника по умолчанию из отчёта)"),
        ("share", "Доля в праве (1/2, 1/3, 50%) — выводится в заявлении, на суммы не влияет"),
        ("fio_gen", "ФИО в родительном (кого) — пусто = склонить само"),
        ("fio_ins", "ФИО в творительном (с кем) — пусто = склонить само"),
        ("birth_date", "Дата рождения"),
        ("birth_place", "Место рождения"),
        ("passport", "Паспорт (серия, номер, кем и когда выдан)"),
        ("reg_address", "Адрес регистрации"),
        ("live_address", "Адрес проживания (пусто = адрес помещения)"),
    ]
    ENTRY_FIELDS = [
        ("Если собственники неизвестны", [
            ("cadastral", "Кадастровый номер помещения"),
        ]),
        ("По делу", [
            ("account", "Лицевой счёт"),
            ("debt", "Сумма долга по помещению (пусто = из отчёта)"),
            ("penalty", "Сумма пеней по помещению"),
            ("debt_from", "Долг за период с"),
            ("debt_to", "Долг за период по"),
            ("pen_from", "Пеня за период с"),
            ("pen_to", "Пеня за период по"),
            ("duty", "Госпошлина (пусто = по умолчанию организации)"),
            ("payment_order", "Платёжное поручение (№ и дата)"),
            ("invoice_month", "Счёт-извещение за (напр. март 2023 года)"),
        ]),
        ("Дом", [
            ("managed_since", "Дом в управлении с (по умолчанию из списка домов организации)"),
        ]),
    ]

    def __init__(self, app: "App", info: dict, org: orgmod.Organization):
        super().__init__(app)
        self.app, self.info, self.org = app, info, org
        self.card = owners.get_or_new(info["address"], info["flat"])
        # рабочая копия списка собственников; нет сохранённых — один собственник по ФИО из отчёта
        self.owner_list = [replace(o) for o in self.card.owners] or \
                          [owners.Owner(fio=owners.normalize_fio(str(info["report_fio"])))]
        self.cur = 0
        self.title("Данные собственников")
        self.transient(app)
        self.geometry("680x780")

        head = ttk.Frame(self, padding=(12, 10, 12, 4))
        head.pack(fill="x")
        flat = claim.clean_flat(info["flat"])
        ttk.Label(head, text=f"{info['address']}, кв. {flat}", font=("", 13, "bold")).pack(anchor="w")
        ttk.Label(head, text=f"В отчёте: {info['report_fio']} · долг {fmt_money(info['debt'])}",
                  style="Muted.TLabel").pack(anchor="w")
        self.mode_lbl = ttk.Label(head, text="", wraplength=620, justify="left")
        self.mode_lbl.pack(anchor="w", pady=(4, 0))

        # прокручиваемая форма
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=(12, 0))
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas)
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas._wheel_scrollable = True   # колесо и трекпад над любыми полями формы прокручивают её

        # --- собственники помещения ---
        obox = ttk.LabelFrame(form, text="Собственники помещения", padding=8)
        obox.pack(fill="x", pady=(0, 8), padx=(0, 10))
        ttk.Label(obox, text="Заявление формируется на каждого собственника; в каждом указаны все собственники.",
                  style="Muted.TLabel", wraplength=600, justify="left").pack(anchor="w")
        lrow = ttk.Frame(obox)
        lrow.pack(fill="x", pady=(6, 6))
        self.lb = tk.Listbox(lrow, height=4, exportselection=False, activestyle="none")
        self.lb.pack(side="left", fill="x", expand=True)
        lbtn = ttk.Frame(lrow)
        lbtn.pack(side="left", padx=(8, 0))
        ttk.Button(lbtn, text="Добавить собственника", command=self.add_owner).pack(fill="x")
        ttk.Button(lbtn, text="Удалить выбранного", command=self.remove_owner).pack(fill="x", pady=(4, 0))
        self.lb.bind("<<ListboxSelect>>", lambda e: self.on_list_select())

        self.ovars: dict[str, tk.StringVar] = {}
        for key, label in self.OWNER_ROWS:
            ttk.Label(obox, text=label).pack(anchor="w")
            var = tk.StringVar()
            self.ovars[key] = var
            row = ttk.Frame(obox)
            row.pack(fill="x", pady=(0, 4))
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            if key == "fio":
                ttk.Button(row, text="Из отчёта", command=self.take_report_fio).pack(side="left", padx=(6, 0))
            if key == "fio_gen":
                ttk.Button(row, text="Склонить", command=self.decline).pack(side="left", padx=(6, 0))
            if key in ("fio", "share"):
                var.trace_add("write", lambda *a: self._sync())
        self.unknown = tk.BooleanVar(value=self.card.unknown)
        self.unknown.trace_add("write", lambda *a: self.update_mode())
        ttk.Checkbutton(obox, text="Собственники неизвестны (шаблон без ФИО)", variable=self.unknown).pack(anchor="w", pady=(4, 0))

        # --- остальные данные (по помещению) ---
        self.vars: dict[str, tk.StringVar] = {}
        for title, fields_ in self.ENTRY_FIELDS:
            box = ttk.LabelFrame(form, text=title, padding=8)
            box.pack(fill="x", pady=(0, 8), padx=(0, 10))
            for key, label in fields_:
                ttk.Label(box, text=label).pack(anchor="w")
                var = tk.StringVar(value=getattr(self.card, key))
                if key == "managed_since" and not self.card.managed_since.strip():
                    var.set(orgmod.house_since(org, info["address"]))
                self.vars[key] = var
                ttk.Entry(box, textvariable=var).pack(fill="x", pady=(0, 4))
            if title == "Дом":
                ttk.Label(box, text="Судебный участок для заявления (пусто = выбирается при формировании)").pack(anchor="w", pady=(6, 0))
                self.picker = CourtPicker(box, courtsmod.load()["courts"], self.card.court_code)
                self.picker.pack(fill="x")
                ttk.Button(box, text="Сбросить выбор", command=self.picker.clear).pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(self, padding=12)
        btns.pack(fill="x")
        ttk.Button(btns, text="Сохранить", command=self.save).pack(side="right")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=6)
        if owners.get_card(info["address"], info["flat"]):
            ttk.Button(btns, text="Удалить карточку", command=self.remove).pack(side="left")
        self._loading = False
        self.refresh_list(0)
        self.load_owner(0)
        center_over(self, app)

    # ----- список собственников -----
    def _label(self, i: int, o) -> str:
        fio = o.fio.strip() or ("(по отчёту)" if i == 0 else "(без ФИО)")
        return f"{i + 1}. {fio}" + (f" — {o.share.strip()}" if o.share.strip() else "")

    def refresh_list(self, select: int | None = None):
        self.lb.delete(0, "end")
        for i, o in enumerate(self.owner_list):
            self.lb.insert("end", self._label(i, o))
        if select is not None:
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(select)
            self.lb.see(select)

    def destroy(self):
        super().destroy()
        try:
            self.app.refresh_card_flags()            # карточка могла измениться — сразу обновляем колонку «Данные»
        except Exception:
            pass

    def commit(self):
        """Переносит значения полей в текущего собственника."""
        if self._loading or not 0 <= self.cur < len(self.owner_list):
            return
        o = self.owner_list[self.cur]
        for key in owners.OWNER_FIELDS:
            setattr(o, key, self.ovars[key].get().strip())

    def load_owner(self, i: int):
        self._loading = True
        self.cur = i
        o = self.owner_list[i]
        for key in owners.OWNER_FIELDS:
            self.ovars[key].set(getattr(o, key))
        self._loading = False
        self.update_mode()

    def on_list_select(self):
        sel = self.lb.curselection()
        if sel and sel[0] != self.cur:
            self.commit()
            self.load_owner(sel[0])
            self.refresh_list(sel[0])

    def _sync(self):
        """Поля ФИО/доли изменились: обновляем подпись в списке и подсказку."""
        if self._loading:
            return
        self.commit()
        cur = self.cur
        self.lb.delete(cur)
        self.lb.insert(cur, self._label(cur, self.owner_list[cur]))
        self.lb.selection_set(cur)
        self.update_mode()

    def add_owner(self):
        self.commit()
        self.owner_list.append(owners.Owner())
        self.refresh_list(len(self.owner_list) - 1)
        self.load_owner(len(self.owner_list) - 1)

    def remove_owner(self):
        if len(self.owner_list) == 1:
            self.owner_list[0] = owners.Owner()          # единственного не удаляем — очищаем
            self.refresh_list(0)
            self.load_owner(0)
            return
        del self.owner_list[self.cur]
        i = min(self.cur, len(self.owner_list) - 1)
        self.refresh_list(i)
        self.load_owner(i)

    def update_mode(self):
        self.commit()
        report = str(self.info["report_fio"])
        probe = owners.Card(unknown=bool(self.unknown.get()), owners=[replace(o) for o in self.owner_list])
        people = probe.people(report)
        if not people:
            self.mode_lbl.config(text="Шаблон заявления: собственник НЕИЗВЕСТЕН (1 заявление)", style="Warn.TLabel")
            return
        text = f"Заявлений будет: {len(people)}"
        if len(people) > 1:
            text += " — по одному на каждого собственника\nСумма долга и пеней в каждом заявлении указывается полностью."
        self.mode_lbl.config(text=text, style="Ok.TLabel")

    def take_report_fio(self):
        self.ovars["fio"].set(owners.normalize_fio(str(self.info["report_fio"])))

    def decline(self):
        fio = self.ovars["fio"].get().strip()
        if not fio:
            messagebox.showinfo("Склонение", "Сначала введите ФИО.", parent=self)
            return
        self.ovars["fio_gen"].set(owners.decline_fio(fio, "gen"))
        self.ovars["fio_ins"].set(owners.decline_fio(fio, "ins"))

    def save(self):
        self.commit()
        for key, var in self.vars.items():
            setattr(self.card, key, var.get().strip())
        self.card.unknown = bool(self.unknown.get())
        # пустых собственников (без единого заполненного поля) не сохраняем
        self.card.owners = [o for o in self.owner_list if any(getattr(o, k).strip() for k in owners.OWNER_FIELDS)]
        self.card.court_code = self.picker.get()
        if self.card.managed_since == orgmod.house_since(self.org, self.info["address"]):
            self.card.managed_since = ""          # совпадает со списком домов — отдельно не храним
        self.card.address = str(self.info["address"]).strip()
        self.card.flat = claim.clean_flat(self.info["flat"])
        owners.save_card(self.card)
        self.destroy()

    def remove(self):
        if messagebox.askyesno("Удалить", "Удалить карточку помещения с данными собственников (персональные данные)?",
                               parent=self):
            owners.delete_card(self.info["address"], self.info["flat"])
            self.destroy()


class HousesEditor(ttk.Frame):
    """Список домов в обслуживании: адрес дома (как в отчёте), дата, с которой дом в управлении,
    и судебный участок, закреплённый за домом (подставляется в заявления, если не выбран в карточке)."""

    def __init__(self, master, app: "App"):
        super().__init__(master)
        self.app = app
        self.courts = courtsmod.load()["courts"]
        self.codes: dict[str, str] = {}                 # строка таблицы -> код участка
        self.court_code = ""
        ttk.Label(self, text="Дома в обслуживании: адрес как в отчёте, дата, с которой дом в управлении, и судебный участок "
                             "дома (пусто = все дома файла)", wraplength=760, justify="left").pack(anchor="w")
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True, pady=(4, 8))
        self.tree = ttk.Treeview(box, columns=("address", "since", "court"), show="headings", height=10, selectmode="extended")
        for c, text, w, anchor in (("address", "Адрес дома", 300, "w"), ("since", "В управлении с", 110, "center"),
                                   ("court", "Судебный участок", 240, "w")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())
        self.tree.bind("<Delete>", lambda e: self.remove())
        self.tree.bind("<BackSpace>", lambda e: self.remove())
        for seq in ("<Command-a>", "<Control-a>"):
            self.tree.bind(seq, lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.addr, self.since = tk.StringVar(), tk.StringVar()
        ttk.Entry(row, textvariable=self.addr).pack(side="left", fill="x", expand=True)
        ttk.Entry(row, textvariable=self.since, width=12).pack(side="left", padx=6)
        ttk.Button(row, text="Добавить / обновить", command=self.upsert).pack(side="left")
        self.del_btn = ttk.Button(row, text="Удалить", command=self.remove)
        self.del_btn.pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Из отчёта", command=self.from_report).pack(side="left", padx=(6, 0))

        crow = ttk.Frame(self)
        crow.pack(fill="x", pady=(8, 0))
        ttk.Label(crow, text="Судебный участок:").pack(side="left")
        self.combo = AutoCombo(crow, self._source, self._on_pick, width=52)
        self.combo.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(crow, text="Назначить выбранным домам", command=self.assign).pack(side="left")
        if not self.courts:
            ttk.Label(self, text="Список участков не загружен: настройки (шестерёнка) → «Судебные участки» → «Загрузить список».",
                      style="Warn.TLabel").pack(anchor="w", pady=(4, 0))

    # --- участки ---
    def _source(self, query: str):
        return [(c.name, c.code) for c in courtsmod.search(self.courts, query)]

    def _on_pick(self, code: str):
        self.court_code = code

    def _court_label(self, code: str) -> str:
        c = courtsmod.find_by_code(self.courts, code)
        return courtsmod.short_name(c) if c else (code or "")

    def _insert(self, address: str, since: str, code: str) -> str:
        item = self.tree.insert("", "end", values=(address, since, self._court_label(code)))
        self.codes[item] = code
        return item

    def _set_court(self, item: str, code: str):
        self.codes[item] = code
        vals = list(self.tree.item(item, "values"))
        vals[2] = self._court_label(code)
        self.tree.item(item, values=vals)

    def assign(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Дома", "Выделите дома в таблице, которым нужно назначить участок.", parent=self.winfo_toplevel())
            return
        if not self.court_code:
            messagebox.showinfo("Дома", "Выберите участок в выпадающем списке.", parent=self.winfo_toplevel())
            return
        for item in sel:
            self._set_court(item, self.court_code)

    # --- данные ---
    def set(self, houses: list[dict]):
        self.tree.delete(*self.tree.get_children())
        self.codes = {}
        for h in houses:
            self._insert(h["address"], h["since"], h.get("court", ""))
        self.addr.set(""); self.since.set("")
        self.court_code = ""
        self.combo.set_text("")

    def get(self) -> list[dict]:
        out = []
        for i in self.tree.get_children():
            v = self.tree.item(i, "values")
            if str(v[0]).strip():
                out.append({"address": str(v[0]).strip(), "since": str(v[1]).strip(), "court": self.codes.get(i, "")})
        return out

    def load_selected(self):
        sel = self.tree.selection()
        if len(sel) == 1:
            a, s = self.tree.item(sel[0], "values")[:2]
            self.addr.set(a); self.since.set(s)
            code = self.codes.get(sel[0], "")
            self.court_code = code
            c = courtsmod.find_by_code(self.courts, code)
            self.combo.set_text(c.name if c else "")
        else:                                   # несколько строк выделено — поля правки очищаем
            self.addr.set(""); self.since.set("")
        self.del_btn.config(text=f"Удалить ({len(sel)})" if len(sel) > 1 else "Удалить")

    def upsert(self):
        addr = self.addr.get().strip()
        if not addr:
            return
        key = orgmod.norm_addr(addr)
        for i in self.tree.get_children():
            if orgmod.norm_addr(self.tree.item(i, "values")[0]) == key:
                self.tree.item(i, values=(addr, self.since.get().strip(), self._court_label(self.court_code)))
                self.codes[i] = self.court_code
                return
        item = self._insert(addr, self.since.get().strip(), self.court_code)
        self.tree.see(item)
        self.addr.set(""); self.since.set("")

    def remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        if len(sel) > 1 and not messagebox.askyesno("Удалить дома", f"Удалить выделенные дома ({len(sel)})?",
                                                    parent=self.winfo_toplevel()):
            return
        for i in sel:
            self.codes.pop(i, None)
            self.tree.delete(i)
        self.addr.set(""); self.since.set("")
        self.del_btn.config(text="Удалить")

    def from_report(self):
        """Добавляет адреса домов из открытого отчёта (без строк «Итог»); даты можно заполнить потом."""
        a = self.app
        if not a.sheet:
            messagebox.showinfo("Дома", "Сначала откройте отчёт в главном окне.", parent=self.winfo_toplevel())
            return
        addr_col, name_col = a.col_vars["addr_col"].get(), a.col_vars["name_col"].get()
        if addr_col not in a.sheet.headers:
            messagebox.showinfo("Дома", "В настройках выберите колонку «Адрес дома».", parent=self.winfo_toplevel())
            return
        idx = {c: i for i, c in enumerate(a.sheet.headers)}
        house_col = a.col_vars["house_col"].get()
        house_col = None if house_col in ("", NONE) else house_col
        ni = a.sheet.headers.index(name_col) if name_col in a.sheet.headers else None
        have = {orgmod.norm_addr(h["address"]) for h in self.get()}
        added = 0
        for r in a.sheet.rows:
            if ni is not None and not r[ni]:
                continue                                       # строки «Итог» без ФИО
            addr = orgmod.clean_house_address(core.row_address(r, idx, addr_col, house_col))   # без квартиры, скобок и пунктуации
            if addr and orgmod.norm_addr(addr) not in have:
                have.add(orgmod.norm_addr(addr))
                self._insert(addr, "", "")
                added += 1
        messagebox.showinfo("Дома", f"Добавлено домов: {added}. Заполните даты, с которых дома в управлении.",
                            parent=self.winfo_toplevel())


class OrgDialog(tk.Toplevel):
    """Редактор организаций: реквизиты, дома, текст претензии."""

    def __init__(self, parent, orgs, selected, on_close):
        super().__init__(parent)
        self.title("Организации")
        self.geometry("820x640")
        self.transient(parent)
        self.orgs = [orgmod.Organization(**vars(o)) for o in orgs]
        self.on_close, self.cur = on_close, None

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=8, pady=8)
        self.lb = tk.Listbox(left, width=26, exportselection=False)
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.pick())
        ttk.Button(left, text="Добавить", command=self.add).pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="Удалить", command=self.remove).pack(fill="x", pady=2)

        nb = ttk.Notebook(self)
        nb.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        f = ttk.Frame(nb)
        g = ttk.Frame(nb)
        hs = ttk.Frame(nb, padding=(0, 0, 0, 4))
        hd = ttk.Frame(nb)
        nb.add(hs, text="Дома")
        nb.add(hd, text="Шапка")
        nb.add(f, text="Претензия")
        nb.add(g, text="Письмо в ЕИРЦ")
        h = ttk.Frame(nb)
        nb.add(h, text="Судебный приказ")
        self.name = tk.StringVar(); self.match = tk.StringVar(); self.agent = tk.StringVar()
        self.agent_addr = tk.StringVar(); self.days = tk.StringVar()

        def row(label, var):
            ttk.Label(f, text=label).pack(anchor="w")
            ttk.Entry(f, textvariable=var).pack(fill="x", pady=(0, 4))

        row("Название в претензии (напр. ООО УО «ДомСервис»)", self.name)
        row("Слово для автоопределения по заголовку файла (напр. ДомСервис)", self.match)
        row("Платёжный агент (напр. ООО «ЕИРЦ»; можно пусто)", self.agent)
        row("Адрес платёжного агента", self.agent_addr)
        row("Срок оплаты в претензии", self.days)

        def text(label, h):
            ttk.Label(f, text=label).pack(anchor="w")
            t = tk.Text(f, height=h, wrap="word")
            t.pack(fill="both", expand=True, pady=(0, 4))
            return t
        self.houses = HousesEditor(hs, parent)
        self.houses.pack(fill="both", expand=True)
        self.body = text("Текст претензии (пусто = стандартный). Поля: {org} {agent} {agent_address} {date} {debt} {days}; **жирный**", 8)

        b = ttk.Frame(f); b.pack(fill="x")
        ttk.Button(b, text="Стандартный текст", command=self.std_text).pack(side="right", padx=6)

        # --- вкладка «Шапка»: реквизиты организации в верхней части документов ---
        def htext(label, hint, height):
            ttk.Label(hd, text=label, font=("", 12, "bold")).pack(anchor="w", pady=(6, 0))
            ttk.Label(hd, text=hint, style="Muted.TLabel", wraplength=720, justify="left").pack(anchor="w")
            t = tk.Text(hd, height=height, wrap="word")
            t.pack(fill="both", expand=True, pady=(4, 8))
            return t
        self.header = htext("Шапка претензии", "Реквизиты организации по строке на строку (отображаются по центру).", 9)
        self.l_header = htext("Шапка письма в ЕИРЦ и заявления о судебном приказе",
                              "Строка с «# » в начале — крупным шрифтом (название организации); все строки жирным.", 9)

        # --- вкладка «Письмо в ЕИРЦ» ---
        def lrow(label, var):
            ttk.Label(g, text=label).pack(anchor="w")
            ttk.Entry(g, textvariable=var).pack(fill="x", pady=(0, 4))

        def ltext(label, h):
            ttk.Label(g, text=label).pack(anchor="w")
            t = tk.Text(g, height=h, wrap="word")
            t.pack(fill="both", expand=True, pady=(0, 4))
            return t
        self.l_to = ltext("Кому (справа). **жирный**", 4)
        self.l_body = ltext("Текст письма (пусто = стандартный). Поле {date} — срок ответа", 4)
        self.sign_role = tk.StringVar(); self.sign_name = tk.StringVar()
        self.city = tk.StringVar(); self.l_days = tk.StringVar()
        lrow("Должность подписанта", self.sign_role)
        lrow("Подписант (В. Е. Павличенко)", self.sign_name)
        lrow("Город в адресах", self.city)
        lrow("Срок ответа ЕИРЦ, дней", self.l_days)

        # --- вкладка «Судебный приказ» ---
        self.c_vars = {k: tk.StringVar() for k in ("applicant_address", "region", "city_in", "duty_default",
                                                    "license_text", "poa_text")}
        for key, label in (
            ("applicant_address", "Адрес заявителя в заявлении"),
            ("region", "Регион (в адресах помещений)"),
            ("city_in", "Город в предложном падеже («в г. Таганроге»)"),
            ("duty_default", "Госпошлина по умолчанию, руб. (проверьте ставку по НК РФ)"),
            ("license_text", "Уведомление о лицензии («№ 679 от 18.05.2021»)"),
            ("poa_text", "Доверенность от («23.08.2022г.»)"),
        ):
            ttk.Label(h, text=label).pack(anchor="w")
            ttk.Entry(h, textvariable=self.c_vars[key]).pack(fill="x", pady=(0, 4))
        ttk.Label(h, text="Шапка заявления берётся со вкладки «Шапка»; подписант — со вкладки «Письмо в ЕИРЦ». Судебный участок закрепляется за домом на вкладке «Дома» или выбирается в карточке помещения и при формировании заявлений.",
                  wraplength=760, justify="left",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        ttk.Button(left, text="Сохранить и закрыть", command=self.save).pack(fill="x", pady=(16, 0))
        self.refresh(selected)
        self.protocol("WM_DELETE_WINDOW", self.save)
        center_over(self, parent)

    def refresh(self, name=None):
        self.lb.delete(0, "end")
        for o in self.orgs:
            self.lb.insert("end", o.name)
        i = next((k for k, o in enumerate(self.orgs) if o.name == name), 0) if self.orgs else None
        if i is not None:
            self.lb.selection_set(i)
            self.cur = None
            self.pick()

    def commit(self):
        if self.cur is None or self.cur >= len(self.orgs):
            return
        o = self.orgs[self.cur]
        o.name, o.match, o.agent = self.name.get().strip(), self.match.get().strip(), self.agent.get().strip()
        o.agent_address, o.days = self.agent_addr.get().strip(), self.days.get().strip() or "10 (десяти) дней"
        o.header = self.header.get("1.0", "end").strip()
        o.houses = self.houses.get()
        o.body = self.body.get("1.0", "end").strip()
        for key, var in self.c_vars.items():
            setattr(o, key, var.get().strip())
        o.letter_header = self.l_header.get("1.0", "end").strip()
        o.letter_to = self.l_to.get("1.0", "end").strip()
        o.letter_body = self.l_body.get("1.0", "end").strip()
        o.sign_role, o.sign_name = self.sign_role.get().strip(), self.sign_name.get().strip()
        o.city = self.city.get().strip() or "г. Таганрог"
        try:
            o.letter_days = max(1, int(self.l_days.get()))
        except ValueError:
            o.letter_days = 10

    def pick(self):
        sel = self.lb.curselection()
        if not sel:
            return
        self.commit()
        self.cur = sel[0]
        o = self.orgs[self.cur]
        self.name.set(o.name); self.match.set(o.match); self.agent.set(o.agent)
        self.agent_addr.set(o.agent_address); self.days.set(o.days)
        self.sign_role.set(o.sign_role); self.sign_name.set(o.sign_name)
        self.city.set(o.city); self.l_days.set(str(o.letter_days))
        for key, var in self.c_vars.items():
            var.set(getattr(o, key))
        self.houses.set(o.houses)
        for w, v in ((self.header, o.header), (self.body, o.body),
                     (self.l_header, o.letter_header), (self.l_to, o.letter_to), (self.l_body, o.letter_body)):
            w.delete("1.0", "end"); w.insert("1.0", v)
        self.lb.delete(self.cur); self.lb.insert(self.cur, o.name); self.lb.selection_set(self.cur)

    def std_text(self):
        self.commit()
        o = self.orgs[self.cur]
        self.body.delete("1.0", "end")
        self.body.insert("1.0", orgmod.BODY_WITH_AGENT if o.agent else orgmod.BODY_NO_AGENT)

    def add(self):
        self.commit()
        self.orgs.append(orgmod.Organization(name="Новая организация"))
        self.refresh("Новая организация")

    def remove(self):
        if self.cur is None or len(self.orgs) < 2:
            messagebox.showinfo("Организации", "Должна остаться хотя бы одна организация.", parent=self)
            return
        if messagebox.askyesno("Удалить", f"Удалить «{self.orgs[self.cur].name}»?", parent=self):
            del self.orgs[self.cur]
            self.cur = None
            self.refresh()

    def save(self):
        self.commit()
        orgmod.save_orgs(self.orgs)
        name = self.orgs[self.cur].name if self.cur is not None and self.cur < len(self.orgs) else None
        self.destroy()
        self.on_close(name)


def main():
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)  # чёткий шрифт на HiDPI-мониторах
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
