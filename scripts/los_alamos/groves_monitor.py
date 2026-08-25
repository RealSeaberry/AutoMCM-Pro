#!/usr/bin/env python3
"""
groves_monitor.py — Groves 自我状态 Agent（纯脚本，不涉及 LLM）

职责刻意做窄（LOS_ALAMOS_DESIGN.md §6）：只读 messages.jsonl / pipeline.json，
计算漂移比例、预算燃烧速度、返工/回溯次数，超阈值时追加 DRIFT_ALERT / BUDGET_ALERT
消息给 Director。不直接干预任何 Division，不做科学判断。

用法：
  python scripts/los_alamos/groves_monitor.py check --problem-n 1
  python scripts/los_alamos/groves_monitor.py check --problem-n 1 --window 20 --drift-threshold 0.3

退出码：始终为 0（Groves 只上报，不阻塞——是否行动由 Director 决定），
        除非输入本身有错误（如消息日志损坏）才非 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bus  # noqa: E402

WORKSPACE = Path("CUMCM_Workspace")
PIPELINE  = WORKSPACE / "state" / "pipeline.json"


def _status_path(problem_n: int) -> Path:
    return WORKSPACE / "state" / f"groves_status_{problem_n}.json"


def _log_path() -> Path:
    return WORKSPACE / "memory" / "groves_log.md"


def compute_drift_ratio(msgs: list[dict], window: int) -> tuple[float, int, int]:
    """
    在最近 window 条 INTEL_REQUEST 里，计算"探索型"(new_assumption_proposal 非空)
    占比。返回 (drift_ratio, exploratory_count, total_count)。
    """
    intel_requests = [m for m in msgs if m.get("performative") == "INTEL_REQUEST"]
    recent = intel_requests[-window:] if window > 0 else intel_requests
    if not recent:
        return 0.0, 0, 0
    exploratory = sum(1 for m in recent if m.get("new_assumption_proposal"))
    return exploratory / len(recent), exploratory, len(recent)


def compute_backtrack_count(msgs: list[dict]) -> int:
    return sum(1 for m in msgs if m.get("performative") == "BACKTRACK")


def compute_red_team_stats(msgs: list[dict]) -> dict:
    reports = [m for m in msgs if m.get("performative") == "RED_TEAM_REPORT"]
    verdicts = [m.get("content", {}).get("verdict") for m in reports]
    total = len(verdicts)
    broken = verdicts.count("broken")
    return {
        "total": total,
        "broken": broken,
        "broken_rate": (broken / total) if total else 0.0,
    }


def compute_orphan_assumptions(problem_n: int) -> list[str]:
    """
    孤儿假设检测（§5.3）：扫描 memory/ledgers/problem{N}_*.json，找出
    downstream_impact 为空的假设 id。best-effort——ledger 目录不存在时返回空列表。
    """
    ledger_dir = WORKSPACE / "memory" / "ledgers"
    orphans = []
    if not ledger_dir.exists():
        return orphans
    for f in sorted(ledger_dir.glob(f"problem{problem_n}_*.json")):
        try:
            entries = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            if isinstance(e, dict) and not e.get("downstream_impact"):
                orphans.append(e.get("id", "?"))
    return orphans


def read_rework_counts(problem_n: int) -> dict:
    """从 pipeline.json 读各阶段 review_round（现有字段，SOP 既有的返工计数）。"""
    if not PIPELINE.exists():
        return {}
    try:
        state = json.loads(PIPELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    stages = state.get("stages", {})
    return {
        name: entry.get("review_round", 0)
        for name, entry in stages.items()
        if isinstance(entry, dict) and f"{problem_n}" in name and entry.get("review_round", 0) > 0
    }


def check(problem_n: int, window: int, drift_threshold: float, max_reworks: int) -> dict:
    msgs = bus.read_messages(problem_n)
    drift_ratio, exploratory, total_recent = compute_drift_ratio(msgs, window)
    backtrack_count = compute_backtrack_count(msgs)
    red_team = compute_red_team_stats(msgs)
    orphans = compute_orphan_assumptions(problem_n)
    reworks = read_rework_counts(problem_n)

    alerts = []

    if total_recent > 0 and drift_ratio > drift_threshold:
        alerts.append(("DRIFT_ALERT", {
            "drift_ratio": round(drift_ratio, 3),
            "threshold": drift_threshold,
            "exploratory": exploratory,
            "window": total_recent,
            "detail": f"最近 {total_recent} 条 INTEL_REQUEST 中 {exploratory} 条为探索型"
                      f"（未挂靠已有假设），比例 {drift_ratio:.0%} 超过阈值 {drift_threshold:.0%}",
        }))

    for stage, rounds in reworks.items():
        if rounds >= max_reworks - 2:
            alerts.append(("BUDGET_ALERT", {
                "stage": stage,
                "review_round": rounds,
                "max_reworks": max_reworks,
                "detail": f"阶段 {stage} 已返工 {rounds} 次，接近上限 {max_reworks}",
            }))

    if backtrack_count >= 3:
        alerts.append(("DRIFT_ALERT", {
            "backtrack_count": backtrack_count,
            "detail": f"累计回溯 {backtrack_count} 次，可能存在反复复活同一条死路的情形",
        }))

    status = {
        "problem_n": problem_n,
        "drift_ratio": round(drift_ratio, 3),
        "exploratory_requests": exploratory,
        "recent_intel_requests": total_recent,
        "backtrack_count": backtrack_count,
        "red_team": red_team,
        "orphan_assumptions": orphans,
        "rework_counts": reworks,
        "alerts_raised": len(alerts),
    }

    status_path = _status_path(problem_n)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for performative, content in alerts:
            msg = bus.append_message(
                problem_n=problem_n,
                performative=performative,
                sender="Groves",
                receiver="Director",
                content=content,
            )
            f.write(f"- [{msg['timestamp']}] {performative}: {content.get('detail', '')}\n")

    return status


def main():
    p = argparse.ArgumentParser(description="Groves 自我状态监控")
    sub = p.add_subparsers(dest="cmd")

    pc = sub.add_parser("check", help="计算漂移/预算/回溯/红队指标，超阈值追加告警消息")
    pc.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pc.add_argument("--window", type=int, default=20, help="漂移比例计算的滑动窗口大小")
    pc.add_argument("--drift-threshold", type=float, default=0.3, dest="drift_threshold")
    pc.add_argument("--max-reworks", type=int, default=5, dest="max_reworks",
                     help="沿用 SOP S4 的返工上限")

    args = p.parse_args()
    if args.cmd == "check":
        status = check(args.problem_n, args.window, args.drift_threshold, args.max_reworks)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        if status["alerts_raised"]:
            print(f"\n⚠ Groves 本次上报了 {status['alerts_raised']} 条告警"
                  f"（已写入 messages.jsonl，供 Director 下一回合读取处理）", file=sys.stderr)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
