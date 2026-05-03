#!/usr/bin/env python3
"""
contest_git.py — 竞赛工作区 Git 版本控制

在 CUMCM_Workspace/ 下维护独立的 Git 仓库，与 AutoMCM-Pro 工具仓库完全分离。
每个流水线阶段 approved 后自动快照，支持多轮迭代历史追踪与版本对比。

直接调用（可单独使用）：
  python scripts/contest_git.py init
  python scripts/contest_git.py log
  python scripts/contest_git.py diff draft-v1 draft-v2
  python scripts/contest_git.py status
  python scripts/contest_git.py tag final-v2 "第二轮修改后最终版"

由 pipeline_manager.py 在以下事件自动调用：
  advance <stage>   → auto_commit()
  rework  <stage>   → rework_commit() 开始记录
  init    --git     → init()
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ── 常量 ──────────────────────────────────────────────────────────────────
WORKSPACE   = Path("CUMCM_Workspace")
GIT_ROOT    = WORKSPACE          # git 仓库根目录
GIT_DIR     = WORKSPACE / ".git"

# 里程碑阶段：这些阶段 approved 后额外打 tag
MILESTONE_STAGES = {
    "latex_draft":    "draft",
    "final_compile":  "final",
}

# LaTeX 中间文件等不需要追踪的内容
GITIGNORE = """\
# Python
__pycache__/
*.py[cod]
*.pyo

# LaTeX 中间产物（保留 .tex 和 .pdf）
*.aux
*.log
*.toc
*.out
*.fls
*.fdb_latexmk
*.synctex.gz
*.blg
*.bbl
*.bcf
*.run.xml
*.lot
*.lof
*.idx
*.ilg
*.ind

# Editor / OS
.DS_Store
Thumbs.db
*.swp
*.swo
*~

# 字体缓存（matplotlib 等）
.mplconfig/

# 密钥与凭证（绝不入库）
.env
.env.*
*.key
*.pem
*.p12
credentials.*
secrets.*
*_secret*
*_token*
config.local.*
"""

# 提交前密钥扫描：匹配常见 secret 模式
import re as _re
_SECRET_PATTERNS = [
    _re.compile(r'sk-[A-Za-z0-9]{20,}'),           # OpenAI API key
    _re.compile(r'ghp_[A-Za-z0-9]{36}'),            # GitHub personal token
    _re.compile(r'AKIA[A-Z0-9]{16}'),               # AWS access key
    _re.compile(r'(?i)(password|passwd|secret|token|api[-_]?key)\s*[:=]\s*\S{8,}'),
]

def _scan_staged_for_secrets() -> list[str]:
    """扫描暂存区中的文件，返回疑似包含密钥的警告列表。"""
    warnings = []
    try:
        diff = _git("diff", "--cached", "--unified=0", silent=True)
        for line in diff.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            for pat in _SECRET_PATTERNS:
                if pat.search(line):
                    snippet = line[1:60] + ("…" if len(line) > 61 else "")
                    warnings.append(f"  疑似密钥: {snippet}")
                    break
    except RuntimeError:
        pass
    return warnings


# ── 底层 git 调用 ─────────────────────────────────────────────────────────
def _git(*args, check: bool = True, silent: bool = False) -> str:
    """在 GIT_ROOT 下执行 git 命令，返回 stdout。"""
    cmd = ["git", "-C", str(GIT_ROOT), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        if not silent:
            print(f"[contest_git] git error: {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def is_enabled() -> bool:
    """检查工作区 git 仓库是否已初始化。"""
    return GIT_DIR.exists()


def _has_commits() -> bool:
    try:
        _git("rev-parse", "HEAD", silent=True)
        return True
    except RuntimeError:
        return False


# ── 公开 API ──────────────────────────────────────────────────────────────
def init(contest_name: str = "", author: str = "AutoMCM-Pro Agent") -> None:
    """
    在 CUMCM_Workspace/ 下初始化 Git 仓库。
    工作区必须已由 setup_workspace.py 创建。
    """
    if not WORKSPACE.exists():
        print("[contest_git] ERROR: CUMCM_Workspace/ 不存在，请先运行 setup_workspace.py",
              file=sys.stderr)
        sys.exit(1)

    if GIT_DIR.exists():
        print("[contest_git] 仓库已存在，跳过 init")
        return

    _git("init", "-b", "main")
    _git("config", "user.name",  author)
    _git("config", "user.email", "agent@automcm.local")

    # 写入 .gitignore
    gitignore_path = WORKSPACE / ".gitignore"
    gitignore_path.write_text(GITIGNORE, encoding="utf-8")

    # 初始提交
    _git("add", "-A")
    msg = f"chore: init workspace"
    if contest_name:
        msg = f"chore: init workspace — {contest_name}"
    _git("commit", "-m", msg, "--allow-empty")

    print(f"[contest_git] ✓ 仓库初始化完成: {GIT_ROOT.resolve()}")
    if contest_name:
        print(f"[contest_git]   竞赛: {contest_name}")


def auto_commit(stage: str, mode: str = "AP", round_n: int = 1) -> str | None:
    """
    阶段 approved 后自动提交工作区快照。
    返回 commit hash，若无变更则返回 None。
    """
    if not is_enabled():
        return None

    _git("add", "-A")

    # 检查是否有变更
    try:
        _git("diff", "--cached", "--quiet", silent=True)
        return None   # 无变更
    except RuntimeError:
        pass  # 有变更，继续提交

    # 密钥扫描
    secret_warnings = _scan_staged_for_secrets()
    if secret_warnings:
        print(f"[contest_git] ⚠ 暂存区中发现疑似密钥，已阻止提交:", file=sys.stderr)
        for w in secret_warnings:
            print(w, file=sys.stderr)
        print("[contest_git]   请检查并从暂存区移除敏感内容后重试。", file=sys.stderr)
        _git("reset", "HEAD")   # 取消暂存
        return None

    # 构造语义化提交消息
    if round_n > 1:
        msg = f"fix({stage}): rework r{round_n} approved [{mode}]"
    else:
        msg = f"feat({stage}): approved [{mode}]"

    _git("commit", "-m", msg)
    sha = _git("rev-parse", "--short", "HEAD")
    print(f"[contest_git] ✓ {sha}  {msg}")

    # 里程碑自动打 tag
    if stage in MILESTONE_STAGES:
        _auto_milestone_tag(stage, round_n)

    return sha


def rework_start(stage: str, round_n: int) -> None:
    """
    Rework 阶段开始时记录空提交（标记 rework 入口点）。
    在 git log 中留下清晰的 rework 起始标记。
    """
    if not is_enabled():
        return
    msg = f"rework({stage}): start round {round_n} — awaiting human feedback"
    _git("commit", "--allow-empty", "-m", msg)
    sha = _git("rev-parse", "--short", "HEAD")
    print(f"[contest_git] ↩ {sha}  {msg}")


def milestone_tag(name: str, message: str = "") -> None:
    """手动打里程碑 tag，例如：final-v2、draft-v3。"""
    if not is_enabled():
        return
    if not _has_commits():
        return
    msg = message or f"Milestone: {name}"
    try:
        _git("tag", "-a", name, "-m", msg)
        print(f"[contest_git] 🏷  tag: {name}")
    except RuntimeError:
        # Tag 已存在，覆盖
        _git("tag", "-a", name, "-m", msg, "-f")
        print(f"[contest_git] 🏷  tag updated: {name}")


def _auto_milestone_tag(stage: str, round_n: int) -> None:
    """为里程碑阶段自动打 tag（draft-v1, final-v1, etc.）。"""
    prefix  = MILESTONE_STAGES[stage]
    tag     = f"{prefix}-v{round_n}"
    message = {
        "latex_draft":   f"论文草稿 v{round_n} 完成",
        "final_compile": f"最终版本 v{round_n} 编译完成",
    }.get(stage, f"{stage} v{round_n}")
    milestone_tag(tag, message)


def log(n: int = 15, oneline: bool = False) -> str:
    """返回格式化 git log。"""
    if not is_enabled() or not _has_commits():
        return "[contest_git] 尚无提交历史"
    if oneline:
        fmt = "--oneline"
    else:
        fmt = "--pretty=format:%C(yellow)%h%Creset  %C(cyan)%ar%Creset  %s%C(green)%d%Creset"
    return _git("log", fmt, f"-{n}", "--decorate")


def diff(ref1: str, ref2: str = "HEAD", stat_only: bool = False) -> str:
    """
    比较两个版本之间的差异。
    常用：diff draft-v1 draft-v2  （比较两轮草稿的论文变化）
    """
    if not is_enabled():
        return "[contest_git] 版本控制未启用"
    try:
        if stat_only:
            return _git("diff", "--stat", ref1, ref2)
        return _git("diff", ref1, ref2,
                    "--", "latex/main.tex",
                    "src/models/*.py",
                    "src/verifications/*.py")
    except RuntimeError as e:
        return f"[contest_git] diff 失败: {e}"


def status() -> str:
    """显示工作区文件状态。"""
    if not is_enabled():
        return "[contest_git] 版本控制未启用"
    tags = ""
    try:
        tags = _git("tag", "--sort=-creatordate", silent=True)
        tags = "\n  最近 tag: " + tags.split("\n")[0] if tags else ""
    except RuntimeError:
        pass
    return _git("status", "--short") + tags


def list_tags() -> str:
    """列出所有里程碑 tag。"""
    if not is_enabled():
        return "[contest_git] 版本控制未启用"
    try:
        return _git("tag", "-l", "--sort=-creatordate",
                    "--format=%(refname:short)  %(subject)")
    except RuntimeError:
        return "(无 tag)"


# ── CLI（独立使用）────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="竞赛工作区 Git 版本控制",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    # init
    pi = sub.add_parser("init", help="初始化工作区 Git 仓库")
    pi.add_argument("--name", default="", help="竞赛名称（写入初始提交）")
    pi.add_argument("--author", default="AutoMCM-Pro Agent", help="git user.name")

    # log
    pl = sub.add_parser("log", help="查看提交历史")
    pl.add_argument("-n", type=int, default=15, help="显示最近 N 条（默认 15）")
    pl.add_argument("--oneline", action="store_true", help="单行格式")

    # diff
    pd = sub.add_parser("diff", help="比较两个版本差异")
    pd.add_argument("ref1", help="起始版本（tag 或 commit hash）")
    pd.add_argument("ref2", nargs="?", default="HEAD", help="目标版本（默认 HEAD）")
    pd.add_argument("--stat", action="store_true", help="只显示变更统计")

    # status
    sub.add_parser("status", help="显示工作区文件状态")

    # tag
    pt = sub.add_parser("tag", help="打里程碑 tag")
    pt.add_argument("name", help="tag 名称（如 final-v2）")
    pt.add_argument("message", nargs="?", default="", help="tag 说明")

    # tags
    sub.add_parser("tags", help="列出所有里程碑 tag")

    args = p.parse_args()

    if args.cmd == "init":
        init(contest_name=args.name, author=args.author)
    elif args.cmd == "log":
        print(log(n=args.n, oneline=args.oneline))
    elif args.cmd == "diff":
        print(diff(args.ref1, args.ref2, stat_only=args.stat))
    elif args.cmd == "status":
        print(status())
    elif args.cmd == "tag":
        milestone_tag(args.name, args.message)
    elif args.cmd == "tags":
        print(list_tags())
    else:
        p.print_help()


if __name__ == "__main__":
    main()
