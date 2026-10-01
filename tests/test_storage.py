import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class MigrationTest(unittest.TestCase):
    def test_legacy_files_moved_into_folder(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".debtors_owners.json").write_text("{}", encoding="utf-8")
            (Path(home) / ".debtors_finder.json").write_text("{}", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "DEBTORS_HOME"} | {"HOME": home, "USERPROFILE": home}
            code = "import storage; print(storage.DATA_DIR)"
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            d = Path(home) / ".debtors"
            self.assertTrue((d / "owners.json").exists())
            self.assertTrue((d / "settings.json").exists())
            self.assertFalse((Path(home) / ".debtors_owners.json").exists())

    def test_env_override_used_without_migration(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data:
            (Path(home) / ".debtors_owners.json").write_text("{}", encoding="utf-8")
            env = dict(os.environ) | {"HOME": home, "USERPROFILE": home, "DEBTORS_HOME": data}
            code = "import storage; print(storage.OWNERS_PATH)"
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), str(Path(data) / "owners.json"))
            self.assertTrue((Path(home) / ".debtors_owners.json").exists())


if __name__ == "__main__":
    unittest.main()


class TrashAndTransferTest(unittest.TestCase):
    def setUp(self):
        import owners as O
        self.O = O
        self.old = O.OWNERS_PATH, O.TRASH_PATH
        self.tmp = Path(tempfile.mkdtemp())
        O.OWNERS_PATH, O.TRASH_PATH = self.tmp / "owners.json", self.tmp / "trash.json"

    def tearDown(self):
        self.O.OWNERS_PATH, self.O.TRASH_PATH = self.old

    def test_deleted_card_goes_to_trash_and_can_be_restored(self):
        O = self.O
        O.save_card(O.Card(address="ул. Тестовая, д. 1", flat="5", owners=[O.Owner(fio="Иванов Иван", passport="1")]))
        O.delete_card("ул. Тестовая, д. 1", "5")
        self.assertIsNone(O.get_card("ул. Тестовая, д. 1", "5"))
        self.assertTrue(O.has_trashed("ул. Тестовая, д. 1", "5"))
        card = O.restore_card("ул. Тестовая, д. 1", "5")
        self.assertEqual(card.owners[0].fio, "Иванов Иван")
        self.assertFalse(O.has_trashed("ул. Тестовая, д. 1", "5"))
        self.assertEqual(oct(O.TRASH_PATH.stat().st_mode & 0o777), "0o600")

    def test_old_trash_entries_are_purged(self):
        import json
        O = self.O
        O.TRASH_PATH.write_text(json.dumps({"x|1": {"card": {}, "deleted": "2000-01-01"}}), encoding="utf-8")
        O.save_card(O.Card(address="ул. А, д. 1", flat="1"))
        O.delete_card("ул. А, д. 1", "1")
        self.assertNotIn("x|1", O._load_trash())

    def test_export_import_roundtrip_with_backup(self):
        import json
        import storage
        src, dst = self.tmp / "src", self.tmp / "dst"
        src.mkdir(); dst.mkdir()
        (src / "orgs.json").write_text(json.dumps([{"name": "А"}]), encoding="utf-8")
        (src / "owners.json").write_text("{}", encoding="utf-8")
        (src / "state.json").write_text("{}", encoding="utf-8")                        # состояние не переносится
        z = self.tmp / "out.zip"
        self.assertEqual(sorted(storage.export_data(z, src)), ["orgs.json", "owners.json"])
        (dst / "orgs.json").write_text("[]", encoding="utf-8")
        self.assertEqual(storage.import_data(z, dst), ["orgs.json", "owners.json"])
        self.assertEqual(json.loads((dst / "orgs.json").read_text(encoding="utf-8")), [{"name": "А"}])
        self.assertEqual(len(list((dst / "backups").glob("*.zip"))), 1)
        self.assertFalse((dst / "state.json").exists())

    def test_import_rejects_foreign_or_broken_archive(self):
        import storage
        import zipfile
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("hello.txt", "x")
        with self.assertRaises(ValueError):
            storage.import_data(bad, self.tmp)
        broken = self.tmp / "broken.zip"
        with zipfile.ZipFile(broken, "w") as zf:
            zf.writestr("orgs.json", "{не json")
        with self.assertRaises(ValueError):
            storage.import_data(broken, self.tmp)
