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
"""

import argparse
import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path

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


def main():
    p = argparse.ArgumentParser(description="AutoMCM-Pro Pipeline Manager")
    sub = p.add_subparsers(dest="command")

    # init
    pi = sub.add_parser("init")
    pi.add_argument("--mode",    required=True, choices=["ap","AP","manual","MANUAL"])
    pi.add_argument("--contest", required=True, choices=["cumcm","CUMCM","mcm","MCM","icm","ICM"])
    pi.add_argument("--tcn",     default="")
    pi.add_argument("--choice",  default="")

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
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
