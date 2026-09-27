import json
import tempfile
import unittest
from pathlib import Path

from linfilecopy.model.settings import AppSettings


class SettingsTest(unittest.TestCase):
    def test_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            s = AppSettings.load(Path(d) / "none.json")
            self.assertEqual(s.style, "system")
            self.assertTrue(s.preview_new_jobs)

    def test_round_trip_and_clamping(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            AppSettings(style="dark", accent="green", history_days=99999).save(p)
            s = AppSettings.load(p)
            self.assertEqual((s.style, s.accent, s.history_days), ("dark", "green", 3650))

    def test_unknown_keys_and_bad_values_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"style": "neon", "bogus": 1, "accent": "nope"}))
            s = AppSettings.load(p)
            self.assertEqual((s.style, s.accent), ("system", "blue"))

    def test_corrupt_file_gives_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text("{not json")
            self.assertEqual(AppSettings.load(p), AppSettings())


if __name__ == "__main__":
    unittest.main()
