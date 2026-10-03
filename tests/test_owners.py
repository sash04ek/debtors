"""Собственники помещения, доли и заявления на каждого: python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import court  # noqa: E402
import orgs  # noqa: E402
import owners as O  # noqa: E402
from docx import Document  # noqa: E402


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.old = O.OWNERS_PATH, O.TRASH_PATH
        tmp = Path(tempfile.mkdtemp())
        O.OWNERS_PATH, O.TRASH_PATH = tmp / "owners.json", tmp / "trash.json"

    def tearDown(self):
        O.OWNERS_PATH, O.TRASH_PATH = self.old

    def test_save_load_delete_roundtrip_with_several_owners(self):
        card = O.Card(address="Сызранова ул 28-1", flat="13", penalty="600",
                      owners=[O.Owner(fio="Иванов Иван", share="1/2"), O.Owner(fio="Петрова Анна", share="1/2")])
        O.save_card(card)
        self.assertEqual(oct(O.OWNERS_PATH.stat().st_mode & 0o777), "0o600")           # персональные данные — только владельцу
        got = O.get_card("сызранова ул. 28-1", "13")
        self.assertEqual([(o.fio, o.share) for o in got.owners], [("Иванов Иван", "1/2"), ("Петрова Анна", "1/2")])
        self.assertIsNone(O.get_card("Сызранова ул 28-1", "14"))
        self.assertIsNotNone(O.get_or_new("Сызранова ул 28-1", "14"))                   # новая карточка для другой квартиры
        O.delete_card("Сызранова ул 28-1", "13")
        self.assertIsNone(O.get_card("Сызранова ул 28-1", "13"))

    def test_flat_with_apostrophe_is_a_separate_card(self):
        self.assertNotEqual(O.make_key("Турубаровых ул 72", "19'"), O.make_key("Турубаровых ул 72", "19"))

    def test_legacy_file_is_read_and_saved_in_new_format(self):
        O.OWNERS_PATH.write_text('{"x|1": {"address": "Х ул 1", "flat": "1", "fio": "Старый Собственник", "penalty": "5"}}',
                                 encoding="utf-8")
        O.OWNERS_PATH.chmod(0o600)
        got = O._from_dict(O._load_all()["x|1"])
        self.assertEqual([o.fio for o in got.owners], ["Старый Собственник"])


class CardTest(unittest.TestCase):
    def test_legacy_card_becomes_single_owner(self):
        c = O._from_dict({"address": "Х ул 1", "flat": "5", "fio": "", "reg_address": "Таганрог", "passport": "6000 1"})
        self.assertEqual(len(c.owners), 1)
        self.assertEqual(c.owners[0].reg_address, "Таганрог")
        self.assertEqual([p.fio for p in c.people("ИВАНОВ ИВАН ИВАНОВИЧ")], ["Иванов Иван Иванович"])   # ФИО — из отчёта

    def test_people_rules(self):
        c = O.Card(address="x", flat="1", owners=[O.Owner(fio="", share="1/2"), O.Owner(fio="Сидорова Мария"), O.Owner()])
        self.assertEqual([p.fio for p in c.people("КУЗНЕЦОВ ПЁТР")], ["Кузнецов Пётр", "Сидорова Мария"])
        self.assertEqual(O.Card(address="x", flat="1").people(""), [])
        c.unknown = True
        self.assertEqual(c.people("КУЗНЕЦОВ ПЁТР"), [])


class ApplicationsTest(unittest.TestCase):
    def setUp(self):
        self.org = orgs.default_orgs()[0]
        self.tmp = Path(tempfile.mkdtemp())

    def texts(self, case, card):
        path = self.tmp / "z.docx"
        court.build_court_application(self.org, card, case, path=path)
        return [p.text for p in Document(str(path)).paragraphs if p.text.strip()]

    def card(self, shares):
        return O.Card(address="Водопроводная ул 13", flat="34", penalty="600", debt_from="01.11.2021", debt_to="10.03.2023",
                      pen_from="11.12.2021", pen_to="10.03.2023",
                      owners=[O.Owner(fio="Иванов Иван Иванович", share=shares[0]),
                              O.Owner(fio="Иванова Анна Петровна", share=shares[1])])

    def test_one_application_per_owner_with_full_amounts(self):
        card = self.card(("1/2", "1/2"))
        cases = court.plan_cases(card, "ИВАНОВ ИВАН ИВАНОВИЧ", 1000.0)
        self.assertEqual(len(cases), 2)
        # суммы не делятся: в каждом заявлении полный долг и пени по помещению
        self.assertEqual([c.debt for c in cases], [1000.0, 1000.0])
        self.assertEqual([c.penalty for c in cases], [600.0, 600.0])
        t = self.texts(cases[1], card)
        text = "\n".join(t)
        # все собственники названы; заявление — на второго
        self.assertIn("собственниками вышеуказанного помещения являются: Иванов Иван Иванович (доля в праве 1/2); "
                      "Иванова Анна Петровна (доля в праве 1/2)", text)
        self.assertIn("ДОЛЖНИК: Иванова Анна Петровна", text)
        self.assertIn("Доля в праве: 1/2", text)
        self.assertIn("Сособственники: Иванов Иван Иванович (доля в праве 1/2)", text)
        self.assertIn("Настоящее заявление подаётся в отношении Ивановой Анны Петровны (доля в праве 1/2)", text)
        self.assertIn("Сумма задолженности: 1 000,00 руб.", text.replace("\u00a0", " "))
        self.assertIn("Сумма пеней: 600,00 руб.", text.replace("\u00a0", " "))
        self.assertIn("составляет 1 000 (одна тысяча) рублей 00 коп.", text)
        self.assertNotIn("Задолженность на долю", text)
        self.assertIn("Взыскать с Ивановой Анны Петровны в пользу", text)

    def test_shares_are_optional_and_do_not_change_amounts(self):
        card = self.card(("", ""))
        cases = court.plan_cases(card, "ИВАНОВ ИВАН ИВАНОВИЧ", 1000.0)
        self.assertEqual(len(cases), 2)
        self.assertEqual([c.debt for c in cases], [1000.0, 1000.0])
        text = "\n".join(self.texts(cases[0], card))
        self.assertNotIn("Доля в праве:", text)
        self.assertIn("Иванов Иван Иванович; Иванова Анна Петровна", text)

    def test_single_owner_and_unknown_keep_old_behavior(self):
        single = O.Card(address="Водопроводная ул 13", flat="34")
        cases = court.plan_cases(single, "ПЕТРОВА АННА СЕРГЕЕВНА", 777.0)
        self.assertEqual(len(cases), 1)
        text = "\n".join(self.texts(cases[0], single))
        self.assertIn("должник является собственником вышеуказанного помещения", text)
        self.assertNotIn("Сособственники", text)
        unk = O.Card(address="Водопроводная ул 13", flat="102", unknown=True, cadastral="61:58:1")
        cases = court.plan_cases(unk, "ПЕТРОВА АННА", 500.0)
        self.assertEqual(len(cases), 1)
        self.assertIsNone(cases[0].owner)
        self.assertIn("Физическое лицо (фамилия, имя и отчество, которого не известно)", "\n".join(self.texts(cases[0], unk)))


if __name__ == "__main__":
    unittest.main()


class CardStatusTest(unittest.TestCase):
    def test_none_partial_full(self):
        self.assertEqual(O.card_status(None), "none")
        self.assertEqual(O.card_status(O.Card(address="Х", flat="1")), "none")
        partial = O.Card(address="Х", flat="1", owners=[O.Owner(passport="6000 1")])
        self.assertEqual(O.card_status(partial, "Иванов Иван Иванович"), "partial")
        full = O.Card(address="Х", flat="1", owners=[O.Owner(birth_date="01.01.1980", birth_place="г. Город", passport="6000 1",
                                                            reg_address="ул. Тестовая, 1")])
        self.assertEqual(O.card_status(full, "Иванов Иван Иванович"), "full")

    def test_second_owner_without_data_makes_card_partial(self):
        data = dict(birth_date="01.01.1980", birth_place="г. Город", passport="6000 1", reg_address="ул. Тестовая, 1")
        card = O.Card(address="Х", flat="1", owners=[O.Owner(**data), O.Owner(fio="Петров Пётр Петрович")])
        self.assertEqual(O.card_status(card, "Иванов Иван Иванович"), "partial")

    def test_unknown_owner_needs_cadastral(self):
        self.assertEqual(O.card_status(O.Card(address="Х", flat="1", unknown=True, cadastral="61:00:000:1")), "full")
        self.assertEqual(O.card_status(O.Card(address="Х", flat="1", unknown=True)), "none")
