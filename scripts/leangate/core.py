from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
POLICIES = {"off", "selected", "required"}
LIFECYCLES = {"DRAFT", "FROZEN", "RUNNING", "CLOSED", "WITHDRAWN"}
PROOF_STATES = {"UNCHECKED", "PROVED", "DISPROVED", "UNKNOWN"}
SEMANTIC_STATES = {"PENDING", "AUTO_AUDITED", "HUMAN_AUDITED", "REJECTED"}
ASSURANCE_LEVELS = {"NUMERICAL", "VERIFIED_CHECKER_RUNTIME", "KERNEL_PROOF", "EXTERNAL_RECHECKED"}
APPLICABILITY = {"ELIGIBLE", "NOT_APPLICABLE", "DEFERRED"}
RISK_CATEGORIES = {
    "integer_feasibility", "resource_conservation", "safety_bound",
    "graph_property", "dynamic_programming", "algorithm_invariant",
    "uniqueness_monotonicity_convergence", "solver_certificate",
    "decision_critical", "cross_problem_dependency",
}
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
CLAIM_ID = re.compile(r"^LG-P([1-9][0-9]*)-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
THEOREM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_'.]*$")
FORBIDDEN_LEAN = re.compile(r"\b(sorry|admit)\b|\bunsafe\b|^\s*axiom\b", re.MULTILINE)
FREEZE_FIELDS = ("claim_id", "problem_n", "title", "epistemic_type", "formal_level",
                 "semantic_review", "applicability", "spec_file", "proof_file",
                 "theorem_name", "assumption_ids", "empirical_dependencies",
                 "certificate_file", "scope_note", "semantic_approval", "required_approval")
MANIFEST_FIELDS = {"schema_version", "policy", "obligations", "claims"}
OBLIGATION_FIELDS = {"claim_id", "problem_n", "applicability", "exclusion_reason",
                     "required", "registered_at", "required_at", "approval_note",
                     "required_approval", "mandatory", "risk_categories",
                     "classification_reason"}
CLAIM_FIELDS = set(FREEZE_FIELDS) | {
    "lifecycle", "proof", "freshness", "assurance", "error_reason", "frozen_hashes",
    "last_verified_at", "verification_snapshot", "semantic_review_note",
    "semantic_review_at", "frozen_at",
}
REQUIRED_CLAIM_FIELDS = set(FREEZE_FIELDS) | {
    "lifecycle", "proof", "freshness", "assurance", "error_reason", "frozen_hashes",
    "last_verified_at", "verification_snapshot",
}


class LeanGateError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LeanGateError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LeanGateError(f"invalid JSON in {path}: {exc}") from exc


def safe_relative(value: str, *, suffix: str | None = None) -> Path:
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise LeanGateError(f"unsafe relative path: {value!r}")
    if suffix and path.suffix != suffix:
        raise LeanGateError(f"path must end with {suffix}: {value!r}")
    return path


def safe_path(root: Path, value: str, *, suffix: str | None = None,
              require_exists: bool = False) -> Path:
    """Resolve a manifest path under root and reject every symlink component."""
    rel = safe_relative(value, suffix=suffix)
    root_resolved = root.resolve()
    candidate = root / rel
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise LeanGateError(f"symlink is not allowed in LeanGate path: {value!r}")
    resolved = candidate.resolve(strict=False)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise LeanGateError(f"LeanGate path escapes formal root: {value!r}")
    if require_exists and not candidate.is_file():
        raise LeanGateError(f"missing LeanGate file: {value!r}")
    return candidate


def lean_sources(root: Path) -> list[Path]:
    """List local Lean sources and reject symlinked files or directories."""
    sources: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(current)
        kept: list[str] = []
        for name in dirnames:
            child = directory / name
            if child.is_symlink():
                raise LeanGateError(f"symlink directory is forbidden under formal root: {child}")
            if name == ".lake":
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if not name.endswith(".lean"):
                continue
            path = directory / name
            if path.is_symlink():
                raise LeanGateError(f"symlink Lean source is forbidden: {path}")
            sources.append(path)
    return sorted(sources)


def formal_dir(workspace: Path) -> Path:
    return workspace / "formal"


def manifest_path(workspace: Path) -> Path:
    return formal_dir(workspace) / "claims.json"


def read_manifest(workspace: Path) -> dict[str, Any]:
    data = load_json(manifest_path(workspace))
    validate_manifest(data, formal_dir(workspace), require_files=False)
    return data


def validate_manifest(data: Any, root: Path, *, require_files: bool) -> None:
    def validate_evidence(value: Any, label: str) -> None:
        if value is None:
            return
        if not isinstance(value, dict) or set(value) != {"file", "sha256", "marker"}:
            raise LeanGateError(f"{label}: invalid approval evidence")
        safe_relative(value["file"])
        if not str(value["file"]).startswith("state/"):
            raise LeanGateError(f"{label}: approval evidence must be under state/")
        if not re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", "")):
            raise LeanGateError(f"{label}: invalid approval hash")
        if not re.fullmatch(r"\[(?:APPROVED|REWORK|REQUIRED) LeanGate LG-P[1-9][0-9]*-[A-Z0-9]+(?:-[A-Z0-9]+)*\]",
                            value.get("marker", "")):
            raise LeanGateError(f"{label}: invalid approval marker")

    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise LeanGateError(f"claims.json requires schema_version={SCHEMA_VERSION}")
    unknown = set(data) - MANIFEST_FIELDS
    if unknown:
        raise LeanGateError(f"unknown manifest fields: {sorted(unknown)}")
    if data.get("policy") not in POLICIES:
        raise LeanGateError(f"invalid policy: {data.get('policy')!r}")
    obligations = data.get("obligations")
    if not isinstance(obligations, list):
        raise LeanGateError("obligations must be a list")
    obligation_ids: set[str] = set()
    for obligation in obligations:
        if not isinstance(obligation, dict) or not CLAIM_ID.fullmatch(obligation.get("claim_id", "")):
            raise LeanGateError("invalid obligation entry")
        unknown = set(obligation) - OBLIGATION_FIELDS
        if unknown:
            raise LeanGateError(f"unknown obligation fields: {sorted(unknown)}")
        match = CLAIM_ID.fullmatch(obligation["claim_id"])
        if (isinstance(obligation.get("problem_n"), bool) or
                not isinstance(obligation.get("problem_n"), int) or
                int(match.group(1)) != obligation["problem_n"]):
            raise LeanGateError(f"obligation problem mismatch: {obligation['claim_id']}")
        if obligation["claim_id"] in obligation_ids:
            raise LeanGateError(f"duplicate obligation: {obligation['claim_id']}")
        obligation_ids.add(obligation["claim_id"])
        if obligation.get("applicability") not in APPLICABILITY:
            raise LeanGateError(f"invalid obligation applicability: {obligation.get('claim_id')}")
        if obligation["applicability"] != "ELIGIBLE" and not obligation.get("exclusion_reason"):
            raise LeanGateError(f"excluded obligation needs a reason: {obligation['claim_id']}")
        if not isinstance(obligation.get("required"), bool):
            raise LeanGateError(f"obligation required must be boolean: {obligation['claim_id']}")
        risks = obligation.get("risk_categories", [])
        if not isinstance(risks, list) or any(risk not in RISK_CATEGORIES for risk in risks):
            raise LeanGateError(f"invalid obligation risk categories: {obligation['claim_id']}")
        mandatory = obligation.get("mandatory", False)
        if not isinstance(mandatory, bool) or mandatory != bool(risks):
            raise LeanGateError(f"mandatory classification mismatch: {obligation['claim_id']}")
        if mandatory and obligation["applicability"] != "ELIGIBLE":
            raise LeanGateError(f"mandatory obligation must be ELIGIBLE: {obligation['claim_id']}")
        if not isinstance(obligation.get("classification_reason", ""), str):
            raise LeanGateError(f"invalid classification reason: {obligation['claim_id']}")
        if risks and not obligation.get("classification_reason", "").strip():
            raise LeanGateError(f"risk-classified obligation needs a reason: {obligation['claim_id']}")
        validate_evidence(obligation.get("required_approval"), obligation["claim_id"])
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise LeanGateError("claims must be a list")
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise LeanGateError("each claim must be an object")
        missing_fields = REQUIRED_CLAIM_FIELDS - set(claim)
        if missing_fields:
            raise LeanGateError(f"missing claim fields: {sorted(missing_fields)}")
        unknown = set(claim) - CLAIM_FIELDS
        if unknown:
            raise LeanGateError(f"unknown claim fields: {sorted(unknown)}")
        cid = claim.get("claim_id", "")
        match = CLAIM_ID.fullmatch(cid)
        if not match or int(match.group(1)) != claim.get("problem_n"):
            raise LeanGateError(f"invalid or mismatched claim_id/problem_n: {cid!r}")
        if cid in seen:
            raise LeanGateError(f"duplicate claim_id: {cid}")
        seen.add(cid)
        if not isinstance(claim.get("title"), str) or not claim["title"].strip():
            raise LeanGateError(f"{cid}: title is required")
        if not isinstance(claim.get("scope_note"), str) or not claim["scope_note"].strip():
            raise LeanGateError(f"{cid}: scope_note is required")
        if claim.get("epistemic_type") not in {"theorem", "bound", "certificate"}:
            raise LeanGateError(f"{cid}: invalid epistemic_type")
        if claim.get("formal_level") not in {"L1", "L2", "L3"}:
            raise LeanGateError(f"{cid}: invalid formal_level")
        for field, allowed in (("lifecycle", LIFECYCLES), ("proof", PROOF_STATES),
                               ("semantic_review", SEMANTIC_STATES),
                               ("assurance", ASSURANCE_LEVELS),
                               ("applicability", APPLICABILITY)):
            if claim.get(field) not in allowed:
                raise LeanGateError(f"{cid}: invalid {field}: {claim.get(field)!r}")
        if claim.get("freshness") not in {"FRESH", "STALE"}:
            raise LeanGateError(f"{cid}: invalid freshness")
        if not THEOREM_NAME.fullmatch(claim.get("theorem_name", "")):
            raise LeanGateError(f"{cid}: invalid theorem_name")
        for field in ("spec_file", "proof_file"):
            safe_path(root, claim.get(field, ""), suffix=".lean", require_exists=require_files)
        cert = claim.get("certificate_file")
        if claim.get("epistemic_type") == "certificate" and not cert:
            raise LeanGateError(f"{cid}: certificate epistemic_type requires certificate_file")
        if cert:
            safe_path(root, cert, suffix=".json", require_exists=require_files)
        if cid not in obligation_ids:
            raise LeanGateError(f"claim has no obligation registry entry: {cid}")
        obligation = next(item for item in obligations if item["claim_id"] == cid)
        if (obligation["problem_n"] != claim["problem_n"] or
                obligation["applicability"] != claim["applicability"]):
            raise LeanGateError(f"claim/obligation scope mismatch: {cid}")
        for field in ("assumption_ids", "empirical_dependencies"):
            if not isinstance(claim.get(field), list) or not all(
                    isinstance(item, str) for item in claim[field]):
                raise LeanGateError(f"{cid}: {field} must be a list of strings")
        for field in ("frozen_hashes",):
            hashes = claim.get(field)
            if not isinstance(hashes, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) and
                    re.fullmatch(r"[0-9a-f]{64}", value)
                    for key, value in hashes.items()):
                raise LeanGateError(f"{cid}: invalid {field}")
        snapshot = claim.get("verification_snapshot")
        if snapshot is not None and (not isinstance(snapshot, dict) or not all(
                isinstance(key, str) and isinstance(value, str) and
                re.fullmatch(r"[0-9a-f]{64}", value)
                for key, value in snapshot.items())):
            raise LeanGateError(f"{cid}: invalid verification_snapshot")
        validate_evidence(claim.get("semantic_approval"), cid)
        validate_evidence(claim.get("required_approval"), cid)
        if obligation.get("required") != (claim.get("required_approval") is not None):
            raise LeanGateError(f"required approval state mismatch: {cid}")
        if obligation.get("required_approval") != claim.get("required_approval"):
            raise LeanGateError(f"required approval evidence mismatch: {cid}")
    if seen != obligation_ids:
        raise LeanGateError(f"claim/obligation registry mismatch: {sorted(obligation_ids - seen)}")


def initialize(workspace: Path, addon: Path, policy: str, *, force: bool = False) -> Path:
    if policy not in POLICIES - {"off"}:
        raise LeanGateError("init policy must be selected or required")
    target = formal_dir(workspace)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        dst = target / name
        if force or not dst.exists():
            shutil.copy2(addon / name, dst)
    library = target / "LeanGate"
    if force and library.exists():
        shutil.rmtree(library)
    if not library.exists():
        shutil.copytree(addon / "LeanGate", library)
    schemas = target / "schemas"
    if force and schemas.exists():
        shutil.rmtree(schemas)
    if not schemas.exists():
        shutil.copytree(addon / "schemas", schemas)
    root_file = target / "LeanGate.lean"
    if force or not root_file.exists():
        shutil.copy2(addon / "LeanGate.lean", root_file)
    for dirname in ("Specs", "Proofs", "Certificates", "reports", "snapshots"):
        (target / dirname).mkdir(exist_ok=True)
    manifest = manifest_path(workspace)
    if not manifest.exists():
        atomic_json(manifest, {"schema_version": SCHEMA_VERSION, "policy": policy,
                               "obligations": [], "claims": []})
    else:
        data = load_json(manifest)
        if data.get("policy") == "required" and policy != "required":
            raise LeanGateError("refusing to downgrade existing required policy during init")
        data["policy"] = policy
        data.setdefault("obligations", [])
        atomic_json(manifest, data)
    return target


def claim_by_id(data: dict[str, Any], claim_id: str) -> dict[str, Any]:
    for claim in data["claims"]:
        if claim["claim_id"] == claim_id:
            return claim
    raise LeanGateError(f"unknown claim: {claim_id}")


def current_hashes(root: Path, claim: dict[str, Any]) -> dict[str, str]:
    paths = {"spec_sha256": safe_path(root, claim["spec_file"], require_exists=True),
             "proof_sha256": safe_path(root, claim["proof_file"], require_exists=True)}
    if claim.get("certificate_file"):
        paths["certificate_sha256"] = safe_path(root, claim["certificate_file"], require_exists=True)
    result = {}
    for key, path in paths.items():
        if not path.is_file():
            raise LeanGateError(f"missing claim input: {path}")
        result[key] = sha256(path)
    for config in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        path = safe_path(root, config, require_exists=True)
        result[f"project:{config}"] = sha256(path)
    # Conservatively bind every Lean source under formal/. This over-invalidates
    # unrelated claims but cannot miss a transitive local import.
    for path in lean_sources(root):
        result[f"source:{path.relative_to(root)}"] = sha256(path)
    result["claim_contract_sha256"] = sha256_json(
        {field: claim.get(field) for field in FREEZE_FIELDS})
    return result


def refresh_freshness(root: Path, claim: dict[str, Any]) -> str:
    if claim.get("lifecycle") == "DRAFT" or not claim.get("frozen_hashes"):
        return "STALE"
    try:
        fresh = current_hashes(root, claim) == claim["frozen_hashes"]
    except LeanGateError:
        fresh = False
    return "FRESH" if fresh else "STALE"


def audit_claim(root: Path, claim: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in ("spec_file", "proof_file"):
        path = safe_path(root, claim[field], suffix=".lean")
        if not path.is_file():
            issues.append(f"missing {field}: {path}")
            continue
        match = FORBIDDEN_LEAN.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            issues.append(f"forbidden Lean token {match.group(0)!r} in {path}")
    if claim.get("certificate_file"):
        cert_path = safe_path(root, claim["certificate_file"], suffix=".json")
        if not cert_path.is_file():
            issues.append(f"missing certificate_file: {cert_path}")
        else:
            marker = f"LEANGATE-CERTIFICATE-SHA256: {sha256(cert_path)}"
            for field in ("spec_file", "proof_file"):
                text = safe_path(root, claim[field], suffix=".lean").read_text(
                    encoding="utf-8", errors="replace")
                if marker not in text:
                    issues.append(f"{field} is not bound to the current certificate hash")
    proof_text = safe_path(root, claim["proof_file"]).read_text(
        encoding="utf-8", errors="replace")
    declaration = claim["theorem_name"].rsplit(".", 1)[-1]
    if not re.search(rf"^\s*(?:theorem|lemma)\s+{re.escape(declaration)}\b", proof_text, re.MULTILINE):
        issues.append(f"theorem_name {claim['theorem_name']!r} not found in proof file")
    try:
        sources = lean_sources(root)
    except LeanGateError as exc:
        issues.append(str(exc))
        sources = []
    for path in sources:
        match = FORBIDDEN_LEAN.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            issue = f"forbidden transitive Lean token {match.group(0)!r} in {path}"
            if issue not in issues:
                issues.append(issue)
    return issues


def run_lean(root: Path, spec_file: str, proof_file: str, timeout: int) -> subprocess.CompletedProcess[str]:
    lake = shutil.which("lake")
    if not lake:
        raise LeanGateError("lake is not installed")
    rel = safe_relative(proof_file, suffix=".lean")
    spec_rel = safe_relative(spec_file, suffix=".lean")
    spec_module = ".".join(spec_rel.with_suffix("").parts)
    proof_module = ".".join(rel.with_suffix("").parts)
    env = os.environ.copy()
    env["LEAN_ABORT_ON_PANIC"] = "1"
    # Build the shared core and generated Specs first so proof files import
    # compiled modules from Lake's controlled search path.
    return subprocess.run([lake, "build", "LeanGate", spec_module, proof_module],
                          cwd=root, env=env, text=True, capture_output=True,
                          timeout=timeout, check=False)


def run_axiom_audit(root: Path, proof_file: str, theorem_name: str,
                    timeout: int) -> subprocess.CompletedProcess[str]:
    lake = shutil.which("lake")
    if not lake:
        raise LeanGateError("lake is not installed")
    proof_module = ".".join(safe_relative(proof_file, suffix=".lean").with_suffix("").parts)
    source = f"import {proof_module}\n#print axioms {theorem_name}\n"
    fd, temp_name = tempfile.mkstemp(prefix="leangate-axioms-", suffix=".lean")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(source)
        return subprocess.run([lake, "env", "lean", temp_name], cwd=root, text=True,
                              capture_output=True, timeout=timeout, check=False)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def axiom_audit_ok(output: str) -> tuple[bool, list[str]]:
    match = re.search(r"depends on axioms:\s*\[([^]]*)\]", output)
    if not match:
        return (True, []) if "does not depend on any axioms" in output else (False, ["UNPARSEABLE_AXIOM_OUTPUT"])
    used = [item.strip() for item in match.group(1).split(",") if item.strip()]
    rejected = [item for item in used if item not in ALLOWED_AXIOMS]
    return not rejected, rejected


def summarize(data: dict[str, Any], root: Path, problem_n: int | None = None) -> dict[str, Any]:
    claims = [c for c in data["claims"] if problem_n is None or c["problem_n"] == problem_n]
    for claim in claims:
        claim["freshness"] = refresh_freshness(root, claim)
    return {
        "policy": data["policy"], "registered": len(claims),
        "proved": sum(c["proof"] == "PROVED" and c["freshness"] == "FRESH" for c in claims),
        "failed": sum(c["proof"] in {"DISPROVED", "UNKNOWN"} for c in claims),
        "stale": sum(c["freshness"] == "STALE" for c in claims),
    }
