import _isolate                      # DEBTORS_HOME во временную папку, до импорта storage
HOME = _isolate.HOME
import json
import os
import stat
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

import app
import claimlog
import core
import orgs
import owners
import storage
import updates


class ClaimLogFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = storage.CLAIMS_PATH
        self.addCleanup(setattr, storage, "CLAIMS_PATH", old)
        storage.CLAIMS_PATH = Path(self.tmp.name) / "claims.json"

    def test_clamp_days(self):
        self.assertEqual([claimlog.clamp_days(v) for v in ("40", 0, "-5", "abc", "", None, 3_000_000, "365", 366)],
                         [40, 1, 1, 40, 40, 40, 365, 365, 365])

    def test_huge_term_does_not_overflow_status(self):
        claimlog.mark_sent([("Х ул 1", "1")], date(2026, 1, 1))
        rec = claimlog.get("Х ул 1", "1")
        self.assertEqual(claimlog.status(rec, claimlog.clamp_days(3_000_000), date(2027, 6, 1)), claimlog.OVERDUE)

    @unittest.skipIf(sys.platform == "win32", "права файлов POSIX")
    def test_claims_file_is_private_and_import_keeps_it_private(self):
        claimlog.mark_sent([("Х ул 1", "1")], date(2026, 1, 1))
        self.assertEqual(stat.S_IMODE(os.stat(storage.CLAIMS_PATH).st_mode), 0o600)
        z = Path(self.tmp.name) / "d.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("claims.json", json.dumps({"schema_version": 1, "records": {}}))
        target = Path(self.tmp.name) / "target"
        target.mkdir()
        storage.import_data(z, target)
        self.assertEqual(stat.S_IMODE(os.stat(target / "claims.json").st_mode), 0o600)

    def test_overdue_is_in_natural_order(self):
        claimlog.mark_sent([("Ленина ул 10", "2"), ("Ленина ул 2", "10"), ("Ленина ул 2", "2"), ("Ленина ул 2", "1")], date(2026, 1, 1))
        got = [(r["address"], r["flat"]) for r in claimlog.overdue(40, date(2026, 6, 1))]
        self.assertEqual(got, [("Ленина ул 2", "1"), ("Ленина ул 2", "2"), ("Ленина ул 2", "10"), ("Ленина ул 10", "2")])

    def test_overdue_accepts_preloaded_data(self):
        claimlog.mark_sent([("Х ул 1", "1")], date(2026, 1, 1))
        data = claimlog._load()
        storage.CLAIMS_PATH.unlink()
        self.assertEqual(len(claimlog.overdue(40, date(2026, 6, 1), data=data)), 1)


class LookupHelpersTest(unittest.TestCase):
    def test_court_map_matches_house_court(self):
        org = orgs.Organization(name="О", houses=[{"address": "Тестовая ул 1", "court": "61MS1"}, {"address": "тестовая ул 1", "court": "61MS2"},
                                                  {"address": "Тестовая ул 2", "court": ""}])
        m = orgs.court_map(org)
        for addr in ("Тестовая ул 1", "ТЕСТОВАЯ УЛ 2", "Нет ул 9"):
            self.assertEqual(m.get(orgs.norm_addr(addr), ""), orgs.house_court(org, addr))

    def test_get_or_new_uses_preloaded_cards(self):
        cards = {owners.make_key("Тестовая ул 1", "5"): {"address": "Тестовая ул 1", "flat": "5", "owners": [{"passport": "1"}]}}
        old = owners._load_all
        owners._load_all = lambda: self.fail("owners.json не должен читаться заново")
        try:
            self.assertEqual(owners.get_or_new("Тестовая ул 1", "5", cards).owners[0].passport, "1")
            self.assertEqual(owners.get_or_new("Тестовая ул 1", "6", cards).flat, "6")
        finally:
            owners._load_all = old


class AppFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        saved = (storage.CLAIMS_PATH, app.save_settings, app.messagebox.showinfo, app.messagebox.askyesno, updates.check, owners._load_all)

        def restore():
            storage.CLAIMS_PATH, app.save_settings, app.messagebox.showinfo, app.messagebox.askyesno, updates.check, owners._load_all = saved
        self.addCleanup(restore)                                   # регистрируется до подмен: сработает и при skipTest
        storage.CLAIMS_PATH = Path(self.tmp.name) / "claims.json"
        app.save_settings = lambda s: None
        self.shown = []
        app.messagebox.showinfo = lambda *a, **kw: self.shown.append(a[1])
        app.messagebox.askyesno = lambda *a, **kw: False
        try:
            self.app = app.App()
        except Exception:
            self.skipTest("нет дисплея")
        self.addCleanup(self.app.destroy)

    def load(self, n=4):
        a, s = self.app, self.app.settings
        s.addr_col, s.flat_col, s.name_col, s.debt_col = "Адрес", "Кв", "ФИО", "Долг"
        for key, val in (("addr_col", "Адрес"), ("flat_col", "Кв"), ("name_col", "ФИО"), ("debt_col", "Долг")):
            a.col_vars[key].set(val)
        h = ["ФИО", "Адрес", "Кв", "Долг"]
        rows = [[f"Иванов {i}", "Тестовая ул 1", str(i + 1), "1 000,00"] for i in range(n)]
        a.result = core.Result(h, rows, [1000.0] * n, {})
        a.show_rows(h, rows, numbered=True)
        a.update()

    def wait(self, cond, seconds=3):
        end = time.time() + seconds
        while time.time() < end and not cond():
            self.app.update()
            time.sleep(0.02)
        return cond()

    # --- сортировка колонок «Претензия» и «Приказ»
    def test_claim_column_sorts_by_status_then_date_and_empty_last(self):
        self.load()
        a, t = self.app, date.today()
        claimlog.mark_sent([("Тестовая ул 1", "1")], t - timedelta(days=5))       # idx 0: ждём ответа
        claimlog.mark_sent([("Тестовая ул 1", "2")], t - timedelta(days=50))      # idx 1: срок истёк
        claimlog.mark_sent([("Тестовая ул 1", "3")], t - timedelta(days=20))      # idx 2: ждём ответа, раньше idx 0
        a.after_claims_changed()
        a.sort_view("c4")
        self.assertEqual(a.order_all, [2, 0, 1, 3])                              # по возрастанию, без отметки — в конце
        a.sort_view("c4")
        self.assertEqual(a.order_all, [1, 0, 2, 3])                              # по убыванию: строка без отметки всё равно последняя

    def test_claim_column_sorts_chronologically_across_months(self):
        self.load(3)
        a = self.app
        claimlog.mark_sent([("Тестовая ул 1", "1")], date(2026, 1, 15))
        claimlog.mark_sent([("Тестовая ул 1", "2")], date(2026, 10, 4))
        claimlog.mark_sent([("Тестовая ул 1", "3")], date(2026, 2, 4))
        a.settings.claim_reply_days = 3650
        a.claim_days_var.set("365")
        a.after_claims_changed()
        a.sort_view("c4")
        self.assertEqual(a.order_all, [0, 2, 1])                                 # 15.01, 04.02, 04.10 (раньше шло по дню месяца)

    def test_court_column_sorts_empty_last_in_both_directions(self):
        self.load(5)
        a = self.app
        claimlog.mark_court([("Тестовая ул 1", "2")], date(2026, 3, 1))
        claimlog.mark_court([("Тестовая ул 1", "4")], date(2026, 1, 5))
        a.after_claims_changed()
        a.sort_view("c5")
        self.assertEqual(a.order_all[:2], [3, 1])
        a.sort_view("c5")
        self.assertEqual(a.order_all[:2], [1, 3])
        self.assertEqual(sorted(a.order_all[2:]), [0, 2, 4])

    # --- сводка проверки
    def test_precheck_summary_groups_by_kind_not_by_date(self):
        self.load(5)
        a, t = self.app, date.today()
        claimlog.mark_sent([("Тестовая ул 1", "1"), ("Тестовая ул 1", "2")], t - timedelta(days=3))
        claimlog.mark_sent([("Тестовая ул 1", "3")], t - timedelta(days=9))
        a.after_claims_changed()
        summary, rows = a.check_problems("claims", [0, 1, 2, 3, 4])
        self.assertEqual(len(rows), 3)
        self.assertEqual(summary.count("уже отправлена"), 1, summary)
        self.assertIn("3 из 5", summary)
        self.assertTrue(summary[0].isupper())

    # --- срок ответа
    def test_typed_term_is_clamped_and_applied_after_a_pause(self):
        self.load(2)
        a = self.app
        calls = []
        a.after_claims_changed = lambda: calls.append(1)
        a.claim_days_var.set("3000000")
        a.claim_days_var.set("3000001")                                           # два изменения подряд — один пересчёт
        self.assertEqual((a.claim_days(), a.collect_settings().claim_reply_days), (claimlog.MAX_DAYS, claimlog.MAX_DAYS))
        self.assertTrue(self.wait(lambda: calls))
        self.assertEqual(calls, [1])
        claimlog.mark_sent([("Тестовая ул 1", "1")], date(2026, 1, 1))
        del a.after_claims_changed
        a.compute_claim_marks()                                                   # раньше при огромном сроке падало OverflowError

    def test_claim_actions_do_not_recompute_cards(self):
        self.load(3)
        a = self.app
        counter = []
        real = a.compute_card_flags
        a.compute_card_flags = lambda: (counter.append(1), real())[1]
        a.after_claims_changed()
        self.assertEqual(counter, [])

    # --- окна
    def test_orgs_editor_is_a_single_window(self):
        a = self.app
        first = a.edit_orgs()
        self.assertIs(a.edit_orgs(), first)
        first.destroy()
        second = a.edit_orgs()
        self.assertIsNot(second, first)
        second.destroy()

    def test_court_jobs_reads_owners_once(self):
        self.load(4)
        a = self.app
        reads = []
        owners._load_all = lambda: (reads.append(1), {})[1]
        a.court_jobs([0, 1, 2, 3])
        self.assertEqual(len(reads), 1)

    # --- проверка обновлений
    def test_update_worker_failure_is_reported_and_not_polled_forever(self):
        a = self.app

        def boom(current):
            raise RuntimeError("сбой")
        updates.check = boom
        a.app_version = lambda: "1.0.19"
        a.start_update_check(manual=True)
        self.assertTrue(self.wait(lambda: self.shown))
        self.assertIn("Не удалось проверить", self.shown[0])
        self.assertFalse(a._update_busy)

    def test_second_update_check_is_ignored_while_one_runs(self):
        a = self.app
        calls = []
        updates.check = lambda current: (calls.append(1), ("current", {"tag": current}))[1]
        a.app_version = lambda: "1.0.19"
        a._update_busy = True
        a.start_update_check(manual=True)
        self.assertEqual(calls, [])

    def test_settings_are_not_written_after_import(self):
        a = self.app
        written = []
        app.save_settings = lambda s: written.append(1)
        a._settings_frozen = True
        a.save_settings_now()
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
