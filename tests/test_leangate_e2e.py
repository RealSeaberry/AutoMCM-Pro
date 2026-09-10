from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import jsonschema

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "scripts" / "leangate.py"
GATE = REPO / "scripts" / "quality_gate.py"
TOOLCHAIN = "leanprover/lean4:v4.32.0"


class LeanGateEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["elan", "toolchain", "list"], text=True,
                                capture_output=True, check=False)
        if result.returncode != 0 or TOOLCHAIN not in result.stdout:
            raise unittest.SkipTest(f"{TOOLCHAIN} is not installed")

    def run_cli(self, root: Path, *args: str, expected: int = 0):
        result = subprocess.run([sys.executable, str(CLI), "--workspace",
                                 str(root / "CUMCM_Workspace"), *args],
                                cwd=root, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_certificate_to_kernel_gate_and_staleness(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = root / "CUMCM_Workspace"
            self.run_cli(root, "init", "--policy", "required")
            shutil.copy2(REPO / "tests" / "fixtures" / "resource_certificate.json",
                         ws / "formal" / "Certificates" / "problem1.json")
            (ws / "state").mkdir(parents=True, exist_ok=True)
            approval = ws / "state" / "leangate_approval.md"
            approval.write_text("[APPROVED LeanGate LG-P1-FEAS-001]\n"
                                "[REQUIRED LeanGate LG-P1-FEAS-001]\n", encoding="utf-8")
            self.run_cli(root, "generate-resource", "--problem-n", "1",
                         "--certificate-file", "Certificates/problem1.json",
                         "--spec-file", "Specs/Problem1.lean",
                         "--proof-file", "Proofs/Problem1.lean",
                         "--theorem-name", "candidate_feasible")
            self.run_cli(root, "register", "--claim-id", "LG-P1-FEAS-001",
                         "--problem-n", "1", "--title", "exact resource feasibility",
                         "--spec-file", "Specs/Problem1.lean", "--proof-file", "Proofs/Problem1.lean",
                         "--theorem-name", "LeanGate.Generated.P1.candidate_feasible",
                         "--certificate-file", "Certificates/problem1.json",
                         "--scope-note", "exact scaled feasibility and budget only")
            self.run_cli(root, "semantic-review", "--claim-id", "LG-P1-FEAS-001",
                         "--verdict", "pass", "--reviewer", "human",
                         "--approval-file", str(approval), "--note", "approved fixture semantics")
            self.run_cli(root, "require", "--claim-id", "LG-P1-FEAS-001",
                         "--approval-file", str(approval), "--note", "required fixture")
            self.run_cli(root, "freeze", "--claim-id", "LG-P1-FEAS-001")
            self.run_cli(root, "verify", "--problem-n", "1", "--timeout", "60")

            gate = subprocess.run([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                                  cwd=root, text=True, capture_output=True, check=False)
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            artifact = root / "artifact"
            self.run_cli(root, "export", "--problem-n", "1", "--output", str(artifact))
            self.assertTrue((artifact / "LeanGate" / "Core" / "ResourceAllocation.lean").is_file())
            exported = json.loads((artifact / "claims.json").read_text(encoding="utf-8"))
            self.assertEqual(exported["obligations"][0]["claim_id"], "LG-P1-FEAS-001")
            schema = json.loads((artifact / "schemas/claims.schema.json").read_text())
            jsonschema.validate(exported, schema)

            original_approval = approval.read_text(encoding="utf-8")
            approval.write_text(original_approval + "tampered\n", encoding="utf-8")
            gate = subprocess.run([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                                  cwd=root, text=True, capture_output=True, check=False)
            self.assertEqual(gate.returncode, 1, gate.stdout + gate.stderr)
            approval.write_text(original_approval, encoding="utf-8")

            certificate = ws / "formal" / "Certificates" / "problem1.json"
            data = json.loads(certificate.read_text(encoding="utf-8"))
            data["allocations"][0] -= 1
            certificate.write_text(json.dumps(data), encoding="utf-8")
            gate = subprocess.run([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                                  cwd=root, text=True, capture_output=True, check=False)
            self.assertEqual(gate.returncode, 1, gate.stdout + gate.stderr)
            self.assertIn("freshness=STALE", gate.stdout)


if __name__ == "__main__":
    unittest.main()
