from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "scripts/installer/lifecycle.py"


class InstallerLifecycleTests(unittest.TestCase):
    def call(self, home: Path, *args: str, expected=0):
        result = subprocess.run([sys.executable, str(CLI), *args, "--home", str(home)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_symlink_install_check_partial_and_full_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--runtime", "codex", "--runtime", "dsh", "--without-lean")
            self.assertTrue((home / ".agents/skills/auto-mcm").is_symlink())
            self.assertTrue((home / ".dsh/skills/auto-mcm").is_symlink())
            self.call(home, "check")
            self.call(home, "uninstall", "--runtime", "dsh")
            self.assertTrue((home / ".agents/skills/auto-mcm").is_symlink())
            self.assertFalse((home / ".dsh/skills/auto-mcm").exists())
            receipt = json.loads((home / ".local/share/auto-mcm-pro/install-receipt.json").read_text())
            self.assertEqual(receipt["runtimes"], ["codex"])
            self.call(home, "uninstall")
            self.assertFalse((home / ".local/share/auto-mcm-pro/install-receipt.json").exists())

    def test_copy_install_update_and_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--copy", "--runtime", "all", "--without-lean")
            bundle = home / ".local/share/auto-mcm-pro/current"
            self.assertTrue((bundle / "addons/leangate/lean-toolchain").is_file())
            self.assertTrue((bundle / "LEAN_GATE_DESIGN.md").is_file())
            self.assertTrue((bundle / "CHANGELOG.md").is_file())
            self.assertFalse((bundle / ".opencode/node_modules").exists())
            self.assertTrue((home / ".claude/skills/auto-mcm").is_symlink())
            self.call(home, "install")
            repeated = json.loads((bundle.parent / "install-receipt.json").read_text())
            self.assertEqual(repeated["mode"], "copy")
            self.assertEqual(repeated["runtimes"], ["claude", "codex", "dsh", "opencode"])
            self.call(home, "update", "--repair")
            self.call(home, "update", "--check")
            self.call(home, "uninstall")
            self.assertFalse(bundle.exists())
            self.assertFalse(bundle.parent.exists())

    def test_refuses_unmanaged_destination_and_unsafe_toolchain_purge(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); target = home / ".agents/skills/auto-mcm"
            target.mkdir(parents=True); (target / "mine.txt").write_text("keep")
            self.call(home, "install", "--runtime", "codex", "--without-lean", expected=1)
            self.assertTrue((target / "mine.txt").is_file())
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--runtime", "codex", "--without-lean")
            self.call(home, "uninstall", "--purge-toolchain", expected=1)
            self.assertTrue((home / ".agents/skills/auto-mcm").is_symlink())

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--copy", "--runtime", "all", "--with-lean", "--dry-run")
            self.assertEqual(list(home.iterdir()), [])

    def test_first_interactive_install_prompts_for_dependencies_and_lean(self):
        import scripts.installer.lifecycle as lifecycle

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            args = type("Args", (), {"home": str(home), "runtime": ["codex"],
                "copy": False, "with_python_deps": False,
                "without_python_deps": False, "with_lean": False,
                "without_lean": False, "check": False, "dry_run": False})()
            fake_stdin = mock.Mock()
            fake_stdin.isatty.return_value = True

            def prepared(target, _dry_run):
                target["python_dependencies"] = {
                    "packages": list(lifecycle.PYTHON_DEPENDENCIES.values()),
                    "installed_by_installer": [], "python": sys.executable}

            with mock.patch.object(lifecycle.sys, "stdin", fake_stdin), \
                    mock.patch("builtins.input", side_effect=["", "n"]) as prompt, \
                    mock.patch.object(lifecycle, "prepare_python_dependencies",
                                      side_effect=prepared), \
                    mock.patch.object(lifecycle, "missing_python_dependencies",
                                      return_value=[]):
                self.assertEqual(lifecycle.install(args), 0)
            self.assertEqual(prompt.call_count, 2)
            receipt = json.loads((home / ".local/share/auto-mcm-pro/install-receipt.json").read_text())
            self.assertIsNotNone(receipt["python_dependencies"])
            self.assertIsNone(receipt["lean"])

    def test_preflight_failure_leaves_no_orphan_links(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); conflict = home / ".dsh/skills/auto-mcm"
            conflict.mkdir(parents=True); (conflict / "mine.txt").write_text("keep")
            self.call(home, "install", "--runtime", "all", "--without-lean", expected=1)
            self.assertFalse((home / ".agents/skills/auto-mcm").exists())
            self.assertFalse((home / ".claude/skills/auto-mcm").exists())
            self.assertTrue((conflict / "mine.txt").is_file())

    def test_copy_refusal_preserves_preexisting_recovery_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / ".local/share/auto-mcm-pro"
            backup = data / ".previous"
            backup.mkdir(parents=True)
            (backup / "marker.txt").write_text("preserve")
            self.call(home, "install", "--copy", "--runtime", "codex",
                      "--without-lean", "--without-python-deps", expected=1)
            self.assertEqual((backup / "marker.txt").read_text(), "preserve")
            self.assertFalse((data / "current").exists())
            self.assertEqual(list(data.glob(".staging-*")), [])

    def test_rejects_unsafe_receipt_target(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--runtime", "codex", "--without-lean")
            receipt_path = home / ".local/share/auto-mcm-pro/install-receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["targets"][0]["path"] = str(home / "valuable-data")
            receipt_path.write_text(json.dumps(receipt))
            self.call(home, "uninstall", expected=1)
            self.assertTrue((home / ".agents/skills/auto-mcm").is_symlink())

    def test_update_preserves_lean_ownership_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.call(home, "install", "--runtime", "codex", "--without-lean")
            receipt_path = home / ".local/share/auto-mcm-pro/install-receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["lean"] = {"toolchain": "leanprover/lean4:v4.32.0",
                               "created_elan": True, "created_toolchain": True}
            receipt_path.write_text(json.dumps(receipt))

            # Avoid invoking Elan in this unit test while exercising the same merge.
            import scripts.installer.lifecycle as lifecycle
            original = lifecycle.prepare_lean
            original_verify = lifecycle.verify_install
            try:
                lifecycle.prepare_lean = lambda _home, target, _dry: target.update(
                    lean={"toolchain": "leanprover/lean4:v4.32.0",
                          "created_elan": False, "created_toolchain": False})
                lifecycle.verify_install = lambda _home, _receipt, lean: True
                args = type("Args", (), {"home": str(home), "runtime": ["codex"],
                    "copy": False, "with_lean": True, "without_lean": False,
                    "with_python_deps": False, "without_python_deps": True,
                    "check": False, "dry_run": False})()
                self.assertEqual(lifecycle.install(args), 0)
            finally:
                lifecycle.prepare_lean = original
                lifecycle.verify_install = original_verify
            updated = json.loads(receipt_path.read_text())
            self.assertTrue(updated["lean"]["created_elan"])
            self.assertTrue(updated["lean"]["created_toolchain"])


if __name__ == "__main__":
    unittest.main()
