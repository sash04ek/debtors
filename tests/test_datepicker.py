"""Выбор даты: разбор, форматирование и календарь."""
import sys
import tkinter as tk
import unittest
from tkinter import ttk
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import datepicker as dp  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_parse_various_forms(self):
        self.assertEqual(dp.parse_date("01.06.2015г"), date(2015, 6, 1))
        self.assertEqual(dp.parse_date("с 1.6.15"), date(2015, 6, 1))
        self.assertEqual(dp.parse_date("2015-06-01"), date(2015, 6, 1))
        self.assertEqual(dp.parse_date("23.08.2022г."), date(2022, 8, 23))
        self.assertIsNone(dp.parse_date("31.02.2020"))
        self.assertIsNone(dp.parse_date("март 2023 года"))

    def test_normalize_only_whole_dates(self):
        self.assertEqual(dp.normalize("1.6.15"), "01.06.2015")
        self.assertEqual(dp.normalize("23.8.2022 г", "г."), "23.08.2022г.")
        self.assertEqual(dp.normalize("01.06.2015г ушел"), "01.06.2015г ушел")      # не просто дата — не трогаем
        self.assertEqual(dp.normalize("ушел"), "ушел")

    def test_month_grid_starts_on_monday_and_has_six_weeks(self):
        grid = dp.month_grid(2026, 10)                          # 1 октября 2026 — четверг
        self.assertEqual(len(grid), 6)
        self.assertTrue(all(len(w) == 7 for w in grid))
        self.assertEqual(grid[0][0], date(2026, 9, 28))
        self.assertEqual(grid[0][3], date(2026, 10, 1))


class WidgetTest(unittest.TestCase):
    def setUp(self):
        self.old_native = dp.USE_NATIVE
        dp.USE_NATIVE = False                                   # тесты проверяют календарь программы, системный окон не открывает
        self.root = tk.Tk()
        self.root.update()

    def tearDown(self):
        dp.USE_NATIVE = self.old_native
        self.root.destroy()

    def _entry(self, value="15.03.2020", **kw):
        var = tk.StringVar(value=value)
        w = dp.DateEntry(self.root, var, **kw)
        w.pack()
        self.root.update()
        return w, var

    def test_calendar_pick_and_clear(self):
        w, var = self._entry(suffix="г.")
        w.open_calendar()
        pop = w._popup
        self.assertEqual((pop.year, pop.month), (2020, 3))
        pop.shift(1)
        self.assertEqual((pop.year, pop.month), (2020, 4))
        pop.pick(date(2020, 4, 9))
        self.assertEqual(var.get(), "09.04.2020г.")
        self.assertFalse(w.is_open())
        w.open_calendar()
        w._popup.clear()
        self.assertEqual(var.get(), "")

    def test_typed_date_is_tidied_on_focus_out_and_free_text_kept(self):
        w, var = self._entry("1.6.15")
        w.tidy()
        self.assertEqual(var.get(), "01.06.2015")
        var.set("март 2023")
        w.tidy()
        self.assertEqual(var.get(), "март 2023")

    def test_year_navigation_wraps_months(self):
        w, _ = self._entry("31.12.2025")
        w.open_calendar()
        w._popup.shift(1)
        self.assertEqual((w._popup.year, w._popup.month), (2026, 1))
        w._popup.shift(-13)
        self.assertEqual((w._popup.year, w._popup.month), (2024, 12))
        w.close_calendar()

    def test_click_on_field_opens_calendar_once_and_no_arrow_button(self):
        w, _ = self._entry()
        self.assertEqual([c for c in w.winfo_children() if isinstance(c, ttk.Button)], [])      # кнопки со стрелкой нет
        w.entry.event_generate("<Button-1>", x=5, y=5)
        self.root.update()
        first = w._popup
        self.assertIsNotNone(first)
        w.entry.event_generate("<Button-1>", x=6, y=5)                  # повторный клик не пересоздаёт календарь
        self.root.update()
        self.assertIs(w._popup, first)
        w.close_calendar()

    def test_calendar_follows_typed_date_and_focus_stays_in_field(self):
        w, var = self._entry()
        w.entry.focus_force()
        self.root.update()
        w.open_calendar()
        self.root.update()
        var.set("09.04.2021")
        w._sync_typed()
        self.assertEqual((w._popup.year, w._popup.month, w._popup.selected), (2021, 4, date(2021, 4, 9)))
        var.set("09.04.20")                                              # год набран не полностью — календарь не прыгает
        w._sync_typed()
        self.assertEqual(w._popup.selected, date(2021, 4, 9))
        self.assertIs(self.root.focus_get(), w.entry)                    # фокус остался в поле: можно продолжать печатать
        w.close_calendar()

    def test_escape_return_and_click_elsewhere_close_calendar(self):
        w, var = self._entry()
        other = tk.Label(self.root, text="x")
        other.pack()
        for how in ("escape", "return", "away", "focusout"):
            w.open_calendar()
            self.assertTrue(w.is_open(), how)
            if how == "escape":
                self.assertEqual(w._escape(), "break")
            elif how == "return":
                self.assertEqual(w._return(), "break")
            elif how == "away":
                ev = type("E", (), {"widget": other})()
                w._away_click(ev)
            else:
                w._opened_at -= 1
                w._focus_out()
            self.assertFalse(w.is_open(), how)
        self.assertIsNone(w._escape())                                   # календарь закрыт — Esc идёт дальше (закрыть диалог)

    def test_click_on_own_entry_does_not_close(self):
        w, _ = self._entry()
        w.open_calendar()
        w._away_click(type("E", (), {"widget": w.entry})())
        self.assertTrue(w.is_open())
        w.close_calendar()

    def test_disabled_field_does_not_open(self):
        w, _ = self._entry("")
        w.set_enabled(False)
        w.open_calendar()
        self.assertFalse(w.is_open())
        w.set_enabled(True)


class FakePending:
    def __init__(self):
        self.synced, self.cancelled = [], False

    def sync(self, d):
        self.synced.append(d)

    def cancel(self):
        self.cancelled = True


class NativeTest(unittest.TestCase):
    """Системный календарь: команды запуска, разбор ответа, подключение к DateEntry (процессы не запускаются)."""

    def test_parse_output(self):
        import native_date as nd
        self.assertEqual(nd.parse_output("OK:2026-10-09\n"), ("pick", date(2026, 10, 9)))
        self.assertEqual(nd.parse_output("CLEAR"), ("clear", None))
        self.assertEqual(nd.parse_output("CANCEL"), ("cancel", None))
        self.assertEqual(nd.parse_output(""), ("cancel", None))
        self.assertEqual(nd.parse_output("OK:мусор"), ("cancel", None))

    def test_commands_per_platform(self):
        import base64
        import native_date as nd
        cmd, kw = nd.build_command("2026-10-09", True, 100, 200, platform="darwin", y_above=180, look="dark", sync_path="/tmp/s.txt")
        self.assertEqual(cmd[:4], ["osascript", "-l", "JavaScript", "-e"])
        self.assertEqual(cmd[5:], ["2026-10-09", "1", "100", "200", "180", "", "dark", "/tmp/s.txt"])
        self.assertIn("NSDatePicker", cmd[4])
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", cmd[4])      # панель не забирает фокус
        cmd, kw = nd.build_command("", False, 100, 200, platform="win32", sync_path="C:\\Temp\\s'.txt")
        self.assertEqual(cmd[0], "powershell")
        script = base64.b64decode(cmd[-1]).decode("utf-16-le")
        self.assertIn("MonthCalendar", script)
        self.assertIn("Point(100, 200)", script)
        self.assertIn("0x08000088", script)                                 # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        self.assertIn("s''.txt", script)                                    # кавычки в пути не ломают скрипт
        self.assertNotIn("$clear", script)
        self.assertEqual(kw["creationflags"], 0x08000000)
        script = base64.b64decode(nd.build_command("2026-10-09", True, 1, 2, platform="win32")[0][-1]).decode("utf-16-le")
        self.assertIn("$clear", script)
        self.assertIn("ParseExact('2026-10-09'", script)
        with self.assertRaises(OSError):
            nd.build_command("", False, platform="linux")

    def test_pending_sync_and_cancel(self):
        import os
        import tempfile
        import native_date as nd
        fd, path = tempfile.mkstemp()
        os.close(fd)
        p = nd.Pending(None, path)
        p.sync(date(2026, 10, 9))
        self.assertEqual(open(path, encoding="utf-8").read(), "2026-10-09")
        p.sync(None)
        self.assertEqual(open(path, encoding="utf-8").read(), "2026-10-09")
        p.cancel()
        self.assertTrue(p.cancelled)
        os.unlink(path)

    def test_entry_with_native_calendar(self):
        import native_date as nd
        root = tk.Tk()
        old = (dp.USE_NATIVE, nd.available, nd.ask)
        try:
            dp.USE_NATIVE = True
            nd.available = lambda: True
            pending = FakePending()
            calls = []
            nd.ask = lambda widget, current, allow_clear, on_result, **kw: (calls.append((current, kw)), setattr(pending, "on", on_result),
                                                                              pending)[-1]
            var = tk.StringVar(value="01.01.2020")
            w = dp.DateEntry(root, var, suffix="г.")
            w.pack()
            root.update()
            w.open_calendar()
            self.assertEqual(calls[0][0], date(2020, 1, 1))
            self.assertEqual(calls[0][1]["look"] in ("dark", "light", ""), True)
            w.open_calendar()                                           # уже показан — второй раз не открывается
            self.assertEqual(len(calls), 1)
            var.set("09.10.2026")
            w._sync_typed()                                             # календарь следует за набранной датой
            self.assertEqual(pending.synced, [date(2026, 10, 9)])
            self.assertEqual(w._escape(), "break")                      # Esc закрывает панель
            self.assertTrue(pending.cancelled)
            self.assertFalse(w.is_open())
            # выбор в панели
            pending2 = FakePending()
            nd.ask = lambda widget, current, allow_clear, on_result, **kw: (setattr(pending2, "on", on_result), pending2)[-1]
            w.open_calendar()
            pending2.on("pick", date(2027, 2, 3))
            self.assertEqual(var.get(), "03.02.2027г.")
            self.assertFalse(w.is_open())
            w.open_calendar()
            pending2.on("clear", None)
            self.assertEqual(var.get(), "")
            w.open_calendar()
            pending2.on("cancel", None)                                 # отмена — значение не меняется
            self.assertEqual(var.get(), "")
            w.open_calendar()
            pending2.on("error", None)                                  # ошибка — открывается календарь программы
            self.assertIsNotNone(w._popup)
            w.close_calendar()
        finally:
            dp.USE_NATIVE, nd.available, nd.ask = old
            root.destroy()

    @unittest.skipUnless(__import__("os").environ.get("DEBTORS_NATIVE_E2E") == "1" and sys.platform == "darwin",
                         "ручная проверка: DEBTORS_NATIVE_E2E=1, откроет панель macOS на пару секунд")
    def test_macos_panel_end_to_end(self):
        import os
        import subprocess
        import tempfile
        import native_date as nd
        fd, path = tempfile.mkstemp()
        os.write(fd, b"2026-12-25")                                     # набранная в поле дата: панель должна перейти на неё
        os.close(fd)
        cmd, kw = nd.build_command("2026-10-09", True, 600, 400, auto="ok", sync_path=path)
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw).stdout
        os.unlink(path)
        self.assertEqual(nd.parse_output(out), ("pick", date(2026, 12, 25)))


if __name__ == "__main__":
    unittest.main()
