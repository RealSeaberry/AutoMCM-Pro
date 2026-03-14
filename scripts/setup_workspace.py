#!/usr/bin/env python3
"""
CUMCM-Master / MCM-Master Workspace Setup
在当前目录创建标准化的竞赛工作区结构，并初始化必要的占位文件。

用法:
  python scripts/setup_workspace.py              # 国赛模式（默认）
  python scripts/setup_workspace.py --mode mcm   # 美赛模式
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("CUMCM_Workspace")

DIRS = [
    ROOT / "data",
    ROOT / "src" / "models",        # 核心求解代码
    ROOT / "src" / "verifications", # 强制独立验证脚本
    ROOT / "latex" / "images",
    ROOT / "memory",
    ROOT / "state",                 # GitOps 状态文件
    ROOT / "output",
]

PENDING_CUMCM = [
    "Phase 1: 破题分析与文献调研",
    "Phase 2: 数据预处理",
    "Phase 2: 问题建模与验证",
    "Phase 3: LaTeX 论文撰写（中文）",
    "Phase 5: 编译 PDF",
]

PENDING_MCM = [
    "Phase 1: Problem analysis & literature research",
    "Phase 2: Data preprocessing",
    "Phase 2: Model development & verification",
    "Phase 3: Summary page writing",
    "Phase 3: Full paper LaTeX (English)",
    "Phase 4 (if required): Practical deliverable (memo/letter)",
    "Phase 5: Compile PDF",
]


def setup(mode: str = "cumcm"):
    is_mcm = mode.lower() == "mcm"
    label  = "MCM/ICM-Master" if is_mcm else "CUMCM-Master"

    print("=" * 58)
    print(f"  {label}  工作区初始化")
    if is_mcm:
        print("  美赛模式 (MCM/ICM) — English paper + mcmthesis")
    print("=" * 58)

    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  [创建] {d}")

    # ── iteration.json ──────────────────────────────────────────────────
    iteration_file = ROOT / "memory" / "iteration.json"
    if not iteration_file.exists():
        state = {
            "title": "",
            "mode": mode.lower(),
            "phase": "init",
            "phase_index": 0,
            "problems": [],
            "models": [],
            "iterations": 0,
            # MCM-specific fields
            "tcn": "",              # Team Control Number
            "problem_choice": "",   # A/B/C/D/E/F
            "contest_type": "",     # MCM or ICM
            "memo_mode": "",        # "agent" / "student" / "" (N/A)
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "completed_tasks": [],
            "pending_tasks": PENDING_MCM if is_mcm else PENDING_CUMCM,
        }
        iteration_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  [创建] {iteration_file}")

    # ── LaTeX 模板 ──────────────────────────────────────────────────────
    if is_mcm:
        template_src = Path("templates/mcm_template.tex")
        memo_src     = Path("templates/mcm_memo_template.tex")
        template_dst = ROOT / "latex" / "main.tex"
        memo_dst     = ROOT / "latex" / "memo.tex"

        if template_src.exists() and not template_dst.exists():
            shutil.copy(template_src, template_dst)
            print(f"  [复制] MCM 论文模板 → {template_dst}")
        elif not template_dst.exists():
            print(f"  [警告] 模板 {template_src} 不存在，请手动放置")

        if memo_src.exists() and not memo_dst.exists():
            shutil.copy(memo_src, memo_dst)
            print(f"  [复制] Memo 模板    → {memo_dst}")
    else:
        template_src = Path("templates/latex_template.tex")
        template_dst = ROOT / "latex" / "main.tex"
        if template_src.exists() and not template_dst.exists():
            shutil.copy(template_src, template_dst)
            print(f"  [复制] 国赛 LaTeX 模板 → {template_dst}")
        elif not template_dst.exists():
            print(f"  [警告] 模板 {template_src} 不存在，请手动放置")

    # ── memory 文件占位 ─────────────────────────────────────────────────
    thought_file = ROOT / "memory" / "thought_process.md"
    if not thought_file.exists():
        header = "# Thought Process Log\n\n" if is_mcm else "# 思考过程记录\n\n"
        thought_file.write_text(
            header + "> Workspace initialized. Awaiting problem input.\n",
            encoding="utf-8"
        )
        print(f"  [创建] {thought_file}")

    eval_file = ROOT / "memory" / "evaluation_log.md"
    if not eval_file.exists():
        header = "# Feedback & Evaluation Log\n\n" if is_mcm else "# 用户反馈评价记录\n\n"
        eval_file.write_text(header + "(No feedback yet)\n", encoding="utf-8")
        print(f"  [创建] {eval_file}")

    # ── src/__init__.py ─────────────────────────────────────────────────
    init_py = ROOT / "src" / "__init__.py"
    if not init_py.exists():
        init_py.write_text("# source package\n", encoding="utf-8")

    print()
    print(f"  工作区初始化完成！模式: {'MCM/ICM (English)' if is_mcm else 'CUMCM (中文)'}")
    print(f"  工作目录：{ROOT.resolve()}")
    print("=" * 58)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["cumcm", "mcm"], default="cumcm",
                        help="竞赛模式: cumcm (国赛) 或 mcm (美赛)")
    args = parser.parse_args()
    setup(mode=args.mode)
