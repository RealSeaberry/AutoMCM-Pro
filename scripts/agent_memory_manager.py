#!/usr/bin/env python3
"""
CUMCM-Master Agent Memory Manager
负责维护智能体的思考过程、状态机和用户反馈记录。
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path


WORKSPACE = Path("CUMCM_Workspace")
MEMORY_DIR = WORKSPACE / "memory"
THOUGHT_PROCESS = MEMORY_DIR / "thought_process.md"
EVALUATION_LOG = MEMORY_DIR / "evaluation_log.md"
ITERATION_FILE = MEMORY_DIR / "iteration.json"

PHASES = ["init", "phase1_analysis", "phase2_coding", "phase3_writing",
          "phase4_feedback", "phase5_compile", "complete"]


def ensure_dirs():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_iteration():
    if ITERATION_FILE.exists():
        return json.loads(ITERATION_FILE.read_text(encoding="utf-8"))
    return {
        "title": "",
        "phase": "init",
        "phase_index": 0,
        "problems": [],
        "models": [],
        "iterations": 0,
        "created_at": now(),
        "updated_at": now(),
        "completed_tasks": [],
        "pending_tasks": [],
    }


def save_iteration(state: dict):
    state["updated_at"] = now()
    ITERATION_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_init(args):
    """初始化工作区记忆文件"""
    ensure_dirs()

    problems = args.problems.split("|") if args.problems else []
    models = args.models.split("|") if args.models else []

    state = load_iteration()
    state.update({
        "title": args.title,
        "phase": "phase1_analysis",
        "phase_index": 1,
        "problems": problems,
        "models": models,
        "created_at": now(),
    })
    save_iteration(state)

    # 初始化 thought_process.md
    content = f"""# 思考过程记录 — {args.title}

> 创建时间：{now()}

---

## 赛题理解

（待填写：题目背景、核心挑战）

---

## 问题分解

"""
    for i, (prob, model) in enumerate(zip(problems, models), 1):
        content += f"### 问题{i}\n- **题目描述**：{prob}\n- **拟用模型**：{model}\n- **数学推导**：（待填写）\n\n"

    content += """---

## 数学推导记录

（每完成一个模型后在此追加推导过程）

---

## 关键结果汇总

（代码运行后在此记录核心数值结果）
"""

    if not THOUGHT_PROCESS.exists():
        THOUGHT_PROCESS.write_text(content, encoding="utf-8")
        print(f"[init] 创建 {THOUGHT_PROCESS}")
    else:
        print(f"[init] {THOUGHT_PROCESS} 已存在，跳过覆盖")

    # 初始化 evaluation_log.md
    if not EVALUATION_LOG.exists():
        EVALUATION_LOG.write_text(
            f"# 用户反馈评价记录 — {args.title}\n\n> 创建时间：{now()}\n\n---\n\n"
            "(暂无用户反馈)\n",
            encoding="utf-8",
        )
        print(f"[init] 创建 {EVALUATION_LOG}")

    print(f"[init] 状态机初始化完成 → phase: phase1_analysis")


def cmd_thought(args):
    """追加思考记录到 thought_process.md"""
    ensure_dirs()
    entry = f"\n\n---\n\n### [{now()}] {args.section}\n\n{args.content}\n"
    with THOUGHT_PROCESS.open("a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[thought] 已追加到 {THOUGHT_PROCESS}")


def cmd_result(args):
    """记录代码运行的关键数值结果"""
    ensure_dirs()
    entry = (
        f"\n\n---\n\n### [{now()}] 结果记录 — {args.problem}\n\n"
        f"**代码文件**：`{args.script}`\n\n"
        f"**关键结果**：\n\n{args.result}\n\n"
        f"**图表输出**：`{args.figures}`\n"
    )
    with THOUGHT_PROCESS.open("a", encoding="utf-8") as f:
        f.write(entry)

    state = load_iteration()
    state["completed_tasks"].append(f"结果记录: {args.problem} @ {now()}")
    save_iteration(state)
    print(f"[result] 已记录结果到 {THOUGHT_PROCESS}")


def cmd_feedback(args):
    """记录用户反馈与批判性评价"""
    ensure_dirs()
    entry = (
        f"\n\n---\n\n## [{now()}] 用户反馈 #{_count_feedback() + 1}\n\n"
        f"### 用户建议\n{args.summary}\n\n"
        f"### 批判性评价\n{args.criticism}\n\n"
        f"### 决策\n**{args.decision}**\n\n"
        f"### 理由\n{args.reason}\n"
    )
    with EVALUATION_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    state = load_iteration()
    state["iterations"] += 1
    if args.decision in ("采纳", "部分采纳"):
        state["phase"] = "phase2_coding"
        state["phase_index"] = 2
        print(f"[feedback] 采纳建议，状态回退至 phase2_coding")
    save_iteration(state)
    print(f"[feedback] 已记录至 {EVALUATION_LOG}")


def cmd_advance(args):
    """推进状态机到下一阶段"""
    state = load_iteration()
    current_idx = PHASES.index(state["phase"]) if state["phase"] in PHASES else 0
    next_idx = min(current_idx + 1, len(PHASES) - 1)
    state["phase"] = PHASES[next_idx]
    state["phase_index"] = next_idx
    save_iteration(state)
    print(f"[advance] 状态推进至 {state['phase']}")


def cmd_complete(args):
    """标记任务完成"""
    state = load_iteration()
    state["phase"] = "complete"
    state["phase_index"] = len(PHASES) - 1
    save_iteration(state)

    summary = (
        f"\n\n---\n\n## [{now()}] 任务完成\n\n"
        f"- 论文标题：{state['title']}\n"
        f"- 总迭代次数：{state['iterations']}\n"
        f"- 完成时间：{now()}\n"
        f"- 输出文件：`CUMCM_Workspace/output/final_paper.pdf`\n"
    )
    with THOUGHT_PROCESS.open("a", encoding="utf-8") as f:
        f.write(summary)
    print("[complete] 任务标记为完成，记录已写入 thought_process.md")


def cmd_status(args):
    """显示当前状态"""
    if not ITERATION_FILE.exists():
        print("[status] 尚未初始化，请先运行 init 命令")
        return
    state = load_iteration()
    print(json.dumps(state, ensure_ascii=False, indent=2))


def _count_feedback():
    if not EVALUATION_LOG.exists():
        return 0
    return EVALUATION_LOG.read_text(encoding="utf-8").count("## [")


def main():
    parser = argparse.ArgumentParser(
        description="CUMCM-Master Agent Memory Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="初始化记忆文件")
    p_init.add_argument("--title", required=True, help="赛题标题")
    p_init.add_argument("--problems", default="", help="问题描述，用|分隔")
    p_init.add_argument("--models", default="", help="拟用模型，用|分隔")

    # thought
    p_thought = sub.add_parser("thought", help="追加思考记录")
    p_thought.add_argument("--section", required=True, help="章节标题")
    p_thought.add_argument("--content", required=True, help="内容（支持Markdown）")

    # result
    p_result = sub.add_parser("result", help="记录代码结果")
    p_result.add_argument("--problem", required=True, help="对应问题编号")
    p_result.add_argument("--script", default="", help="代码文件名")
    p_result.add_argument("--result", required=True, help="关键数值结果")
    p_result.add_argument("--figures", default="", help="生成的图表文件名")

    # feedback
    p_fb = sub.add_parser("feedback", help="记录用户反馈")
    p_fb.add_argument("--summary", required=True, help="用户建议摘要")
    p_fb.add_argument("--criticism", required=True, help="批判性评价")
    p_fb.add_argument("--decision", required=True,
                      choices=["采纳", "部分采纳", "拒绝"], help="决策")
    p_fb.add_argument("--reason", required=True, help="决策理由")

    # advance / complete / status
    sub.add_parser("advance", help="推进到下一阶段")
    sub.add_parser("complete", help="标记任务完成")
    sub.add_parser("status", help="显示当前状态")

    args = parser.parse_args()
    cmds = {
        "init": cmd_init, "thought": cmd_thought, "result": cmd_result,
        "feedback": cmd_feedback, "advance": cmd_advance,
        "complete": cmd_complete, "status": cmd_status,
    }
    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
