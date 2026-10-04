import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path

import app
import claimlog
import core
import precheck
import storage


class ClaimLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = storage.CLAIMS_PATH
        storage.CLAIMS_PATH = Path(self.tmp.name) / "claims.json"

    def tearDown(self):
        storage.CLAIMS_PATH = self.old
        self.tmp.cleanup()

    def test_mark_status_and_due_date(self):
        claimlog.mark_sent([("Тестовая ул 1", "5"), ("Тестовая ул 1", "6")], date(2026, 1, 1), "Орг")
        rec = claimlog.get("Тестовая ул 1", "5")
        self.assertEqual(claimlog.due_date(rec, 40), date(2026, 2, 10))
        self.assertEqual(claimlog.status(rec, 40, date(2026, 2, 9)), claimlog.SENT)
        self.assertEqual(claimlog.status(rec, 40, date(2026, 2, 10)), claimlog.OVERDUE)       # на 40-й день срок уже вышел
        self.assertEqual(claimlog.status(None, 40), "")

    def test_days_setting_changes_deadline(self):
        claimlog.mark_sent([("Тестовая ул 1", "5")], date(2026, 1, 1))
        rec = claimlog.get("Тестовая ул 1", "5")
        self.assertEqual(claimlog.status(rec, 10, date(2026, 1, 12)), claimlog.OVERDUE)
        self.assertEqual(claimlog.status(rec, 60, date(2026, 1, 12)), claimlog.SENT)

    def test_overdue_list_sorted_and_close_removes_reminder(self):
        claimlog.mark_sent([("Тестовая ул 2", "1")], date(2026, 1, 5))
        claimlog.mark_sent([("Тестовая ул 1", "1")], date(2026, 1, 1))
        claimlog.mark_sent([("Тестовая ул 3", "1")], date(2026, 3, 1))
        due = claimlog.overdue(40, date(2026, 3, 1))
        self.assertEqual([r["address"] for r in due], ["Тестовая ул 1", "Тестовая ул 2"])    # давние первыми, свежая не в списке
        self.assertEqual(due[0]["late"], 19)
        claimlog.close([("Тестовая ул 1", "1")], date(2026, 3, 2))
        self.assertEqual(claimlog.status(claimlog.get("Тестовая ул 1", "1"), 40, date(2026, 3, 5)), claimlog.CLOSED)
        self.assertEqual(len(claimlog.overdue(40, date(2026, 3, 1))), 1)

    def test_repeat_mark_resets_closed_and_unmark_removes(self):
        claimlog.mark_sent([("Х ул 1", "1")], date(2026, 1, 1))
        claimlog.close([("Х ул 1", "1")])
        claimlog.mark_sent([("Х ул 1", "1")], date(2026, 2, 1))
        self.assertEqual(claimlog.get("Х ул 1", "1")["closed"], "")
        self.assertEqual(claimlog.unmark([("Х ул 1", "1"), ("Нет ул 9", "9")]), 1)
        self.assertIsNone(claimlog.get("Х ул 1", "1"))

    def test_key_ignores_case_and_flat_spaces(self):
        claimlog.mark_sent([("Тестовая ул 1", "5 ")], date(2026, 1, 1))
        self.assertIsNotNone(claimlog.get("тестовая ул 1", "5"))

    def test_precheck_warns_about_already_sent_claim(self):
        import orgs
        org = orgs.Organization(name="О")
        self.assertEqual(precheck.row_issues("claims", org, "Х ул 1", claim_sent="01.01.2026"), ["претензия уже отправлена 01.01.2026"])
        self.assertEqual(precheck.row_issues("letter", org, "Х ул 1", claim_sent="01.01.2026"), [])


class ClaimUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (storage.CLAIMS_PATH, app.save_settings, app.messagebox.showinfo)
        storage.CLAIMS_PATH = Path(self.tmp.name) / "claims.json"
        app.save_settings = lambda s: None
        app.messagebox.showinfo = lambda *a, **kw: None
        try:
            self.app = app.App()
        except tk.TclError:
            self.skipTest("нет дисплея")

    def tearDown(self):
        self.app.destroy()
        storage.CLAIMS_PATH, app.save_settings, app.messagebox.showinfo = self.old
        self.tmp.cleanup()

    def load(self, n=3):
        a, s = self.app, self.app.settings
        s.addr_col, s.flat_col, s.name_col, s.debt_col = "Адрес", "Кв", "ФИО", "Долг"
        for key, val in (("addr_col", "Адрес"), ("flat_col", "Кв"), ("name_col", "ФИО"), ("debt_col", "Долг")):
            a.col_vars[key].set(val)
        h = ["ФИО", "Адрес", "Кв", "Долг"]
        rows = [[f"Иванов {i}", "Тестовая ул 1", str(i + 1), "1 000,00"] for i in range(n)]
        a.result = core.Result(h, rows, [1000.0] * n, {})
        a.show_rows(h, rows, numbered=True)
        a.update()

    def test_marks_shown_in_claim_column_and_overdue_banner(self):
        self.load()
        a = self.app
        claimlog.mark_sent([("Тестовая ул 1", "1")], date.today())
        claimlog.mark_sent([("Тестовая ул 1", "2")], date(2020, 1, 1))
        a.after_claims_changed()
        self.assertEqual(a.claim_marks[0].split()[0], "✉")
        self.assertEqual(a.claim_marks[1].split()[0], "⚠")
        self.assertEqual(a.claim_marks[2], "")
        self.assertIsNotNone(a.claims_bar)                                    # есть просроченная претензия
        vals = a.tree.item(a.tree.get_children()[0], "values")
        self.assertEqual(len(vals), app.N_SERVICE + 4)
        claimlog.close([("Тестовая ул 1", "2")])
        a.after_claims_changed()
        self.assertTrue(a.claim_marks[1].startswith("✓"))
        self.assertIsNone(a.claims_bar)

    def test_change_claims_for_checked_rows(self):
        self.load()
        a = self.app
        a.check_state = [True, False, True]
        claimlog.mark_sent([("Тестовая ул 1", "1"), ("Тестовая ул 1", "2")], date.today())
        a.change_claims("unmark")
        self.assertEqual(a.claim_marks, ["", "✉ " + claimlog.short(date.today().isoformat()), ""])
