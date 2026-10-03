"""Адрес из двух колонок («Улица» + «Дом») и организации по домам: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402
import orgs  # noqa: E402

HEAD = ["УК", "Улица", "Дом", "Кв", "ЛС", "ФИО", "Тип", "Сальдо"]
ROWS = [
    ['ООО УО "Василёк"', "2-й пер", "114", "н/п1", 1, "ИВАНОВА А.А.", "Владелец", 12289.38],
    ['ООО УО "Василёк"', "Тестовая ул", "19-3 (нежилые)", "н/п", 2, "ПЕТРОВА Б.Б.", "Владелец", 8108.02],
    ['ООО УО "Василёк"', "Чужая ул", 5.0, "3", 3, "СИДОРОВ В.В.", "Владелец", 700.0],
    ['ООО УО "Василёк"', "2-й пер", "114", "н/п2", 4, "ОБЩЕСТВО ЛАНДЫШ", "Владелец", 900.0],
]


class AddressColumnsTest(unittest.TestCase):
    def test_guess_finds_street_and_house_columns(self):
        g = core.guess_columns(HEAD)
        self.assertEqual((g["addr_col"], g["house_col"], g["debt_col"]), ("Улица", "Дом", "Сальдо"))
        # колонка «Дом» стоит раньше «Улицы» — адресом всё равно считается улица
        g2 = core.guess_columns(["Дом", "Улица", "ФИО", "Долг"])
        self.assertEqual((g2["addr_col"], g2["house_col"]), ("Улица", "Дом"))
        # один столбец «Адрес» — отдельной колонки дома нет
        self.assertIsNone(core.guess_columns(["Адрес", "Кв", "ФИО", "Долг"])["house_col"])

    def test_row_address_joins_street_and_house(self):
        idx = {h: i for i, h in enumerate(HEAD)}
        self.assertEqual(core.row_address(ROWS[0], idx, "Улица", "Дом"), "2-й пер 114")
        self.assertEqual(core.row_address(ROWS[2], idx, "Улица", "Дом"), "Чужая ул 5")            # 5.0 → «5»
        self.assertEqual(core.row_address(ROWS[0], idx, "Улица", None), "2-й пер")              # без колонки дома — как раньше
        self.assertEqual(core.row_address(["Х ул 1, кв. 2"], {"А": 0}, "А", "нет"), "Х ул 1, кв. 2")

    def test_houses_filter_uses_combined_address(self):
        org = orgs.Organization(name="Василёк", houses=["2-й пер 114", "Тестовая ул 19-3"])
        s = core.Settings(name_col="ФИО", debt_col="Сальдо", addr_col="Улица", house_col="Дом", flat_col="Кв",
                          skip_nonresidential=False)
        r = core.process(core.Sheet(HEAD, [list(x) for x in ROWS]), s, org)
        self.assertEqual([row[5] for row in r.top], ["ИВАНОВА А.А.", "ПЕТРОВА Б.Б."])     # чужой дом и организация отсеяны
        self.assertEqual(r.stats["дома других организаций"], 1)
        # без колонки дома совпадений с «2-й пер 114» нет — именно так и получался пустой список
        s2 = core.Settings(name_col="ФИО", debt_col="Сальдо", addr_col="Улица", flat_col="Кв", skip_nonresidential=False)
        self.assertEqual(core.process(core.Sheet(HEAD, [list(x) for x in ROWS]), s2, org).top, [])


if __name__ == "__main__":
    unittest.main()
