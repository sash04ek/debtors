"""Порции отбора «следующие N»: python -m unittest discover tests"""
import _isolate                      # DEBTORS_HOME во временную папку, до импорта storage
HOME = _isolate.HOME
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from openpyxl import load_workbook

import app
import core

HEAD = ["Адрес", "Кв", "ФИО", "Долг"]
# 7 должников с долгом 700, 600 … 100 и одна организация — она в порции не попадает
ROWS = [["Тестовая ул 1", str(i), f"Иванов{'а' * i} Иван", 100.0 * (8 - i)] for i in range(1, 8)]
ROWS.insert(3, ["Тестовая ул 1", "99", "ООО «Ромашка»", 5000.0])


def settings(top_n=3):
    return core.Settings(top_n=top_n, name_col="ФИО", debt_col="Долг", addr_col="Адрес", flat_col="Кв")


def debts(res):
    return [int(a) for a in res.amounts]


class ProcessOffsetTest(unittest.TestCase):
    def sheet(self):
        return core.Sheet(HEAD, [list(r) for r in ROWS])

    def test_batches_follow_each_other_until_debtors_end(self):
        s = settings(3)
        self.assertEqual(debts(core.process(self.sheet(), s)), [700, 600, 500])
        self.assertEqual(debts(core.process(self.sheet(), s, offset=3)), [400, 300, 200])
        last = core.process(self.sheet(), s, offset=6)
        self.assertEqual(debts(last), [100])                                    # последняя порция — сколько осталось
        self.assertEqual((last.offset, last.stats["отобрано с №"], last.stats["отобрано по №"]), (6, 7, 7))
        self.assertEqual(last.stats["физлиц с долгом"], 7)

    def test_offset_is_clamped(self):
        s = settings(3)
        self.assertEqual(core.process(self.sheet(), s, offset=50).offset, 6)    # за концом — последняя порция
        self.assertEqual(core.process(self.sheet(), s, offset=-5).offset, 0)
        empty = core.process(core.Sheet(HEAD, []), s, offset=3)
        self.assertEqual((empty.offset, empty.top, empty.stats["отобрано с №"]), (0, [], 0))

    def test_export_numbers_continue_and_roundtrip(self):
        res = core.process(self.sheet(), settings(3), offset=3)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "batch.xlsx"
            core.export(res, p, "Долг", {})
            wb = load_workbook(p)
            ws = wb["Топ-4–6 должников"]
            self.assertEqual([ws.cell(r, 1).value for r in (2, 3, 4)], [4, 5, 6])  # № сквозные, не с 1
            self.assertEqual(core.detect_file_kind(p)[1]["offset"], 3)
            back = core.read_filtered(p)
            self.assertEqual(len(back["rows"]), 3)
            self.assertEqual(back["meta"]["offset"], 3)

    def test_file_name_shows_batch(self):
        self.assertEqual(app.export_file_name("", "отчёт", 20), "отчёт_топ20.xlsx")
        self.assertEqual(app.export_file_name("", "отчёт", 20, 20), "отчёт_топ21-40.xlsx")
        self.assertEqual(app.export_file_name("", "", 7, 40), "должники_41-47.xlsx")


class AppBatchTest(unittest.TestCase):
    def setUp(self):
        saved = (app.save_settings, app.messagebox.showinfo, app.messagebox.showerror)

        def restore():
            app.save_settings, app.messagebox.showinfo, app.messagebox.showerror = saved
        self.addCleanup(restore)
        app.save_settings = lambda s: None
        app.messagebox.showinfo = lambda *a, **kw: None
        app.messagebox.showerror = lambda *a, **kw: self.fail(a)
        try:
            self.app = app.App()
        except tk.TclError:
            self.skipTest("нет дисплея")
        self.addCleanup(self.app.destroy)
        a = self.app
        a.save_state = lambda: None                                             # state.json этого теста не нужен
        for o in a.orgs:
            o.houses = []                                                       # все строки файла — без отбора по домам
        a.sheet, a.kind = core.Sheet(HEAD, [list(r) for r in ROWS]), "original"
        for key, val in (("addr_col", "Адрес"), ("flat_col", "Кв"), ("name_col", "ФИО"), ("debt_col", "Долг"),
                         ("house_col", app.NONE)):
            a.col_vars[key].set(val)
        a.top_n.set(3)

    def state(self, btn):
        return str(btn.cget("state"))

    def test_next_and_previous_batches(self):
        a = self.app
        self.assertEqual(self.state(a.next_batch_btn), "disabled")             # до фильтра листать нечего
        self.assertTrue(a.run())
        self.assertEqual(debts(a.result), [700, 600, 500])
        self.assertEqual((self.state(a.prev_batch_btn), self.state(a.next_batch_btn)), ("disabled", "normal"))
        self.assertEqual(a.next_batch_btn.cget("text"), "Следующие 3 ▶")
        a.shift_batch(1)
        self.assertEqual(debts(a.result), [400, 300, 200])
        self.assertEqual(a.service_values(0)[1], 4)                            # № в таблице сквозной
        self.assertEqual(a.next_batch_btn.cget("text"), "Следующие 1 ▶")       # осталось меньше порции
        self.assertIn("№ 4–6 из 7", a.stats_lbl.cget("text"))
        a.shift_batch(1)
        self.assertEqual(debts(a.result), [100])
        self.assertEqual((self.state(a.prev_batch_btn), self.state(a.next_batch_btn)), ("normal", "disabled"))
        a.shift_batch(-1)
        a.shift_batch(-1)
        self.assertEqual(a.result.offset, 0)
        a.on_filter_button()                                                   # сброс фильтра — порции недоступны
        self.assertEqual((self.state(a.prev_batch_btn), self.state(a.next_batch_btn)), ("disabled", "disabled"))
        a.on_filter_button()                                                   # новый фильтр — снова с начала
        self.assertEqual(a.result.offset, 0)

    def test_filtered_file_does_not_page(self):
        a = self.app
        a.run()
        a.kind = "filtered"
        a.update_batch_buttons()
        self.assertEqual((self.state(a.prev_batch_btn), self.state(a.next_batch_btn)), ("disabled", "disabled"))


if __name__ == "__main__":
    unittest.main()
