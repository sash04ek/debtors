import _isolate                      # DEBTORS_HOME во временную папку, до импорта storage
HOME = _isolate.HOME
import tempfile
import unittest
from pathlib import Path

import claim
import orgs


class FileNamesTest(unittest.TestCase):
    def test_short_fio(self):
        self.assertEqual(claim.short_fio("ИВАНОВ ИВАН ИВАНОВИЧ"), "Иванов И. И.")
        self.assertEqual(claim.short_fio("иванова-петрова анна"), "Иванова-Петрова А.")
        self.assertEqual(claim.short_fio("Иванов И.И."), "Иванов И.И.")
        self.assertEqual(claim.short_fio("Иванов"), "Иванов")
        self.assertEqual(claim.short_fio(""), "")

    def test_name_is_short_and_keeps_the_flat(self):
        name = claim.file_name("ИВАНОВ ИВАН ИВАНОВИЧ", "Очень длинная улица имени кого-то великого и известного 125/3 корпус 4", "17'")
        self.assertLessEqual(len(name), claim.MAX_STEM + len(".docx"))
        self.assertTrue(name.endswith("кв 17.docx"), name)
        self.assertTrue(name.startswith("Претензия Иванов И. И. Очень длинная"))

    def test_short_name_is_not_truncated(self):
        self.assertEqual(claim.file_name("Иванов Иван Иванович", "Тестовая ул 1", "5"), "Претензия Иванов И. И. Тестовая ул 1 кв 5.docx")

    def test_forbidden_characters_replaced(self):
        self.assertNotRegex(claim.doc_name("Претензия", 'Иванов "И"', "ул. А/Б: 1", "2"), r'[\\/:*?"<>|]')

    def test_unknown_owner_court_name(self):
        name = claim.doc_name("Судебный приказ", "собственник не известен", "Тестовая ул 1", "5", shorten=False)
        self.assertEqual(name, "Судебный приказ собственник не известен Тестовая ул 1 кв 5")

    def test_worst_case_path_survives_doubled_cyrillic(self):
        """Если zip прочитан в неверной кодировке, русские буквы удваиваются: имя + типичная папка назначения должны влезать в 260."""
        longest = claim.doc_name("Судебный приказ", "Иванов-Петров Александр Александрович", "я" * 120, "1234") + ".docx"
        self.assertLess(len(longest.encode("utf-8")) + len("C:\\Users\\Администратор\\Downloads\\Должники-документы-2026-10-21\\01 "), 260)

    def test_poa_and_letter_names_are_capped(self):
        org = orgs.Organization(name="ООО УО «" + "Очень длинное название " * 6 + "»")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "a.docx"
            src.write_bytes(b"x")
            old = orgs.storage.POA_DIR
            orgs.storage.POA_DIR = Path(d) / "poa"
            try:
                org.poa_mail = orgs.import_poa(src, "mail")
                dest = orgs.copy_poa(org, "mail", d)
            finally:
                orgs.storage.POA_DIR = old
            self.assertLessEqual(len(dest.name), 70 + len(".docx"))
            self.assertTrue(dest.name.endswith(".docx"))
        self.assertLessEqual(len(claim.safe_name(f"Письмо в ЕИРЦ {org.name}", claim.MAX_STEM)), claim.MAX_STEM)
