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
