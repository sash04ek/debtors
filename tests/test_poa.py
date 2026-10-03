import tempfile
import unittest
import zipfile
from pathlib import Path

import orgs
import storage


class PowerOfAttorneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.old = storage.POA_DIR
        storage.POA_DIR = self.dir / "poa"
        self.src = self.dir / "Моя доверенность.docx"
        self.src.write_bytes(b"docx-data")

    def tearDown(self):
        storage.POA_DIR = self.old
        self.tmp.cleanup()

    def test_import_copy_and_replace(self):
        name = orgs.import_poa(self.src, "mail")
        self.assertTrue(orgs.poa_path(name).is_file())
        new = orgs.import_poa(self.src, "mail", old=name)
        self.assertIsNone(orgs.poa_path(name))
        self.assertTrue(orgs.poa_path(new).is_file())

    def test_old_doc_format_keeps_extension(self):
        doc = self.dir / "старая.doc"
        doc.write_bytes(b"doc")
        org = orgs.Organization(name="Орг", poa_court=orgs.import_poa(doc, "court"))
        self.assertTrue(org.poa_court.endswith("-court.doc"))
        out = self.dir / "o"
        out.mkdir()
        self.assertEqual(orgs.copy_poa(org, "court", out).name, "Доверенность для суда Орг.doc")

    def test_only_word(self):
        txt = self.dir / "a.pdf"
        txt.write_bytes(b"x")
        with self.assertRaises(ValueError):
            orgs.import_poa(txt, "court")

    def test_copy_next_to_documents_with_kind_in_name(self):
        org = orgs.Organization(name="ООО УО «Ромашка»")
        out = self.dir / "out"
        out.mkdir()
        self.assertIsNone(orgs.copy_poa(org, "mail", out))
        org.poa_mail = orgs.import_poa(self.src, "mail")
        org.poa_court = orgs.import_poa(self.src, "court")
        mail, court = orgs.copy_poa(org, "mail", out), orgs.copy_poa(org, "court", out)
        self.assertEqual(mail.name, "Доверенность для почты ООО УО Ромашка.docx")
        self.assertEqual(court.name, "Доверенность для суда ООО УО Ромашка.docx")
        self.assertEqual(mail.read_bytes(), b"docx-data")

    def test_path_traversal_ignored(self):
        self.assertIsNone(orgs.poa_path("../secret.docx"))

    def test_export_import_carries_poa(self):
        data = self.dir                                         # POA_DIR лежит в <data>/poa
        (data / "orgs.json").write_text("[]", encoding="utf-8")
        name = orgs.import_poa(self.src, "court")
        z = self.dir.parent / f"{self.dir.name}-x.zip"
        self.addCleanup(z.unlink, missing_ok=True)
        storage.export_data(z, data)
        with zipfile.ZipFile(z) as f:
            self.assertIn(f"poa/{name}", f.namelist())
        target = self.dir / "target"
        target.mkdir()
        storage.import_data(z, target)
        self.assertEqual((target / "poa" / name).read_bytes(), b"docx-data")
