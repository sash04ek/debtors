import tempfile
import unittest
from datetime import date
from pathlib import Path

import orgs
import precheck
import storage


def full_org(**kw):
    base = dict(name="О", header="шапка", letter_header="шапка письма", letter_to="Кому", sign_name="А. А. Иванов",
                applicant_address="адрес", license_text="№ 1", poa_text="01.01.2022г.")
    return orgs.Organization(**(base | kw))


class OrgIssuesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = storage.POA_DIR
        storage.POA_DIR = Path(self.tmp.name) / "poa"
        src = Path(self.tmp.name) / "d.docx"
        src.write_bytes(b"x")
        self.poa = {k: orgs.import_poa(src, k) for k in ("mail", "court")}

    def tearDown(self):
        storage.POA_DIR = self.old
        self.tmp.cleanup()

    def test_complete_org_has_no_issues(self):
        org = full_org(poa_mail=self.poa["mail"], poa_court=self.poa["court"])
        for kind in precheck.KINDS:
            self.assertEqual(precheck.org_issues(kind, org), [], kind)

    def test_missing_poa_reported_per_kind(self):
        org = full_org(poa_court=self.poa["court"])
        self.assertTrue(any("доверенность для почты" in i for i in precheck.org_issues("letter", org)))
        self.assertEqual(precheck.org_issues("court", org), [])
        self.assertEqual(precheck.org_issues("claims", org), [])

    def test_empty_fields_named_with_place(self):
        org = full_org(sign_name="", poa_text="", poa_court=self.poa["court"])
        issues = precheck.org_issues("court", org)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("подписант" in i and "Письмо в ЕИРЦ" in i for i in issues))
        self.assertTrue(any("дата доверенности" in i for i in issues))


class RowIssuesTests(unittest.TestCase):
    def test_court_needs_card_and_court(self):
        org = full_org()
        self.assertEqual(precheck.row_issues("court", org, "ул 1", card_ok=False, court_ok=False),
                         ["нет персональных данных", "нет участка"])
        self.assertEqual(precheck.row_issues("claims", org, "ул 1", card_ok=False, court_ok=False), [])

    def test_partial_card_reported(self):
        self.assertEqual(precheck.row_issues("court", full_org(), "ул 1", card_ok=True, card_full=False),
                         ["карточка заполнена не полностью"])

    def test_houses_checked_only_when_list_exists(self):
        self.assertEqual(precheck.row_issues("claims", full_org(), "ул 1"), [])
        org = full_org(houses=[{"address": "Тестовая ул 1", "since": "01.01.2020"},
                               {"address": "Тестовая ул 2", "since": "01.01.2020", "until": "01.01.2021"}])
        today = date(2026, 1, 1)
        self.assertEqual(precheck.row_issues("claims", org, "Тестовая ул 1", today=today), [])
        self.assertEqual(precheck.row_issues("claims", org, "Другая ул 5", today=today), ["дома нет в списке организации"])
        left = precheck.row_issues("letter", org, "Тестовая ул 2", today=today)
        self.assertEqual(len(left), 1)
        self.assertIn("дом не в управлении", left[0])
