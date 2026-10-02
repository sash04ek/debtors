"""Дома: дата прихода, дата ухода и признак «ушёл»; миграция прежних записей."""
import json
import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402
import orgs  # noqa: E402
import storage  # noqa: E402

TODAY = date(2026, 10, 1)


class HouseModelTest(unittest.TestCase):
    def test_legacy_since_text_is_split(self):
        n = orgs.normalize_house
        self.assertEqual(n({"address": "А 1", "since": "01.06.2015г"})["since"], "01.06.2015")
        h = n({"address": "А 1", "since": "01.12.2019г-01.11.2020гг"})
        self.assertEqual((h["since"], h["until"], h["left"]), ("01.12.2019", "01.11.2020", False))
        h = n({"address": "А 1", "since": "01.06.2015г ушел"})
        self.assertEqual((h["since"], h["until"], h["left"]), ("01.06.2015", "", True))
        h = n({"address": "А 1", "since": "ушел"})
        self.assertEqual((h["since"], h["left"]), ("", True))
        self.assertEqual(n("Б ул 2"), {"address": "Б ул 2", "since": "", "until": "", "left": False, "court": ""})

    def test_new_records_are_kept_as_is(self):
        h = {"address": "А 1", "since": "01.06.2015", "until": "", "left": True, "court": "61MS0001"}
        self.assertEqual(orgs.normalize_house(h), h)

    def test_is_managed_house(self):
        m = lambda **k: orgs.is_managed_house({"since": "", "until": "", "left": False, **k}, TODAY)
        self.assertFalse(m())                                           # нет даты прихода
        self.assertTrue(m(since="01.06.2015"))
        self.assertFalse(m(since="01.12.2026"))                         # ещё не пришёл
        self.assertFalse(m(since="01.06.2015", until="01.09.2019"))     # ушёл по дате
        self.assertTrue(m(since="01.06.2015", until="31.12.2026"))      # уход ещё впереди
        self.assertFalse(m(since="01.06.2015", left=True))              # ушёл, дата неизвестна
        self.assertTrue(m(since="01.06.2015", left=True, until="31.12.2026"))   # дата ухода важнее признака

    def test_period_text(self):
        t = orgs.house_period_text
        self.assertEqual(t({"since": "01.06.2015", "until": "", "left": False}), "с 01.06.2015")
        self.assertEqual(t({"since": "01.12.2019", "until": "01.11.2020", "left": False}), "с 01.12.2019 по 01.11.2020")
        self.assertIn("ушёл (дата ухода неизвестна)", t({"since": "01.06.2015", "until": "", "left": True}))
        self.assertEqual(t({"since": "", "until": "", "left": True}), "ушёл (дата ухода неизвестна)")


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.old = orgs.ORGS_PATH
        self.path = Path(tempfile.mkdtemp()) / "orgs.json"
        orgs.ORGS_PATH = self.path

    def tearDown(self):
        orgs.ORGS_PATH = self.old

    def test_schema_1_file_is_migrated_on_load_and_saved_as_schema_2(self):
        self.path.write_text(json.dumps({"schema_version": 1, "organizations": [{"name": "О", "match": "О", "houses": [
            {"address": "А 1", "since": "01.06.2015г ушел", "court": ""},
            {"address": "Б 2", "since": "01.12.2019г-01.11.2020гг", "court": "61MS0001"}]}]}), encoding="utf-8")
        loaded = orgs.load_orgs()
        self.assertEqual([(h["since"], h["until"], h["left"]) for h in loaded[0].houses],
                         [("01.06.2015", "", True), ("01.12.2019", "01.11.2020", False)])
        orgs.save_orgs(loaded)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], 2)
        self.assertEqual(raw["organizations"][0]["houses"][1]["until"], "01.11.2020")

    def test_unversioned_file_is_migrated_too(self):
        self.path.write_text(json.dumps([{"name": "О", "match": "О", "houses": [{"address": "А 1", "since": "01.06.2015г"}]}]),
                             encoding="utf-8")
        self.assertEqual(orgs.load_orgs()[0].houses[0]["since"], "01.06.2015")


class HousesEditorTest(unittest.TestCase):
    def setUp(self):
        self.old = app.save_settings
        app.save_settings = lambda s: None
        app.App.restore_last_state = lambda self: None
        self.a = app.App()
        self.a.update()

    def tearDown(self):
        self.a.destroy()
        app.save_settings = self.old

    def test_editor_roundtrip_with_until_and_left(self):
        ed = app.HousesEditor(self.a, self.a)
        ed.set([{"address": "А 1", "since": "01.06.2015", "until": "", "left": False, "court": ""},
                {"address": "Б 2", "since": "01.12.2019", "until": "01.11.2020", "left": False, "court": ""},
                {"address": "В 3", "since": "01.06.2015", "until": "", "left": True, "court": ""}])
        self.assertEqual([(h["since"], h["until"], h["left"]) for h in ed.get()],
                         [("01.06.2015", "", False), ("01.12.2019", "01.11.2020", False), ("01.06.2015", "", True)])
        self.assertEqual([ed.tree.item(i, "values")[2] for i in ed.tree.get_children()], ["", "01.11.2020", "ушёл"])

    def test_upsert_tidies_typed_dates_and_left_excludes_date(self):
        ed = app.HousesEditor(self.a, self.a)
        ed.addr.set("Г ул 4")
        ed.since.set("1.6.15")
        ed.until.set("")
        ed.left.set(True)
        ed._left_toggled()
        ed.upsert()
        h = ed.get()[0]
        self.assertEqual((h["since"], h["until"], h["left"]), ("01.06.2015", "", True))
        ed.tree.selection_set(ed.tree.get_children()[0])
        ed.update()
        self.assertEqual((ed.since.get(), ed.until.get(), ed.left.get()), ("01.06.2015", "", True))
        ed.until.set("01.09.2024")
        ed.left.set(False)
        ed.upsert()
        self.assertEqual((ed.get()[0]["until"], ed.get()[0]["left"]), ("01.09.2024", False))


if __name__ == "__main__":
    unittest.main()
