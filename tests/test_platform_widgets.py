"""Элементы управления на разных платформах: macOS — свои «как в настройках macOS», Windows/Linux — стандартные ttk."""
import sys
import unittest
from tkinter import ttk

import app
import widgets


class PlatformWidgetsTest(unittest.TestCase):
    def setUp(self):
        self.old = (app.save_settings, app._is_mac, widgets.is_aqua)
        app.save_settings = lambda s: None

    def tearDown(self):
        app.save_settings, app._is_mac, widgets.is_aqua = self.old

    def _app(self):
        app.App.restore_last_state = lambda self: None
        a = app.App()
        a.update()
        return a

    def test_macos_uses_custom_controls(self):
        if sys.platform != "darwin":                   # на не-Mac этот тест не применим
            self.skipTest("не macOS")
        a = self._app()
        try:
            sw = widgets.Switch(a, app.tk.BooleanVar(value=True))
            sel = widgets.PopupSelect(a, None, ["а", "б"])
            self.assertNotIsInstance(sw, ttk.Checkbutton)
            self.assertNotIsInstance(sel, ttk.Combobox)
            self.assertTrue(int(sw.cget("takefocus")))                       # доступен с клавиатуры (Tab)
        finally:
            a.destroy()

    def test_macos_menubar_has_file_and_edit(self):
        if sys.platform != "darwin":
            self.skipTest("не macOS")
        a = self._app()
        try:
            bar = a.nametowidget(a["menu"])
            labels = [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)
                      if bar.type(i) == "cascade" and bar.entrycget(i, "label")]
            self.assertEqual(labels, ["Файл", "Правка", "Справочники"])
            idx = next(i for i in range(bar.index("end") + 1) if bar.type(i) == "cascade" and bar.entrycget(i, "label") == "Файл")
            apple = bar.nametowidget(bar.entrycget(0, "menu"))
            self.assertEqual(apple.entrycget(0, "label"), "О программе «Должники»")      # стандартный пункт About в меню приложения
            file_menu = bar.nametowidget(bar.entrycget(idx, "menu"))
            self.assertEqual(file_menu.entrycget(0, "label"), "Открыть Excel…")
        finally:
            a.destroy()

    def test_ok_cancel_order_follows_platform(self):
        a = self._app()
        try:
            for mac in (True, False):
                app._is_mac = lambda r, m=mac: m
                f = ttk.Frame(a)
                f.pack()
                ok, cancel = ttk.Button(f, text="OK"), ttk.Button(f, text="Отмена")
                app.pack_ok_cancel(ok, cancel)
                f.update_idletasks()
                if mac:
                    self.assertLess(cancel.winfo_x(), ok.winfo_x())          # macOS: «Отмена» слева от главной
                else:
                    self.assertLess(ok.winfo_x(), cancel.winfo_x())          # Windows: главная слева, «Отмена» справа
                f.destroy()
        finally:
            a.destroy()

    def test_windows_mode_builds_all_dialogs_with_standard_controls(self):
        widgets.is_aqua = lambda r: False
        app._is_mac = lambda r: False
        a = self._app()
        try:
            self.assertEqual(str(a["menu"]), "")                              # системной строки меню нет — она всегда светлая
            self.assertEqual([b.cget("text") for b in a.menubar_frame.winfo_children() if isinstance(b, ttk.Button)],
                             ["Файл", "Правка", "Справочники", "Справка"])      # на Windows своя строка меню
            self.assertEqual(a.menus["Файл"].entrycget(0, "label"), "Открыть Excel…")
            self.assertIsInstance(a.sheet_cb, ttk.Combobox)
            self.assertIsInstance(a.org_cb, ttk.Combobox)
            sd = app.SettingsDialog(a)
            sd.update()
            kinds = {type(w).__name__ for w in _walk(sd)}
            self.assertIn("Combobox", kinds)
            self.assertIn("Checkbutton", kinds)
            self.assertNotIn("_AquaSwitch", kinds)
            self.assertNotIn("_AquaPopupSelect", kinds)
            cd = app.CourtsDialog(a)                                  # справочник участков — отдельное окно, не вкладка настроек
            cd.update()
            for dlg in (app.RegionsDialog(cd), app.DutyScaleDialog(sd)):
                dlg.update()
                dlg.destroy()
            cd.destroy()
            sd.destroy()
            a.settings.theme = "dark"                                  # тёмная палитра поверх clam
            app.apply_theme(a, "dark")
            a.update()
            a.settings.theme = "light"
            app.apply_theme(a, "light")
            a.update()
            # значения программно меняются, как у Combobox
            a.sheet_cb["values"] = ["Лист1", "Лист2"]
            a.sheet_cb.set("Лист2")
            self.assertEqual(a.sheet_cb.get(), "Лист2")
        finally:
            a.destroy()


class WheelBindingTest(unittest.TestCase):
    def test_missing_touchpad_event_does_not_break_startup(self):
        """Регрессия: в Tk 8.6 (Windows) нет события <TouchpadScroll> — программа падала при запуске."""
        class Root:
            def __init__(self):
                self.bound = []

            def _bind(self, *args):
                if "<TouchpadScroll>" in args:
                    raise app.tk.TclError('bad event type or keysym "TouchpadScroll"')
                self.bound.append(args)

            bind_all = lambda self, seq, fn: self._bind(seq, fn)
            bind_class = lambda self, cls, seq, fn: self._bind(cls, seq, fn)

        root = Root()
        app.install_wheel(root)                                      # не должно бросать исключение
        self.assertTrue(any("<MouseWheel>" in b for b in root.bound))      # обычное колесо мыши по-прежнему привязано


class DarkTitlebarTest(unittest.TestCase):
    def test_noop_outside_windows(self):
        root = app.tk.Tk()
        try:
            if sys.platform.startswith("win"):
                self.skipTest("только не Windows")
            app.set_titlebar_dark(root, True)                           # не должно ничего делать и падать
        finally:
            root.destroy()

    def test_windows_sets_immersive_dark_attribute_and_redraws_frame(self):
        import ctypes
        calls = []

        class User32:
            GetParent = staticmethod(lambda hwnd: 4242)
            SetWindowPos = staticmethod(lambda *a: calls.append(("pos", a)) or 1)

        class Dwm:
            @staticmethod
            def DwmSetWindowAttribute(hwnd, attr, ref, size):
                calls.append(("dwm", hwnd, attr, ref._obj.value, size))
                return 0

        fake = type("W", (), {"user32": User32, "dwmapi": Dwm})
        old_platform, had = app.sys.platform, hasattr(ctypes, "windll")
        old_windll = getattr(ctypes, "windll", None)
        root = app.tk.Tk()
        try:
            app.sys.platform = "win32"
            ctypes.windll = fake
            app.set_titlebar_dark(root, True)
            app.set_titlebar_dark(root, False)
        finally:
            app.sys.platform = old_platform
            if had:
                ctypes.windll = old_windll
            else:
                del ctypes.windll
            root.destroy()
        dwm = [c for c in calls if c[0] == "dwm"]
        self.assertEqual([(c[1], c[2], c[3]) for c in dwm], [(4242, 20, 1), (4242, 20, 0)])    # тёмный, затем светлый
        self.assertEqual(len([c for c in calls if c[0] == "pos"]), 2)                        # рамка перерисована


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


if __name__ == "__main__":
    unittest.main()


class SettingsTabsTest(unittest.TestCase):
    def test_tabs_switch_pages_and_remember_choice(self):
        old = (app.save_settings,)
        app.save_settings = lambda s: None
        try:
            a = app.App()
            sd = app.SettingsDialog(a)
            sd.update()
            self.assertTrue(sd.pages["Отбор"].winfo_ismapped())
            sd.tabs.select(2)
            sd.update()
            self.assertTrue(sd.pages["Документы"].winfo_ismapped())
            self.assertFalse(sd.pages["Отбор"].winfo_ismapped())
            sd.destroy()
            sd2 = app.SettingsDialog(a)
            sd2.update()
            self.assertTrue(sd2.pages["Документы"].winfo_ismapped())          # открывается на последней вкладке
            sd2.destroy()
            a.destroy()
        finally:
            app.save_settings, = old


class OwnerDialogSwitchTest(unittest.TestCase):
    def test_switch_is_not_inside_labelframe(self):
        """У рамки LabelFrame на macOS свой оттенок фона: переключатель внутри неё окружён прямоугольником другого цвета."""
        import orgs
        old = app.save_settings
        app.save_settings = lambda s: None
        try:
            a = app.App()
            dlg = app.OwnerDialog(a, {"address": "Тестовая ул 1", "flat": "5", "report_fio": "Иванов Иван Иванович", "debt": 1000.0},
                                  orgs.default_orgs()[0])

            def walk(w, inside=False):
                inside = inside or w.winfo_class() == "TLabelframe"
                if type(w).__name__ == "_AquaSwitch":
                    self.assertFalse(inside, "переключатель внутри LabelFrame")
                for c in w.winfo_children():
                    walk(c, inside)
            walk(dlg)
            dlg.destroy()
            a.destroy()
        finally:
            app.save_settings = old


class ReferencesMenuTest(unittest.TestCase):
    def test_references_menu_and_settings_no_longer_hold_them(self):
        old = app.save_settings
        app.save_settings = lambda s: None
        try:
            a = app.App()
            refs = a.menus["Справочники"]
            self.assertEqual([refs.entrycget(i, "label") for i in range(3 - 1)], ["Организации…", "Судебные участки…"])
            sd = app.SettingsDialog(a)
            sd.update()
            texts = {w.cget("text") for w in _walk(sd) if "text" in w.keys()}
            self.assertNotIn("Список организаций", texts)                     # переехало в «Справочники»
            self.assertNotIn("Судьи и адреса участков", texts)
            sd.destroy()
            a.open_courts()
            first = a._courts_win
            a.open_courts()
            self.assertIs(a._courts_win, first)                               # второй вызов поднимает то же окно
            first.destroy()
            a.destroy()
        finally:
            app.save_settings = old
