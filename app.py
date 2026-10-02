"""Окно приложения «Должники» (Tkinter — работает на Windows и macOS)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import claim
import core
import court
import datepicker
import native_date
import duty
import courts as courtsmod
import orgs as orgmod
import owners
import storage
import widgets
from datetime import date

CONFIG_PATH = storage.SETTINGS_PATH
STATE_PATH = storage.STATE_PATH                    # состояние приложения между запусками
NONE = "— нет —"
SORT_DEBT_LABEL = "Сумма долга"
DESC_LABEL = "по убыванию (от большего к меньшему)"
ASC_LABEL = "по возрастанию (от меньшего к большему)"


FIRST_RUN = not CONFIG_PATH.exists()          # файла настроек ещё нет — программа запущена впервые
STARTUP_FILE_EXT = (".xls", ".xlsx", ".xlsm")


def load_settings() -> core.Settings:
    try:
        data = storage.load_json(CONFIG_PATH, "settings")
        if not isinstance(data, dict):
            return core.Settings()
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
        storage.save_json(CONFIG_PATH, "settings", asdict(s))
    except OSError:
        pass


def make_tip(parent: tk.Misc, text: str) -> tk.Toplevel:
    """Безрамочное окошко-подсказка (на macOS — системного стиля)."""
    tip = tk.Toplevel(parent)
    try:
        if tip.tk.call("tk", "windowingsystem") == "aqua":
            # на macOS обычное безрамочное окно не рисуется — берём системный стиль подсказки
            tip.tk.call("::tk::unsupported::MacWindowStyle", "style", tip._w, "help", "noActivates")
        else:
            tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
    except tk.TclError:
        tip.wm_overrideredirect(True)
    tk.Label(tip, text=text, background="#ffffe0", foreground="#202020", relief="solid",
             borderwidth=1, padx=6, pady=2, justify="left", wraplength=520).pack()
    tip.update_idletasks()
    return tip


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
        tip = self._tip = make_tip(self.widget, self.text)
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


def make_autoscroll(canvas: tk.Canvas, content: tk.Misc, sb: ttk.Scrollbar, pad: int = 0) -> int:
    """Прокрутка формы только когда содержимое не помещается в окно: иначе область прокрутки равна окну
    (содержимое не «скачет» от колеса и трекпада), а полоса прокрутки скрыта. Возвращает id окна внутри canvas."""
    win = canvas.create_window((0, 0), window=content, anchor="nw")

    def update(_e=None):
        ch, need = canvas.winfo_height(), content.winfo_reqheight()
        if need <= ch:
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), ch))
            canvas.yview_moveto(0)
            if sb.winfo_ismapped():
                sb.pack_forget()
        else:
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), need))
            if not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")

    def resize(e):
        canvas.itemconfigure(win, width=e.width)
        update()
    content.bind("<Configure>", update)
    canvas.bind("<Configure>", resize)
    return win


def pack_ok_cancel(ok: ttk.Button, cancel: ttk.Button, default: bool = False) -> None:
    """Порядок кнопок диалога по правилам платформы. macOS: «Отмена» слева от главной кнопки, главная — крайняя справа.
    Windows/Linux: главная кнопка слева, «Отмена» — крайняя справа. default — главная кнопка выделена (срабатывает по Enter)."""
    if default:
        ok.configure(default="active")
    if _is_mac(ok):
        ok.pack(side="right")
        cancel.pack(side="right", padx=6)
    else:
        cancel.pack(side="right")
        ok.pack(side="right", padx=6)


class Dialog(tk.Toplevel):
    """Дочернее окно, которое не показывается, пока не построено и не поставлено на место (center_over):
    иначе оно на мгновение появляется в углу экрана и потом «переезжает».
    На macOS скрытое окно с transient() показывается при первой же обработке событий, поэтому transient
    откладывается до момента показа."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.withdraw()
        self._transient_master = None
        if _is_mac(self):
            self.bind("<Command-w>", lambda e: self._close_by_shortcut())              # ⌘W закрывает окно, как в macOS
        self._show_job = self.after(150, self._ensure_shown)   # страховка, если окно не вызывает center_over (idle-обработчик сработал бы слишком рано)

    def geometry(self, newGeometry=None):
        """Запоминает заданный размер: у скрытого окна winfo_width() ещё 1, а center_over нужен настоящий размер."""
        m = re.match(r"(\d+)x(\d+)", newGeometry or "")
        if m:
            self._req_size = (int(m.group(1)), int(m.group(2)))
        return super().geometry(newGeometry) if newGeometry is not None else super().geometry()

    def transient(self, master=None):
        if master is None:
            return super().transient()
        self._transient_master = master

    def show(self):
        try:
            if self.state() == "withdrawn":
                if self._transient_master is not None:
                    super().transient(self._transient_master)
                self.deiconify()
        except tk.TclError:
            pass                                               # окно уже закрыли

    def _ensure_shown(self):
        self.show()

    def _close_by_shortcut(self):
        handler = self.protocol("WM_DELETE_WINDOW")           # у окон с «сохранить при закрытии» — их обработчик
        if handler:
            self.tk.call(handler)
        else:
            self.destroy()

    def destroy(self):
        try:
            self.after_cancel(self._show_job)
        except Exception:
            pass
        super().destroy()


def center_over(win: tk.Misc, parent: tk.Misc) -> None:
    """Ставит дочернее окно по центру родительского (и не даёт уйти за край экрана), затем показывает его."""
    win.update_idletasks()
    parent.update_idletasks()
    size = getattr(win, "_req_size", None)                     # размер, заданный окном явно
    w = size[0] if size else max(win.winfo_width(), win.winfo_reqwidth())
    h = size[1] if size else max(win.winfo_height(), win.winfo_reqheight())
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    x = max(0, min(x, win.winfo_screenwidth() - w))
    y = max(0, min(y, win.winfo_screenheight() - h))
    # geometry задаёт положение с рамкой окна: компенсируем высоту заголовка (её берём у уже показанного родителя)
    dy = parent.winfo_toplevel().winfo_rooty() - parent.winfo_toplevel().winfo_y()
    if 0 < dy < 100:
        y = max(0, y - dy)
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.update_idletasks()
    if isinstance(win, Dialog):
        win.show()                                             # показываем уже на своём месте
    elif win.state() == "withdrawn":
        win.deiconify()
    win.update_idletasks()


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


FONT_LABELS = {"normal": "Обычный", "large": "Крупный", "xlarge": "Очень крупный"}
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
        win.update_idletasks()                          # окно должно уже существовать, иначе Tk не может выставить оформление
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
        muted = widgets.mix(root, fg, bg, 0.45)
        stripe = widgets.mix(root, field, fg, 0.07 if dark else 0.04)
    except tk.TclError:
        dark, muted, stripe = False, "gray", "#f4f5f5"
    st.configure("Muted.TLabel", foreground=muted)
    st.configure("Ok.TLabel", foreground="#5fc27e" if dark else "#2e7d32")
    st.configure("Warn.TLabel", foreground="#f0a93c" if dark else "#b26a00")
    st.configure("Status.TLabel", foreground=muted, font="TkSmallCaptionFont")
    root.stripe_color = stripe
    widgets.retheme(root)                                       # подсказка пустого экрана и выпадающие списки главного окна
    tree = getattr(root, "tree", None)
    if tree is not None:
        tree.tag_configure("odd", background=stripe)              # чередование строк, как в Finder
    for t in list(getattr(root, "striped_trees", [])):            # и в других таблицах (например, список домов)
        try:
            t.tag_configure("odd", background=stripe)
        except tk.TclError:
            root.striped_trees.remove(t)                          # таблицу уже закрыли


def stripe_rows(tree: ttk.Treeview) -> None:
    """Чередование цвета строк таблицы, как в таблице должников: нечётные строки чуть темнее/светлее. Вызывается после любого
    изменения набора строк."""
    for i, item in enumerate(tree.get_children()):
        tree.item(item, tags=("odd",) if i % 2 else ())


def make_striped(tree: ttk.Treeview) -> None:
    """Включает чередование для таблицы: цвет берётся из темы и обновляется при её смене."""
    root = tree.nametowidget(".")
    tree.tag_configure("odd", background=getattr(root, "stripe_color", "#f4f5f5"))
    if not hasattr(root, "striped_trees"):
        root.striped_trees = []
    root.striped_trees.append(tree)
    stripe_rows(tree)


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
        self.restore_geometry()
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
        if _is_mac(self):
            self.createcommand("::tk::mac::OpenDocument", self._on_open_documents)     # файл брошен на значок программы / «Открыть в»
            self.createcommand("tk::mac::Quit", self.on_close)                           # ⌘Q сохраняет состояние
        self._startup_file = next((Path(a) for a in sys.argv[1:] if a.lower().endswith(STARTUP_FILE_EXT) and Path(a).is_file()), None)
        self._build_menubar()
        self.apply_table_font()
        self.update_hint()
        self.after(150, self.restore_last_state)          # прошлое состояние восстанавливаем, когда окно уже показано
        if FIRST_RUN and not self.settings.welcomed:
            self.after(500, lambda: WelcomeDialog(self))

    # ---------- интерфейс ----------
    def _build(self):
        pad = {"padx": 6, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Открыть Excel…", command=self.open_file).pack(side="left")
        self.recent_btn = ttk.Button(top, text="▾", width=2, command=self.show_recent_menu)
        self.recent_btn.pack(side="left", padx=(2, 0))
        Tooltip(self.recent_btn, "Последние файлы")
        self.file_lbl = ttk.Label(top, text="Файл не выбран", style="Muted.TLabel")
        self.file_lbl.pack(side="left", padx=(8, 2))
        self.kind_lbl = ttk.Label(top, text="", style="Muted.TLabel")
        self.kind_lbl.pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Лист:").pack(side="left", padx=(16, 2))
        self.sheet_cb = widgets.PopupSelect(top, None, [], chars=24,
                                            command=lambda: self.kind == "original" and self.load_sheet(self.sheet_cb.get()))
        self.sheet_cb.pack(side="left")
        # кнопка «Настройки» — шестерёнка в правом верхнем углу
        try:
            self._gear = tk.PhotoImage(file=str(resource_path("assets/gear.png")))
            self._gear_hover = tk.PhotoImage(file=str(resource_path("assets/gear_hover.png")))
            gear = ttk.Label(top, image=self._gear)
            gear.bind("<Enter>", lambda e: gear.configure(image=self._gear_hover), add="+")
            gear.bind("<Leave>", lambda e: gear.configure(image=self._gear), add="+")
        except tk.TclError:
            gear = ttk.Label(top, text="⚙", font=("", 18))
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.pack(side="right", padx=(0, 4))
        Tooltip(gear, "Настройки")

        orow = ttk.Frame(self)
        orow.pack(fill="x", **pad)
        ttk.Label(orow, text="Организация:").pack(side="left")
        self.org_cb = widgets.PopupSelect(orow, None, [], chars=34,
                                          command=lambda: (self.save_state(), self.refresh_card_flags()))
        self.org_cb.pack(side="left", padx=6)
        self.org_hint = ttk.Label(orow, text="", style="Muted.TLabel")
        self.org_hint.pack(side="left", padx=10)
        self.refresh_orgs()

        # значения настроек живут в переменных; окно «Настройки» лишь показывает их
        self.col_vars = {k: tk.StringVar() for k in COLUMN_FIELDS}
        self.col_options = {k: [] for k in COLUMN_FIELDS}
        self.top_n = tk.IntVar(value=self.settings.top_n)
        self.ip_as_person = tk.BooleanVar(value=self.settings.ip_as_person)
        self.skip_nonres = tk.BooleanVar(value=self.settings.skip_nonresidential)
        self.only_managed = tk.BooleanVar(value=self.settings.only_managed)
        self.duty_auto = tk.BooleanVar(value=self.settings.duty_auto)
        self.restore_var = tk.BooleanVar(value=self.settings.restore_state)
        self.auto_filter_var = tk.BooleanVar(value=self.settings.auto_filter)
        self.native_date_var = tk.BooleanVar(value=self.settings.native_datepicker)
        datepicker.USE_NATIVE = self.settings.native_datepicker
        self.font_var = tk.StringVar(value=FONT_LABELS.get(self.settings.table_font, FONT_LABELS["normal"]))
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
        self.docs_btn = ttk.Button(docs, text="Создать документы ▾", command=self.show_docs_menu, state="disabled")
        self.docs_btn.pack(side="left")

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
        ttk.Button(pick_bar, text="✕", width=2, command=lambda: self.search_var.set("")).pack(side="right")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(pick_bar, textvariable=self.search_var, width=26)
        self.search_entry.pack(side="right", padx=(0, 4))
        ttk.Label(pick_bar, text="Поиск:").pack(side="right", padx=(0, 4))
        self._search_job = None
        self.search_var.trace_add("write", lambda *_: self._schedule_search())
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
        size_cb = widgets.PopupSelect(pager, self.page_size_var, ("20", "50", "100", "200", "500"), width=4, chars=5,
                                      command=self.change_page_size)
        size_cb.pack(side="left", padx=(4, 0))

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True, **pad)
        self.table_frame = table
        self.hint_panel = tk.Frame(table, bd=0)                  # пустое состояние: закрывает таблицу, пока данных нет
        self.hint_panel.role = "field"
        inner = tk.Frame(self.hint_panel, bd=0)
        inner.role = "field"
        inner.place(relx=0.5, rely=0.5, anchor="center")
        head = tk.Label(inner, text="Что делать дальше", bd=0, font=("", 18, "bold"))
        head.role = "field-label"
        head.pack()
        head.pack_configure(pady=(0, 8))
        widgets.steps_list(inner, NEXT_STEPS).pack()
        widgets.retheme(self.hint_panel)
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
        self.order_all: list[int] = []
        self.card_flags: list[bool] = []
        self.court_flags: list[bool] = []
        self.visible_cols: list[str] = []
        self.num_cols: set[int] = set()
        self.manual_widths = False
        self.page = 0
        self._page_first = 0
        self.tree.bind("<Configure>", lambda e: self.fit_columns())
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", self.on_tree_space)
        self.tree.bind("<Double-Button-1>", self.on_tree_double)
        self._build_context_menu()
        self._bind_shortcuts()
        self._bind_table_extras()
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
        self.bind_all(f"<{mod}-f>", lambda e: (self.search_entry.focus_set(), self.search_entry.select_range(0, "end"), "break")[2])
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
        if self.tree.identify_region(event.x, event.y) == "heading":
            return self.show_header_menu(event)
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

    # ---------- ширина и видимость колонок, подсказка с полным текстом ячейки ----------
    def _bind_table_extras(self):
        self._press_region = ""
        self._cell_job, self._cell_tip, self._cell_key = None, None, None
        self.tree.bind("<ButtonPress-1>", lambda e: setattr(self, "_press_region", self.tree.identify_region(e.x, e.y)), add="+")
        self.tree.bind("<ButtonRelease-1>", self._after_drag, add="+")
        self.tree.bind("<Motion>", self._cell_hover, add="+")
        self.tree.bind("<Leave>", lambda e: self._hide_cell_tip(), add="+")
        self.tree.bind("<ButtonPress>", lambda e: self._hide_cell_tip(), add="+")
        self.tree.bind("<MouseWheel>", lambda e: self._hide_cell_tip(), add="+")

    def _after_drag(self, event):
        """Ширину колонки потянули мышью — запоминаем ширины всех колонок и больше не подгоняем их автоматически."""
        if self._press_region != "separator" or not self.cols:
            return
        self._press_region = ""
        widths = dict(self.settings.col_widths)
        for i, h in enumerate(self.cols):
            if not (self.has_checks and h in SERVICE_COLS) and f"c{i}" in self.visible_cols:
                widths[h] = int(self.tree.column(f"c{i}", "width"))
        self.settings.col_widths = widths
        self.manual_widths = True
        self.save_settings_now()

    def auto_widths(self):
        self.settings.col_widths = {}
        self.manual_widths = False
        for i, h in enumerate(self.cols):
            self.tree.column(f"c{i}", width=self.col_weights.get(f"c{i}", 130))
        self.fit_columns()
        self.save_settings_now()

    def _data_titles(self) -> list[str]:
        return [h for h in self.cols if not (self.has_checks and h in SERVICE_COLS)]

    def apply_hidden(self):
        hidden = set(self.settings.hidden_cols)
        self.visible_cols = [f"c{i}" for i, h in enumerate(self.cols)
                             if (self.has_checks and h in SERVICE_COLS) or h not in hidden]
        self.tree["displaycolumns"] = self.visible_cols or "#all"

    def toggle_column(self, title: str):
        hidden = set(self.settings.hidden_cols)
        hidden.symmetric_difference_update({title})
        self.settings.hidden_cols = sorted(hidden)
        self.apply_hidden()
        self.fit_columns()
        self.save_settings_now()

    def show_all_columns(self):
        self.settings.hidden_cols = []
        self.apply_hidden()
        self.fit_columns()
        self.save_settings_now()

    def show_header_menu(self, event):
        if not self.cols:
            return
        menu = tk.Menu(self, tearoff=0)
        hidden = set(self.settings.hidden_cols)
        self._col_vars = []
        for title in self._data_titles():
            var = tk.BooleanVar(value=title not in hidden)
            self._col_vars.append(var)
            menu.add_checkbutton(label=title, variable=var, command=lambda t=title: self.toggle_column(t))
        menu.add_separator()
        menu.add_command(label="Показать все колонки", command=self.show_all_columns)
        menu.add_command(label="Автоширина колонок", command=self.auto_widths)
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _cell_hover(self, event):
        key = (self.tree.identify_row(event.y), self.tree.identify_column(event.x))
        if key == self._cell_key:
            return
        self._hide_cell_tip()
        self._cell_key = key
        if self.tree.identify_region(event.x, event.y) == "cell" and key[0]:
            self._cell_job = self.after(500, lambda: self._show_cell_tip(key, event.x_root, event.y_root))

    def _show_cell_tip(self, key, x, y):
        self._cell_job = None
        item, col = key
        try:
            text = str(self.tree.set(item, col))
            width = int(self.tree.column(col, "width"))
        except tk.TclError:
            return
        if not text or tkfont.nametofont("TkDefaultFont").measure(text) + 14 <= width:
            return                                                  # текст помещается — подсказка не нужна
        self._cell_tip = make_tip(self, text)
        self._cell_tip.wm_geometry(f"+{x + 12}+{y + 16}")

    def _hide_cell_tip(self):
        if self._cell_job:
            self.after_cancel(self._cell_job)
            self._cell_job = None
        if self._cell_tip is not None:
            self._cell_tip.destroy()
            self._cell_tip = None
        self._cell_key = None

    def copy_rows(self):
        rows = ["\t".join(str(v) for v in self.tree.item(i, "values")[N_SERVICE if self.has_checks else 0:])
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
            ok = self.open_filtered(path, quiet)                # файл, сохранённый этой программой («Сохранить в Excel»)
            if ok:
                self.add_recent(path)
            return ok
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
        self.add_recent(path)
        if not quiet and not self._restoring:
            self.auto_filter()
        return True

    def auto_filter(self):
        """Включена настройка «Фильтровать при открытии файла» — сразу фильтруем только что открытый исходный отчёт.
        Если колонки ещё не выбраны, ничего не делаем (без окон): список просто загружен."""
        s = self.collect_settings()
        if s.auto_filter and self.kind == "original" and self.sheet and s.name_col and s.debt_col:
            self.run()

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
        self.docs_btn.config(state="disabled")
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
            storage.save_json(STATE_PATH, "state", {
                "file": str(self.path) if self.path else "", "sheet": self.sheet_cb.get(), "org": self.org_cb.get(),
                "filtered": bool(self.result), "unchecked": unchecked})
        except Exception:
            pass

    def restore_last_state(self):
        """При запуске: открыть прошлый файл, заново отфильтровать список и вернуть снятые галочки."""
        if self._startup_file:                                    # программу запустили с файлом — открываем его, а не прошлый
            self.open_path(self._startup_file)
            return
        if not self.settings.restore_state:
            return
        st = storage.load_json(STATE_PATH, "state")
        if not isinstance(st, dict):
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

    def destroy(self):
        job = getattr(self, "_search_job", None)
        if job:
            try:
                self.after_cancel(job)                               # отложенный поиск не должен сработать в закрытом окне
            except Exception:
                pass
        super().destroy()

    def on_close(self):
        self.save_state()
        try:
            self.settings.geometry = self.geometry()
            self.save_settings_now()
        except Exception:
            pass
        self.destroy()

    def restore_geometry(self):
        """Возвращает размер и положение окна с прошлого раза (если они помещаются на экран)."""
        m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.settings.geometry or "")
        if not m:
            return
        w, h, x, y = map(int, m.groups())
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = max(600, min(w, sw)), max(360, min(h, sh - 60))
        x, y = max(0, min(x, sw - 120)), max(0, min(y, sh - 120))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_open_documents(self, *paths):
        files = [p for p in paths if str(p).lower().endswith(STARTUP_FILE_EXT)]
        if files:
            self.after(100, lambda: self.open_path(Path(files[0])))

    # ---------- строка меню ----------
    def _build_menubar(self):
        """Строка меню по правилам платформы: на macOS меню приложения («О программе», «Настройки…» ⌘, и «Завершить»
        добавляет сама система), «Файл», «Правка»; на Windows — «Файл» (с «Настройки…» и «Выход»), «Правка», «Справка»."""
        mac = _is_mac(self)
        key = "⌘" if mac else "Ctrl+"
        bar = tk.Menu(self)
        if mac:
            apple = tk.Menu(bar, name="apple", tearoff=0)                              # меню приложения
            apple.add_command(label="О программе «Должники»", command=self.show_about)  # «Настройки…», «Скрыть», «Завершить» добавляет система
            bar.add_cascade(menu=apple)
            self.createcommand("tkAboutDialog", self.show_about)
            self.createcommand("::tk::mac::ShowPreferences", self.open_settings)
        file = tk.Menu(bar, tearoff=0)
        file.add_command(label="Открыть Excel…", accelerator=f"{key}O", command=self.open_file)
        recent = tk.Menu(file, tearoff=0, postcommand=lambda: self.fill_recent_menu(recent))
        file.add_cascade(label="Последние файлы", menu=recent)
        file.add_separator()
        file.add_command(label="Сохранить в Excel…", command=self.export)
        if not mac:
            file.add_separator()
            file.add_command(label="Настройки…", accelerator="Ctrl+,", command=self.open_settings)
            file.add_separator()
            file.add_command(label="Выход", accelerator="Alt+F4", command=self.on_close)
        bar.add_cascade(label="Файл", menu=file)
        edit = tk.Menu(bar, tearoff=0)
        for label, event, acc in (("Вырезать", "<<Cut>>", "X"), ("Копировать", "<<Copy>>", "C"), ("Вставить", "<<Paste>>", "V")):
            edit.add_command(label=label, accelerator=f"{key}{acc}", command=lambda e=event: self._edit_event(e))
        edit.add_separator()
        edit.add_command(label="Выделить всё", accelerator=f"{key}A", command=lambda: self._edit_event("<<SelectAll>>"))
        bar.add_cascade(label="Правка", menu=edit)
        if not mac:
            help_menu = tk.Menu(bar, tearoff=0)
            help_menu.add_command(label="О программе", command=self.show_about)
            bar.add_cascade(label="Справка", menu=help_menu)
        self.configure(menu=bar)

    def _edit_event(self, event: str) -> None:
        """Команды меню «Правка» действуют на элемент, где сейчас фокус (в таблице «Копировать» копирует строки)."""
        w = self.focus_get()
        if w is None:
            return
        if w is self.tree and event == "<<Copy>>":
            self.copy_rows()
        elif w is self.tree and event == "<<SelectAll>>":
            self.tree.selection_set(self.tree.get_children())
        else:
            w.event_generate(event)

    def show_about(self):
        try:
            from version import VERSION
        except ImportError:
            VERSION = "разработка"
        messagebox.showinfo("О программе «Должники»", f"Должники\nВерсия: {VERSION}\n\n"
                            "Поиск должников по отчёту ЕИРЦ и формирование документов.\n"
                            f"Данные хранятся на этом компьютере: {storage.DATA_DIR}")

    # ---------- последние файлы ----------
    def add_recent(self, path: Path):
        p = str(path)
        self.settings.recent_files = [p] + [r for r in self.settings.recent_files if r != p]
        self.settings.recent_files = self.settings.recent_files[:8]
        self.save_settings_now()

    def fill_recent_menu(self, menu: tk.Menu) -> None:
        menu.delete(0, "end")
        files = [f for f in self.settings.recent_files if Path(f).exists()]
        for f in files:
            menu.add_command(label=f"{Path(f).name}  —  {Path(f).parent}", command=lambda f=f: self.open_path(Path(f)))
        if not files:
            menu.add_command(label="Список пуст", state="disabled")
        else:
            menu.add_separator()
            menu.add_command(label="Очистить список", command=self.clear_recent)

    def show_recent_menu(self):
        menu = tk.Menu(self, tearoff=0)
        self.fill_recent_menu(menu)
        b = self.recent_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def clear_recent(self):
        self.settings.recent_files = []
        self.save_settings_now()

    # ---------- шрифт таблицы ----------
    TABLE_FONT_STEPS = {"normal": 0, "large": 2, "xlarge": 5}

    def apply_table_font(self):
        base = tkfont.nametofont("TkDefaultFont")
        font = tkfont.Font(family=base.actual("family"), size=int(base.actual("size")) + self.TABLE_FONT_STEPS.get(self.settings.table_font, 0))
        self._table_font = font                                  # ссылку держим, иначе Tk удалит шрифт
        st = ttk.Style(self)
        st.configure("Treeview", font=font, rowheight=font.metrics("linespace") + 6)

    # ---------- подсказка на пустом экране ----------
    def update_hint(self):
        empty = not self.data_rows
        if empty:
            self.hint_panel.place(in_=self.table_frame, x=0, y=0, relwidth=1, relheight=1)
            self.hint_panel.lift()
        else:
            self.hint_panel.place_forget()

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
        if st.get("дома не в управлении", 0) and st["дома не в управлении"] >= total - st.get("дома других организаций", 0) > 0:
            messagebox.showinfo("Пустой список", f"Включён отбор «Только дома в управлении», а все дома организации «{org.name}» из этого "
                                "отчёта сейчас не в управлении: у них не указана дата «В управлении с» или дом уже выбыл "
                                f"(строк отброшено: {st['дома не в управлении']}).\n\nУкажите даты в Настройки → Организации → Дома "
                                "или выключите отбор в настройках.")
            return
        parts = [f"{k}: {st[k]}" for k in ("дома не в управлении", "не физлица", "нежилые помещения", "без долга / сумма не распознана") if st.get(k)]
        messagebox.showinfo("Пустой список", "Под условия отбора не подошла ни одна строка.\n\n"
                            + (("Пропущено: " + "; ".join(parts) + ".\n\n") if parts else "")
                            + "Проверьте колонки в настройках (ФИО, «Сумма долга», «Адрес дома», «Квартира») и галочки отбора.")

    # ---------- организации ----------
    def refresh_orgs(self, keep=None):
        self.orgs = orgmod.load_orgs()
        names = [o.name for o in self.orgs]
        self.org_cb["values"] = names
        self.org_cb.set(keep if keep in names else names[0])

    def current_org(self) -> orgmod.Organization:
        return next((o for o in self.orgs if o.name == self.org_cb.get()), self.orgs[0])

    def open_settings(self):
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = SettingsDialog(self)

    def edit_orgs(self):
        OrgDialog(self, self.orgs, self.org_cb.get(), on_close=lambda name: self.refresh_orgs(name))

    # ---------- создание документов ----------
    DOC_KINDS = {
        "claims": "Претензии",
        "letter": "Письмо в ЕИРЦ",
        "court": "Заявления о судебном приказе",
    }

    def make_claims(self):
        self.create_docs("claims")

    def make_letter(self):
        self.create_docs("letter")

    def make_court(self):
        self.create_docs("court")

    def court_jobs(self, pick: list[int]) -> list[dict]:
        """По каждому отмеченному адресу: карточка и список дел (по одному на каждого собственника)."""
        jobs = []
        for k in pick:
            info = self.row_info(k)
            card = owners.get_card(info["address"], info["flat"]) or owners.get_or_new(info["address"], info["flat"])
            jobs.append({"k": k, "info": info, "card": card,
                         "cases": court.plan_cases(card, info["report_fio"], info["debt"])})
        return jobs

    def show_docs_menu(self):
        """Меню кнопки «Создать документы»: у каждого пункта — сколько документов получится."""
        pick = self.checked_indexes()
        n = len(pick)
        menu = tk.Menu(self, tearoff=0)
        try:
            n_court = sum(len(j["cases"]) for j in self.court_jobs(pick)) if (n and self.settings.addr_col
                                                                              and self.settings.flat_col) else 0
        except Exception:
            n_court = n
        menu.add_command(label=f"Претензии — {n}", command=self.make_claims)
        menu.add_command(label=f"Письмо в ЕИРЦ — 1 письмо, адресов: {n}", command=self.make_letter)
        menu.add_command(label=f"Заявления о судебном приказе — {n_court}", command=self.make_court)
        if not n:
            for i in range(3):
                menu.entryconfig(i, state="disabled")
        b = self.docs_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def check_problems(self, kind: str, pick: list[int]) -> tuple[str, list[tuple]]:
        """Что может оказаться незаполненным в документах: (краткая сводка, [(адрес, кв., проблема)])."""
        if kind != "court":
            return "", []
        rows, no_data, no_court = [], 0, 0
        for k in pick:
            miss = []
            if not self.card_flags[k]:
                no_data += 1
                miss.append("нет персональных данных")
            if not self.court_flags[k]:
                no_court += 1
                miss.append("нет участка")
            if miss:
                info = self.row_info(k)
                rows.append((info["address"], info["flat"], ", ".join(miss)))
        parts = []
        if no_data:
            parts.append(f"у {no_data} из {len(pick)} нет персональных данных")
        if no_court:
            parts.append(f"у {no_court} нет участка")
        return (", ".join(parts).capitalize() if parts else ""), rows

    def start_progress(self, title: str, total: int):
        return ProgressWindow(self, title, total) if total >= 3 else NoProgress()

    def finish_docs(self, title: str, text: str, folder: Path):
        """Итог создания; предлагает открыть папку с документами."""
        if messagebox.askyesno(title, f"{text}\n\nОткрыть папку?"):
            open_folder(folder)

    def create_docs(self, kind: str):
        if not self.result or not self.result.top:
            return
        s, org = self.settings, self.current_org()
        title = self.DOC_KINDS[kind]
        if not (s.addr_col and s.flat_col):
            messagebox.showinfo("Нет колонок", "Для документов выберите колонки «Адрес дома» и «Квартира» в настройках.")
            return
        if kind == "letter" and not org.letter_header.strip():
            messagebox.showinfo("Нет шапки", "Заполните вкладку «Письмо в ЕИРЦ» в настройках → «Организации…».")
            return
        pick = self.checked_indexes()
        if not pick:
            messagebox.showinfo(title, "Не отмечено ни одного адреса.")
            return
        jobs = self.court_jobs(pick) if kind == "court" else None
        if kind == "claims":
            count = f"Претензий: {len(pick)}"
        elif kind == "letter":
            count = f"Одно письмо, адресов в нём: {len(pick)}"
        else:
            count = f"Заявлений: {sum(len(j['cases']) for j in jobs)} (адресов: {len(pick)})"
        summary, rows = self.check_problems(kind, pick)
        dlg = DocsDialog(self, title, org.name, count, summary, rows, Path(s.out_dir) if s.out_dir else DEFAULT_OUT_DIR)
        self.wait_window(dlg)
        if not dlg.ok:
            return
        out = dlg.folder
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось создать папку:\n{out}\n{e}")
            return
        s.out_dir = str(out)
        self.save_settings_now()
        {"claims": self._gen_claims, "letter": self._gen_letter, "court": self._gen_court}[kind](org, pick, out, jobs)

    def _gen_claims(self, org, pick, out: Path, _jobs):
        s, h = self.settings, self.result.headers
        fi, ni = h.index(s.flat_col), h.index(s.name_col)
        today, made = date.today(), 0
        prog = self.start_progress("Претензии", len(pick))
        try:
            for n, k in enumerate(pick, 1):
                if prog.cancelled:
                    break
                row = self.result.top[k]
                addr, flat = orgmod.addr_flat(self.row_addr(row), row[fi])
                fn = f"{k + 1:02d} " + claim.file_name(row[ni], addr, flat)
                claim.build_claim(org, address=addr, flat=flat, debt=self.result.amounts[k],
                                  on_date=today, path=out / fn)
                made += 1
                prog.step(n, fn)
        except Exception as e:
            prog.close()
            messagebox.showerror("Ошибка", f"Сформировано {made}, затем ошибка:\n{e}")
            return
        prog.close()
        stopped = "\n(прервано пользователем)" if prog.cancelled else ""
        self.finish_docs("Готово", f"Претензий: {made}{stopped}\nОрганизация: {org.name}\nПапка: {out}", out)

    def _gen_letter(self, org, pick, out: Path, _jobs):
        s, h = self.settings, self.result.headers
        fi = h.index(s.flat_col)
        name = f"Письмо в ЕИРЦ {org.name}.docx".replace("«", "").replace("»", "").replace('"', "")
        path = out / name
        try:
            n = claim.build_letter(org, items=[orgmod.addr_flat(self.row_addr(self.result.top[k]), self.result.top[k][fi])
                                               for k in pick],
                                   on_date=date.today(), path=path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сформировать письмо:\n{e}")
            return
        self.finish_docs("Готово", f"Адресов в письме: {n}\nОрганизация: {org.name}\n{path}", out)

    def _gen_court(self, org, pick, out: Path, jobs):
        data = courtsmod.load()
        courts_list, batch_code = data["courts"], ""
        lacking = sum(1 for j in jobs if not orgmod.house_court(org, j["info"]["address"]))
        if courts_list and lacking:
            dlg = CourtChoiceDialog(self, courts_list, data["last"], lacking, len(pick))
            self.wait_window(dlg)
            if dlg.result is None:
                return
            batch_code = dlg.result
            if batch_code:
                courtsmod.save_last(batch_code)
        elif not courts_list:
            messagebox.showinfo("Судебные участки", "Список участков не загружен: в заявлениях поле суда останется пустым. "
                                "Загрузить список можно в настройках (шестерёнка → «Судебные участки»).")
        total = sum(len(j["cases"]) for j in jobs)
        n_known = n_unknown = no_card = no_court = multi = done = n_duty = 0
        prog = self.start_progress("Заявления о судебном приказе", total)
        try:
            for job in jobs:
                if prog.cancelled:
                    break
                k, info, card, cases = job["k"], job["info"], job["card"], job["cases"]
                if not self.card_flags[k] and owners.get_card(info["address"], info["flat"]) is None:
                    no_card += 1
                court_obj = (courtsmod.find_by_code(courts_list, orgmod.house_court(org, info["address"]))
                             or courtsmod.find_by_code(courts_list, batch_code))
                if len(cases) > 1:
                    multi += 1
                for j, case in enumerate(cases, 1):
                    if prog.cancelled:
                        break
                    who = case.owner.fio if case.owner else "собственник не известен"
                    num = f"{k + 1:02d}" + (f"-{j}" if len(cases) > 1 else "")
                    fn = f"{num} " + claim.safe_name(
                        f"Заявление о судебном приказе {who} {info['address']} кв {claim.clean_flat(info['flat'])}") + ".docx"
                    no_court += 0 if court_obj else 1
                    duty_val = None
                    if self.settings.duty_auto and case.debt is not None and not (card.duty or "").strip():
                        duty_val = duty.court_order_duty(case.debt + (case.penalty or 0), self.settings.duty_scale or None,
                                                         self.settings.duty_share)
                        n_duty += 1
                    if court.build_court_application(org, card, case, path=out / fn, court_obj=court_obj, duty=duty_val):
                        n_known += 1
                    else:
                        n_unknown += 1
                    done += 1
                    prog.step(done, fn)
        except Exception as e:
            prog.close()
            messagebox.showerror("Ошибка", f"Не удалось сформировать заявление:\n{e}")
            return
        prog.close()
        note = (f"\n\nДля {no_card} адресов карточка собственника не заполнена: ФИО взято из отчёта, а дата и место "
                "рождения, паспорт, пени, периоды остались пустыми (____). Заполните их в «Данные собственника…» "
                "или в Word.") if no_card else ""
        if multi:
            note += (f"\n\nПомещений с несколькими собственниками: {multi} — на каждого собственника сформировано "
                     "отдельное заявление (номера вида 05-1, 05-2).")
        if no_court:
            note += f"\n\nБез судебного участка (поле суда пустое): {no_court}."
        if n_duty:
            note += (f"\n\nГоспошлина рассчитана по ст. 333.19 НК РФ (50 % от пошлины по иску) в заявлениях: {n_duty}. "
                     "Проверьте ставки в Настройки → Госпошлина → «Таблица ставок…».")
        if prog.cancelled:
            note += "\n\nСоздание прервано пользователем."
        self.finish_docs("Готово", f"Заявлений: {n_known + n_unknown}\n"
                                   f"• с ФИО собственника: {n_known}\n• собственник неизвестен: {n_unknown}\n"
                                   f"Организация: {org.name}\nПапка: {out}{note}", out)

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
        self.all_var.set(bool(self.order) and all(self.check_state[i] for i in self.order) if self.has_checks else False)
        text = ""
        if self.has_checks:
            text = f"Отмечено адресов: {n} из {total}"
            if self.result and len(self.result.amounts) == total:
                text += f" · долг отмеченных: {fmt_money(sum(a for a, on in zip(self.result.amounts, self.check_state) if on))}"
        self.pick_lbl.config(text=text)
        if hasattr(self, "docs_btn"):
            self.docs_btn.config(text=f"Создать документы ({n}) ▾" if (self.has_checks and n) else "Создать документы ▾")
        self.save_state()

    def toggle_all(self):
        if not self.has_checks:
            return
        for i in self.order:                                                  # все страницы сразу, но только найденные строки
            self.check_state[i] = self.all_var.get()
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
        for b in (self.export_btn, self.docs_btn):
            b.config(state="disabled")
        self.filter_btn.config(text="Фильтровать")
        self.save_state()

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

    def edit_markers(self):
        win = Dialog(self)
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
            if not self.sheet:                                     # файл не открыт — выбранные раньше колонки не затираем
                break
            v = var.get()
            setattr(s, key, None if v in ("", NONE) else v)
        try:
            s.top_n = max(1, int(self.top_n.get()))
        except (tk.TclError, ValueError):
            s.top_n = 20
        s.ip_as_person = self.ip_as_person.get()
        s.skip_nonresidential = self.skip_nonres.get()
        s.only_managed = self.only_managed.get()
        s.duty_auto = self.duty_auto.get()
        s.restore_state = self.restore_var.get()
        s.auto_filter = self.auto_filter_var.get()
        s.native_datepicker = self.native_date_var.get()
        datepicker.USE_NATIVE = s.native_datepicker
        s.table_font = next((k for k, v in FONT_LABELS.items() if v == self.font_var.get()), "normal")
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
            f"Организация: {self.current_org().name} · строк: {st['всего строк']} · "
            + (f"не в управлении: {st['дома не в управлении']} · " if st.get("дома не в управлении") else "")
            + f"физлиц с долгом: {st['физлиц с долгом']} · "
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
            self._mark_sort(f"c{self.result.headers.index(sort_col) + N_SERVICE}", sort_desc)      # перед данными — служебные колонки
        else:
            self._mark_sort("c1", False)
        state = "normal" if self.result.top else "disabled"
        for b in (self.export_btn, self.docs_btn):
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
        self.cols = (list(SERVICE_COLS) if numbered else []) + list(headers)
        self.has_checks = numbered
        self.data_rows = [["" if v is None else v for v in r] for r in rows]
        self.check_state = [True] * len(rows) if numbered else []
        self.order_all = list(range(len(rows)))                  # порядок после сортировки кликом (без учёта поиска)
        self.order = list(self.order_all)                         # то, что показано: порядок + поиск
        self.haystack = [" ".join(str(v) for v in r).lower() for r in self.data_rows]
        self.view_sort = None
        self.page = 0
        self.search_var.set("")
        self.compute_card_flags()
        debt = self.settings.debt_col
        nser = N_SERVICE if numbered else 0
        self.num_cols = {j for j in range(len(headers))
                         if headers[j] == debt or any(isinstance(r[j], float) for r in self.data_rows)}
        self.col_titles = {f"c{i}": h for i, h in enumerate(self.cols)}
        self.tree["displaycolumns"] = "#all"                     # иначе Tk держит ссылки на старые колонки и падает
        self.tree["columns"] = [f"c{i}" for i in range(len(self.cols))]
        saved = self.settings.col_widths
        self.manual_widths = False
        for i, h in enumerate(self.cols):
            service = numbered and h in SERVICE_COLS
            self.tree.heading(f"c{i}", text=h, command=lambda c=f"c{i}": self.sort_view(c))
            width = SERVICE_COLS[h] if service else col_width(h)
            if not service and h in saved:
                width, self.manual_widths = int(saved[h]), True
            anchor = "center" if service else ("e" if i - nser in self.num_cols else "w")
            self.tree.column(f"c{i}", width=width, minwidth=36 if service else 50, stretch=False, anchor=anchor)
        self.col_weights = {f"c{i}": SERVICE_COLS[h] if (numbered and h in SERVICE_COLS) else col_width(h)
                            for i, h in enumerate(self.cols)}
        self.fixed_cols = {f"c{i}" for i, h in enumerate(self.cols) if numbered and h in SERVICE_COLS}
        self.all_cb.config(state="normal" if numbered and rows else "disabled")
        self.apply_hidden()
        self.fit_columns()
        self.render_page()
        self.update_hint()

    def fit_columns(self):
        """Ширина колонок подгоняется под ширину окна пропорционально их «весу», поэтому таблица
        помещается без горизонтальной прокрутки (узкие служебные колонки не сжимаются).
        Если ширину колонок задали мышью — она сохраняется, автоподгонка не применяется."""
        weights = getattr(self, "col_weights", None)
        if not weights or getattr(self, "manual_widths", False):
            return
        avail = self.tree.winfo_width() - 6
        if avail < 200:                                         # окно ещё не показано
            return
        shown = set(getattr(self, "visible_cols", weights))
        fixed = sum(w for c, w in weights.items() if c in self.fixed_cols and c in shown)
        flex = {c: w for c, w in weights.items() if c not in self.fixed_cols and c in shown}
        total = sum(flex.values()) or 1
        room = max(avail - fixed, 50 * len(flex))
        for c, w in flex.items():
            self.tree.column(c, width=max(50, int(room * w / total)))

    def fmt_cell(self, j: int, v):
        """Числа с копейками показываются одинаково: 1 234,50 (в данных остаются числа — сортировка не страдает)."""
        if j in self.num_cols and isinstance(v, (int, float)) and not isinstance(v, bool):
            return fmt_money(float(v))
        return v

    # --- поиск ---
    def _schedule_search(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(200, self.apply_search)

    def apply_search(self):
        """Оставляет в таблице только строки, где встречается введённый текст (по всем колонкам, без учёта регистра)."""
        self._search_job = None
        q = self.search_var.get().strip().lower()
        self.order = [i for i in self.order_all if q in self.haystack[i]] if q else list(self.order_all)
        self.page = 0
        self.render_page()

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

    def change_table_font(self):
        self.settings.table_font = self.collect_settings().table_font
        self.apply_table_font()
        self.save_settings_now()

    def change_theme(self):
        """Тема выбрана в настройках: применяется сразу и запоминается."""
        self.settings.theme = self.collect_settings().theme
        apply_theme(self, self.settings.theme)
        self.save_settings_now()
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None:
            self.update_idletasks()
            widgets.retheme(dlg)                                  # карточки настроек перекрашиваются в новую тему

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
            vals = self.service_values(idx) + [self.fmt_cell(j, v) for j, v in enumerate(self.data_rows[idx])]
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

    def service_values(self, idx: int) -> list:
        if not self.has_checks:
            return []
        return [("☑" if self.check_state[idx] else "☐"), idx + 1,
                "✓" if self.card_flags[idx] else "", "✓" if self.court_flags[idx] else ""]

    def compute_card_flags(self):
        """Для каждой строки результата: есть ли карточка с персональными данными собственника."""
        n = len(self.data_rows) if self.has_checks else 0
        self.card_flags = [False] * n
        self.court_flags = [False] * n                    # известен ли судебный участок (в карточке или за домом)
        if not (n and self.result and self.result.top and self.settings.addr_col and self.settings.flat_col):
            return
        cards, org = owners._load_all(), self.current_org()
        for idx in range(min(n, len(self.result.top))):
            info = self.row_info(idx)
            d = cards.get(owners.make_key(info["address"], info["flat"]))
            if d:
                card = owners._from_dict(d)
                self.card_flags[idx] = any(getattr(o, k).strip() for o in card.owners for k in owners.OWNER_FIELDS)
            self.court_flags[idx] = bool(orgmod.house_court(org, info["address"]))

    def refresh_card_flags(self):
        """Карточки, дома или организация могли измениться — обновляем колонки «Данные» и «Участок» на видимой странице."""
        if not self.has_checks:
            return
        self.compute_card_flags()
        for item, idx in self.item_index.items():
            vals = list(self.tree.item(item, "values"))
            vals[:N_SERVICE] = self.service_values(idx)
            self.tree.item(item, values=vals)

    def sort_view(self, colid: str):
        """Сортировка таблицы кликом по заголовку — по всему списку, а не только по видимой странице.
        Первый клик — по возрастанию, повторный — по убыванию. Меняет только порядок показа;
        какие должники отобраны — определяет «Сортировать по» в настройках."""
        if not self.order_all:
            return
        ci = int(colid[1:])
        j = ci - (N_SERVICE if self.has_checks else 0)                    # позиция в data_rows
        if self.has_checks and ci == 0:
            getter = lambda idx: 1 if self.check_state[idx] else 0
        elif self.has_checks and ci == 1:
            getter = lambda idx: idx + 1
        elif self.has_checks and ci == 2:
            getter = lambda idx: 1 if self.card_flags[idx] else 0
        elif self.has_checks and ci == 3:
            getter = lambda idx: 1 if self.court_flags[idx] else 0
        else:
            getter = lambda idx: self.data_rows[idx][j]
        desc = bool(self.view_sort and self.view_sort[0] == colid and not self.view_sort[1])
        self.order_all = core.sort_by_values(list(self.order_all), getter, desc)
        self.apply_search()
        self._mark_sort(colid, desc)

    def _mark_sort(self, colid: str, desc: bool):
        """Стрелка в заголовке колонки, по которой отсортирован список (▲ по возрастанию, ▼ по убыванию)."""
        self.view_sort = (colid, desc)
        for cid, title in self.col_titles.items():
            self.tree.heading(cid, text=title + (("  ▼" if desc else "  ▲") if cid == colid else ""))


NEXT_STEPS = (
    ("Откройте файл отчёта", "Кнопка «Открыть Excel…» (⌘O / Ctrl+O) или перетащите файл на значок программы."),
    ("Проверьте организацию и колонки", "Шестерёнка → «Настройки» и «Организации» (дома, шапки, участки)."),
    ("Нажмите «Фильтровать»", "Останутся физлица с наибольшим долгом."),
    ("Заполните данные собственников", "Двойной клик по строке. Галка в колонке «Данные» — карточка заполнена."),
    ("Создайте документы", "Претензии, письмо в ЕИРЦ и заявления о судебном приказе."),
)

SERVICE_COLS = {"✓": 36, "№": 46, "Данные": 64, "Участок": 70}      # служебные колонки таблицы результата и их ширина
N_SERVICE = len(SERVICE_COLS)

COLUMN_FIELDS = {
    "name_col": "ФИО *",
    "debt_col": "Сумма долга *",
    "addr_col": "Адрес дома (или улица)",
    "house_col": "Номер дома (если в отдельной колонке)",
    "flat_col": "Квартира",
}
OPTIONAL_COLUMNS = ("addr_col", "house_col", "flat_col")


class SettingsDialog(Dialog):
    """Экран настроек: колонки файла, число должников, правила отбора."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Настройки")
        self.transient(app)
        if _is_mac(app):                                           # тема окна — до построения, чтобы цвета блоков считались верно
            set_window_appearance(app, self, app.settings.theme)

        # прокручиваемая форма из блоков-карточек в стиле системных настроек
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=(16, 0), pady=(0, 0))
        canvas = tk.Canvas(outer, highlightthickness=0, width=1060)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        make_autoscroll(canvas, body, sb)
        canvas._wheel_scrollable = True
        pad_r = ttk.Frame(body)                               # отступ справа от полосы прокрутки
        pad_r.pack(fill="both", expand=True, padx=(0, 14))
        body = pad_r
        left = ttk.Frame(body)                                # блоки в два столбца: окно не вытягивается по вертикали
        right = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="new", padx=(0, 8))
        right.grid(row=0, column=1, sticky="new", padx=(8, 0))
        body.columnconfigure(0, weight=1, uniform="cols")
        body.columnconfigure(1, weight=1, uniform="cols")

        cols = widgets.section(left, "Колонки файла", pady=(8, 0))
        for key, text in COLUMN_FIELDS.items():
            widgets.PopupSelect(cols.row(text), app.col_vars[key], app.col_options[key] or [""]).pack()

        rules = widgets.section(right, "Отбор", pady=(8, 0))
        ttk.Spinbox(rules.row("Показать должников"), from_=1, to=100000, textvariable=app.top_n, width=7).pack()
        widgets.Switch(rules.row("ИП считать физлицами"), app.ip_as_person).pack()
        widgets.Switch(rules.row("Пропускать нежилые помещения"), app.skip_nonres).pack()
        widgets.Switch(rules.row("Только дома в управлении"), app.only_managed).pack()
        widgets.Switch(rules.row("Фильтровать при открытии файла"), app.auto_filter_var).pack()
        widgets.Switch(rules.row("Запоминать состояние при запуске"), app.restore_var).pack()
        widgets.PopupSelect(rules.row("Сортировать по"), app.sort_var, app.sort_options).pack()
        widgets.PopupSelect(rules.row("Порядок"), app.sort_dir_var, [DESC_LABEL, ASC_LABEL]).pack()
        ttk.Button(rules.row("Признаки организаций"), text="Изменить…", command=app.edit_markers).pack()

        look = widgets.section(left, "Внешний вид")
        widgets.PopupSelect(look.row("Тема"), app.theme_var, list(THEME_LABELS.values()), command=app.change_theme).pack()
        widgets.PopupSelect(look.row("Шрифт таблицы"), app.font_var, list(FONT_LABELS.values()),
                            command=app.change_table_font).pack()
        if native_date.available():
            widgets.Switch(look.row("Системный календарь"), app.native_date_var, command=app.save_settings_now).pack()

        dty = widgets.section(left, "Госпошлина")
        widgets.Switch(dty.row("Рассчитывать по НК РФ"), app.duty_auto).pack()
        ttk.Button(dty.row("Ставки и проверка расчёта"), text="Таблица ставок…", command=self.edit_duty).pack()

        orgs = widgets.section(left, "Организации")
        ttk.Button(orgs.row("Список организаций"), text="Открыть…", command=app.edit_orgs).pack()

        cf = widgets.section(right, "Судебные участки")
        self.regions = tk.StringVar(value=courtsmod.load()["regions"])                  # код(ы) региона — именно он хранится
        reg_right = cf.row("Регионы")
        ttk.Button(reg_right, text="Выбрать…", command=self.choose_regions).pack(side="right")
        self.region_lbl = tk.Label(reg_right, text=courtsmod.regions_summary(self.regions.get()), bd=0)
        self.region_lbl.role = "label"
        self.region_lbl.pack(side="right", padx=(0, 8))
        loaded = cf.row("Загружено")
        self.courts_lbl = tk.Label(loaded, text="", bd=0)
        self.courts_lbl.role = "muted"
        self.courts_lbl.pack()
        ttk.Button(cf.row("Список с sudrf.ru"), text="Загрузить", command=self.load_courts).pack()
        ttk.Button(cf.row("Судьи и адреса участков"), text="Изменить…", command=self.edit_courts).pack()
        dbox = widgets.section(right, "Данные")
        ttk.Button(dbox.row("Экспорт данных"), text="Экспорт…", command=self.export_data).pack()
        ttk.Button(dbox.row("Импорт данных"), text="Импорт…", command=self.import_data).pack()

        self.show_courts_info()
        widgets.retheme(self)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=16, pady=12)
        ttk.Button(btns, text="Готово", command=self.close, default="active").pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Return>", lambda e: self.close())
        self.bind("<Escape>", lambda e: self.close())
        self.update_idletasks()
        h = min(canvas.bbox("all")[3] + 70, self.winfo_screenheight() - 140)
        self.geometry(f"1100x{h}")
        self.resizable(False, True)
        app.settings_dialog = self
        center_over(self, app)

    def destroy(self):
        self.app.settings_dialog = None
        super().destroy()

    def edit_duty(self):
        DutyScaleDialog(self)

    def export_data(self):
        if not messagebox.askokcancel("Экспорт данных", "В файл попадут персональные данные собственников. "
                                      "Храните и передавайте его только защищённым способом. Продолжить?", parent=self):
            return
        p = filedialog.asksaveasfilename(parent=self, defaultextension=".zip", filetypes=[("Архив", "*.zip")],
                                         initialfile=f"Должники-данные-{date.today():%Y-%m-%d}.zip")
        if not p:
            return
        try:
            self.app.save_settings_now()
            names = storage.export_data(p)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}", parent=self)
            return
        messagebox.showinfo("Готово", f"Файлов в архиве: {len(names)}\n{p}", parent=self)

    def import_data(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("Архив", "*.zip")], title="Файл с данными программы")
        if not p:
            return
        if not messagebox.askokcancel("Импорт данных", "Текущие настройки, организации, участки и карточки будут заменены "
                                      "данными из файла. Копия текущих данных сохранится в папке backups внутри "
                                      "~/.debtors. Продолжить?", parent=self):
            return
        try:
            names = storage.import_data(p)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить данные:\n{e}", parent=self)
            return
        messagebox.showinfo("Готово", f"Загружено файлов: {len(names)}. Приложение будет закрыто — запустите его снова.",
                            parent=self)
        self.app.destroy()                                        # без сохранения: иначе старые настройки затрут загруженные

    def show_courts_info(self):
        d = courtsmod.load()
        self.courts_lbl.config(text=(f"Загружено участков: {len(d['courts'])} (обновлено {d['updated']})"
                                     if d["courts"] else "Список участков не загружен."))

    def edit_courts(self):
        if not courtsmod.load()["courts"]:
            messagebox.showinfo("Судебные участки", "Сначала загрузите список участков кнопкой слева.", parent=self)
            return
        CourtsEditorDialog(self)

    def choose_regions(self):
        RegionsDialog(self)

    def regions_chosen(self, codes: list[str]):
        """Выбраны регионы: запоминаем коды сразу и обновляем подпись."""
        value = ", ".join(codes)
        self.regions.set(value)
        courtsmod.set_regions(value)
        self.region_lbl.config(text=courtsmod.regions_summary(value))

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
        missing = courtsmod.missing_regions(courts_list, self.regions.get())
        note = ("\n\nВ списке sudrf.ru нет участков для: " + "; ".join(missing) + ". Для них участки нужно будет добавить другим способом.") \
            if missing else ""
        messagebox.showinfo("Судебные участки", f"Загружено участков: {len(courts_list)}.{note}", parent=self)

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


class CourtEditDialog(Dialog):
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
        pack_ok_cancel(ttk.Button(btns, text="Сохранить", command=self.save), ttk.Button(btns, text="Отмена", command=self.destroy))
        self.bind("<Escape>", lambda e: self.destroy())
        center_over(self, parent.winfo_toplevel())

    def save(self):
        courtsmod.set_override(self.court.code, self.judge.get(), self.address.get())
        self.destroy()
        self.on_done()


class CourtsEditorDialog(Dialog):
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
        self.parent_app = getattr(parent, "app", parent)       # окно открывается из «Настроек», у которых главное окно в .app
        self.query = tk.StringVar(value=self.parent_app.settings.courts_query)      # прошлый поиск запоминается
        self.query_entry = ttk.Entry(top, textvariable=self.query)
        self.query_entry.pack(side="left", fill="x", expand=True, padx=6)
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
        self.query_entry.focus_set()
        self.query_entry.select_range(0, "end")                  # прошлый запрос выделен: можно сразу печатать новый

    def destroy(self):
        try:
            self.parent_app.settings.courts_query = self.query.get()
            self.parent_app.save_settings_now()
        except Exception:
            pass
        super().destroy()

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


DEFAULT_OUT_DIR = Path.home() / "Documents" / "Должники"      # куда складываются документы, пока папка не выбрана


def open_folder(path: Path) -> None:
    """Открывает папку в Finder / Проводнике."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("win"):
            os.startfile(str(path))                         # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def _num(text: str) -> float:
    return float(str(text).replace(" ", "").replace("\u00a0", "").replace(",", "."))


class RegionsDialog(Dialog):
    """Выбор регионов (можно несколько): в списке название, хранятся коды."""

    def __init__(self, parent: "SettingsDialog"):
        super().__init__(parent)
        self.parent_dlg = parent
        self.title("Регионы")
        self.transient(parent)
        if _is_mac(parent.app):
            set_window_appearance(parent.app, self, parent.app.settings.theme)
        self.chosen = {c for c in courtsmod.region_codes(parent.regions.get()) if c in courtsmod.REGIONS}
        self.codes = sorted(courtsmod.REGIONS, key=lambda c: courtsmod.REGIONS[c])
        self.shown: list[str] = []
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Label(top, text="Поиск:").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        self.query.trace_add("write", lambda *a: self.refresh())
        box = ttk.Frame(body)
        box.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(box, columns=("mark", "name", "code"), show="headings", height=14, selectmode="browse")
        for c, text, w, anchor in (("mark", "", 34, "center"), ("name", "Регион", 380, "w"), ("code", "Код", 60, "center")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=c == "name")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<space>", lambda e: (self.toggle_selected(), "break")[1])
        self.count_lbl = ttk.Label(body, text="", style="Muted.TLabel")
        self.count_lbl.pack(anchor="w")
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        pack_ok_cancel(ttk.Button(btns, text="Сохранить", command=self.save), ttk.Button(btns, text="Отмена", command=self.destroy))
        ttk.Button(btns, text="Снять все", command=self.clear).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        center_over(self, parent)
        entry.focus_set()

    def refresh(self):
        q = self.query.get().strip().lower()
        self.shown = [c for c in self.codes if not q or q in courtsmod.REGIONS[c].lower() or q in c]
        self.tree.delete(*self.tree.get_children())
        for c in self.shown:
            self.tree.insert("", "end", iid=c, values=("☑" if c in self.chosen else "☐", courtsmod.REGIONS[c], c))
        self.count_lbl.config(text=f"Выбрано регионов: {len(self.chosen)}")

    def _toggle(self, code: str):
        self.chosen.symmetric_difference_update({code})
        self.tree.item(code, values=("☑" if code in self.chosen else "☐", courtsmod.REGIONS[code], code))
        self.count_lbl.config(text=f"Выбрано регионов: {len(self.chosen)}")

    def on_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell":
            item = self.tree.identify_row(event.y)
            if item:
                self._toggle(item)
                return "break"

    def toggle_selected(self):
        for item in self.tree.selection():
            self._toggle(item)

    def clear(self):
        self.chosen.clear()
        self.refresh()

    def save(self):
        if not self.chosen:
            messagebox.showinfo("Регионы", "Выберите хотя бы один регион.", parent=self)
            return
        self.parent_dlg.regions_chosen(sorted(self.chosen))
        self.destroy()


class DutyScaleDialog(Dialog):
    """Таблица ставок госпошлины (ст. 333.19 НК РФ), доля для судебного приказа и проверка расчёта на примере."""

    def __init__(self, parent: "SettingsDialog"):
        super().__init__(parent)
        self.app = parent.app
        self.title("Госпошлина")
        self.transient(parent)
        if _is_mac(self.app):
            set_window_appearance(self.app, self, self.app.settings.theme)
        s = self.app.settings
        self.scale = [dict(r) for r in (s.duty_scale or duty.DEFAULT_SCALE)]
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Иск имущественного характера: пошлина = базовая сумма + процент от суммы свыше порога. "
                             "Последняя строка без границы цены.", wraplength=640, justify="left").pack(anchor="w")
        box = ttk.Frame(body)
        box.pack(fill="both", expand=True, pady=(8, 6))
        self.tree = ttk.Treeview(box, columns=("up_to", "base", "rate", "over"), show="headings", height=10, selectmode="browse")
        for c, text, w in (("up_to", "Цена иска до, руб.", 150), ("base", "Базовая сумма, руб.", 150),
                           ("rate", "% с суммы свыше", 120), ("over", "Порог «свыше», руб.", 150)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.vars = [tk.StringVar() for _ in range(4)]
        for v in self.vars:
            ttk.Entry(row, textvariable=v, width=14).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Добавить / обновить", command=self.upsert).pack(side="left")
        ttk.Button(row, text="Удалить", command=self.remove).pack(side="left", padx=6)
        srow = ttk.Frame(body)
        srow.pack(fill="x", pady=(10, 0))
        ttk.Label(srow, text="Судебный приказ, % от пошлины по иску:").pack(side="left")
        self.share = tk.StringVar(value=f"{s.duty_share:g}")
        ttk.Entry(srow, textvariable=self.share, width=7).pack(side="left", padx=6)
        crow = ttk.Frame(body)
        crow.pack(fill="x", pady=(10, 0))
        ttk.Label(crow, text="Проверка. Цена требования, руб.:").pack(side="left")
        self.price = tk.StringVar()
        ttk.Entry(crow, textvariable=self.price, width=14).pack(side="left", padx=6)
        self.price.trace_add("write", lambda *a: self.check())
        self.check_lbl = ttk.Label(body, text="", style="Muted.TLabel", wraplength=640, justify="left")
        self.check_lbl.pack(anchor="w", pady=(4, 0))
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        pack_ok_cancel(ttk.Button(btns, text="Сохранить", command=self.save), ttk.Button(btns, text="Отмена", command=self.destroy))
        ttk.Button(btns, text="Сбросить к НК РФ", command=self.reset).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        center_over(self, parent)

    @staticmethod
    def _fmt(v) -> str:
        return "" if v in (None, "") else f"{float(v):,.2f}".replace(",", " ").replace(".00", "")

    def refresh(self):
        self.scale.sort(key=lambda r: (r.get("up_to") in (None, ""), float(r.get("up_to") or 0)))
        self.tree.delete(*self.tree.get_children())
        for r in self.scale:
            up = self._fmt(r.get("up_to")) or "без границы"
            self.tree.insert("", "end", values=(up, self._fmt(r["base"]), f"{float(r.get('rate') or 0):g}", self._fmt(r.get("over") or 0)))
        self.check()

    def load_selected(self):
        sel = self.tree.selection()
        if sel:
            r = self.scale[self.tree.index(sel[0])]
            for v, val in zip(self.vars, (r.get("up_to"), r["base"], r.get("rate") or 0, r.get("over") or 0)):
                v.set("" if val in (None, "") else f"{float(val):g}")

    def upsert(self):
        try:
            up = self.vars[0].get().strip()
            row = {"up_to": _num(up) if up else None, "base": _num(self.vars[1].get()),
                   "rate": _num(self.vars[2].get() or 0), "over": _num(self.vars[3].get() or 0)}
        except ValueError:
            messagebox.showinfo("Госпошлина", "Введите числа (разделитель — запятая или точка).", parent=self)
            return
        sel = self.tree.selection()
        if sel:
            self.scale[self.tree.index(sel[0])] = row
        else:
            self.scale.append(row)
        self.refresh()

    def remove(self):
        sel = self.tree.selection()
        if sel and len(self.scale) > 1:
            del self.scale[self.tree.index(sel[0])]
            self.refresh()

    def reset(self):
        self.scale = [dict(r) for r in duty.DEFAULT_SCALE]
        self.share.set(f"{duty.DEFAULT_SHARE:g}")
        self.refresh()

    def _valid(self):
        """Таблица пригодна для расчёта: есть строка без границы цены (и только последняя)."""
        if not self.scale or self.scale[-1].get("up_to") not in (None, "") or any(
                r.get("up_to") in (None, "") for r in self.scale[:-1]):
            return False
        return True

    def check(self):
        try:
            price = _num(self.price.get())
            share = _num(self.share.get() or duty.DEFAULT_SHARE)
        except ValueError:
            self.check_lbl.config(text="")
            return
        self.check_lbl.config(text=duty.explain(price, self.scale, share) if self._valid() else
                              "В таблице нужна последняя строка без границы цены.")

    def save(self):
        try:
            share = _num(self.share.get())
        except ValueError:
            messagebox.showinfo("Госпошлина", "Укажите процент для судебного приказа числом.", parent=self)
            return
        if not self._valid():
            messagebox.showinfo("Госпошлина", "Последняя строка таблицы должна быть без границы цены (одна такая строка).", parent=self)
            return
        s = self.app.settings
        s.duty_scale = [] if self.scale == duty.DEFAULT_SCALE else self.scale
        s.duty_share = share
        self.app.save_settings_now()
        self.destroy()


class WelcomeDialog(Dialog):
    """Приветствие при первом запуске: коротко о том, как работать с программой."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Добро пожаловать")
        self.transient(app)
        if _is_mac(app):
            set_window_appearance(app, self, app.settings.theme)
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Должники", font=("", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="Поиск должников по отчёту ЕИРЦ и формирование документов для их взыскания.",
                  wraplength=560, justify="left").pack(anchor="w", pady=(2, 10))
        widgets.steps_list(body, NEXT_STEPS, surface="window", wrap=480).pack(anchor="w")
        widgets.retheme(body)
        ttk.Label(body, text="Все данные хранятся только на этом компьютере, в папке ~/.debtors.",
                  style="Muted.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(10, 0))
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Открыть Excel…", command=lambda: self.finish(app.open_file)).pack(side="right")
        ttk.Button(btns, text="Настроить организации…", command=lambda: self.finish(app.edit_orgs)).pack(side="right", padx=6)
        ttk.Button(btns, text="Позже", command=lambda: self.finish(None)).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", lambda: self.finish(None))
        center_over(self, app)

    def finish(self, then):
        self.app.settings.welcomed = True
        self.app.save_settings_now()
        self.destroy()
        if then:
            self.app.after(100, then)


class NoProgress:
    """Для небольшого числа документов окно прогресса не нужно."""
    cancelled = False

    def step(self, n: int, text: str = "") -> None:
        pass

    def close(self) -> None:
        pass


class ProgressWindow(Dialog):
    """Индикатор выполнения при создании большого числа документов; можно прервать."""

    def __init__(self, app: "App", title: str, total: int):
        super().__init__(app)
        self.title(title)
        self.transient(app)
        self.resizable(False, False)
        self.total, self.cancelled = total, False
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.lbl = ttk.Label(body, text=f"0 из {total}", width=60)
        self.lbl.pack(anchor="w")
        self.bar = ttk.Progressbar(body, maximum=total, length=420)
        self.bar.pack(fill="x", pady=8)
        ttk.Button(body, text="Прервать", command=self.cancel).pack(anchor="e")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        center_over(self, app)
        self.update()

    def cancel(self):
        self.cancelled = True
        self.lbl.config(text="Прерываю после текущего документа…")

    def step(self, n: int, text: str = "") -> None:
        self.bar["value"] = n
        short = text if len(text) < 58 else text[:55] + "…"
        self.lbl.config(text=f"{n} из {self.total}: {short}")
        self.update()

    def close(self) -> None:
        self.destroy()


class DocsDialog(Dialog):
    """Подтверждение перед созданием документов: сколько будет создано, что не заполнено и в какую папку сохранить."""

    def __init__(self, app: "App", title: str, org_name: str, count: str, summary: str, rows: list[tuple], folder: Path):
        super().__init__(app)
        self.title(title)
        self.transient(app)
        self.ok, self.folder = False, folder
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(body, text=f"{count}\nОрганизация: {org_name}", justify="left").pack(anchor="w", pady=(4, 8))
        if rows:
            ttk.Label(body, text=summary + ". Документы всё равно будут созданы, недостающие поля останутся пустыми (____).",
                      style="Warn.TLabel", wraplength=640, justify="left").pack(anchor="w")
            box = ttk.Frame(body)
            box.pack(fill="both", expand=True, pady=(4, 8))
            tree = ttk.Treeview(box, columns=("addr", "flat", "what"), show="headings", height=min(8, len(rows)))
            for c, text, w in (("addr", "Адрес", 240), ("flat", "Кв.", 60), ("what", "Чего не хватает", 320)):
                tree.heading(c, text=text)
                tree.column(c, width=w, stretch=c == "what")
            for r in rows:
                tree.insert("", "end", values=r)
            sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            tree.pack(side="left", fill="both", expand=True)
            sb.pack(side="left", fill="y")
        frow = ttk.Frame(body)
        frow.pack(fill="x", pady=(4, 0))
        ttk.Label(frow, text="Папка:").pack(side="left")
        self.folder_lbl = ttk.Label(frow, text=str(folder), wraplength=470, justify="left")
        self.folder_lbl.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(frow, text="Изменить…", command=self.choose).pack(side="right")
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        pack_ok_cancel(ttk.Button(btns, text="Создать", command=self.accept), ttk.Button(btns, text="Отмена", command=self.destroy),
                       default=True)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.accept())
        center_over(self, app)
        self.grab_set()

    def choose(self):
        p = filedialog.askdirectory(parent=self, title="Папка для документов", initialdir=str(self.folder.parent if not self.folder.exists() else self.folder))
        if p:
            self.folder = Path(p)
            self.folder_lbl.config(text=p)

    def accept(self):
        self.ok = True
        self.destroy()


class CourtChoiceDialog(Dialog):
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


class OwnerDialog(Dialog):
    """Карточка помещения: собственники (у помещения их может быть несколько) и данные по делу.
    Заявление о судебном приказе формируется на каждого собственника."""

    DATE_KEYS = {"birth_date", "debt_from", "debt_to", "pen_from", "pen_to"}        # поля с выбором даты

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
            ("duty", "Госпошлина, руб. (пусто = расчёт по НК РФ)"),
            ("payment_order", "Платёжное поручение (№ и дата)"),
            ("invoice_month", "Счёт-извещение за (напр. март 2023 года)"),
        ]),
    ]

    def __init__(self, app: "App", info: dict, org: orgmod.Organization):
        super().__init__(app)
        self.app, self.info, self.org = app, info, org
        if _is_mac(app):
            set_window_appearance(app, self, app.settings.theme)
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
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        make_autoscroll(canvas, form, sb)
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
            if key in self.DATE_KEYS:
                datepicker.DateEntry(row, var).pack(side="left")
            else:
                ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            if key == "fio":
                ttk.Button(row, text="Из отчёта", command=self.take_report_fio).pack(side="left", padx=(6, 0))
            if key == "fio_gen":
                ttk.Button(row, text="Склонить", command=self.decline).pack(side="left", padx=(6, 0))
            if key in ("fio", "share"):
                var.trace_add("write", lambda *a: self._sync())
        self.unknown = tk.BooleanVar(value=self.card.unknown)
        self.unknown.trace_add("write", lambda *a: self.update_mode())
        urow = ttk.Frame(obox)
        urow.pack(fill="x", pady=(6, 0))
        ttk.Label(urow, text="Собственники неизвестны (шаблон без ФИО)").pack(side="left")
        widgets.Switch(urow, self.unknown, surface="window").pack(side="right")

        # --- остальные данные (по помещению) ---
        self.vars: dict[str, tk.StringVar] = {}
        for title, fields_ in self.ENTRY_FIELDS:
            box = ttk.LabelFrame(form, text=title, padding=8)
            box.pack(fill="x", pady=(0, 8), padx=(0, 10))
            for key, label in fields_:
                ttk.Label(box, text=label).pack(anchor="w")
                var = tk.StringVar(value=getattr(self.card, key))
                self.vars[key] = var
                if key in self.DATE_KEYS:
                    datepicker.DateEntry(box, var).pack(anchor="w", pady=(0, 4))
                else:
                    ttk.Entry(box, textvariable=var).pack(fill="x", pady=(0, 4))
        self.house_box = ttk.LabelFrame(form, text="Дом", padding=8)
        self.house_box.pack(fill="x", pady=(0, 8), padx=(0, 10))
        self.render_house_box()

        btns = ttk.Frame(self, padding=12)
        btns.pack(fill="x")
        pack_ok_cancel(ttk.Button(btns, text="Сохранить", command=self.save), ttk.Button(btns, text="Отмена", command=self.destroy))
        if owners.get_card(info["address"], info["flat"]):
            ttk.Button(btns, text="Удалить карточку", command=self.remove).pack(side="left")
        elif owners.has_trashed(info["address"], info["flat"]):
            ttk.Button(btns, text="Восстановить удалённую карточку", command=self.restore).pack(side="left")
        self._loading = False
        self.refresh_list(0)
        self.load_owner(0)
        center_over(self, app)

    # ----- дом: данные только из списка домов организации -----
    def render_house_box(self):
        """«В управлении с» и судебный участок дома только показываются; если не указаны — кнопка перехода к списку домов."""
        for w in self.house_box.winfo_children():
            w.destroy()
        addr = self.info["address"]
        house = orgmod.find_house(self.org, addr)
        period = orgmod.house_period_text(house) if house else ""
        managed = bool(house) and orgmod.is_managed_house(house)
        code = orgmod.house_court(self.org, addr)
        court_obj = courtsmod.find_by_code(courtsmod.load()["courts"], code) if code else None

        def line(title, text, ok, style="Ok.TLabel"):
            ttk.Label(self.house_box, text=title).pack(anchor="w", pady=(4, 0))
            if ok:
                ttk.Label(self.house_box, text=text, style=style, justify="left", wraplength=620).pack(anchor="w")
            else:
                ttk.Label(self.house_box, text="не указан" if title.startswith("В упр") else "не назначен",
                          style="Warn.TLabel").pack(anchor="w")
                ttk.Button(self.house_box, text="Указать в списке домов…", command=self.open_houses).pack(anchor="w", pady=(2, 0))
        line("В управлении", period, bool(period), "Ok.TLabel" if managed else "Warn.TLabel")
        line("Судебный участок", f"{court_obj.name}\nСудья: {court_obj.judge or 'не указан'}\n{court_obj.address}"
             if court_obj else "", bool(court_obj))
        if period or court_obj:
            ttk.Button(self.house_box, text="Изменить в списке домов…", command=self.open_houses).pack(anchor="w", pady=(6, 0))

    def open_houses(self):
        """Переход к списку домов организации (Настройки → Организации → Дома) с выбранным домом; потом данные обновляются."""
        app = self.app
        dlg = OrgDialog(app, app.orgs, self.org.name, on_close=lambda name: app.refresh_orgs(name),
                        focus_address=self.info["address"])
        self.wait_window(dlg)
        self.org = app.current_org()
        self.render_house_box()
        app.refresh_card_flags()

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
        self.card.address = str(self.info["address"]).strip()
        self.card.flat = claim.clean_flat(self.info["flat"])
        owners.save_card(self.card)
        self.destroy()

    def restore(self):
        if owners.restore_card(self.info["address"], self.info["flat"]):
            messagebox.showinfo("Корзина", "Карточка восстановлена.", parent=self)
            app, info, org = self.app, self.info, self.org
            self.destroy()
            OwnerDialog(app, info, org)

    def remove(self):
        if messagebox.askyesno("Удалить", "Удалить карточку помещения с данными собственников?\n\n"
                               f"Она попадёт в корзину, и её можно будет восстановить в течение {owners.TRASH_DAYS} дней.",
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
        ttk.Label(self, text="Дома в обслуживании: адрес как в отчёте, дата прихода (с которой дом в управлении), дата ухода "
                             "(или отметка «ушёл, дата неизвестна») и судебный участок дома (пусто = все дома файла)",
                  wraplength=680, justify="left").pack(anchor="w")
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True, pady=(4, 8))
        self.meta: dict[str, dict] = {}                 # строка таблицы -> {"until": дата ухода, "left": ушёл без даты}
        self.tree = ttk.Treeview(box, columns=("address", "since", "until", "court"), show="headings", height=10,
                                 selectmode="extended")
        for c, text, w, anchor in (("address", "Адрес дома", 250, "w"), ("since", "В управлении с", 105, "center"),
                                   ("until", "Ушёл (по)", 120, "center"), ("court", "Судебный участок", 220, "w")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        make_striped(self.tree)                         # чередование строк, как в таблице должников
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())
        self.tree.bind("<Delete>", lambda e: self.remove())
        self.tree.bind("<BackSpace>", lambda e: self.remove())
        for seq in ("<Command-a>", "<Control-a>"):
            self.tree.bind(seq, lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.addr, self.since = tk.StringVar(), tk.StringVar()
        self.until, self.left = tk.StringVar(), tk.BooleanVar(value=False)
        ttk.Entry(row, textvariable=self.addr).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row, text="Добавить / обновить", command=self.upsert).pack(side="left")
        self.del_btn = ttk.Button(row, text="Удалить", command=self.remove)
        self.del_btn.pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Из отчёта", command=self.from_report).pack(side="left", padx=(6, 0))

        drow = ttk.Frame(self)
        drow.pack(fill="x", pady=(6, 0))
        ttk.Label(drow, text="В управлении с:").pack(side="left")
        self.since_entry = datepicker.DateEntry(drow, self.since)
        self.since_entry.pack(side="left", padx=(6, 14))
        ttk.Label(drow, text="Ушёл (по):").pack(side="left")
        self.until_entry = datepicker.DateEntry(drow, self.until)
        self.until_entry.pack(side="left", padx=(6, 14))
        ttk.Checkbutton(drow, text="Ушёл, дата неизвестна", variable=self.left, command=self._left_toggled).pack(side="left")

        crow = ttk.Frame(self)
        crow.pack(fill="x", pady=(8, 0))
        ttk.Label(crow, text="Судебный участок:").pack(side="left")
        self.combo = AutoCombo(crow, self._source, self._on_pick, width=34)
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

    @staticmethod
    def _until_text(until: str, left: bool) -> str:
        return until or ("ушёл" if left else "")

    def _left_toggled(self):
        """«Ушёл, дата неизвестна» и дата ухода взаимоисключают друг друга."""
        if self.left.get():
            self.until.set("")
        self.until_entry.set_enabled(not self.left.get())

    def _clear_fields(self):
        self.addr.set(""); self.since.set(""); self.until.set(""); self.left.set(False)
        self.until_entry.set_enabled(True)

    def _insert(self, address: str, since: str, until: str, left: bool, code: str) -> str:
        item = self.tree.insert("", "end", values=(address, since, self._until_text(until, left), self._court_label(code)))
        self.codes[item] = code
        self.meta[item] = {"until": until, "left": left}
        stripe_rows(self.tree)
        return item

    def _set_court(self, item: str, code: str):
        self.codes[item] = code
        vals = list(self.tree.item(item, "values"))
        vals[3] = self._court_label(code)
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
        self.codes, self.meta = {}, {}
        for h in houses:
            self._insert(h["address"], h["since"], h.get("until", ""), bool(h.get("left")), h.get("court", ""))
        self._clear_fields()
        self.court_code = ""
        self.combo.set_text("")

    def get(self) -> list[dict]:
        out = []
        for i in self.tree.get_children():
            v = self.tree.item(i, "values")
            if str(v[0]).strip():
                m = self.meta.get(i, {})
                out.append({"address": str(v[0]).strip(), "since": str(v[1]).strip(), "until": m.get("until", ""),
                            "left": bool(m.get("left")), "court": self.codes.get(i, "")})
        return out

    def focus_address(self, address: str):
        """Выбирает дом в списке; если его там нет — подставляет адрес в поле, чтобы осталось нажать «Добавить»."""
        want = orgmod.norm_addr(address)
        for item in self.tree.get_children():
            if orgmod.norm_addr(str(self.tree.item(item, "values")[0])) == want:
                self.tree.selection_set(item)
                self.tree.see(item)
                return
        self._clear_fields()
        self.addr.set(str(address))

    def load_selected(self):
        sel = self.tree.selection()
        if len(sel) == 1:
            a, s = self.tree.item(sel[0], "values")[:2]
            m = self.meta.get(sel[0], {})
            self.addr.set(a); self.since.set(s)
            self.until.set(m.get("until", "")); self.left.set(bool(m.get("left")))
            self.until_entry.set_enabled(not self.left.get())
            code = self.codes.get(sel[0], "")
            self.court_code = code
            c = courtsmod.find_by_code(self.courts, code)
            self.combo.set_text(c.name if c else "")
        else:                                   # несколько строк выделено — поля правки очищаем
            self._clear_fields()
        self.del_btn.config(text=f"Удалить ({len(sel)})" if len(sel) > 1 else "Удалить")

    def upsert(self):
        addr = self.addr.get().strip()
        if not addr:
            return
        key = orgmod.norm_addr(addr)
        self.since_entry.tidy()
        self.until_entry.tidy()
        since, until, left = self.since.get().strip(), self.until.get().strip(), bool(self.left.get()) and not self.until.get().strip()
        for i in self.tree.get_children():
            if orgmod.norm_addr(self.tree.item(i, "values")[0]) == key:
                self.tree.item(i, values=(addr, since, self._until_text(until, left), self._court_label(self.court_code)))
                self.codes[i] = self.court_code
                self.meta[i] = {"until": until, "left": left}
                return
        item = self._insert(addr, since, until, left, self.court_code)
        self.tree.see(item)
        self._clear_fields()

    def remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        if len(sel) > 1 and not messagebox.askyesno("Удалить дома", f"Удалить выделенные дома ({len(sel)})?",
                                                    parent=self.winfo_toplevel()):
            return
        for i in sel:
            self.codes.pop(i, None)
            self.meta.pop(i, None)
            self.tree.delete(i)
        stripe_rows(self.tree)
        self._clear_fields()
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
                self._insert(addr, "", "", False, "")
                added += 1
        messagebox.showinfo("Дома", f"Добавлено домов: {added}. Заполните даты, с которых дома в управлении.",
                            parent=self.winfo_toplevel())


class OrgDialog(Dialog):
    """Редактор организаций: реквизиты, дома, текст претензии."""

    def __init__(self, parent, orgs, selected, on_close, focus_address: str = ""):
        super().__init__(parent)
        self.title("Организации")
        self.geometry("1060x640")
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
        self.c_vars = {k: tk.StringVar() for k in ("applicant_address", "region", "city_in",
                                                    "license_text", "poa_text")}
        for key, label in (
            ("applicant_address", "Адрес заявителя в заявлении"),
            ("region", "Регион (в адресах помещений)"),
            ("city_in", "Город в предложном падеже («в г. Таганроге»)"),
            ("license_text", "Уведомление о лицензии («№ 679 от 18.05.2021»)"),
            ("poa_text", "Доверенность от («23.08.2022г.»)"),
        ):
            ttk.Label(h, text=label).pack(anchor="w")
            if key == "poa_text":
                datepicker.DateEntry(h, self.c_vars[key], suffix="г.").pack(anchor="w", pady=(0, 4))     # «23.08.2022г.»
            else:
                ttk.Entry(h, textvariable=self.c_vars[key]).pack(fill="x", pady=(0, 4))
        ttk.Label(h, text="Шапка заявления берётся со вкладки «Шапка»; подписант — со вкладки «Письмо в ЕИРЦ». Судебный участок закрепляется за домом на вкладке «Дома» или выбирается в карточке помещения и при формировании заявлений.",
                  wraplength=760, justify="left",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        ttk.Button(left, text="Сохранить и закрыть", command=self.save).pack(fill="x", pady=(16, 0))
        self.refresh(selected)
        if focus_address:                                       # пришли из карточки собственника — сразу к нужному дому
            nb.select(hs)
            self.houses.focus_address(focus_address)
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
