"""Атомарная запись и версия схемы файлов данных: python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import storage  # noqa: E402


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_write_replaces_file_and_leaves_no_temp(self):
        p = self.dir / "a.json"
        storage.write_atomic(p, "one")
        storage.write_atomic(p, "two")
        self.assertEqual(p.read_text(encoding="utf-8"), "two")
        self.assertEqual([x.name for x in self.dir.iterdir()], ["a.json"])

    def test_failure_keeps_old_content_and_cleans_temp(self):
        p = self.dir / "a.json"
        storage.write_atomic(p, "old")
        with mock.patch("storage.os.replace", side_effect=OSError("диск отвалился")):
            with self.assertRaises(OSError):
                storage.write_atomic(p, "new")
        self.assertEqual(p.read_text(encoding="utf-8"), "old")
        self.assertEqual([x.name for x in self.dir.iterdir()], ["a.json"])

    def test_private_file_mode(self):
        p = self.dir / "o.json"
        storage.write_atomic(p, "{}", private=True)
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")


class VersionedJsonTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_new_files_carry_schema_version(self):
        for kind, payload, key in (("settings", {"top_n": 20}, None), ("orgs", [{"name": "О"}], "organizations"),
                                   ("owners", {"а|1": {"fio": "И"}}, "cards"), ("trash", {"а|1": {}}, "items"),
                                   ("courts", {"regions": "61"}, None), ("state", {"file": ""}, None)):
            p = self.dir / f"{kind}.json"
            storage.save_json(p, kind, payload)
            raw = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], storage.SCHEMA_VERSION[kind], kind)
            if key:
                self.assertEqual(raw[key], payload)
            self.assertEqual(storage.load_json(p, kind), payload, kind)

    def test_legacy_files_without_version_are_read(self):
        (self.dir / "orgs.json").write_text(json.dumps([{"name": "О"}]), encoding="utf-8")
        (self.dir / "owners.json").write_text(json.dumps({"а|1": {"fio": "И"}}), encoding="utf-8")
        (self.dir / "settings.json").write_text(json.dumps({"top_n": 7}), encoding="utf-8")
        self.assertEqual(storage.load_json(self.dir / "orgs.json", "orgs"), [{"name": "О"}])
        self.assertEqual(storage.load_json(self.dir / "owners.json", "owners"), {"а|1": {"fio": "И"}})
        self.assertEqual(storage.load_json(self.dir / "settings.json", "settings"), {"top_n": 7})

    def test_missing_or_broken_file_gives_default(self):
        self.assertEqual(storage.load_json(self.dir / "no.json", "owners", {}), {})
        (self.dir / "bad.json").write_text("{не json", encoding="utf-8")
        self.assertIsNone(storage.load_json(self.dir / "bad.json", "settings"))

    def test_migration_runs_from_old_version(self):
        p = self.dir / "settings.json"
        p.write_text(json.dumps({"schema_version": 1, "top_n": 5}), encoding="utf-8")
        with mock.patch.dict(storage.SCHEMA_VERSION, {"settings": 3}), mock.patch.dict(storage.MIGRATIONS, {
                ("settings", 1): lambda d: {**d, "a": 1}, ("settings", 2): lambda d: {**d, "b": 2}}):
            self.assertEqual(storage.load_json(p, "settings"), {"top_n": 5, "a": 1, "b": 2})

    def test_newer_file_is_backed_up_before_overwrite(self):
        p = self.dir / "settings.json"
        p.write_text(json.dumps({"schema_version": 99, "из_будущего": True}), encoding="utf-8")
        storage.save_json(p, "settings", {"top_n": 20})
        self.assertTrue((self.dir / "settings.json.v99.bak").exists())
        self.assertEqual(json.loads((self.dir / "settings.json.v99.bak").read_text(encoding="utf-8"))["из_будущего"], True)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["schema_version"], storage.SCHEMA_VERSION["settings"])


if __name__ == "__main__":
    unittest.main()


class RemovedFieldsCompatTest(unittest.TestCase):
    """Поля, убранные из программы, остаются в старых файлах и не мешают чтению."""

    def test_old_card_and_org_and_settings_keys_are_ignored(self):
        import owners
        import orgs
        card = owners._from_dict({"address": "ул. А, д. 1", "flat": "5", "court_code": "61MS0001", "managed_since": "01.01.2020",
                                  "owners": [{"fio": "Иванов Иван"}]})
        self.assertEqual(card.owners[0].fio, "Иванов Иван")
        self.assertFalse(hasattr(card, "court_code"))
        org = orgs.Organization(**{k: v for k, v in {"name": "О", "match": "О", "claim_no_prefix": "", "duty_default": "200"}.items()
                                   if k in {f.name for f in orgs.fields(orgs.Organization)}})
        self.assertEqual(org.name, "О")

    def test_settings_file_with_removed_keys_loads(self):
        import app
        d = Path(tempfile.mkdtemp())
        (d / "settings.json").write_text(json.dumps({"top_n": 7, "inn_col": "ИНН", "type_col": "Тип", "type_value": "физ"}),
                                         encoding="utf-8")
        old = app.CONFIG_PATH
        app.CONFIG_PATH = d / "settings.json"
        try:
            self.assertEqual(app.load_settings().top_n, 7)
        finally:
            app.CONFIG_PATH = old
