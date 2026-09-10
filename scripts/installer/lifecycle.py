#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((REPO / "release-manifest.json").read_text(encoding="utf-8"))
VERSION = MANIFEST["product_version"]
TOOLCHAIN = MANIFEST["lean_toolchain"]
PYTHON_DEPENDENCIES = {
    "pdfplumber": "pdfplumber",
    "scipy": "scipy",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
}
RUNTIMES = {
    "claude": (Path(".claude/skills"), ["auto-mcm", "cumcm-master", "mcm-master"]),
    "codex": (Path(".agents/skills"), ["auto-mcm"]),
    "opencode": (Path(".config/opencode/skills"), ["auto-mcm"]),
    "dsh": (Path(".dsh/skills"), ["auto-mcm"]),
}
SOURCE_DIR = {"claude": ".claude/skills", "codex": ".agents/skills",
              "opencode": ".opencode/skills", "dsh": ".dsh/skills"}
BUNDLE_ITEMS = [".claude", ".agents", ".opencode", ".dsh", "addons", "scripts", "templates",
                "AutoMCM_SOP.md", "LEAN_GATE_DESIGN.md", "CHANGELOG.md",
                "release-manifest.json", "README.md", "LICENSE", "install.sh", "update.sh", "uninstall.sh"]


class LifecycleError(RuntimeError): pass


def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2); handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def parse_runtimes(values: list[str] | None) -> list[str]:
    values = values or ["all"]
    result = list(RUNTIMES) if "all" in values else values
    invalid = sorted(set(result) - set(RUNTIMES))
    if invalid: raise LifecycleError(f"unknown runtime(s): {invalid}")
    return list(dict.fromkeys(result))


def locations(home: Path) -> tuple[Path, Path, Path]:
    data = home / ".local/share/auto-mcm-pro"
    return data, data / "current", data / "install-receipt.json"


def copy_bundle(destination: Path, dry_run: bool) -> Path | None:
    if dry_run: return None
    staging = destination.parent / f".staging-{os.getpid()}"
    backup = destination.parent / ".previous"
    if backup.exists():
        raise LifecycleError(f"recovery backup already exists; inspect it before updating: {backup}")
    if staging.exists(): shutil.rmtree(staging)
    backup_created = False
    try:
        staging.mkdir(parents=True)
        for name in BUNDLE_ITEMS:
            source = REPO / name; target = staging / name
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns(
                    ".lake", "node_modules", ".pytest_cache", "__pycache__", "*.pyc"))
            elif source.is_file(): shutil.copy2(source, target)
        if destination.exists():
            os.replace(destination, backup)
            backup_created = True
        os.replace(staging, destination)
    except Exception:
        if backup_created and not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return backup if backup.exists() else None


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    try: answer = input(prompt).strip().lower()
    except EOFError: return default
    if not answer: return default
    return answer in {"y", "yes"}


def managed_target(home: Path, runtime: str, skill: str) -> Path:
    return home / RUNTIMES[runtime][0] / skill


def replace_link(destination: Path, source: Path, dry_run: bool) -> None:
    if destination.exists() and not destination.is_symlink():
        raise LifecycleError(f"refusing to overwrite unmanaged path: {destination}")
    if dry_run: return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.new-{os.getpid()}"
    if temporary.is_symlink(): temporary.unlink()
    temporary.symlink_to(source)
    os.replace(temporary, destination)


def prepare_lean(home: Path, receipt: dict, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN prepare Lean toolchain {TOOLCHAIN}")
        return
    elan = shutil.which("elan"); created_elan = False; env = {**os.environ, "HOME": str(home)}
    if not elan:
        installer = Path(tempfile.mkdtemp(prefix="automcm-elan-")) / "elan-init.sh"
        urllib.request.urlretrieve("https://raw.githubusercontent.com/leanprover/elan/v4.1.2/elan-init.sh", installer)
        subprocess.run(["sh", str(installer), "-y", "--no-modify-path", "--default-toolchain", "none"], check=True, env=env)
        elan = str(home / ".elan/bin/elan"); created_elan = True
    before = subprocess.run([elan, "toolchain", "list"], text=True, capture_output=True, check=True, env=env).stdout
    created_toolchain = TOOLCHAIN not in before
    if not dry_run: subprocess.run([elan, "toolchain", "install", TOOLCHAIN], check=True, env=env)
    receipt["lean"] = {"toolchain": TOOLCHAIN, "created_elan": created_elan,
                       "created_toolchain": created_toolchain}


def missing_python_dependencies() -> list[str]:
    return [package for module, package in PYTHON_DEPENDENCIES.items()
            if importlib.util.find_spec(module) is None]


def prepare_python_dependencies(receipt: dict, dry_run: bool) -> None:
    missing = missing_python_dependencies()
    if dry_run:
        detail = " ".join(missing) if missing else "none (already available)"
        print(f"DRY-RUN prepare Python dependencies: {detail}")
    elif missing:
        subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=True)
    receipt["python_dependencies"] = {
        "packages": list(PYTHON_DEPENDENCIES.values()),
        "installed_by_installer": missing,
        "python": sys.executable,
    }


def verify_install(home: Path, receipt: dict, *, lean: bool) -> bool:
    ok = True
    for entry in receipt.get("targets", []):
        path = Path(entry["path"]); good = path.is_symlink() and (path / "SKILL.md").is_file()
        print(f"{'PASS' if good else 'FAIL'} {entry['runtime']}:{entry['skill']} {path}"); ok &= good
    root = Path(receipt["source_root"])
    for relative in ("scripts/pipeline_manager.py", "scripts/leangate.py",
                     "addons/leangate/lean-toolchain", "release-manifest.json"):
        good = (root / relative).is_file()
        print(f"{'PASS' if good else 'FAIL'} shared:{relative}"); ok &= good
    if lean:
        env = {**os.environ, "HOME": str(home)}
        env["PATH"] = str(home / ".elan/bin") + os.pathsep + env.get("PATH", "")
        result = subprocess.run([sys.executable, str(root / "scripts/leangate.py"), "doctor"],
                                cwd=root, check=False, env=env)
        ok &= result.returncode == 0
    if receipt.get("python_dependencies"):
        missing = missing_python_dependencies()
        good = not missing
        print(f"{'PASS' if good else 'FAIL'} Python dependencies"
              f"{'' if good else ': missing ' + ', '.join(missing)}")
        ok &= good
    return ok


def install(args) -> int:
    home = Path(args.home).expanduser().resolve(); _, bundle, receipt_path = locations(home)
    if getattr(args, "check", False): return check(args)
    first_install = not receipt_path.is_file()
    previous = None if first_install else load_receipt(home)[1]
    runtime_values = args.runtime or (previous.get("runtimes") if previous else None)
    runtimes = parse_runtimes(runtime_values)
    explicit_copy = bool(getattr(args, "copy", False))
    explicit_symlink = bool(getattr(args, "symlink", False))
    if explicit_copy and explicit_symlink:
        raise LifecycleError("cannot combine --copy and --symlink")
    if explicit_copy: mode = "copy"
    elif explicit_symlink: mode = "symlink"
    elif previous: mode = previous["mode"]
    else: mode = "symlink"
    if previous and mode != previous["mode"] and set(runtimes) != set(previous["runtimes"]):
        raise LifecycleError("switching install mode requires all previously installed runtimes")
    interactive_first_install = first_install and sys.stdin.isatty()
    if not args.with_python_deps and not args.without_python_deps and interactive_first_install:
        args.with_python_deps = ask_yes_no(
            "Install/check core Python modeling dependencies "
            "(pdfplumber, scipy, numpy, matplotlib, pandas, openpyxl)? [Y/n] ", default=True)
    if not args.with_lean and not args.without_lean and interactive_first_install:
        args.with_lean = ask_yes_no(
            f"Prepare optional LeanGate toolchain {TOOLCHAIN}? [y/N] ", default=False)
    source_root = bundle if mode == "copy" else REPO
    planned = [(runtime, skill, managed_target(home, runtime, skill))
               for runtime in runtimes for skill in RUNTIMES[runtime][1]]
    for _, _, destination in planned:
        if destination.exists() and not destination.is_symlink():
            raise LifecycleError(f"refusing to overwrite unmanaged path: {destination}")
    backup = None; bundle_replaced = False
    receipt = {"receipt_version": 1, "product_version": VERSION, "mode": mode,
               "source_root": str(source_root), "runtimes": runtimes, "targets": [],
               "installed_at": now(), "lean": None, "python_dependencies": None}
    previous_links = {str(destination): os.readlink(destination) if destination.is_symlink() else None
                      for _, _, destination in planned}
    try:
        if mode == "copy":
            backup = copy_bundle(bundle, args.dry_run)
            bundle_replaced = not args.dry_run
        for runtime in runtimes:
            for skill in RUNTIMES[runtime][1]:
                source = source_root / SOURCE_DIR[runtime] / skill
                validation_source = REPO / SOURCE_DIR[runtime] / skill
                if not validation_source.is_dir():
                    raise LifecycleError(f"missing binding source: {validation_source}")
                destination = managed_target(home, runtime, skill)
                print(f"{'DRY-RUN ' if args.dry_run else ''}LINK {runtime}:{skill} -> {source}")
                replace_link(destination, source, args.dry_run)
                receipt["targets"].append({"runtime": runtime, "skill": skill,
                                           "path": str(destination), "source": str(source)})
        if args.with_python_deps: prepare_python_dependencies(receipt, args.dry_run)
        if args.with_lean: prepare_lean(home, receipt, args.dry_run)
        if not args.dry_run:
            if previous:
                selected = set(runtimes)
                receipt["targets"] = [item for item in previous.get("targets", [])
                                      if item["runtime"] not in selected] + receipt["targets"]
                receipt["runtimes"] = sorted({item["runtime"] for item in receipt["targets"]})
                previous_lean = previous.get("lean")
                previous_python_dependencies = previous.get("python_dependencies")
                if not args.with_python_deps:
                    receipt["python_dependencies"] = previous_python_dependencies
                elif previous_python_dependencies and receipt.get("python_dependencies"):
                    receipt["python_dependencies"]["installed_by_installer"] = sorted(set(
                        previous_python_dependencies.get("installed_by_installer", [])) |
                        set(receipt["python_dependencies"].get("installed_by_installer", [])))
                if not args.with_lean:
                    receipt["lean"] = previous_lean
                elif previous_lean and receipt.get("lean") and \
                        previous_lean.get("toolchain") == receipt["lean"].get("toolchain"):
                    # Ownership evidence is monotonic: an update must not forget that
                    # an earlier installer run created Elan or this exact toolchain.
                    receipt["lean"]["created_elan"] = bool(
                        previous_lean.get("created_elan") or receipt["lean"].get("created_elan"))
                    receipt["lean"]["created_toolchain"] = bool(
                        previous_lean.get("created_toolchain") or
                        receipt["lean"].get("created_toolchain"))
            if not verify_install(home, receipt, lean=bool(receipt.get("lean"))):
                raise LifecycleError("post-install verification failed")
            atomic_json(receipt_path, receipt)
            if backup and backup.exists(): shutil.rmtree(backup)
            if mode == "symlink" and previous and previous["mode"] == "copy" and bundle.is_dir():
                shutil.rmtree(bundle)
    except Exception:
        if not args.dry_run:
            for _, _, destination in planned:
                old = previous_links[str(destination)]
                if destination.is_symlink(): destination.unlink()
                if old is not None: destination.symlink_to(old)
            if mode == "copy" and bundle_replaced:
                if bundle.exists(): shutil.rmtree(bundle)
                if backup and backup.exists(): os.replace(backup, bundle)
        raise
    return 0


def load_receipt(home: Path) -> tuple[Path, dict]:
    path = locations(home)[2]
    if not path.is_file(): raise LifecycleError(f"installation receipt not found: {path}")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise LifecycleError(f"invalid installation receipt: {exc}") from exc
    required = {"receipt_version", "product_version", "mode", "source_root", "runtimes", "targets"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise LifecycleError("invalid installation receipt structure")
    if data["mode"] not in {"symlink", "copy"} or not isinstance(data["targets"], list):
        raise LifecycleError("invalid installation receipt values")
    for entry in data["targets"]:
        if not isinstance(entry, dict) or not {"runtime", "skill", "path", "source"}.issubset(entry):
            raise LifecycleError("invalid installation target entry")
        runtime = entry["runtime"]
        if runtime not in RUNTIMES or entry["skill"] not in RUNTIMES[runtime][1]:
            raise LifecycleError("unknown runtime or skill in installation receipt")
        if Path(entry["path"]) != managed_target(home, runtime, entry["skill"]):
            raise LifecycleError("installation receipt contains an unsafe target path")
    return path, data


def check(args) -> int:
    home = Path(args.home).expanduser().resolve()
    try: _, receipt = load_receipt(home)
    except LifecycleError as exc: print(f"FAIL {exc}"); return 1
    print(f"AutoMCM-Pro installed={receipt.get('product_version')} available={VERSION}")
    return 0 if verify_install(home, receipt, lean=bool(receipt.get("lean"))) else 1


def update(args) -> int:
    home = Path(args.home).expanduser().resolve(); _, receipt = load_receipt(home)
    if args.to and args.to != VERSION: raise LifecycleError(f"this source checkout provides {VERSION}, not {args.to}")
    if args.check:
        print(f"installed={receipt.get('product_version')} available={VERSION}")
        return 0 if receipt.get("product_version") == VERSION else 2
    installed = tuple(int(x) for x in str(receipt.get("product_version", "0.0.0")).split(".")[:3])
    minimum = tuple(int(x) for x in MANIFEST["migration_range"]["minimum"].split("."))
    if installed < minimum:
        raise LifecycleError(f"installed version {receipt.get('product_version')} is below supported migration minimum")
    if receipt.get("receipt_version") != 1:
        raise LifecycleError("unsupported receipt schema; refusing update")
    forwarded = argparse.Namespace(home=str(home), runtime=receipt.get("runtimes", []),
        copy=receipt.get("mode") == "copy", with_lean=bool(receipt.get("lean")),
        without_lean=not bool(receipt.get("lean")),
        with_python_deps=bool(receipt.get("python_dependencies")),
        without_python_deps=not bool(receipt.get("python_dependencies")),
        check=False, dry_run=args.dry_run)
    return install(forwarded)


def uninstall(args) -> int:
    home = Path(args.home).expanduser().resolve(); receipt_path, receipt = load_receipt(home)
    if args.purge_toolchain:
        lean = receipt.get("lean") or {}
        if not (args.yes and lean.get("created_toolchain") and lean.get("toolchain") == TOOLCHAIN):
            raise LifecycleError("toolchain purge requires --yes and installer ownership evidence")
    selected = set(parse_runtimes(args.runtime)) if args.runtime else set(receipt.get("runtimes", [])); remaining = []
    for entry in receipt.get("targets", []):
        path = Path(entry["path"])
        if entry["runtime"] not in selected: remaining.append(entry); continue
        expected_root = (home / RUNTIMES[entry["runtime"]][0]).resolve()
        if path.parent.resolve() != expected_root: raise LifecycleError(f"unsafe receipt target: {path}")
        if path.is_symlink() and str(path.resolve()) == str(Path(entry["source"]).resolve()):
            print(f"{'DRY-RUN ' if args.dry_run else ''}REMOVE {path}")
            if not args.dry_run: path.unlink()
        elif path.exists(): print(f"PRESERVE modified/unmanaged target {path}"); remaining.append(entry)
    if args.purge_toolchain:
        lean = receipt.get("lean") or {}
        elan = shutil.which("elan") or str(home / ".elan/bin/elan")
        if not args.dry_run: subprocess.run([elan, "toolchain", "uninstall", TOOLCHAIN], check=True,
            env={**os.environ, "HOME": str(home)})
        receipt["lean"] = None
    if args.purge_leangate_cache:
        cache = locations(home)[0] / "leangate-cache"
        print(f"{'DRY-RUN ' if args.dry_run else ''}PURGE {cache}")
        if not args.dry_run and cache.is_dir(): shutil.rmtree(cache)
    receipt["targets"] = remaining; receipt["runtimes"] = sorted({item["runtime"] for item in remaining})
    if not args.dry_run:
        if remaining: atomic_json(receipt_path, receipt)
        else:
            receipt_path.unlink(missing_ok=True); _, bundle, _ = locations(home)
            if bundle.is_dir(): shutil.rmtree(bundle)
            # Remove only our now-empty data directory; preserve unexpected files.
            try: receipt_path.parent.rmdir()
            except OSError: pass
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AutoMCM-Pro lifecycle manager"); sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False); common.add_argument("--home", default=str(Path.home()), help=argparse.SUPPRESS); common.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("install", parents=[common]); i.add_argument("--runtime", action="append", choices=[*RUNTIMES, "all"]); i.add_argument("--copy", action="store_true"); i.add_argument("--symlink", action="store_true"); i.add_argument("--with-python-deps", action="store_true"); i.add_argument("--without-python-deps", action="store_true"); i.add_argument("--with-lean", action="store_true"); i.add_argument("--without-lean", action="store_true"); i.add_argument("--check", action="store_true")
    sub.add_parser("check", parents=[common])
    u = sub.add_parser("update", parents=[common]); u.add_argument("--check", action="store_true"); u.add_argument("--to"); u.add_argument("--repair", action="store_true")
    x = sub.add_parser("uninstall", parents=[common]); x.add_argument("--runtime", action="append", choices=[*RUNTIMES, "all"]); x.add_argument("--purge-toolchain", action="store_true"); x.add_argument("--yes", action="store_true"); x.add_argument("--keep-leangate-cache", action="store_true"); x.add_argument("--purge-leangate-cache", action="store_true")
    return p


def main() -> None:
    args = parser().parse_args()
    if getattr(args, "with_lean", False) and getattr(args, "without_lean", False): raise SystemExit("cannot combine --with-lean and --without-lean")
    if getattr(args, "with_python_deps", False) and getattr(args, "without_python_deps", False): raise SystemExit("cannot combine --with-python-deps and --without-python-deps")
    try: code = {"install": install, "check": check, "update": update, "uninstall": uninstall}[args.command](args)
    except (LifecycleError, OSError, subprocess.SubprocessError) as exc:
        print(f"[installer] ERROR: {exc}", file=sys.stderr); code = 1
    raise SystemExit(code)


if __name__ == "__main__": main()
