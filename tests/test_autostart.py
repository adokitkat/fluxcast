import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ui import autostart  # noqa: E402


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self._temp_dir.name)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("APPIMAGE", None)

    def tearDown(self):
        self._temp_dir.cleanup()

    def test_toggle_writes_and_removes_the_entry(self):
        path = self.home / "autostart" / "fluxcast.desktop"
        self.assertFalse(autostart.is_enabled())

        autostart.set_enabled(True)
        self.assertTrue(path.is_file())
        self.assertTrue(autostart.is_enabled())
        self.assertIn("--tray", path.read_text(encoding="utf-8"))

        autostart.set_enabled(False)
        self.assertFalse(path.exists())
        autostart.set_enabled(False)  # already off: no error

    def test_entry_skips_itself_once_uninstalled(self):
        entry = autostart.desktop_entry(["/usr/bin/fluxcast"])
        self.assertIn("Exec=/usr/bin/fluxcast --tray\n", entry)
        self.assertIn("TryExec=/usr/bin/fluxcast\n", entry)

    def test_exec_quotes_paths_with_spaces(self):
        entry = autostart.desktop_entry(["/usr/bin/python3", "/home/me/My Apps/main.py"])
        self.assertIn('Exec=/usr/bin/python3 "/home/me/My Apps/main.py" --tray\n', entry)
        self.assertIn("TryExec=/usr/bin/python3\n", entry)

    def test_launch_command_prefers_appimage(self):
        with mock.patch.dict(os.environ, {"APPIMAGE": "/apps/FluxCast.AppImage"}):
            self.assertEqual(autostart.launch_command(), ["/apps/FluxCast.AppImage"])

    def test_launch_command_uses_installed_wrapper(self):
        with mock.patch.object(autostart, "_MAIN", Path("/opt/fluxcast/main.py")), \
             mock.patch("os.access", return_value=True):
            self.assertEqual(autostart.launch_command(), ["/usr/bin/fluxcast"])

    def test_launch_command_from_a_checkout(self):
        with mock.patch.object(autostart, "_MAIN", Path("/src/fluxcast/src/main.py")):
            self.assertEqual(autostart.launch_command(),
                             [sys.executable, "/src/fluxcast/src/main.py"])


class TrayLockTest(unittest.TestCase):
    def test_second_tray_is_refused_until_the_first_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tray.lock"
            first = autostart.acquire_tray_lock(path)
            self.assertIsNotNone(first)
            self.assertIsNone(autostart.acquire_tray_lock(path))
            first.close()
            again = autostart.acquire_tray_lock(path)
            self.assertIsNotNone(again)
            again.close()


if __name__ == "__main__":
    unittest.main()
