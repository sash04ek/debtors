import tkinter as tk
import unittest

import widgets


class PopupMenuTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("нет дисплея")
        self.root.theme_colors = ("#eeeeee", "#202020", "#303030")
        self.root.is_dark = True

    def tearDown(self):
        self.root.destroy()

    def rows(self, menu):
        return [w for w in menu._win.winfo_children()[0].winfo_children()[0].winfo_children() if isinstance(w, tk.Frame)]

    def test_command_runs_after_close(self):
        calls = []
        m = widgets.PopupMenu(self.root)
        m.add_command(label="Раз", command=lambda: calls.append(1))
        m.tk_popup(10, 10)
        self.assertTrue(m.is_open())
        m._invoke(m.entries[0], self.rows(m)[0])
        self.root.update_idletasks()
        self.assertEqual(calls, [1])
        self.assertFalse(m.is_open())

    def test_checkbutton_toggles_variable(self):
        var = tk.BooleanVar(self.root, value=False)
        m = widgets.PopupMenu(self.root)
        m.add_checkbutton(label="Флаг", variable=var)
        m.tk_popup(10, 10)
        m._invoke(m.entries[0], self.rows(m)[0])
        self.assertTrue(var.get())

    def test_delete_index_type_entryconfig(self):
        m = widgets.PopupMenu(self.root)
        self.assertIsNone(m.index("end"))
        m.add_command(label="a")
        m.add_separator()
        m.add_command(label="b")
        self.assertEqual((m.index("end"), m.type(1)), (2, "separator"))
        m.entryconfig(2, state="disabled")
        self.assertEqual(m.entrycget(2, "state"), "disabled")
        m.delete(0, "end")
        self.assertEqual(m.entries, [])

    def test_empty_menu_not_shown_and_postcommand_fills(self):
        m = widgets.PopupMenu(self.root, postcommand=lambda: m.add_command(label="x"))
        m.tk_popup(0, 0)
        self.assertTrue(m.is_open())
        m.unpost()
        self.assertFalse(m.is_open())

    def test_submenu_opens_and_root_closes_both(self):
        sub = widgets.PopupMenu(self.root)
        sub.add_command(label="s")
        m = widgets.PopupMenu(self.root)
        m.add_cascade(label="Ещё", menu=sub)
        m.tk_popup(10, 10)
        m._invoke(m.entries[0], self.rows(m)[0])
        self.assertTrue(sub.is_open())
        m.unpost()
        self.assertFalse(sub.is_open() or m.is_open())

    def test_new_menu_nested_on_non_mac(self):
        import app
        old = app._is_mac
        app._is_mac = lambda r: False
        try:
            outer = app.new_menu(self.root)
            inner = app.new_menu(outer)
        finally:
            app._is_mac = old
        self.assertIsInstance(inner, widgets.PopupMenu)
        self.assertIs(inner.parent, self.root)


if __name__ == "__main__":
    unittest.main()
