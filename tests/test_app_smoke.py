import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from lumendesk.app import MainWindow, _default_project


class ApplicationSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_main_window_starts_with_default_universes(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(Path(directory) / "project.json", _default_project())
            self.assertEqual(window.core.universes, 100)
            self.assertEqual(window.channel_table.rowCount(), 512)
            window.close()


if __name__ == "__main__":
    unittest.main()
