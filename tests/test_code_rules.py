"""Project rules enforced as tests (.claude/rules/project-conventions.md)."""
import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "linfilecopy"
MANIFEST_IDS = {line.split()[0] for line in (ROOT / "tools" / "icons.manifest").read_text().splitlines()
                if line.strip() and not line.startswith("#")}


def py_files(sub: str = ""):  # type: ignore[no-untyped-def]
    return sorted((PKG / sub).rglob("*.py"))


class CodeRulesTest(unittest.TestCase):
    def test_model_and_engine_never_import_gtk(self) -> None:
        for path in py_files("model") + py_files("engine"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "gi.repository":
                    names = {a.name for a in node.names}
                    self.assertFalse(names & {"Gtk", "Gdk"}, f"{path} imports {names & {'Gtk', 'Gdk'}}")

    def test_no_shell_true(self) -> None:
        for path in py_files():
            self.assertNotIn("shell=True", path.read_text(), path)

    def test_no_network_modules(self) -> None:
        banned = {"urllib", "http", "socketserver", "requests", "ftplib", "smtplib", "paramiko"}
        for path in py_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module.split(".")[0]]
                self.assertFalse(set(mods) & banned, f"{path} imports {set(mods) & banned}")

    def test_only_stdlib_and_gi_imports(self) -> None:
        allowed = set(sys.stdlib_module_names) | {"gi", "linfilecopy", "cairo"}
        for path in py_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], allowed, f"{path}: {a.name}")
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    self.assertIn(node.module.split(".")[0], allowed, f"{path}: {node.module}")

    def test_icons_used_exist_in_manifest(self) -> None:
        pattern = re.compile(r"""(?:icon|button|icon_name|status_icon|badge|stat_tile|row|group|switch_row|MessageBar|empty_state|Section)\([^)]*?["']([a-z]+-[a-z0-9-]+)["']""")
        used = set()
        for path in py_files("ui"):
            used |= set(pattern.findall(path.read_text()))
        used |= set(re.findall(r'"((?:status|action|ep|feat|mode|policy|preset|delta|nav|misc|stat|empty|trigger)-[a-z0-9-]+)"',
                               "\n".join(p.read_text() for p in py_files("ui") + py_files("model"))))
        used |= {m for m in re.findall(r"lfc-([a-z0-9-]+)-symbolic", "\n".join(p.read_text() for p in py_files("ui")))}
        used = {u for u in used if not u.endswith("-") and not u.startswith("lfc-")}
        missing = {u for u in used if u not in MANIFEST_IDS}
        self.assertEqual(missing, set())

    def test_vendored_icons_current(self) -> None:
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "vendor_icons.py"), "--check"],
                              capture_output=True, text=True)
        if "missing source" in proc.stdout:
            self.skipTest("Phosphor asset directory not available")
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_no_gettext_shadowing(self) -> None:
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "check_gettext_shadow.py"), str(PKG)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
