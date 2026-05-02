#!/usr/bin/env python3
"""
AutoMCM-Pro Pipeline Manager
GitOps 流水线状态机 — 管理审查请求、人类批准、阶段推进。

命令列表：
  status                        显示当前流水线状态
  init                          初始化流水线
  start-stage <stage>           标记阶段为 in_progress
  request-review <options>      写入审查报告并阻塞流水线
  check-approval <stage>        读取人类反馈，返回 APPROVED/REWORK/PENDING
  advance <stage>               标记阶段为 approved，推进流水线
  rework <stage>                标记阶段为 rework
  checkpoint-banner <stage>     在终端打印等待人类的横幅

  # 并行多 Agent 支持
  parallel-start <s1> <s2>...   同时将多个阶段标记为 in_progress（并行启动）
  parallel-status <s1> <s2>...  查看一组并行阶段的完成情况
  parallel-all-done <s1>...     若全部 approved 则退出码 0，否则 1

  # 竞赛工作区版本控制（需 init --git 开启）
  contest-git log [-n N] [--oneline]    查看提交历史
  contest-git diff <ref1> [ref2]        比较两版本差异
  contest-git status                    工作区文件状态
  contest-git tag <name> [message]      打里程碑 tag
  contest-git tags                      列出所有 tag
"""

import argparse
import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# 竞赛工作区 Git（可选）
try:
    import contest_git as _cgit
    _CGIT_AVAILABLE = True
except ImportError:
    _CGIT_AVAILABLE = False

WORKSPACE    = Path("CUMCM_Workspace")
STATE_DIR    = WORKSPACE / "state"
PIPELINE     = STATE_DIR / "pipeline.json"
REVIEW_REQ   = STATE_DIR / "review_request.md"
HUMAN_FILE   = STATE_DIR / "human_intervention.md"
EVAL_LOG     = WORKSPACE / "memory" / "evaluation_log.md"

STAGE_ORDER = [
    "problem_analysis",
    "data_preprocessing",
    "model_1_build", "model_1_verify",
    "model_2_build", "model_2_verify",
    "model_3_build", "model_3_verify",  # 按实际题目数增减
    "sensitivity_analysis",
    "latex_draft",
    "final_compile",
]

# 允许并行的阶段组：同一组内的阶段可由不同 Agent 同时处理
# prerequisite 中的阶段必须是 approved 后，该组才能启动
PARALLEL_GROUPS: dict[str, dict] = {
    "model_builds": {
        "stages": ["model_1_build", "model_2_build", "model_3_build"],
        "prerequisite": "data_preprocessing",
        "description": "各子问题建模阶段（互相独立，可并行）",
    },
    "model_verifies": {
        "stages": ["model_1_verify", "model_2_verify", "model_3_verify"],
        "prerequisite": None,  # 每个 verify 依赖同编号的 build，由各 Agent 自行管理
        "description": "各子问题验证阶段（互相独立，可并行）",
    },
    "latex_sections": {
        "stages": [],          # 动态：latex_draft 子任务，运行时填充
        "prerequisite": "sensitivity_analysis",
        "description": "LaTeX 各章节写作（可由不同 Agent 并行负责）",
    },
}

STATUS_COLORS = {
    "not_started":    "·",
    "in_progress":    "▶",
    "pending_review": "⏸",
    "approved":       "✓",
    "rework":         "↩",
    "skipped":        "—",
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load():
    if not PIPELINE.exists():
        sys.exit("[pipeline] 流水线未初始化，请先运行 init_gitops.sh")
    return json.loads(PIPELINE.read_text(encoding="utf-8"))


def save(state: dict):
    state["updated_at"] = now()
    PIPELINE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_entry(status="not_started"):
    return {
        "status": status,
        "started_at": None,
        "completed_at": None,
        "approved_at": None,
        "review_round": 0,
        "notes": "",
    }


# ─────────────────────────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────────────────────────

def cmd_init(args):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "memory").mkdir(parents=True, exist_ok=True)

    git_enabled = bool(getattr(args, "git", False))

    stages = {s: _stage_entry() for s in STAGE_ORDER}
    state = {
        "session_id":    datetime.now().strftime("%Y%m%d_%H%M%S"),
        "mode":          args.mode.upper(),      # AP | MANUAL
        "contest":       args.contest.upper(),   # CUMCM | MCM | ICM
        "tcn":           args.tcn or "",
        "problem_choice": args.choice or "",
        "created_at":    now(),
        "updated_at":    now(),
        "current_stage": "problem_analysis",
        "blocked_at":    None,
        "block_reason":  "",
        "stages":        stages,
        "total_reworks": 0,
        "git_enabled":   git_enabled,
    }
    save(state)

    # 初始化 review_request.md
    if not REVIEW_REQ.exists():
        REVIEW_REQ.write_text(
            "# Review Request\n\n_(no review pending)_\n", encoding="utf-8"
        )

    # 初始化 human_intervention.md（Manual 模式含规格模板）
    if not HUMAN_FILE.exists():
        _write_intervention_template(args.mode.upper())

    print(f"[pipeline] 流水线初始化完成")
    print(f"  会话 ID  : {state['session_id']}")
    print(f"  模式     : {state['mode']}")
    print(f"  竞赛     : {state['contest']}")
    print(f"  起始阶段 : problem_analysis")
    print(f"  版本控制 : {'✓ 已启用 (contest_git)' if git_enabled else '✗ 未启用 (可用 --git 开启)'}")

    # 初始化竞赛 git 仓库
    if git_enabled and _CGIT_AVAILABLE:
        contest_name = f"{state['contest']} {state['problem_choice']}".strip()
        _cgit.init(contest_name=contest_name)


def _write_intervention_template(mode: str):
    manual_spec = ""
    if mode == "MANUAL":
        manual_spec = """
---

## [MANUAL_SPEC]

> 请在此区块中填写每个问题的数学规格，AI 将 100% 按此实现。

### 问题一
- **模型类型**: （如：非线性规划 / 线性规划 / ODE / 回归）
- **决策变量**: （列举所有变量及含义）
- **目标函数**: （精确数学表达式，LaTeX 语法亦可）
- **约束条件**:
  - 约束一
  - 约束二
- **求解方法**: （如 scipy.optimize.minimize, method='SLSQP'）
- **特殊处理**: （如 数据对数变换、特殊初始值设定）

### 问题二
（同上）
"""
    HUMAN_FILE.write_text(
        f"# Human Intervention Log\n\n"
        f"> **模式**: {mode}\n"
        f"> **说明**: 在各阶段 AI 停下来等待时，在此文件填写审查结果。\n\n"
        f"## 审查结果区\n\n"
        f"_(AI 停下来时，在此填写 `[APPROVED]` 或 `[REWORK] + 修改意见`)_\n"
        f"{manual_spec}",
        encoding="utf-8"
    )


def cmd_status(args):
    state = load()
    mode_badge = "🤖 AP" if state["mode"] == "AP" else "👤 MANUAL"
    print(f"\n{'═'*58}")
    print(f"  AutoMCM-Pro Pipeline  [{mode_badge}]  {state['contest']}")
    print(f"  会话: {state['session_id']}  更新: {state['updated_at']}")
    print(f"{'═'*58}")
    print(f"  当前阶段: {state['current_stage']}")
    if state.get("blocked_at"):
        print(f"  ⏸ 阻塞于: {state['blocked_at']}  ({state['block_reason']})")
    print(f"\n  阶段一览:")
    for stage, info in state["stages"].items():
        sym = STATUS_COLORS.get(info["status"], "?")
        rw = f" (rework×{info['review_round']})" if info["review_round"] > 0 else ""
        print(f"    {sym}  {stage:<30} {info['status']}{rw}")
    print(f"{'═'*58}\n")
    # Machine-readable return for shell scripts
    return state["current_stage"], state["stages"].get(
        state["current_stage"], {}
    ).get("status", "unknown")


def cmd_start_stage(args):
    state = load()
    stage = args.stage
    if stage not in state["stages"]:
        state["stages"][stage] = _stage_entry()
    state["stages"][stage]["status"] = "in_progress"
    state["stages"][stage]["started_at"] = now()
    state["current_stage"] = stage
    state["blocked_at"] = None
    state["block_reason"] = ""
    save(state)
    print(f"[pipeline] ▶ 阶段开始: {stage}")


def cmd_request_review(args):
    state = load()
    stage = args.stage

    if stage not in state["stages"]:
        state["stages"][stage] = _stage_entry()

    state["stages"][stage]["status"] = "pending_review"
    state["stages"][stage]["completed_at"] = now()
    state["stages"][stage]["review_round"] += 1
    state["blocked_at"] = now()
    state["block_reason"] = f"awaiting human review of {stage}"
    save(state)

    round_n = state["stages"][stage]["review_round"]
    report = f"""# Review Request — Round {round_n}

**阶段**: `{stage}`
**时间**: {now()}
**模式**: {state['mode']}
**状态**: AWAITING HUMAN APPROVAL

---

## 本阶段工作摘要

{args.summary}

---

## 关键结果 / 验证数据

{args.results}

---

## 问题与不确定点

{args.concerns or '（无）'}

---

## 拟进入的下一阶段

{args.next or '（待定）'}

---

## 审查指引

请阅读上述报告，然后在 `state/human_intervention.md` 中填写：

- 同意继续 → `[APPROVED]`
- 需要修改 → `[REWORK]`，并在下方写明具体修改意见

填写完毕后，在终端输入「**继续**」并按 Enter 唤醒 AI。
"""
    REVIEW_REQ.write_text(report, encoding="utf-8")

    # Append to eval log
    entry = (
        f"\n\n---\n\n## [{now()}] Review 请求 — {stage} (Round {round_n})\n\n"
        f"### 摘要\n{args.summary}\n\n"
        f"### 结果\n{args.results}\n"
    )
    with EVAL_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[pipeline] review_request.md 已更新")

    # Print the blocking banner
    cmd_checkpoint_banner(args)


def cmd_check_approval(args):
    """读取 human_intervention.md，返回 APPROVED / REWORK / PENDING"""
    if not HUMAN_FILE.exists():
        print("PENDING")
        return "PENDING"

    content = HUMAN_FILE.read_text(encoding="utf-8")

    # Look for the most recent decision marker
    if "[APPROVED]" in content:
        print("APPROVED")
        return "APPROVED"
    elif "[REWORK]" in content:
        # Extract feedback after [REWORK]
        idx = content.rfind("[REWORK]")
        feedback = content[idx + len("[REWORK]"):].strip()
        print(f"REWORK\n{feedback}")
        return "REWORK"
    else:
        print("PENDING")
        return "PENDING"


def cmd_advance(args):
    state = load()
    stage = args.stage
    if stage not in state["stages"]:
        sys.exit(f"[pipeline] 未知阶段: {stage}")

    state["stages"][stage]["status"] = "approved"
    state["stages"][stage]["approved_at"] = now()
    state["blocked_at"] = None
    state["block_reason"] = ""

    # Find next stage
    if stage in STAGE_ORDER:
        idx = STAGE_ORDER.index(stage)
        if idx + 1 < len(STAGE_ORDER):
            next_stage = STAGE_ORDER[idx + 1]
            state["current_stage"] = next_stage
            state["stages"][next_stage]["status"] = "in_progress"
            state["stages"][next_stage]["started_at"] = now()
            print(f"[pipeline] ✓ {stage} → approved")
            print(f"[pipeline] ▶ 推进至: {next_stage}")
        else:
            state["current_stage"] = "complete"
            print(f"[pipeline] ✓ {stage} → approved")
            print(f"[pipeline] 🏁 流水线全部完成！")
    save(state)

    # Clear APPROVED marker from human_intervention.md so it's ready for next round
    if HUMAN_FILE.exists():
        content = HUMAN_FILE.read_text(encoding="utf-8")
        content = content.replace("[APPROVED]", f"[APPROVED — {stage} @ {now()}]")
        HUMAN_FILE.write_text(content, encoding="utf-8")

    # 自动 git 快照
    if state.get("git_enabled") and _CGIT_AVAILABLE and _cgit.is_enabled():
        round_n = state["stages"][stage].get("review_round", 1)
        _cgit.auto_commit(stage, mode=state["mode"], round_n=round_n)


def cmd_rework(args):
    state = load()
    stage = args.stage
    if stage not in state["stages"]:
        sys.exit(f"[pipeline] 未知阶段: {stage}")

    state["stages"][stage]["status"] = "rework"
    state["total_reworks"] = state.get("total_reworks", 0) + 1
    state["current_stage"] = stage
    state["blocked_at"] = None
    save(state)

    entry = (
        f"\n\n---\n\n## [{now()}] Rework 开始 — {stage}\n\n"
        f"**反馈来源**: human_intervention.md\n\n"
        f"**修改意见**: {args.feedback or '（见 human_intervention.md）'}\n"
    )
    with EVAL_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[pipeline] ↩ {stage} → rework")
    print(f"[pipeline] 请阅读 human_intervention.md 中的修改意见后开始 Rework")

    # Clear REWORK marker
    if HUMAN_FILE.exists():
        content = HUMAN_FILE.read_text(encoding="utf-8")
        content = content.replace("[REWORK]", f"[REWORK — {stage} @ {now()}]")
        HUMAN_FILE.write_text(content, encoding="utf-8")

    # rework 起始标记提交
    if state.get("git_enabled") and _CGIT_AVAILABLE and _cgit.is_enabled():
        round_n = state["stages"][stage].get("review_round", 1) + 1
        _cgit.rework_start(stage, round_n)


def cmd_checkpoint_banner(args):
    stage = getattr(args, "stage", "unknown")
    banner = f"""
╔══════════════════════════════════════════════════════════╗
║  ⏸  CHECKPOINT — 等待人类审查                            ║
╠══════════════════════════════════════════════════════════╣
║  阶段：{stage:<50}║
║  报告：CUMCM_Workspace/state/review_request.md           ║
╠══════════════════════════════════════════════════════════╣
║  请操作：                                                ║
║  1. 阅读 state/review_request.md 中的报告                ║
║  2. 在 state/human_intervention.md 中填写意见            ║
║     • 同意继续  →  写入 [APPROVED]                       ║
║     • 需要修改  →  写入 [REWORK] + 具体指令              ║
║  3. 在终端输入「继续」后按 Enter 唤醒 AI                 ║
╠══════════════════════════════════════════════════════════╣
║  Mind-Reader: http://localhost:8080                      ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)


def cmd_parallel_start(args):
    """同时将多个阶段标记为 in_progress，用于多 Agent 并行启动。"""
    state = load()
    started = []
    for stage in args.stages:
        if stage not in state["stages"]:
            state["stages"][stage] = _stage_entry()
        state["stages"][stage]["status"] = "in_progress"
        state["stages"][stage]["started_at"] = now()
        started.append(stage)

    # current_stage 记录所有活跃阶段（以 | 分隔）
    state["current_stage"] = " | ".join(started)
    state["blocked_at"] = None
    state["block_reason"] = ""
    save(state)
    print(f"[pipeline] ▶ 并行启动 {len(started)} 个阶段:")
    for s in started:
        print(f"    • {s}")
    print(f"[pipeline] 请为每个阶段分配独立的 Agent 子进程。")


def cmd_parallel_status(args):
    """输出一组并行阶段各自的状态。"""
    state = load()
    stages = args.stages
    print(f"\n  并行阶段状态 ({len(stages)} 个)")
    print(f"  {'─'*40}")
    all_approved = True
    for s in stages:
        info = state["stages"].get(s, {"status": "not_started", "review_round": 0})
        sym = STATUS_COLORS.get(info["status"], "?")
        rw = f" (rework×{info['review_round']})" if info.get("review_round", 0) > 0 else ""
        print(f"  {sym}  {s:<32} {info['status']}{rw}")
        if info["status"] != "approved":
            all_approved = False
    print(f"  {'─'*40}")
    print(f"  全部完成: {'✓ YES' if all_approved else '✗ NO (仍有未完成阶段)'}\n")
    return all_approved


def cmd_parallel_all_done(args):
    """
    检查一组并行阶段是否全部 approved。
    退出码 0 = 全部完成，退出码 1 = 尚未全部完成。
    """
    state = load()
    stages = args.stages
    done = all(
        state["stages"].get(s, {}).get("status") == "approved"
        for s in stages
    )
    if done:
        print(f"[pipeline] ✓ 并行组全部完成: {stages}")
        sys.exit(0)
    else:
        pending = [s for s in stages
                   if state["stages"].get(s, {}).get("status") != "approved"]
        print(f"[pipeline] ✗ 尚未完成: {pending}")
        sys.exit(1)


def cmd_contest_git(args):
    """代理到 contest_git 的各子命令。"""
    if not _CGIT_AVAILABLE:
        sys.exit("[pipeline] contest_git 模块不可用，请确认 scripts/contest_git.py 存在")
    sub = args.git_sub
    if sub == "log":
        print(_cgit.log(n=getattr(args, "n", 15), oneline=getattr(args, "oneline", False)))
    elif sub == "diff":
        print(_cgit.diff(args.ref1, getattr(args, "ref2", "HEAD"),
                         stat_only=getattr(args, "stat", False)))
    elif sub == "status":
        print(_cgit.status())
    elif sub == "tag":
        _cgit.milestone_tag(args.name, getattr(args, "message", ""))
    elif sub == "tags":
        print(_cgit.list_tags())
    else:
        print("contest-git 子命令: log | diff | status | tag | tags")


def main():
    p = argparse.ArgumentParser(description="AutoMCM-Pro Pipeline Manager")
    sub = p.add_subparsers(dest="command")

    # init
    pi = sub.add_parser("init")
    pi.add_argument("--mode",    required=True, choices=["ap","AP","manual","MANUAL"])
    pi.add_argument("--contest", required=True, choices=["cumcm","CUMCM","mcm","MCM","icm","ICM"])
    pi.add_argument("--tcn",     default="")
    pi.add_argument("--choice",  default="")
    pi.add_argument("--git",     action="store_true",
                    help="在 CUMCM_Workspace/ 下初始化竞赛 Git 仓库")

    # status
    sub.add_parser("status")

    # start-stage
    ps = sub.add_parser("start-stage")
    ps.add_argument("stage")

    # request-review
    pr = sub.add_parser("request-review")
    pr.add_argument("--stage",    required=True)
    pr.add_argument("--summary",  required=True)
    pr.add_argument("--results",  default="（见 review_request.md）")
    pr.add_argument("--concerns", default="")
    pr.add_argument("--next",     default="")

    # check-approval
    pca = sub.add_parser("check-approval")
    pca.add_argument("--stage", default="")

    # advance
    pav = sub.add_parser("advance")
    pav.add_argument("stage")

    # rework
    prw = sub.add_parser("rework")
    prw.add_argument("stage")
    prw.add_argument("--feedback", default="")

    # checkpoint-banner
    pcb = sub.add_parser("checkpoint-banner")
    pcb.add_argument("--stage", default="")

    # parallel-start
    pps = sub.add_parser("parallel-start",
                         help="同时将多个阶段标记为 in_progress（并行启动）")
    pps.add_argument("stages", nargs="+", help="要并行启动的阶段名列表")

    # parallel-status
    ppst = sub.add_parser("parallel-status",
                          help="查看一组并行阶段的完成情况")
    ppst.add_argument("stages", nargs="+")

    # parallel-all-done
    ppad = sub.add_parser("parallel-all-done",
                          help="若全部 approved 则退出码 0，否则 1")
    ppad.add_argument("stages", nargs="+")

    # contest-git — 竞赛工作区版本控制（嵌套子命令）
    pcg = sub.add_parser("contest-git", help="竞赛工作区 Git 版本控制")
    cg_sub = pcg.add_subparsers(dest="git_sub")

    cg_log = cg_sub.add_parser("log", help="查看提交历史")
    cg_log.add_argument("-n", type=int, default=15)
    cg_log.add_argument("--oneline", action="store_true")

    cg_diff = cg_sub.add_parser("diff", help="比较两个版本差异")
    cg_diff.add_argument("ref1")
    cg_diff.add_argument("ref2", nargs="?", default="HEAD")
    cg_diff.add_argument("--stat", action="store_true")

    cg_sub.add_parser("status", help="显示工作区文件状态")

    cg_tag = cg_sub.add_parser("tag", help="打里程碑 tag")
    cg_tag.add_argument("name")
    cg_tag.add_argument("message", nargs="?", default="")

    cg_sub.add_parser("tags", help="列出所有里程碑 tag")

    args = p.parse_args()

    dispatch = {
        "init":               cmd_init,
        "status":             cmd_status,
        "start-stage":        cmd_start_stage,
        "request-review":     cmd_request_review,
        "check-approval":     cmd_check_approval,
        "advance":            cmd_advance,
        "rework":             cmd_rework,
        "checkpoint-banner":  cmd_checkpoint_banner,
        "parallel-start":     cmd_parallel_start,
        "parallel-status":    cmd_parallel_status,
        "parallel-all-done":  cmd_parallel_all_done,
        "contest-git":        cmd_contest_git,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
