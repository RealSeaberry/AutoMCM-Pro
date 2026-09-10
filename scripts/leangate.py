#!/usr/bin/env python3
"""LeanGate command line interface. All runtime bindings use this entrypoint."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leangate.core import (LeanGateError, atomic_json, audit_claim, axiom_audit_ok, claim_by_id, current_hashes,
                      formal_dir, initialize, load_json, manifest_path, read_manifest,
                      refresh_freshness, run_axiom_audit, run_lean, safe_path, safe_relative, summarize, utc_now,
                      validate_manifest, sha256, RISK_CATEGORIES)

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "leangate"


def workspace(args) -> Path:
    return Path(args.workspace).resolve()


def save_manifest(ws: Path, data: dict) -> None:
    validate_manifest(data, formal_dir(ws), require_files=False)
    atomic_json(manifest_path(ws), data)


def update_pipeline_summary(ws: Path, data: dict, problem_n: int) -> None:
    pipeline = ws / "state" / "pipeline.json"
    if not pipeline.is_file():
        return
    try:
        state = load_json(pipeline)
    except LeanGateError:
        return
    qstate = state.setdefault("lean_formal", {"enabled": True, "policy": data["policy"], "problems": {}})
    qstate["enabled"] = data["policy"] != "off"; qstate["policy"] = data["policy"]
    qstate.setdefault("problems", {})[str(problem_n)] = summarize(data, formal_dir(ws), problem_n)
    atomic_json(pipeline, state)


def sync_pipeline_registry(ws: Path, data: dict) -> None:
    pipeline = ws / "state" / "pipeline.json"
    if not pipeline.is_file():
        return
    state = load_json(pipeline)
    qstate = state.setdefault("lean_formal", {})
    qstate["obligation_ids"] = sorted(o["claim_id"] for o in data["obligations"])
    qstate["obligation_baseline"] = sorted(
        ({key: o[key] for key in ("claim_id", "problem_n", "applicability", "required")}
         for o in data["obligations"]), key=lambda item: item["claim_id"])
    qstate["required_claim_ids"] = sorted(
        o["claim_id"] for o in data["obligations"] if o.get("required"))
    assessment = sorted(({
        "claim_id": o["claim_id"], "problem_n": o["problem_n"],
        "applicability": o["applicability"], "mandatory": o.get("mandatory", False),
        "risk_categories": sorted(o.get("risk_categories", [])),
    } for o in data["obligations"]), key=lambda item: item["claim_id"])
    if not qstate.get("assessment_sealed"):
        qstate["assessment_baseline"] = assessment
    atomic_json(pipeline, state)


def approval_evidence(ws: Path, value: str, marker: str) -> dict:
    if not value:
        raise LeanGateError("approval file is required")
    raw = Path(value)
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    state_root = (ws / "state").resolve()
    current = Path(raw.anchor)
    if any((current := current / part).is_symlink() for part in raw.parts[1:]):
        raise LeanGateError("approval file cannot contain symlink components")
    path = raw.resolve()
    if state_root not in path.parents or not path.is_file():
        raise LeanGateError(f"approval file must be a regular file under {state_root}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker not in text:
        raise LeanGateError(f"approval file must contain {marker}")
    return {"file": str(path.relative_to(ws.resolve())), "sha256": sha256(path),
            "marker": marker}


def cmd_doctor(args) -> int:
    ws = workspace(args)
    root = formal_dir(ws) if formal_dir(ws).exists() else ADDON
    checks = []
    for tool in ("elan", "lean", "lake"):
        path = shutil.which(tool)
        checks.append((tool, bool(path), path or "not found"))
    expected = (root / "lean-toolchain").read_text(encoding="utf-8").strip()
    try:
        proc = subprocess.run(["lean", "--version"], cwd=root, text=True,
                              capture_output=True, timeout=15, check=False)
        output = proc.stdout.strip() or proc.stderr.strip()
        expected_version = expected.rsplit(":v", 1)[-1]
        checks.append(("pinned toolchain", proc.returncode == 0 and expected_version in output, output))
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        checks.append(("pinned toolchain", False, str(exc)))
    print(f"LeanGate doctor (expected {expected})")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def cmd_init(args) -> int:
    target = initialize(workspace(args), ADDON, args.policy, force=args.force)
    print(f"[leangate] initialized {target} (policy={args.policy})")
    return 0


def _exact_int_list(value, field: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise LeanGateError(f"certificate {field} must be a non-empty list")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise LeanGateError(f"certificate {field} must contain exact JSON integers")
    return value


def _fin_cases_proof(size: int, base_indent: str = "  ") -> str:
    def rec(remaining: int, variable: str, indent: str) -> list[str]:
        if remaining == 1:
            return [f"{indent}refine Fin.cases ?_ (fun impossible => Fin.elim0 impossible) {variable}",
                    f"{indent}decide"]
        nxt = f"i{size - remaining + 1}"
        return [f"{indent}refine Fin.cases ?_ (fun {nxt} => ?_) {variable}",
                f"{indent}· decide", f"{indent}· " + rec(remaining - 1, nxt, indent + "  ")[0].lstrip()] + rec(remaining - 1, nxt, indent + "  ")[1:]
    return "\n".join([f"{base_indent}intro i"] + rec(size, "i", base_indent))


def cmd_generate_resource(args) -> int:
    ws = workspace(args); root = formal_dir(ws)
    certificate_path = safe_path(root, args.certificate_file, suffix=".json", require_exists=True)
    certificate = load_json(certificate_path)
    if not isinstance(certificate, dict):
        raise LeanGateError("resource certificate must be a JSON object")
    capacities = _exact_int_list(certificate.get("capacities"), "capacities")
    allocations = _exact_int_list(certificate.get("allocations"), "allocations")
    profits = _exact_int_list(certificate.get("profits"), "profits")
    budget = certificate.get("budget")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise LeanGateError("certificate budget must be an exact JSON integer")
    scaling_policy = certificate.get("scaling_policy")
    if not isinstance(scaling_policy, str) or not scaling_policy.strip():
        raise LeanGateError("certificate requires a non-empty scaling_policy")
    if len(capacities) != len(allocations) or len(capacities) != len(profits):
        raise LeanGateError("capacities, allocations and profits must have the same length")
    if len(capacities) > 256:
        raise LeanGateError("resource certificate exceeds the 256-variable MVP limit")
    if any(value < 0 for value in capacities):
        raise LeanGateError("capacities must be nonnegative")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", args.theorem_name):
        raise LeanGateError("generated theorem_name must be an unqualified Lean identifier")
    n = len(capacities); namespace = f"LeanGate.Generated.P{args.problem_n}"
    cap_cases = "\n".join(f"  | {i} => {value}" for i, value in enumerate(capacities))
    alloc_cases = "\n".join(f"  | {i} => {value}" for i, value in enumerate(allocations))
    profit_cases = "\n".join(f"  | {i} => {value}" for i, value in enumerate(profits))
    certificate_hash = sha256(certificate_path)
    marker = f"-- LEANGATE-CERTIFICATE-SHA256: {certificate_hash}"
    spec = f"""{marker}
import LeanGate.Core.ResourceAllocation

namespace {namespace}

def resourceInstance : LeanGate.ResourceInstance {n} where
  capacity
{cap_cases}
  profit
{profit_cases}
  budget := {budget}

def candidate : Fin {n} → Int
{alloc_cases}

end {namespace}
"""
    spec_rel = safe_relative(args.spec_file, suffix=".lean")
    proof_rel = safe_relative(args.proof_file, suffix=".lean")
    module = ".".join(spec_rel.with_suffix("").parts)
    proof = f"""{marker}
import {module}
import Std.Tactic

namespace {namespace}

theorem {args.theorem_name} : LeanGate.Feasible resourceInstance candidate := by
  constructor
  · {_fin_cases_proof(n, "    ").lstrip()}
  · decide

theorem {args.theorem_name}_certificate :
    LeanGate.UpperBoundCertificate resourceInstance candidate where
  candidate_feasible := {args.theorem_name}
  profit_nonnegative := by
{_fin_cases_proof(n, "    ")}

theorem {args.theorem_name}_objective_upper_bound :
    LeanGate.objective resourceInstance candidate ≤
      LeanGate.objective resourceInstance resourceInstance.capacity :=
  LeanGate.certified_component_upper_bound resourceInstance candidate
    {args.theorem_name}_certificate

end {namespace}
"""
    for rel, content in ((spec_rel, spec), (proof_rel, proof)):
        path = root / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"[leangate] generated exact resource instance ({n} variables) from {args.certificate_file}")
    return 0


def cmd_register(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws)
    pipeline = ws / "state" / "pipeline.json"
    if pipeline.is_file() and load_json(pipeline).get("lean_formal", {}).get("assessment_sealed"):
        raise LeanGateError("formal applicability assessment is sealed; rework problem_analysis before changing it")
    if any(c["claim_id"] == args.claim_id for c in data["claims"]):
        raise LeanGateError(f"duplicate claim_id: {args.claim_id}")
    if args.applicability != "ELIGIBLE" and not args.exclusion_reason:
        raise LeanGateError("non-eligible claim requires --exclusion-reason")
    claim = {
        "claim_id": args.claim_id, "problem_n": args.problem_n, "title": args.title,
        "epistemic_type": args.epistemic_type, "formal_level": args.formal_level,
        "lifecycle": "DRAFT", "proof": "UNCHECKED", "semantic_review": "PENDING",
        "freshness": "STALE", "assurance": "NUMERICAL", "applicability": args.applicability,
        "error_reason": None, "spec_file": str(safe_relative(args.spec_file, suffix=".lean")),
        "proof_file": str(safe_relative(args.proof_file, suffix=".lean")),
        "theorem_name": args.theorem_name, "assumption_ids": args.assumption_id,
        "empirical_dependencies": args.empirical_dependency,
        "certificate_file": str(safe_relative(args.certificate_file, suffix=".json")) if args.certificate_file else None,
        "scope_note": args.scope_note, "frozen_hashes": {}, "last_verified_at": None,
        "verification_snapshot": None, "semantic_approval": None,
        "required_approval": None,
    }
    risks = sorted(set(args.risk_category))
    if risks and args.applicability != "ELIGIBLE":
        raise LeanGateError("risk-classified obligations cannot be NOT_APPLICABLE or DEFERRED")
    data["obligations"].append({"claim_id": args.claim_id, "problem_n": args.problem_n,
        "applicability": args.applicability, "exclusion_reason": args.exclusion_reason,
        "required": False, "registered_at": utc_now(), "mandatory": bool(risks),
        "risk_categories": risks, "classification_reason": args.classification_reason})
    data["claims"].append(claim); validate_manifest(data, root, require_files=False)
    save_manifest(ws, data); sync_pipeline_registry(ws, data)
    print(f"[leangate] registered {args.claim_id}"); return 0


def cmd_seal_assessment(args) -> int:
    ws = workspace(args); data = read_manifest(ws)
    pipeline = ws / "state" / "pipeline.json"
    if not pipeline.is_file():
        raise LeanGateError("pipeline.json is required to seal formal assessment")
    state = load_json(pipeline); qstate = state.get("lean_formal")
    if not qstate or not qstate.get("enabled"):
        raise LeanGateError("LeanGate is not enabled in pipeline")
    count = int(state.get("problem_count", 1))
    uncovered = [n for n in range(1, count + 1) if not any(
        o["problem_n"] == n and o["applicability"] != "DEFERRED"
        for o in data["obligations"])]
    if uncovered:
        raise LeanGateError(f"formal applicability assessment missing problems: {uncovered}")
    sync_pipeline_registry(ws, data)
    state = load_json(pipeline); qstate = state["lean_formal"]
    qstate["assessment_sealed"] = True; qstate["assessment_sealed_at"] = utc_now()
    atomic_json(pipeline, state)
    print("[leangate] formal applicability assessment sealed")
    return 0


def cmd_semantic_review(args) -> int:
    ws = workspace(args); data = read_manifest(ws); claim = claim_by_id(data, args.claim_id)
    if args.reviewer == "human":
        marker = (f"[APPROVED LeanGate {args.claim_id}]" if args.verdict == "pass"
                  else f"[REWORK LeanGate {args.claim_id}]")
        claim["semantic_approval"] = approval_evidence(ws, args.approval_file, marker)
    else:
        claim["semantic_approval"] = None
    claim["semantic_review"] = ("HUMAN_AUDITED" if args.reviewer == "human" else "AUTO_AUDITED") if args.verdict == "pass" else "REJECTED"
    claim["semantic_review_note"] = args.note; claim["semantic_review_at"] = utc_now()
    if args.verdict == "rework":
        claim.update(lifecycle="DRAFT", proof="UNCHECKED", freshness="STALE", assurance="NUMERICAL")
    save_manifest(ws, data); print(f"[leangate] semantic review {args.verdict}: {args.claim_id}")
    return 0 if args.verdict == "pass" else 1


def cmd_require(args) -> int:
    ws = workspace(args); data = read_manifest(ws); claim = claim_by_id(data, args.claim_id)
    if claim["semantic_review"] != "HUMAN_AUDITED":
        raise LeanGateError("required obligation needs HUMAN_AUDITED semantic review")
    marker = f"[REQUIRED LeanGate {args.claim_id}]"
    evidence = approval_evidence(ws, args.approval_file, marker)
    claim["required_approval"] = evidence
    for obligation in data["obligations"]:
        if obligation["claim_id"] == args.claim_id:
            obligation.update(required=True, required_at=utc_now(), approval_note=args.note,
                              required_approval=evidence)
            break
    save_manifest(ws, data); sync_pipeline_registry(ws, data)
    print(f"[leangate] required obligation approved: {args.claim_id}"); return 0


def cmd_freeze(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws)
    claim = claim_by_id(data, args.claim_id)
    if claim["semantic_review"] not in {"AUTO_AUDITED", "HUMAN_AUDITED"}:
        raise LeanGateError("semantic review must pass before freeze")
    validate_manifest(data, root, require_files=True)
    claim["frozen_hashes"] = current_hashes(root, claim)
    claim.update(lifecycle="FROZEN", proof="UNCHECKED", freshness="FRESH",
                 assurance="NUMERICAL", error_reason=None, frozen_at=utc_now())
    save_manifest(ws, data); print(f"[leangate] frozen {args.claim_id}"); return 0


def _verify_one(root: Path, claim: dict, timeout: int) -> dict:
    claim["freshness"] = refresh_freshness(root, claim)
    report = {"claim_id": claim["claim_id"], "problem_n": claim["problem_n"],
              "scope": claim["scope_note"], "checked_at": utc_now(),
              "freshness": claim["freshness"], "audit": "FAIL", "lean_build": "NOT_RUN",
              "result": "FAIL", "assurance": "NUMERICAL", "error_reason": None,
              "snapshot": claim.get("frozen_hashes", {})}
    if claim["lifecycle"] not in {"FROZEN", "CLOSED"} or claim["freshness"] != "FRESH":
        report["error_reason"] = "STALE_SPEC_OR_CERTIFICATE"; return report
    if claim["semantic_review"] not in {"AUTO_AUDITED", "HUMAN_AUDITED"}:
        report["error_reason"] = "SEMANTIC_REVIEW_REQUIRED"; return report
    issues = audit_claim(root, claim)
    if issues:
        report["audit_issues"] = issues; report["error_reason"] = "FORBIDDEN_OR_INVALID_LEAN"; return report
    report["audit"] = "PASS"
    try:
        proc = run_lean(root, claim["spec_file"], claim["proof_file"], timeout)
    except subprocess.TimeoutExpired:
        report["error_reason"] = "TIMEOUT"; return report
    except LeanGateError as exc:
        report["error_reason"] = "TOOLCHAIN_UNAVAILABLE"; report["stderr"] = str(exc); return report
    report["stdout"] = proc.stdout[-8000:]; report["stderr"] = proc.stderr[-8000:]
    report["lean_build"] = "PASS" if proc.returncode == 0 else "FAIL"
    if proc.returncode == 0:
        theorem_name = claim["theorem_name"]
        if "." not in theorem_name and claim["proof_file"].startswith("Proofs/Problem"):
            theorem_name = f"LeanGate.Generated.P{claim['problem_n']}.{theorem_name}"
        try:
            axioms = run_axiom_audit(root, claim["proof_file"], theorem_name, timeout)
        except (subprocess.TimeoutExpired, LeanGateError) as exc:
            report["error_reason"] = "AXIOM_AUDIT_ERROR"; report["axiom_stderr"] = str(exc); return report
        report["axiom_stdout"] = axioms.stdout[-8000:]
        report["axiom_stderr"] = axioms.stderr[-8000:]
        axiom_ok, rejected = axiom_audit_ok(axioms.stdout + axioms.stderr)
        report["rejected_axioms"] = rejected
        report["axiom_audit"] = "PASS" if axioms.returncode == 0 and axiom_ok else "FAIL"
        if report["axiom_audit"] == "PASS":
            report.update(result="FORMALLY_PROVED", assurance="KERNEL_PROOF")
        else:
            report["error_reason"] = "UNAPPROVED_AXIOMS"
    else:
        report["error_reason"] = "BUILD_ERROR"
    return report


def cmd_verify(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws)
    validate_manifest(data, root, require_files=True)
    claims = [c for c in data["claims"] if c["problem_n"] == args.problem_n
              and c["applicability"] == "ELIGIBLE"]
    if not claims:
        print(f"[leangate] no claims for problem {args.problem_n}"); return 2
    all_pass = True
    for claim in claims:
        report = _verify_one(root, claim, args.timeout)
        atomic_json(root / "reports" / f"{claim['claim_id']}.json", report)
        if report["result"] == "FORMALLY_PROVED":
            claim.update(lifecycle="CLOSED", proof="PROVED", freshness="FRESH",
                         assurance=report["assurance"], error_reason=None,
                         last_verified_at=report["checked_at"],
                         verification_snapshot=claim["frozen_hashes"])
            print(f"PASS {claim['claim_id']}: KERNEL_PROOF")
        else:
            claim.update(proof="UNKNOWN", assurance="NUMERICAL",
                         error_reason=report["error_reason"])
            all_pass = False; print(f"FAIL {claim['claim_id']}: {report['error_reason']}")
    save_manifest(ws, data); update_pipeline_summary(ws, data, args.problem_n)
    return 0 if all_pass else 1


def cmd_audit(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws); issues = []
    validate_manifest(data, root, require_files=True)
    for claim in data["claims"]:
        if args.problem_n and claim["problem_n"] != args.problem_n: continue
        issues.extend(f"{claim['claim_id']}: {issue}" for issue in audit_claim(root, claim))
    if issues:
        print("\n".join(f"FAIL {x}" for x in issues)); return 1
    print("PASS LeanGate audit"); return 0


def cmd_status(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws)
    info = summarize(data, root, args.problem_n)
    if args.json: print(json.dumps(info, ensure_ascii=False, indent=2))
    else: print("LeanGate: " + " ".join(f"{k}={v}" for k, v in info.items()))
    save_manifest(ws, data)
    if args.problem_n: update_pipeline_summary(ws, data, args.problem_n)
    return 0


def cmd_export(args) -> int:
    ws = workspace(args); data = read_manifest(ws); root = formal_dir(ws)
    problem_claims = [c for c in data["claims"] if c["problem_n"] == args.problem_n]
    claims = [c for c in problem_claims if c["applicability"] == "ELIGIBLE"]
    for claim in claims:
        if (claim["applicability"] == "ELIGIBLE" and
                not (claim["proof"] == "PROVED" and refresh_freshness(root, claim) == "FRESH")):
            raise LeanGateError(f"cannot export unproved or stale claim: {claim['claim_id']}")
        recheck = _verify_one(root, claim.copy(), 300)
        if (recheck["result"] != "FORMALLY_PROVED" or
                claim.get("assurance") not in {"KERNEL_PROOF", "EXTERNAL_RECHECKED"} or
                claim.get("verification_snapshot") != claim.get("frozen_hashes")):
            raise LeanGateError(f"cannot export claim without a fresh independent kernel recheck: {claim['claim_id']}")
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise LeanGateError(f"export output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    ids = {c["claim_id"] for c in claims}
    obligations = [o for o in data["obligations"] if o["claim_id"] in ids]
    exclusions = [o for o in data["obligations"] if o["problem_n"] == args.problem_n
                  and o["applicability"] != "ELIGIBLE"]
    exported = {"schema_version": data["schema_version"], "policy": data["policy"],
                "obligations": obligations, "claims": claims}
    validate_manifest(exported, root, require_files=True)
    atomic_json(output / "claims.json", exported)
    if exclusions:
        atomic_json(output / "exclusions.json", exclusions)
    (output / "schemas").mkdir(exist_ok=True)
    shutil.copy2(ADDON / "schemas" / "claims.schema.json",
                 output / "schemas" / "claims.schema.json")
    for name in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        if (root / name).is_file(): shutil.copy2(root / name, output / name)
    for claim in claims:
        report = root / "reports" / f"{claim['claim_id']}.json"
        if report.exists():
            (output / "reports").mkdir(exist_ok=True)
            shutil.copy2(report, output / "reports" / report.name)
        for field in ("spec_file", "proof_file", "certificate_file"):
            if not claim.get(field): continue
            source = root / safe_relative(claim[field]); destination = output / claim[field]
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    shutil.copy2(root / "LeanGate.lean", output / "LeanGate.lean")
    shutil.copytree(root / "LeanGate", output / "LeanGate", dirs_exist_ok=True)
    validate_manifest(load_json(output / "claims.json"), output, require_files=True)
    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name != "checksums.json")
    atomic_json(output / "checksums.json", {str(p.relative_to(output)): sha256(p) for p in files})
    print(f"[leangate] exported {len(claims)} claims to {output}"); return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LeanGate formal verification")
    p.add_argument("--workspace", default="CUMCM_Workspace")
    sub = p.add_subparsers(dest="command", required=True)
    d=sub.add_parser("doctor"); d.set_defaults(func=cmd_doctor)
    i=sub.add_parser("init"); i.add_argument("--policy", choices=["selected","required"], default="selected"); i.add_argument("--force", action="store_true"); i.set_defaults(func=cmd_init)
    g=sub.add_parser("generate-resource"); g.add_argument("--problem-n", type=int, required=True); g.add_argument("--certificate-file", required=True); g.add_argument("--spec-file", required=True); g.add_argument("--proof-file", required=True); g.add_argument("--theorem-name", required=True); g.set_defaults(func=cmd_generate_resource)
    r=sub.add_parser("register"); r.add_argument("--claim-id", required=True); r.add_argument("--problem-n", type=int, required=True); r.add_argument("--title", required=True); r.add_argument("--epistemic-type", choices=["theorem","bound","certificate"], default="theorem"); r.add_argument("--formal-level", choices=["L1","L2","L3"], default="L2"); r.add_argument("--spec-file", required=True); r.add_argument("--proof-file", required=True); r.add_argument("--theorem-name", required=True); r.add_argument("--certificate-file", default=""); r.add_argument("--assumption-id", action="append", default=[]); r.add_argument("--empirical-dependency", action="append", default=[]); r.add_argument("--scope-note", required=True); r.add_argument("--applicability", choices=["ELIGIBLE","NOT_APPLICABLE","DEFERRED"], default="ELIGIBLE"); r.add_argument("--exclusion-reason", default=""); r.add_argument("--risk-category", action="append", choices=sorted(RISK_CATEGORIES), default=[]); r.add_argument("--classification-reason", default=""); r.set_defaults(func=cmd_register)
    s=sub.add_parser("seal-assessment"); s.set_defaults(func=cmd_seal_assessment)
    s=sub.add_parser("semantic-review"); s.add_argument("--claim-id", required=True); s.add_argument("--verdict", choices=["pass","rework"], required=True); s.add_argument("--reviewer", choices=["human","agent"], default="human"); s.add_argument("--approval-file", default=""); s.add_argument("--note", required=True); s.set_defaults(func=cmd_semantic_review)
    q=sub.add_parser("require"); q.add_argument("--claim-id", required=True); q.add_argument("--approval-file", required=True); q.add_argument("--note", required=True); q.set_defaults(func=cmd_require)
    f=sub.add_parser("freeze"); f.add_argument("--claim-id", required=True); f.set_defaults(func=cmd_freeze)
    v=sub.add_parser("verify"); v.add_argument("--problem-n", type=int, required=True); v.add_argument("--timeout", type=int, default=300); v.set_defaults(func=cmd_verify)
    a=sub.add_parser("audit"); a.add_argument("--problem-n", type=int, default=0); a.set_defaults(func=cmd_audit)
    t=sub.add_parser("status"); t.add_argument("--problem-n", type=int); t.add_argument("--json", action="store_true"); t.set_defaults(func=cmd_status)
    e=sub.add_parser("export"); e.add_argument("--problem-n", type=int, required=True); e.add_argument("--output", required=True); e.set_defaults(func=cmd_export)
    return p


def main() -> None:
    args = parser().parse_args()
    try: code = args.func(args)
    except LeanGateError as exc:
        print(f"[leangate] ERROR: {exc}", file=sys.stderr); code = 1
    raise SystemExit(code)


if __name__ == "__main__": main()
