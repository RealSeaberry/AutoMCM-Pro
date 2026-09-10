from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "scripts" / "pipeline_manager.py"
CLI = REPO / "scripts" / "leangate.py"
GATE = REPO / "scripts" / "quality_gate.py"
SCHEMA = json.loads((REPO / "addons/leangate/schemas/claims.schema.json").read_text())


class LeanGateSecurityTests(unittest.TestCase):
    def run_cmd(self, command, cwd, expected=0):
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def init(self, root: Path, policy="selected") -> Path:
        self.run_cmd([sys.executable, str(PIPELINE), "init", "--mode", "AP",
                  "--contest", "CUMCM", "--lean-policy", policy], root)
        return root / "CUMCM_Workspace"

    def register_draft(self, root: Path) -> Path:
        ws = self.init(root)
        formal = ws / "formal"
        (formal / "Specs/Problem1.lean").write_text("def sample : Nat := 1\n")
        (formal / "Proofs/Problem1.lean").write_text("theorem sample_ok : True := by trivial\n")
        self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "register",
                  "--claim-id", "LG-P1-TEST-001", "--problem-n", "1", "--title", "test",
                  "--spec-file", "Specs/Problem1.lean", "--proof-file", "Proofs/Problem1.lean",
                  "--theorem-name", "sample_ok", "--scope-note", "test scope"], root)
        self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws),
                      "seal-assessment"], root)
        return ws

    def test_policy_and_obligation_scope_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.register_draft(root)
            manifest_file = ws / "formal/claims.json"
            manifest = json.loads(manifest_file.read_text())
            manifest["policy"] = "required"
            manifest_file.write_text(json.dumps(manifest))
            result = self.run_cmd([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                              root, expected=1)
            self.assertIn("policy", result.stdout)
            manifest["policy"] = "selected"
            manifest["obligations"][0]["applicability"] = "NOT_APPLICABLE"
            manifest["obligations"][0]["exclusion_reason"] = "tamper"
            manifest_file.write_text(json.dumps(manifest))
            result = self.run_cmd([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                              root, expected=1)
            self.assertTrue("scope mismatch" in result.stdout or "baseline" in result.stdout)
            manifest["claims"] = []
            manifest_file.write_text(json.dumps(manifest))
            result = self.run_cmd([sys.executable, str(GATE), "formal", "--problem-n", "1"],
                                  root, expected=1)
            self.assertIn("registry mismatch", result.stdout)

    def test_pipeline_rejects_symlinked_verification_script(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.init(root)
            verification = ws / "src/verifications"
            verification.mkdir(parents=True)
            target = root / "outside.py"; target.write_text("print('PASS')\n")
            link = verification / "verify_1.py"; os.symlink(target, link)
            result = self.run_cmd([sys.executable, str(PIPELINE), "advance", "model_1_verify",
                               "--verify-script", str(link)], root, expected=1)
            self.assertIn("symlink", result.stdout + result.stderr)

    def test_manual_checkpoint_is_bound_to_stage_and_round(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.run_cmd([sys.executable, str(PIPELINE), "init", "--mode", "MANUAL",
                          "--contest", "CUMCM"], root)
            self.run_cmd([sys.executable, str(PIPELINE), "request-review", "--stage",
                          "problem_analysis", "--summary", "done"], root)
            result = self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"],
                                  root, expected=1)
            self.assertIn("尚无人类批准", result.stdout + result.stderr)
            intervention = root / "CUMCM_Workspace/state/human_intervention.md"
            with intervention.open("a") as handle:
                handle.write("\n[APPROVED:model_1_build:1]\n")
            self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"],
                         root, expected=1)
            with intervention.open("a") as handle:
                handle.write("\n[APPROVED:problem_analysis:1]\n")
            self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"], root)

    def test_ap_checkpoint_records_scoped_self_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.init(root, policy="off")
            self.run_cmd([sys.executable, str(PIPELINE), "request-review", "--stage",
                          "problem_analysis", "--summary", "self reviewed"], root)
            self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"], root)

    def test_formal_assessment_is_required_sealed_and_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.init(root, policy="selected")
            self.run_cmd([sys.executable, str(PIPELINE), "request-review", "--stage",
                          "problem_analysis", "--summary", "reviewed"], root)
            result = self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"],
                                  root, expected=1)
            self.assertIn("formal applicability assessment", result.stdout + result.stderr)
            formal = ws / "formal"
            (formal / "Specs/Problem1.lean").write_text("def sample : Nat := 1\n")
            (formal / "Proofs/Problem1.lean").write_text("theorem sample_ok : True := by trivial\n")
            self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "register",
                "--claim-id", "LG-P1-SAFETY-001", "--problem-n", "1", "--title", "safe",
                "--spec-file", "Specs/Problem1.lean", "--proof-file", "Proofs/Problem1.lean",
                "--theorem-name", "sample_ok", "--scope-note", "safety bound",
                "--risk-category", "safety_bound", "--classification-reason", "controls feasibility"], root)
            manifest = json.loads((formal / "claims.json").read_text())
            self.assertTrue(manifest["obligations"][0]["mandatory"])
            self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "seal-assessment"], root)
            self.run_cmd([sys.executable, str(PIPELINE), "advance", "problem_analysis"], root)
            result = self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "register",
                "--claim-id", "LG-P1-LATE-001", "--problem-n", "1", "--title", "late",
                "--spec-file", "Specs/Problem1.lean", "--proof-file", "Proofs/Problem1.lean",
                "--theorem-name", "sample_ok", "--scope-note", "late"], root, expected=1)
            self.assertIn("sealed", result.stderr)
            self.run_cmd([sys.executable, str(PIPELINE), "rework", "problem_analysis",
                          "--feedback", "reclassify"], root)
            self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "register",
                "--claim-id", "LG-P1-LATE-001", "--problem-n", "1", "--title", "late",
                "--spec-file", "Specs/Problem1.lean", "--proof-file", "Proofs/Problem1.lean",
                "--theorem-name", "sample_ok", "--scope-note", "late"], root)

    def test_launch_rejects_unproved_cited_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.register_draft(root)
            paper = ws / "latex"; paper.mkdir()
            (paper / "main.tex").write_text("LG-P1-TEST-001\n")
            result = self.run_cmd([sys.executable, str(GATE), "launch-check"], root, expected=1)
            self.assertIn("proof=UNCHECKED", result.stdout)

    def test_schema_and_runtime_reject_traversal_and_accept_export_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.register_draft(root)
            manifest = json.loads((ws / "formal/claims.json").read_text())
            jsonschema.validate(manifest, SCHEMA)
            manifest["claims"][0]["spec_file"] = "../escape.lean"
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(manifest, SCHEMA)
            (ws / "formal/claims.json").write_text(json.dumps(manifest))
            result = self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "status"],
                              root, expected=1)
            self.assertIn("unsafe", result.stderr)

    def test_excluded_export_is_metadata_only_and_schema_is_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.init(root)
            formal = ws / "formal"
            (formal / "Specs/Problem1.lean").write_text("def excluded : Nat := 1\n")
            (formal / "Proofs/Problem1.lean").write_text("theorem excluded_ok : True := by trivial\n")
            self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "register",
                          "--claim-id", "LG-P1-EXCLUDED-001", "--problem-n", "1",
                          "--title", "excluded", "--spec-file", "Specs/Problem1.lean",
                          "--proof-file", "Proofs/Problem1.lean", "--theorem-name", "excluded_ok",
                          "--scope-note", "not applicable", "--applicability", "NOT_APPLICABLE",
                          "--exclusion-reason", "empirical claim"], root)
            (formal / "schemas/claims.schema.json").write_text("{}\n")
            artifact = root / "artifact"
            self.run_cmd([sys.executable, str(CLI), "--workspace", str(ws), "export",
                          "--problem-n", "1", "--output", str(artifact)], root)
            exported = json.loads((artifact / "claims.json").read_text())
            jsonschema.validate(exported, json.loads((artifact / "schemas/claims.schema.json").read_text()))
            self.assertEqual(exported["claims"], [])
            self.assertEqual(json.loads((artifact / "exclusions.json").read_text())[0]["claim_id"],
                             "LG-P1-EXCLUDED-001")
            self.assertEqual((artifact / "schemas/claims.schema.json").read_bytes(),
                             (REPO / "addons/leangate/schemas/claims.schema.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
