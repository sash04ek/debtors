import tkinter as tk
import unittest
from datetime import date

import app
import updates


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version("1.0.19"), (1, 0, 19))
        self.assertEqual(updates.parse_version("v1.2"), (1, 2))
        self.assertIsNone(updates.parse_version("разработка"))
        self.assertIsNone(updates.parse_version(""))

    def test_newer_compares_numbers_not_strings(self):
        self.assertTrue(updates.is_newer("1.0.20", "1.0.19"))
        self.assertTrue(updates.is_newer("1.0.10", "1.0.9"))
        self.assertFalse(updates.is_newer("1.0.9", "1.0.10"))
        self.assertFalse(updates.is_newer("1.0.19", "1.0.19"))
        self.assertFalse(updates.is_newer("1.0.20", "разработка"))


class CheckTests(unittest.TestCase):
    def test_statuses(self):
        newer = lambda: {"tag": "1.0.20", "url": "u", "notes": ""}
        same = lambda: {"tag": "1.0.19", "url": "u", "notes": ""}

        def broken():
            raise OSError("нет сети")
        self.assertEqual(updates.check("1.0.19", newer)[0], "newer")
        self.assertEqual(updates.check("1.0.19", same)[0], "current")
        self.assertEqual(updates.check("1.0.19", broken), ("error", None))
        self.assertEqual(updates.check("1.0.19", lambda: {"tag": "мусор"}), ("error", None))
        self.assertEqual(updates.check("разработка", newer), ("dev", None))      # без номера версии сеть не трогаем


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.old = (app.save_settings, app.messagebox.showinfo, app.messagebox.askyesno, updates.check, app.App.app_version)
        app.save_settings = lambda s: None
        self.shown = []
        app.messagebox.showinfo = lambda *a, **kw: self.shown.append(a[1])
        app.messagebox.askyesno = lambda *a, **kw: False
        app.App.app_version = staticmethod(lambda: "1.0.19")
        try:
            self.app = app.App()
        except tk.TclError:
            self.skipTest("нет дисплея")

    def tearDown(self):
        self.app.destroy()
        app.save_settings, app.messagebox.showinfo, app.messagebox.askyesno, updates.check, app.App.app_version = self.old

    def test_newer_version_shows_bar_and_skip_hides_it(self):
        info = {"tag": "1.0.20", "url": "https://example.com", "notes": ""}
        updates.check = lambda current: ("newer", info)
        self.app.settings.update_checked = ""
        self.app.start_update_check()
        for _ in range(30):
            self.app.update()
            if getattr(self.app, "update_bar", None):
                break
            self.app.after(50)
            self.app.update()
        self.assertIsNotNone(self.app.update_bar)
        self.assertEqual(self.app.settings.update_checked, date.today().isoformat())
        self.app.skip_update("1.0.20")
        self.assertIsNone(self.app.update_bar)
        self.assertEqual(self.app.settings.update_skipped, "1.0.20")

    def test_not_checked_twice_a_day_or_when_disabled(self):
        calls = []
        updates.check = lambda current: (calls.append(1), ("current", {"tag": "1.0.19"}))[1]
        self.app.settings.update_checked = date.today().isoformat()
        self.app.start_update_check()
        self.app.update_var.set(False)
        self.app.settings.update_checked = ""
        self.app.start_update_check()
        self.assertEqual(calls, [])

    def test_manual_check_reports_result(self):
        updates.check = lambda current: ("current", {"tag": "1.0.19"})
        self.app.start_update_check(manual=True)
        for _ in range(30):
            self.app.update()
            if self.shown:
                break
            self.app.after(50)
            self.app.update()
        self.assertTrue(any("последняя версия" in t for t in self.shown))
