from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from scripts.leangate.core import (LeanGateError, atomic_json, audit_claim, axiom_audit_ok, current_hashes,
                              initialize, read_manifest, refresh_freshness,
                              validate_manifest)


REPO = Path(__file__).resolve().parents[1]
ADDON = REPO / "addons" / "leangate"


class LeanGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "CUMCM_Workspace"
        self.root = initialize(self.workspace, ADDON, "selected")

    def tearDown(self):
        self.tmp.cleanup()

    def claim(self):
        spec = self.root / "Specs" / "Problem1.lean"
        proof = self.root / "Proofs" / "Problem1.lean"
        spec.write_text("def modelValue : Int := 4\n", encoding="utf-8")
        proof.write_text("theorem claimed_value : modelValue = 4 := by rfl\n", encoding="utf-8")
        return {
            "claim_id": "LG-P1-TEST-001", "problem_n": 1, "title": "test",
            "epistemic_type": "theorem", "formal_level": "L2", "lifecycle": "FROZEN",
            "proof": "UNCHECKED", "semantic_review": "HUMAN_AUDITED", "freshness": "FRESH",
            "assurance": "NUMERICAL", "applicability": "ELIGIBLE", "error_reason": None,
            "spec_file": "Specs/Problem1.lean", "proof_file": "Proofs/Problem1.lean",
            "theorem_name": "claimed_value", "assumption_ids": [],
            "empirical_dependencies": [], "certificate_file": None,
            "scope_note": "test only", "frozen_hashes": {}, "last_verified_at": None,
            "verification_snapshot": None, "semantic_approval": None,
            "required_approval": None,
        }

    def test_initialize_is_idempotent(self):
        initialize(self.workspace, ADDON, "required")
        self.assertEqual(read_manifest(self.workspace)["policy"], "required")
        with self.assertRaisesRegex(LeanGateError, "downgrade"):
            initialize(self.workspace, ADDON, "selected")

    def test_manifest_rejects_duplicate_claims(self):
        claim = self.claim()
        obligation = {"claim_id": claim["claim_id"], "problem_n": 1,
                      "applicability": "ELIGIBLE", "required": False}
        data = {"schema_version": 1, "policy": "selected",
                "obligations": [obligation], "claims": [claim, claim.copy()]}
        with self.assertRaisesRegex(LeanGateError, "duplicate"):
            validate_manifest(data, self.root, require_files=True)

    def test_manifest_rejects_path_escape(self):
        claim = self.claim(); claim["proof_file"] = "../outside.lean"
        with self.assertRaisesRegex(LeanGateError, "unsafe"):
            validate_manifest({"schema_version": 1, "policy": "selected",
                               "obligations": [{"claim_id": claim["claim_id"], "problem_n": 1,
                                                "applicability": "ELIGIBLE", "required": False}],
                               "claims": [claim]},
                              self.root, require_files=False)

    def test_changed_input_becomes_stale(self):
        claim = self.claim(); claim["frozen_hashes"] = current_hashes(self.root, claim)
        self.assertEqual(refresh_freshness(self.root, claim), "FRESH")
        (self.root / claim["proof_file"]).write_text("theorem claimed_value : True := by trivial\n", encoding="utf-8")
        self.assertEqual(refresh_freshness(self.root, claim), "STALE")

    def test_changed_contract_or_core_becomes_stale(self):
        claim = self.claim(); claim["frozen_hashes"] = current_hashes(self.root, claim)
        claim["scope_note"] = "a broader and invalid scope"
        self.assertEqual(refresh_freshness(self.root, claim), "STALE")
        claim["scope_note"] = "test only"; claim["frozen_hashes"] = current_hashes(self.root, claim)
        core = self.root / "LeanGate" / "Core" / "ResourceAllocation.lean"
        core.write_text(core.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8")
        self.assertEqual(refresh_freshness(self.root, claim), "STALE")

    def test_symlink_input_is_rejected(self):
        claim = self.claim(); proof = self.root / claim["proof_file"]
        outside = Path(self.tmp.name) / "outside.lean"
        outside.write_text("theorem claimed_value : True := by trivial\n", encoding="utf-8")
        proof.unlink(); os.symlink(outside, proof)
        with self.assertRaisesRegex(LeanGateError, "symlink"):
            current_hashes(self.root, claim)

    def test_certificate_type_requires_certificate_file(self):
        claim = self.claim(); claim["epistemic_type"] = "certificate"
        obligation = {"claim_id": claim["claim_id"], "problem_n": 1,
                      "applicability": "ELIGIBLE", "required": False}
        with self.assertRaisesRegex(LeanGateError, "requires certificate_file"):
            validate_manifest({"schema_version": 1, "policy": "selected",
                               "obligations": [obligation], "claims": [claim]},
                              self.root, require_files=False)

    def test_symlinked_lean_directory_is_rejected(self):
        claim = self.claim()
        outside = Path(self.tmp.name) / "outside"; outside.mkdir()
        (outside / "Injected.lean").write_text("axiom hidden : True\n", encoding="utf-8")
        os.symlink(outside, self.root / "Imported")
        with self.assertRaisesRegex(LeanGateError, "symlink directory"):
            current_hashes(self.root, claim)

    def test_symlinked_lake_cache_is_rejected(self):
        claim = self.claim()
        outside = Path(self.tmp.name) / "fake-cache"; outside.mkdir()
        os.symlink(outside, self.root / ".lake")
        with self.assertRaisesRegex(LeanGateError, "symlink directory"):
            current_hashes(self.root, claim)

    def test_audit_rejects_placeholder_and_fake_name(self):
        claim = self.claim()
        (self.root / claim["proof_file"]).write_text("-- theorem claimed_value\ntheorem other : True := by sorry\n", encoding="utf-8")
        issues = audit_claim(self.root, claim)
        self.assertTrue(any("sorry" in issue for issue in issues))
        self.assertTrue(any("theorem_name" in issue for issue in issues))

    def test_atomic_json_round_trip(self):
        path = self.root / "reports" / "sample.json"
        atomic_json(path, {"ok": True})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})

    def test_axiom_policy(self):
        self.assertEqual(axiom_audit_ok("depends on axioms: [propext]"), (True, []))
        self.assertEqual(axiom_audit_ok("depends on axioms: [evil]"), (False, ["evil"]))
        self.assertEqual(axiom_audit_ok("unexpected Lean output"),
                         (False, ["UNPARSEABLE_AXIOM_OUTPUT"]))

    def test_resource_generator_rejects_float(self):
        cert = self.root / "Certificates" / "bad.json"
        cert.write_text(json.dumps({"capacities": [10], "allocations": [9.5],
                                    "profits": [2], "budget": 10,
                                    "scaling_policy": "exact"}), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(REPO / "scripts" / "leangate.py"),
            "--workspace", str(self.workspace), "generate-resource", "--problem-n", "1",
            "--certificate-file", "Certificates/bad.json", "--spec-file", "Specs/Problem1.lean",
            "--proof-file", "Proofs/Problem1.lean", "--theorem-name", "candidate_feasible",
        ], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("exact JSON integers", result.stderr)


if __name__ == "__main__":
    unittest.main()
