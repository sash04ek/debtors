"""Отбор только домов, которые сейчас в управлении: python -m unittest discover tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402
import orgs  # noqa: E402

TODAY = date(2026, 10, 1)


class IsManagedTest(unittest.TestCase):
    def test_empty_means_not_managed(self):
        self.assertFalse(orgs.is_managed("", TODAY))
        self.assertFalse(orgs.is_managed("   ", TODAY))

    def test_single_date_in_past_or_future(self):
        self.assertTrue(orgs.is_managed("01.06.2015г", TODAY))
        self.assertTrue(orgs.is_managed("01.06.2015г.", TODAY))
        self.assertTrue(orgs.is_managed("01.06.15", TODAY))
        self.assertFalse(orgs.is_managed("01.12.2026г", TODAY))                 # ещё не начался

    def test_left_marker(self):
        self.assertFalse(orgs.is_managed("01.06.2015г ушел", TODAY))

    def test_period_is_managed_only_inside(self):
        self.assertFalse(orgs.is_managed("01.12.2019г-01.11.2020гг", TODAY))
        self.assertFalse(orgs.is_managed("01.07.2019-01.09.2019гг", TODAY))
        self.assertTrue(orgs.is_managed("01.01.2026-31.12.2026", TODAY))

    def test_text_without_date_counts_as_filled(self):
        self.assertTrue(orgs.is_managed("с начала", TODAY))


class FilterTest(unittest.TestCase):
    def _run(self, only_managed):
        org = orgs.Organization(name="О", match="О", houses=[
            {"address": "А ул 1", "since": "01.06.2015г", "court": ""},
            {"address": "Б ул 2", "since": "", "court": ""},
            {"address": "В ул 3", "since": "01.06.2015г ушел", "court": ""}])
        sheet = core.Sheet(headers=["ФИО", "Адрес", "Долг"], rows=[
            ["Иванов Иван Иванович", "А ул 1", 1000], ["Петров Пётр Петрович", "Б ул 2", 2000],
            ["Сидоров Сидор Сидорович", "В ул 3", 3000], ["Орлов Олег Олегович", "Г ул 4", 4000]])
        s = core.Settings(name_col="ФИО", debt_col="Долг", addr_col="Адрес", only_managed=only_managed)
        return core.process(sheet, s, org)

    def test_switch_off_keeps_all_houses_of_organization(self):
        r = self._run(False)
        self.assertEqual(len(r.top), 3)
        self.assertEqual(r.stats["дома не в управлении"], 0)

    def test_switch_on_keeps_only_managed_houses(self):
        r = self._run(True)
        self.assertEqual([row[0] for row in r.top], ["Иванов Иван Иванович"])
        self.assertEqual(r.stats["дома не в управлении"], 2)
        self.assertEqual(r.stats["дома других организаций"], 1)


if __name__ == "__main__":
    unittest.main()
