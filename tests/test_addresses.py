"""Очистка адреса дома: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orgs  # noqa: E402
from claim import split_address  # noqa: E402


class AddressTest(unittest.TestCase):
    def test_clean(self):
        cases = {
            "Калинина ул 113, кв. 5": "Калинина ул 113",
            "Калинина ул 113 кв 5": "Калинина ул 113",
            "Водопроводная ул 13, пом. 3": "Водопроводная ул 13",
            "Инструментальная ул 19-3 (жилые)": "Инструментальная ул 19-3",
            "Инструментальная ул 19-3 (нежилые)": "Инструментальная ул 19-3",
            "Чехова ул 337,": "Чехова ул 337",
            "Лизы Чайкиной ул 31.": "Лизы Чайкиной ул 31",
            "Комарова ул 4": "Комарова ул 4",
        }
        for src, want in cases.items():
            self.assertEqual(orgs.clean_house_address(src), want, src)

    def test_flat_in_address(self):
        """В отчётах квартира бывает записана в адресе: «Новый пер 100-5-к.1»."""
        self.assertEqual(orgs.addr_flat("7-й Новый пер 100-5-к.1", ""), ("7-й Новый пер 100-5", "1"))
        self.assertEqual(orgs.addr_flat("7-й Новый пер 100-5-к.2", None), ("7-й Новый пер 100-5", "2"))
        self.assertEqual(orgs.addr_flat("Калинина ул 113, кв. 5", ""), ("Калинина ул 113", "5"))
        self.assertEqual(orgs.addr_flat("Новый пер 100-5-к.1", "7"), ("Новый пер 100-5", "7"))  # колонка «Кв» приоритетнее
        self.assertEqual(orgs.addr_flat("17-й Новый пер 1", ""), ("17-й Новый пер 1", ""))
        self.assertEqual(orgs.norm_addr("7-й Новый пер 100-5-к.1"), orgs.norm_addr("7-й Новый пер 100-5-к.2"))

    def test_corpus_is_part_of_house(self):
        self.assertEqual(split_address("Красный пер 19 корп 2"), ("пер. Красный", "19 корп 2"))

    def test_same_house_matches(self):
        self.assertEqual(orgs.norm_addr("Калинина ул 113, кв. 5"), orgs.norm_addr("калинина ул. 113"))
        self.assertEqual(orgs.norm_addr("Инструментальная ул 19-3 (жилые)"), orgs.norm_addr("Инструментальная ул 19-3 (нежилые)"))

    def test_split(self):
        self.assertEqual(split_address("Калинина ул 113, кв. 5"), ("ул. Калинина", "113"))
        self.assertEqual(split_address("10-й пер 114"), ("пер. 10-й", "114"))


if __name__ == "__main__":
    unittest.main()
