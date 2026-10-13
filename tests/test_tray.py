import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from ui import tray  # noqa: E402
except ImportError as exc:  # pystray/PIL missing on a headless builder
    tray = None
    _IMPORT_ERROR = exc


@unittest.skipIf(tray is None, "tray dependencies are unavailable")
class TrayResourceTest(unittest.TestCase):
    """The tray resolves assets/ and main.py relative to its own file, so
    moving the module to another directory silently breaks both without
    changing a character of the code (#84 refactor)."""

    def test_icon_path_exists_and_opens(self):
        self.assertTrue(os.path.isfile(tray._ICON_PATH),
                        f"tray icon missing at {tray._ICON_PATH}")
        from PIL import Image
        with Image.open(tray._ICON_PATH) as img:
            self.assertGreater(min(img.size), 0)

    def test_main_entry_point_exists(self):
        self.assertTrue(os.path.isfile(tray._MAIN),
                        f"tray launches casting via {tray._MAIN}, which is missing")

    def test_paths_resolve_into_the_source_root(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(tray.__file__)))
        for path in (tray._ICON_PATH, tray._MAIN):
            self.assertEqual(os.path.dirname(os.path.commonpath([root, path])),
                             os.path.dirname(root))


@unittest.skipIf(tray is None, "tray dependencies are unavailable")
class TrayMiceTest(unittest.TestCase):
    def setUp(self):
        from wfd.mice import MiceSink
        self.sink = MiceSink("192.168.1.50", "Example TV", ready=True)

    @staticmethod
    def _texts(items):
        return [item.text for item in items if item is not tray.pystray.Menu.SEPARATOR]

    def test_ready_sinks_are_listed_and_rescan_offered(self):
        items = tray._mice_items([self.sink], 3, False, True, None)
        self.assertEqual(self._texts(items), ["Example TV  (192.168.1.50)", "Rescan LAN"])
        self.assertTrue(items[0].enabled)

    def test_sinks_need_a_monitor_without_the_portal(self):
        items = tray._mice_items([self.sink], 1, False, False, None)
        self.assertEqual(items[0].text, tray._l("Select a monitor first"))
        self.assertFalse(items[0].enabled)

    def test_empty_states(self):
        self.assertEqual(self._texts(tray._mice_items([], 0, True, True, None)), [tray._l("Scanning…")])
        self.assertEqual(self._texts(tray._mice_items([], 0, False, True, None)),
                         ["No MICE devices found", "Rescan LAN"])
        self.assertIn("Turn the TV's Wi-Fi off and on, then rescan",
                      self._texts(tray._mice_items([], 2, False, True, None)))
        self.assertEqual(self._texts(tray._mice_items([], None, False, True, None))[0],
                         "MICE discovery needs python zeroconf")

    def test_start_mice_passes_the_address_not_auto(self):
        with mock.patch.object(tray, "_launch") as launch, \
             mock.patch.object(tray, "_profile_args", return_value=["--fps", "60"]), \
             mock.patch.object(tray, "_monitor_name", return_value="eDP-1"), \
             mock.patch.object(tray, "_wfd_uses_portal", return_value=False):
            tray._start_mice(self.sink, None)
        cmd, target = launch.call_args.args
        self.assertEqual(cmd[2:], ["--protocol", "wfd", "--wfd-mice", "192.168.1.50",
                                   "--monitor", "eDP-1", "--fps", "60"])
        self.assertEqual(target, "Example TV")

    def test_scan_keeps_only_ready_sinks(self):
        from wfd.mice import MiceSink
        idle = MiceSink("192.168.1.60", "Office PC")
        with mock.patch("wfd.mice.browse_candidates", return_value=[self.sink, idle]), \
             mock.patch("wfd.mice.probe_candidates", return_value=[self.sink]), \
             mock.patch.object(tray, "_refresh"):
            tray._scan_mice()
        self.assertEqual(tray._mice_sinks, [self.sink])
        self.assertEqual(tray._mice_candidates, 2)
        self.assertFalse(tray._scanning_mice)

    def test_scan_reports_missing_zeroconf(self):
        with mock.patch("wfd.mice.browse_candidates", return_value=None), \
             mock.patch.object(tray, "_refresh"):
            tray._scan_mice()
        self.assertEqual(tray._mice_sinks, [])
        self.assertIsNone(tray._mice_candidates)


if __name__ == "__main__":
    unittest.main()
