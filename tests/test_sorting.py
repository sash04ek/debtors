"""Сортировка списка должников: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402

HEAD = ["Адрес", "Кв", "ФИО", "Долг", "Дата посл опл"]
ROWS = [
    ["Бабушкина ул 47", "10", "Иванов Иван Иванович", 500.0, "01.03.2020"],
    ["Бабушкина ул 47", "2", "Петров Пётр Петрович", 900.0, "15.01.2019"],
    ["Абрикосовая ул 3", "1", "Сидорова Анна Сергеевна", 700.0, ""],
    ["Чехова ул 322", "5", "Кузнецов Олег Павлович", 100.0, "10.12.2021"],
    ["Абрикосовая ул 10", "3", "Морозова Мария Ивановна", 900.0, "05.05.2018"],
]


def names(sort_col=None, desc=True, top_n=20):
    s = core.Settings(top_n=top_n, name_col="ФИО", debt_col="Долг", addr_col="Адрес", flat_col="Кв",
                      sort_col=sort_col, sort_desc=desc)
    r = core.process(core.Sheet(HEAD, [list(x) for x in ROWS]), s)
    return [row[2].split()[0] for row in r.top]


class SortTest(unittest.TestCase):
    def test_default_is_debt_descending(self):
        # при равном долге 900 порядок как в файле (Петров раньше Морозовой)
        self.assertEqual(names(), ["Петров", "Морозова", "Сидорова", "Иванов", "Кузнецов"])

    def test_debt_ascending(self):
        self.assertEqual(names(desc=False), ["Кузнецов", "Иванов", "Сидорова", "Петров", "Морозова"])

    def test_text_column_natural_order(self):
        self.assertEqual(names("Адрес", desc=False),
                         ["Сидорова", "Морозова", "Петров", "Иванов", "Кузнецов"])   # «ул 3» раньше «ул 10»;
                         # при одном адресе — по убыванию долга (Петров 900 выше Иванова 500)
        self.assertEqual(names("Адрес", desc=True)[0], "Кузнецов")

    def test_flat_numbers_sort_numerically(self):
        self.assertEqual(names("Кв", desc=False), ["Сидорова", "Петров", "Морозова", "Кузнецов", "Иванов"])   # 1, 2, 3, 5, 10

    def test_dates_sort_as_dates_and_empty_go_last(self):
        self.assertEqual(names("Дата посл опл", desc=False),
                         ["Морозова", "Петров", "Иванов", "Кузнецов", "Сидорова"])      # 2018, 2019, 2020, 2021, пусто
        self.assertEqual(names("Дата посл опл", desc=True),
                         ["Кузнецов", "Иванов", "Петров", "Морозова", "Сидорова"])      # пустая дата в конце и при убывании

    def test_sort_happens_before_top_n_cut(self):
        self.assertEqual(names("Дата посл опл", desc=False, top_n=2), ["Морозова", "Петров"])
        self.assertEqual(names(top_n=2), ["Петров", "Морозова"])

    def test_unknown_sort_column_falls_back_to_debt(self):
        self.assertEqual(names("Нет такой колонки"), names())

    def test_view_helper_handles_money_strings(self):
        vals = ["177 348,10", "9 000,00", "153 247,78", ""]
        self.assertEqual(core.sort_by_values(vals, lambda v: v, desc=True), ["177 348,10", "153 247,78", "9 000,00", ""])
        self.assertEqual(core.sort_by_values(vals, lambda v: v, desc=False), ["9 000,00", "153 247,78", "177 348,10", ""])


if __name__ == "__main__":
    unittest.main()
