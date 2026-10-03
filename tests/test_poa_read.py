import tempfile
import unittest
import zipfile
from pathlib import Path

import orgs
import poa
import storage

TEXT = [
    "ДОВЕРЕННОСТЬ",
    "г. Таганрог «23» августа 2022 г.",
    "ООО УО «ДомСервис», в лице директора Сидорова Петра Ивановича, паспорт выдан 12.05.2015, настоящей доверенностью "
    "доверяет Иванову Алексею Алексеевичу представлять интересы общества в судах.",
    "Директор ______ Сидоров П. И.",
    "Представитель ______ Иванов А. А.",
]


def make_docx(path, lines):
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


class ParseTests(unittest.TestCase):
    def test_date_and_name_from_signature(self):
        text = "\n".join(TEXT)
        self.assertEqual(poa.parse_date(text), "23.08.2022г.")
        self.assertEqual(poa.parse_representative(text), "А. А. Иванов")

    def test_numeric_date_and_passport_date_skipped(self):
        self.assertEqual(poa.parse_date("паспорт выдан 01.02.2010. Доверенность от 23.08.2022"), "23.08.2022г.")

    def test_surname_reversed_when_no_signature(self):
        self.assertEqual(poa.parse_representative("Настоящей доверенностью доверяет Ивановой Анне Петровне"), "А. П. Иванова")
        self.assertEqual(poa.parse_representative("уполномочивает Петрова Ивана Сергеевича действовать"), "И. С. Петров")

    def test_nothing_found(self):
        self.assertEqual(poa.parse_representative("просто текст"), "")
        self.assertEqual(poa.parse_date("без дат"), "")


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.old = storage.POA_DIR
        storage.POA_DIR = self.dir / "poa"
        self.src = self.dir / "d.docx"
        make_docx(self.src, TEXT)

    def tearDown(self):
        storage.POA_DIR = self.old
        self.tmp.cleanup()

    def test_court_fills_date_and_name_once(self):
        org = orgs.Organization(name="О")
        org.poa_court = orgs.import_poa(self.src, "court")
        self.assertEqual(orgs.apply_poa_data(org, "court"), {"sign_name": "А. А. Иванов", "poa_text": "23.08.2022г."})
        self.assertEqual((org.poa_text, org.sign_name), ("23.08.2022г.", "А. А. Иванов"))
        org.sign_name = "Правка вручную"
        self.assertEqual(orgs.apply_poa_data(org, "court"), {})                # второй раз файл не читается
        self.assertEqual(org.sign_name, "Правка вручную")

    def test_mail_gives_only_name(self):
        org = orgs.Organization(name="О")
        org.poa_mail = orgs.import_poa(self.src, "mail")
        self.assertEqual(orgs.apply_poa_data(org, "mail"), {"sign_name": "А. А. Иванов"})
        self.assertEqual(org.poa_text, "")

    def test_saved_files_fill_only_empty_fields(self):
        org = orgs.Organization(name="О", sign_name="Уже введено")
        org.poa_court = orgs.import_poa(self.src, "court")
        orgs.apply_poa_data(org, "court", overwrite=False)
        self.assertEqual((org.sign_name, org.poa_text), ("Уже введено", "23.08.2022г."))
        self.assertIn(org.poa_court, org.poa_read)
