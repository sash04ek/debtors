"""Фильтрация сразу при открытии файла."""
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

import app
import orgs


class AutoFilterTest(unittest.TestCase):
    def setUp(self):
        self.old = app.save_settings
        app.save_settings = lambda s: None
        self.a = app.App()
        self.a.restore_last_state = lambda: None
        self.a.orgs = [orgs.Organization(name="О", match="О")]
        self.a.org_cb["values"] = ["О"]
        self.a.org_cb.set("О")
        wb = Workbook()
        ws = wb.active
        ws.append(["ФИО", "Долг"])
        ws.append(["Иванов Иван Иванович", 1000])
        ws.append(["Петров Пётр Петрович", 5000])
        self.path = Path(tempfile.mkdtemp()) / "отчёт.xlsx"
        wb.save(self.path)
        self.a.update()

    def tearDown(self):
        self.a.destroy()
        app.save_settings = self.old

    def test_default_is_on(self):
        self.assertTrue(app.core.Settings().auto_filter)

    def test_open_filters_immediately_when_enabled(self):
        self.a.auto_filter_var.set(True)
        self.assertTrue(self.a.open_path(self.path))
        self.assertIsNotNone(self.a.result)
        self.assertEqual(len(self.a.result.top), 2)
        self.assertEqual(self.a.filter_btn.cget("text"), "Сбросить фильтр")

    def test_open_only_loads_when_disabled(self):
        self.a.auto_filter_var.set(False)
        self.assertTrue(self.a.open_path(self.path))
        self.assertIsNone(self.a.result)
        self.assertEqual(self.a.filter_btn.cget("text"), "Фильтровать")

    def test_restoring_state_does_not_double_filter(self):
        self.a.auto_filter_var.set(True)
        self.a._restoring = True
        self.assertTrue(self.a.open_path(self.path, quiet=True))
        self.assertIsNone(self.a.result)


if __name__ == "__main__":
    unittest.main()
