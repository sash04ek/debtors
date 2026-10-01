import unittest

import app
import core
import owners


class TableColumnsTest(unittest.TestCase):
    def test_reload_with_different_column_count_and_hidden_columns(self):
        """Регрессия: после скрытия колонок смена набора колонок (файл -> результат) роняла Tk."""
        old_load, old_save = owners._load_all, app.save_settings
        owners._load_all, app.save_settings = (lambda: {}), (lambda s: None)
        a = app.App()
        try:
            a.settings.addr_col, a.settings.flat_col, a.settings.debt_col, a.settings.name_col = "Адрес", "Кв", "Долг", "ФИО"
            a.settings.hidden_cols = ["Д3"]
            h = ["ФИО", "Адрес", "Кв", "Долг", "Опл", "Д1", "Д2", "Д3"]
            rows = [[f"n{i}", "ул. Т, д. 1", str(i), "1 234,50", float(i), "x", "x", "x"] for i in range(30)]
            for _ in range(3):
                a.show_rows(h, rows, numbered=False)
                a.result = core.Result(h, rows, [1.0] * 30, {})
                a.show_rows(h, rows, numbered=True)
                a.update()
            self.assertEqual(len(a.tree.get_children()), 30)
        finally:
            a.destroy()
            owners._load_all, app.save_settings = old_load, old_save


if __name__ == "__main__":
    unittest.main()


class CourtsEditorTest(unittest.TestCase):
    def test_opens_from_settings_and_remembers_query(self):
        """Регрессия: из «Настроек» окно судей открывалось пустым (родитель — не главное окно)."""
        old_save = app.save_settings
        app.save_settings = lambda s: None
        a = app.App()
        try:
            a.settings.courts_query = ""
            dlg = app.SettingsDialog(a)
            ed = app.CourtsEditorDialog(dlg)
            ed.update()
            self.assertEqual(len(ed.tree.get_children()), len(ed.shown))
            ed.query.set("Таганрог")
            ed.destroy()
            self.assertEqual(a.settings.courts_query, "Таганрог")
            dlg.destroy()
        finally:
            a.settings.courts_query = ""
            a.destroy()
            app.save_settings = old_save
