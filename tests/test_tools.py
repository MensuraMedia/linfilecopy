"""Tool detection with injected probes (no real tools needed)."""
import unittest

from linfilecopy.engine import tools


def fake_which(present: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in present else None


class ParseVersionTest(unittest.TestCase):
    def test_parses_rsync_3_2_7(self) -> None:
        text = "rsync  version 3.2.7  protocol version 31\nCopyright ..."
        self.assertEqual(tools.parse_rsync_version(text), (3, 2, 7))

    def test_parses_v_prefix(self) -> None:
        self.assertEqual(tools.parse_rsync_version("rsync  version v3.3.0  protocol version 31"), (3, 3, 0))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(tools.parse_rsync_version("command not found"))


class DetectTest(unittest.TestCase):
    def detect(self, present: set[str], version_text: str = "rsync  version 3.2.7  protocol version 31"):
        def run(argv: list[str]) -> str:
            if argv[1:] == ["--version"]:
                return version_text
            if argv[1:] == ["--user", "show-environment"]:
                return "HOME=/home/x\n"
            return ""

        return tools.detect(fake_which(present), run, udisks_probe=lambda: True, gi_probe=lambda n, v: n == "Secret")

    def test_all_present(self) -> None:
        caps = self.detect({"rsync", "ionice", "nice", "systemctl", "crontab"})
        self.assertTrue(caps.can_run)
        self.assertEqual(caps.rsync.version, "3.2.7")
        self.assertTrue(caps.rsync_at_least(3, 1, 3))
        self.assertTrue(caps.systemd_user.available)
        self.assertTrue(caps.secret.available)
        self.assertFalse(caps.appindicator.available)

    def test_missing_rsync_blocks_runs_and_has_install_hints(self) -> None:
        caps = self.detect({"ionice"})
        self.assertFalse(caps.can_run)
        self.assertFalse(caps.rsync.available)
        self.assertIn("Fedora", caps.rsync.install)

    def test_old_rsync_rejected(self) -> None:
        caps = self.detect({"rsync"}, "rsync  version 3.0.9  protocol version 30")
        self.assertFalse(caps.can_run)
        self.assertFalse(caps.rsync.available)

    def test_no_systemctl(self) -> None:
        caps = self.detect({"rsync", "crontab"})
        self.assertFalse(caps.systemd_user.available)
        self.assertTrue(caps.crontab.available)


if __name__ == "__main__":
    unittest.main()
