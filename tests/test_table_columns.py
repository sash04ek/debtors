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
            a.settings.addr_col, a.settings.flat_col, a.settings.debt_col = "Адрес", "Кв", "Долг"
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
