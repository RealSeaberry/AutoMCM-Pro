#!/usr/bin/env python3
"""
hypothesis_tree.py — 假设树 / DAG 的物化视图（LOS_ALAMOS_DESIGN.md §3）

真相来源永远是 messages.jsonl；本脚本只做"重放消息日志 → 当前树状态"的物化视图
构建（event-sourcing 模式，DESIGN §7.3），不单独维护另一套状态。

子命令：
  expand     Director 对某父节点发起展开，产生新的 proposed 子节点（EXPAND_NODE 消息）
  merge      合并两个节点为一个新节点（MERGE_NODES 消息）
  backtrack  对已终止节点重新展开（BACKTRACK 消息）
  mark       通用状态上报（building / verify_pass / verify_fail / eliminated /
             in_tournament / champion / runner_up），用于 Division 汇报自己的建造进度
  rebuild    重放整份消息日志，重新生成 state/hypothesis_tree_{N}.json
  status     打印当前"前沿"（screened_pass 待决策节点 + in_tournament 存活候选）

节点状态机见 DESIGN §3.2：
  proposed → screened_pass/screened_pruned/merge_candidate → building
           → verify_pass/verify_fail → red_team_review → in_tournament/eliminated
           → champion/runner_up
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bus  # noqa: E402

WORKSPACE = Path("CUMCM_Workspace")
STATE_DIR = WORKSPACE / "state"

# mark 子命令允许直接设置的终态/中间态（不经过专属 performative 驱动的状态机）
_MARKABLE_STATES = {
    "building", "verify_pass", "verify_fail", "eliminated",
    "in_tournament", "champion", "runner_up",
}


def _tree_path(problem_n: int) -> Path:
    return STATE_DIR / f"hypothesis_tree_{problem_n}.json"


def rebuild(problem_n: int) -> dict:
    """重放消息日志，返回 {node_id: node_dict}。"""
    msgs = bus.read_messages(problem_n)
    nodes: dict[str, dict] = {}

    for m in msgs:
        perf = m.get("performative")
        content = m.get("content", {})

        if perf == "EXPAND_NODE":
            nid = content["node_id"]
            nodes[nid] = {
                "node_id": nid,
                "parent_ids": content.get("parent_ids", []),
                "assumption_id": content.get("assumption_id"),
                "seed_paradigm": content.get("seed_paradigm"),
                "depth": content.get("depth", 0),
                "state": "proposed",
                "screening": None,
                "red_team": None,
                "backtrack_count": 0,
                "created_by": m.get("sender"),
                "created_at": m.get("timestamp"),
            }

        elif perf == "SCREEN_VERDICT":
            nid = m.get("ref_assumption_id")
            if nid not in nodes:
                continue
            nodes[nid]["screening"] = content
            verdict = content.get("verdict")
            if verdict == "prune":
                nodes[nid]["state"] = "screened_pruned"
            elif verdict == "merge_candidate":
                nodes[nid]["state"] = "merge_candidate"
            elif verdict == "expand":
                nodes[nid]["state"] = "screened_pass"
            # needs_more_intel: 保持原状态不变，等待补充情报后重新筛选

        elif perf == "MERGE_NODES":
            nid = content["node_id"]
            nodes[nid] = {
                "node_id": nid,
                "parent_ids": content.get("parent_ids", []),
                "assumption_id": content.get("assumption_id"),
                "seed_paradigm": "merge",
                "depth": content.get("depth", 0),
                "state": "proposed",
                "screening": None,
                "red_team": None,
                "backtrack_count": 0,
                "created_by": m.get("sender"),
                "created_at": m.get("timestamp"),
            }

        elif perf == "BACKTRACK":
            nid = content.get("node_id")
            if nid in nodes:
                nodes[nid]["state"] = "proposed"
                nodes[nid]["backtrack_count"] = nodes[nid].get("backtrack_count", 0) + 1

        elif perf == "RED_TEAM_REPORT":
            nid = content.get("node_id")
            if nid not in nodes:
                continue
            nodes[nid]["red_team"] = content
            verdict = content.get("verdict")
            if verdict == "broken":
                nodes[nid]["state"] = "building"  # 打回修复
            elif verdict in ("survived", "weakened"):
                nodes[nid]["state"] = "in_tournament"

        elif perf == "STATUS_REPORT" and "node_id" in content and content.get("state") in _MARKABLE_STATES:
            nid = content["node_id"]
            if nid in nodes:
                nodes[nid]["state"] = content["state"]

    return nodes


def save_tree(problem_n: int, nodes: dict) -> Path:
    path = _tree_path(problem_n)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ── 子命令 ────────────────────────────────────────────────────────────────────

def cmd_expand(args):
    parent_ids = [p for p in (args.parent_ids or "").split(",") if p]
    depth = args.depth
    if depth is None:
        depth = 0

    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="EXPAND_NODE",
        sender=args.sender,
        receiver="Director",
        content={
            "node_id": args.node_id,
            "parent_ids": parent_ids,
            "assumption_id": args.assumption_id,
            "seed_paradigm": args.seed_paradigm,
            "depth": depth,
        },
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    nodes = rebuild(args.problem_n)
    save_tree(args.problem_n, nodes)


def cmd_merge(args):
    parent_ids = [p for p in args.parent_ids.split(",") if p]
    if len(parent_ids) < 2:
        sys.exit("merge 需要至少 2 个 --parent-ids（逗号分隔）")
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="MERGE_NODES",
        sender=args.sender,
        receiver="Director",
        content={
            "node_id": args.node_id,
            "parent_ids": parent_ids,
            "assumption_id": args.assumption_id,
            "depth": args.depth,
        },
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    save_tree(args.problem_n, rebuild(args.problem_n))


def cmd_backtrack(args):
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="BACKTRACK",
        sender=args.sender,
        receiver="Director",
        content={"node_id": args.node_id, "reason": args.reason},
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    save_tree(args.problem_n, rebuild(args.problem_n))


def cmd_mark(args):
    if args.state not in _MARKABLE_STATES:
        sys.exit(f"--state 必须是 {sorted(_MARKABLE_STATES)} 之一")
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="STATUS_REPORT",
        sender=args.sender,
        receiver="Director",
        content={"node_id": args.node_id, "state": args.state},
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    save_tree(args.problem_n, rebuild(args.problem_n))


def cmd_rebuild(args):
    nodes = rebuild(args.problem_n)
    path = save_tree(args.problem_n, nodes)
    print(f"重放 {len(bus.read_messages(args.problem_n))} 条消息 → {len(nodes)} 个节点")
    print(f"写入 {path}")


def cmd_status(args):
    nodes = rebuild(args.problem_n)
    frontier = [n for n in nodes.values() if n["state"] == "screened_pass"]
    tournament = [n for n in nodes.values() if n["state"] == "in_tournament"]
    pruned = [n for n in nodes.values() if n["state"] == "screened_pruned"]

    print(f"树规模: {len(nodes)} 个节点")
    print(f"\n前沿（screened_pass，待 Director 决定下一步）: {len(frontier)}")
    for n in frontier:
        s = n.get("screening") or {}
        print(f"  - {n['node_id']} (depth={n['depth']}, 灵感={n.get('seed_paradigm')}) "
              f"novelty={s.get('novelty')} plausibility={s.get('plausibility')}")

    print(f"\n决赛圈（in_tournament）: {len(tournament)}")
    for n in tournament:
        rt = n.get("red_team") or {}
        print(f"  - {n['node_id']}  红队裁定={rt.get('verdict')}")

    print(f"\n已剪枝归档: {len(pruned)}")


def main():
    p = argparse.ArgumentParser(description="Los Alamos 假设树物化视图")
    sub = p.add_subparsers(dest="cmd")

    pe = sub.add_parser("expand", help="展开新节点")
    pe.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pe.add_argument("--node-id", required=True, dest="node_id")
    pe.add_argument("--parent-ids", default="", dest="parent_ids", help="逗号分隔，根节点留空")
    pe.add_argument("--assumption-id", required=True, dest="assumption_id")
    pe.add_argument("--seed-paradigm", default=None, dest="seed_paradigm")
    pe.add_argument("--depth", type=int, default=None)
    pe.add_argument("--sender", default="Director")

    pm = sub.add_parser("merge", help="合并两个节点")
    pm.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pm.add_argument("--node-id", required=True, dest="node_id")
    pm.add_argument("--parent-ids", required=True, dest="parent_ids", help="逗号分隔，至少 2 个")
    pm.add_argument("--assumption-id", required=True, dest="assumption_id")
    pm.add_argument("--depth", type=int, required=True)
    pm.add_argument("--sender", default="Director")

    pb = sub.add_parser("backtrack", help="对已终止节点重新展开")
    pb.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pb.add_argument("--node-id", required=True, dest="node_id")
    pb.add_argument("--reason", required=True)
    pb.add_argument("--sender", default="Director")

    pk = sub.add_parser("mark", help="通用状态上报（building/verify_pass/...)")
    pk.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pk.add_argument("--node-id", required=True, dest="node_id")
    pk.add_argument("--state", required=True)
    pk.add_argument("--sender", required=True)

    pr = sub.add_parser("rebuild", help="从消息日志重建物化视图")
    pr.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    ps = sub.add_parser("status", help="打印当前前沿/决赛圈概况")
    ps.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    args = p.parse_args()
    dispatch = {
        "expand": cmd_expand, "merge": cmd_merge, "backtrack": cmd_backtrack,
        "mark": cmd_mark, "rebuild": cmd_rebuild, "status": cmd_status,
    }
    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
