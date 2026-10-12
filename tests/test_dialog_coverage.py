import _isolate                      # DEBTORS_HOME во временную папку, до импорта storage
HOME = _isolate.HOME
import inspect
import unittest
from pathlib import Path

import app

# Окна, которых пока нет ни в снимках Windows, ни в проверке запуска. Список только сокращается: новое окно сюда не добавляют,
# а подключают к tests/windows_shots.py и tests/smoke.py (правило AGENTS.md).
UNCOVERED = {"CourtChoiceDialog", "CourtEditDialog", "CourtsEditorDialog", "DocsDialog", "ProgressWindow", "WelcomeDialog"}


class DialogCoverageTest(unittest.TestCase):
    def test_every_dialog_is_in_screenshots_or_smoke(self):
        root = Path(__file__).resolve().parent
        src = (root / "windows_shots.py").read_text(encoding="utf-8") + (root / "smoke.py").read_text(encoding="utf-8")
        names = {n for n, c in inspect.getmembers(app, inspect.isclass)
                 if issubclass(c, app.Dialog) and c is not app.Dialog and c.__module__ == app.__name__}
        self.assertEqual(sorted(n for n in names if n not in src and n not in UNCOVERED), [],
                         "новое окно нужно добавить в tests/windows_shots.py и tests/smoke.py")
        self.assertEqual(sorted(n for n in UNCOVERED if n in src), [], "окно уже покрыто — уберите его из UNCOVERED")
