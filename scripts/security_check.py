#!/usr/bin/env python3
"""
security_check.py — 竞赛工作区安全检查

在 Agent 运行期间可随时调用，也由 pipeline_manager.py 在关键节点自动触发。

退出码：
  0 = 通过
  1 = 发现安全问题，已打印详情
  2 = 跳过（不适用）

用法：
  python scripts/security_check.py path  --paths ./problem.pdf ./data/
  python scripts/security_check.py env   --vars OPENAI_API_KEY ANTHROPIC_API_KEY
  python scripts/security_check.py scan  --files src/models/problem1.py
  python scripts/security_check.py all
"""

import argparse
import os
import re
import sys
from pathlib import Path

WORKSPACE = Path("CUMCM_Workspace")

# ── 密钥模式（与 contest_git.py 保持同步）────────────────────────────────────
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'sk-[A-Za-z0-9]{20,}'),             "OpenAI API Key (sk-…)"),
    (re.compile(r'sk-ant-[A-Za-z0-9\-]{20,}'),       "Anthropic API Key (sk-ant-…)"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'),              "GitHub Personal Token"),
    (re.compile(r'AKIA[A-Z0-9]{16}'),                 "AWS Access Key"),
    (re.compile(r'(?i)(password|passwd)\s*[:=]\s*\S{8,}'), "Password literal"),
    (re.compile(r'(?i)(api[-_]?key|secret[-_]?key|access[-_]?token)\s*[:=]\s*["\']?\S{8,}'),
                                                       "Generic API Key / Secret"),
]

# 最多打印的片段长度（避免在终端泄露完整密钥）
_SNIPPET_LEN = 40


def _redact(text: str) -> str:
    for pat, _ in _SECRET_PATTERNS:
        text = pat.sub("***REDACTED***", text)
    return text


# ── 检查 1：文件路径安全（路径遍历防护）─────────────────────────────────────

def check_paths(paths: list[str]) -> tuple[bool, list[str]]:
    """验证用户提供的文件路径在工作目录内，且文件存在。"""
    cwd = Path.cwd().resolve()
    issues = []
    for raw in paths:
        p = Path(raw).resolve()
        if not str(p).startswith(str(cwd)):
            issues.append(f"路径越界（Path Traversal）: {raw} → {p}")
        elif not p.exists():
            issues.append(f"文件不存在: {raw}")
    return len(issues) == 0, issues


# ── 检查 2：环境变量中的密钥不得写入文件 ─────────────────────────────────────

def check_env_not_leaked(var_names: list[str]) -> tuple[bool, list[str]]:
    """
    确认指定环境变量的值未出现在工作区任何被追踪的文件中。
    只扫描 src/ 和 latex/ 下的文本文件，避免误报。
    """
    values = {k: os.environ.get(k, "") for k in var_names}
    values = {k: v for k, v in values.items() if v}  # 仅检查已设置的变量

    if not values:
        return True, []

    issues = []
    scan_dirs = [WORKSPACE / "src", WORKSPACE / "latex", WORKSPACE / "memory"]
    for d in scan_dirs:
        if not d.exists():
            continue
        for fpath in d.rglob("*"):
            if not fpath.is_file():
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for var, val in values.items():
                if val in text:
                    rel = fpath.relative_to(WORKSPACE)
                    issues.append(f"{var} 值出现在文件中: {rel}")

    return len(issues) == 0, issues


# ── 检查 3：任意文件密钥扫描 ─────────────────────────────────────────────────

def scan_files_for_secrets(files: list[str]) -> tuple[bool, list[str]]:
    """扫描指定文件，检测是否含有硬编码密钥。"""
    issues = []
    for fpath_str in files:
        fpath = Path(fpath_str)
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, desc in _SECRET_PATTERNS:
            for m in pat.finditer(text):
                snippet = m.group(0)[:_SNIPPET_LEN]
                lineno = text[:m.start()].count("\n") + 1
                issues.append(f"{fpath}:{lineno}: 疑似 {desc} — {snippet[:20]}…")

    return len(issues) == 0, issues


# ── 检查 4：工作区全局扫描 ────────────────────────────────────────────────────

def scan_workspace_all() -> tuple[bool, list[str]]:
    """扫描整个工作区的 Python 和 Markdown 文件。"""
    all_files = []
    for ext in ("*.py", "*.md", "*.tex", ".env", "*.json"):
        all_files.extend(WORKSPACE.rglob(ext))
    # 排除 .git 目录
    all_files = [f for f in all_files if ".git" not in str(f)]
    return scan_files_for_secrets([str(f) for f in all_files])


# ── 主程序 ────────────────────────────────────────────────────────────────────

def _print_result(check_name: str, passed: bool, issues: list[str]):
    if passed:
        print(f"✓ [{check_name}] 通过")
    else:
        print(f"✗ [{check_name}] 发现问题：")
        for issue in issues:
            print(f"  • {issue}")


def main():
    p = argparse.ArgumentParser(
        description="AutoMCM-Pro 竞赛工作区安全检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    # path
    pp = sub.add_parser("path", help="验证文件路径安全（路径遍历防护）")
    pp.add_argument("--paths", nargs="+", required=True)

    # env
    pe = sub.add_parser("env", help="检查环境变量是否泄露到文件")
    pe.add_argument("--vars", nargs="+",
                    default=["OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                              "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID"])

    # scan
    ps = sub.add_parser("scan", help="扫描指定文件中的硬编码密钥")
    ps.add_argument("--files", nargs="+", required=True)

    # all
    sub.add_parser("all", help="运行全部安全检查")

    args = p.parse_args()
    overall = True

    if args.cmd == "path":
        passed, issues = check_paths(args.paths)
        _print_result("path-safety", passed, issues)
        sys.exit(0 if passed else 1)

    elif args.cmd == "env":
        passed, issues = check_env_not_leaked(args.vars)
        _print_result("env-leak", passed, issues)
        sys.exit(0 if passed else 1)

    elif args.cmd == "scan":
        passed, issues = scan_files_for_secrets(args.files)
        _print_result("secret-scan", passed, issues)
        sys.exit(0 if passed else 1)

    elif args.cmd == "all":
        p1, i1 = check_env_not_leaked(
            ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID"]
        )
        _print_result("env-leak", p1, i1)

        p2, i2 = scan_workspace_all()
        _print_result("workspace-secret-scan", p2, i2)

        overall = p1 and p2
        print(f"\n{'✓ 安全检查全部通过' if overall else '✗ 发现安全问题，请处理后继续'}")
        sys.exit(0 if overall else 1)

    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
