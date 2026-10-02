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
        self.root = tk.Tk()
        self.root.update()

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
