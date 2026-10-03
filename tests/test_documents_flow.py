import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import app
import core
import owners


class DocumentsFlowTest(unittest.TestCase):
    def setUp(self):
        self.old = (owners._load_all, app.save_settings, app.messagebox.askyesno, app.messagebox.showinfo,
                    app.messagebox.showerror)
        owners._load_all = lambda: {}
        app.save_settings = lambda s: None
        self.asked = []
        app.messagebox.askyesno = lambda title, text, **kw: (self.asked.append(text), False)[1]
        app.messagebox.showinfo = lambda *a, **kw: None
        app.messagebox.showerror = lambda *a, **kw: self.fail(f"ошибка: {a}")
        self.app = app.App()
        for o in self.app.orgs:                            # доверенности из реальных данных не должны попадать в проверяемую папку
            o.poa_mail = o.poa_court = ""
        self.out = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.app.destroy()
        (owners._load_all, app.save_settings, app.messagebox.askyesno, app.messagebox.showinfo,
         app.messagebox.showerror) = self.old

    def _prepare(self, n=5):
        a = self.app
        s = a.settings
        s.addr_col, s.flat_col, s.name_col, s.debt_col = "Адрес", "Кв", "ФИО", "Долг"
        for key, val in (("addr_col", "Адрес"), ("flat_col", "Кв"), ("name_col", "ФИО"), ("debt_col", "Долг")):
            a.col_vars[key].set(val)                       # настройки читаются из переменных окна
        h = ["ФИО", "Адрес", "Кв", "Долг"]
        rows = [[f"Иванов Иван {i}", "ул. Тестовая, д. 1", str(i + 1), "1 000,00"] for i in range(n)]
        a.result = core.Result(h, rows, [1000.0] * n, {})
        a.show_rows(h, rows, numbered=True)
        a.update()

    def _accept(self, dlg_holder):
        """Подтверждает диалог создания: выбирает временную папку и нажимает «Создать»."""
        def go():
            dlg = [w for w in self.app.winfo_children() if isinstance(w, app.DocsDialog)][0]
            dlg.folder = self.out
            dlg.accept()
        self.app.after(200, go)

    def test_claims_and_letter_into_chosen_folder_with_progress(self):
        self._prepare(5)
        a = self.app
        holder = []
        self._accept(holder)
        a.create_docs("claims")
        self.assertEqual(len(list(self.out.glob("*.docx"))), 5)
        self.assertEqual(a.settings.out_dir, str(self.out))
        self.assertIn("Открыть папку", self.asked[-1])
        self._accept(holder)
        a.create_docs("letter")
        self.assertEqual(len(list(self.out.glob("Письмо*.docx"))), 1)

    def test_court_reports_problems_and_creates_applications(self):
        self._prepare(3)
        a = self.app
        summary, rows = a.check_problems("court", a.checked_indexes())
        self.assertEqual(len(rows), 3)
        self.assertIn("нет персональных данных", summary)
        self._accept([])
        orig = app.CourtChoiceDialog
        app.CourtChoiceDialog = lambda *args, **kw: type("D", (), {"result": ""})()
        real_wait = a.wait_window
        a.wait_window = lambda w: real_wait(w) if isinstance(w, tk.Toplevel) else None
        try:
            a.create_docs("court")
        finally:
            app.CourtChoiceDialog = orig
        self.assertEqual(len(list(self.out.glob("*.docx"))), 3)


if __name__ == "__main__":
    unittest.main()
