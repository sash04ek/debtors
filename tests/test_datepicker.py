"""Выбор даты: разбор, форматирование и календарь."""
import sys
import tkinter as tk
import unittest
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

    def test_calendar_pick_and_clear(self):
        var = tk.StringVar(value="15.03.2020")
        w = dp.DateEntry(self.root, var, suffix="г.")
        w.pack()
        w.open_calendar()
        pop = w._popup
        self.assertEqual((pop.year, pop.month), (2020, 3))
        pop.shift(1)
        self.assertEqual((pop.year, pop.month), (2020, 4))
        pop.pick(date(2020, 4, 9))
        self.assertEqual(var.get(), "09.04.2020г.")
        w.open_calendar()
        w._popup.clear()
        self.assertEqual(var.get(), "")

    def test_typed_date_is_tidied_on_focus_out_and_free_text_kept(self):
        var = tk.StringVar(value="1.6.15")
        w = dp.DateEntry(self.root, var)
        w.pack()
        w.tidy()
        self.assertEqual(var.get(), "01.06.2015")
        var.set("март 2023")
        w.tidy()
        self.assertEqual(var.get(), "март 2023")

    def test_year_navigation_wraps_months(self):
        w = dp.DateEntry(self.root, tk.StringVar(value="31.12.2025"))
        w.pack()
        w.open_calendar()
        w._popup.shift(1)
        self.assertEqual((w._popup.year, w._popup.month), (2026, 1))
        w._popup.shift(-13)
        self.assertEqual((w._popup.year, w._popup.month), (2024, 12))
        w._popup.destroy()


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
        cmd, kw = nd.build_command("2026-10-09", True, "Дата ухода", platform="darwin")
        self.assertEqual(cmd[:4], ["osascript", "-l", "JavaScript", "-e"])
        self.assertEqual(cmd[5:8], ["2026-10-09", "1", "Дата ухода"])
        self.assertIn("NSDatePicker", cmd[4])
        cmd, kw = nd.build_command("", False, "Дата", 100, 200, platform="win32")
        self.assertEqual(cmd[0], "powershell")
        script = base64.b64decode(cmd[-1]).decode("utf-16-le")
        self.assertIn("MonthCalendar", script)
        self.assertIn("Point(100, 200)", script)
        self.assertNotIn("$clear", script)
        self.assertEqual(kw["creationflags"], 0x08000000)
        _, _ = nd.build_command("", True, "О'Нил", platform="win32")             # кавычки в заголовке не ломают скрипт
        script = base64.b64decode(nd.build_command("2026-10-09", True, "О'Нил", platform="win32")[0][-1]).decode("utf-16-le")
        self.assertIn("О''Нил", script)
        self.assertIn("$clear", script)
        self.assertIn("ParseExact('2026-10-09'", script)
        with self.assertRaises(OSError):
            nd.build_command("", False, "x", platform="linux")

    def test_entry_uses_native_result_and_falls_back_on_error(self):
        import native_date as nd
        root = tk.Tk()
        old = (dp.USE_NATIVE, nd.available, nd.ask)
        try:
            dp.USE_NATIVE = True
            nd.available = lambda: True
            results = iter([("pick", date(2026, 10, 9)), ("clear", None), ("cancel", None), ("error", None)])
            nd.ask = lambda widget, current, allow_clear, title, on_result, **kw: on_result(*next(results))
            var = tk.StringVar(value="01.01.2020")
            w = dp.DateEntry(root, var, suffix="г.", title="Дата ухода")
            w.pack()
            w.open_calendar()
            self.assertEqual(var.get(), "09.10.2026г.")
            w.open_calendar()
            self.assertEqual(var.get(), "")
            var.set("05.05.2025")
            w.open_calendar()                                   # отмена — значение не меняется
            self.assertEqual(var.get(), "05.05.2025г.")         # перед открытием набранная дата приводится к единому виду
            w.open_calendar()                                   # ошибка — открывается календарь программы
            self.assertIsNotNone(w._popup)
            w._popup.destroy()
        finally:
            dp.USE_NATIVE, nd.available, nd.ask = old
            root.destroy()

    @unittest.skipUnless(__import__("os").environ.get("DEBTORS_NATIVE_E2E") == "1" and sys.platform == "darwin",
                         "ручная проверка: DEBTORS_NATIVE_E2E=1, откроет окно macOS на секунду")
    def test_macos_dialog_end_to_end(self):
        import subprocess
        import native_date as nd
        cmd, kw = nd.build_command("2026-10-09", True, "Проверка", auto="ok")
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw).stdout
        self.assertEqual(nd.parse_output(out), ("pick", date(2026, 10, 9)))


if __name__ == "__main__":
    unittest.main()
