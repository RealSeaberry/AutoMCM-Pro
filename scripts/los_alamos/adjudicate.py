#!/usr/bin/env python3
"""
adjudicate.py — Los Alamos 四层评估机制的落地脚本（Track 0 / R / 1 / 2）

LOS_ALAMOS_DESIGN.md §8 的具体实现：
  screen         记录 Track 0 语义筛选裁定（SCREEN_VERDICT 消息）
  redteam        记录 Track R Bletchley 红队攻击报告（RED_TEAM_REPORT 消息）
  entropy-weight 计算 Track 1：熵权法客观赋权 + TOPSIS 排序（纯数学，无 LLM 主观分）
  panel-vote     记录 Track 2 评审小组的一次两两比较投票（VOTE 消息）
  panel-entropy  汇总 Track 2 投票为 Copeland 排名 + 分歧熵（Shannon entropy）
  combine        合并 Track 1 / Track 2 结果，产出 leaderboard 与是否升级 Checkpoint LA

所有子命令都通过 bus.py 读写 CUMCM_Workspace/state/messages/problem{N}.jsonl，
不直接维护另一套真相来源（DESIGN §7.3 的物化视图模式）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bus  # noqa: E402
import hypothesis_tree  # noqa: E402


def _sync_tree(problem_n: int):
    """screen/redteam 写完消息后，顺手把假设树物化视图快照也刷新一遍，避免
    直接读 hypothesis_tree_{N}.json 的人拿到过期状态（DESIGN §4.3）。status/
    rebuild 本身永远从消息日志重放、不受此影响，这里只是让快照文件本身别过期。"""
    hypothesis_tree.save_tree(problem_n, hypothesis_tree.rebuild(problem_n))

WORKSPACE = Path("CUMCM_Workspace")
STATE_DIR = WORKSPACE / "state"


# ── Track 0：语义筛选 ─────────────────────────────────────────────────────────

def cmd_screen(args):
    content = {
        "coherence": args.coherence,
        "plausibility": args.plausibility,
        "novelty": args.novelty,
        "problem_alignment": args.problem_alignment,
        "verdict": args.verdict,
        "rationale": args.rationale,
    }
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="SCREEN_VERDICT",
        sender=args.sender,
        receiver="Director",
        content=content,
        ref_assumption_id=args.node_id,
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    if args.verdict not in ("expand", "prune", "merge_candidate", "needs_more_intel"):
        print(f"⚠ 非标准 verdict '{args.verdict}'（建议用 expand/prune/merge_candidate/"
              f"needs_more_intel 之一，见 DESIGN §8.1）", file=sys.stderr)
    _sync_tree(args.problem_n)


# ── Track R：Bletchley 红队 ───────────────────────────────────────────────────

def cmd_redteam(args):
    attacks = json.loads(args.attacks_json) if args.attacks_json else []
    content = {
        "node_id": args.node_id,
        "attacks_attempted": attacks,
        "verdict": args.verdict,
        "severity": args.severity,
        "rationale": args.rationale,
    }
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="RED_TEAM_REPORT",
        sender=args.sender,
        receiver="Director",
        content=content,
        ref_assumption_id=args.node_id,
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    if args.verdict not in ("survived", "weakened", "broken"):
        print(f"⚠ 非标准 verdict '{args.verdict}'（应为 survived/weakened/broken，"
              f"见 DESIGN §8.2）", file=sys.stderr)
    _sync_tree(args.problem_n)


def red_team_verdict(problem_n: int, node_id: str) -> str | None:
    """取某节点最近一次 RED_TEAM_REPORT 的 verdict，供 quality_gate.py 复用。"""
    reports = [
        m for m in bus.read_messages(problem_n, "RED_TEAM_REPORT")
        if m.get("content", {}).get("node_id") == node_id
    ]
    if not reports:
        return None
    return reports[-1]["content"].get("verdict")


# ── Track 1：熵权法客观赋权 + TOPSIS ──────────────────────────────────────────

def entropy_weight_topsis(candidates: list[str], criteria: dict) -> dict:
    """
    candidates: 候选 id 列表
    criteria: {name: {"direction": "positive"|"negative", "values": {cand_id: value}}}
    返回：{"weights": {...}, "scores": {cand_id: closeness}, "ranking": [cand_id,...]}
    """
    m = len(candidates)
    if m < 2:
        raise ValueError("熵权法至少需要 2 个候选方案才能计算区分度")

    crit_names = list(criteria.keys())
    n = len(crit_names)
    eps = 1e-4

    # 1. 归一化（正向/负向指标分别处理）→ x'
    norm: dict[str, dict[str, float]] = {c: {} for c in candidates}
    for cj in crit_names:
        spec = criteria[cj]
        direction = spec.get("direction", "positive")
        raw = [spec["values"][c] for c in candidates]
        lo, hi = min(raw), max(raw)
        for c in candidates:
            x = spec["values"][c]
            if hi == lo:
                xp = 1.0  # 所有候选表现相同 → 无区分信息，后续熵会算出 1、权重算出 0
            elif direction == "positive":
                xp = (x - lo) / (hi - lo)
            else:
                xp = (hi - x) / (hi - lo)
            norm[c][cj] = xp

    # 2. 每个指标的信息熵 e_j
    k = 1.0 / math.log(m)
    entropy: dict[str, float] = {}
    for cj in crit_names:
        col = [norm[c][cj] + eps for c in candidates]
        s = sum(col)
        ps = [v / s for v in col]
        e = -k * sum(p * math.log(p) for p in ps)
        entropy[cj] = e

    # 3. 客观权重 w_j = (1-e_j) / Σ(1-e_k)
    diversity = {cj: max(0.0, 1.0 - entropy[cj]) for cj in crit_names}
    total_div = sum(diversity.values())
    if total_div <= 1e-12:
        weights = {cj: 1.0 / n for cj in crit_names}  # 所有指标都无区分度，退化为等权
    else:
        weights = {cj: diversity[cj] / total_div for cj in crit_names}

    # 4. TOPSIS：加权矩阵 → 正/负理想解 → 贴近度
    v = {c: {cj: weights[cj] * norm[c][cj] for cj in crit_names} for c in candidates}
    ideal_pos = {cj: max(v[c][cj] for c in candidates) for cj in crit_names}
    ideal_neg = {cj: min(v[c][cj] for c in candidates) for cj in crit_names}

    closeness: dict[str, float] = {}
    for c in candidates:
        d_pos = math.sqrt(sum((v[c][cj] - ideal_pos[cj]) ** 2 for cj in crit_names))
        d_neg = math.sqrt(sum((v[c][cj] - ideal_neg[cj]) ** 2 for cj in crit_names))
        closeness[c] = d_neg / (d_pos + d_neg) if (d_pos + d_neg) > 1e-12 else 0.5

    ranking = sorted(candidates, key=lambda c: closeness[c], reverse=True)

    return {
        "weights": {cj: round(weights[cj], 4) for cj in crit_names},
        "entropy": {cj: round(entropy[cj], 4) for cj in crit_names},
        "normalized": {c: {cj: round(norm[c][cj], 4) for cj in crit_names} for c in candidates},
        "scores": {c: round(closeness[c], 4) for c in candidates},
        "ranking": ranking,
    }


def cmd_entropy_weight(args):
    data = json.loads(Path(args.matrix_file).read_text(encoding="utf-8"))
    result = entropy_weight_topsis(data["candidates"], data["criteria"])

    out_path = STATE_DIR / f"track1_result_{args.problem_n}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    bus.append_message(
        problem_n=args.problem_n,
        performative="STATUS_REPORT",
        sender="adjudicate.entropy-weight",
        receiver="Director",
        content={"track": 1, "ranking": result["ranking"], "scores": result["scores"]},
    )

    print(f"客观权重（熵权法）: {json.dumps(result['weights'], ensure_ascii=False)}")
    print(f"贴近度排名（TOPSIS）:")
    for rank, c in enumerate(result["ranking"], 1):
        print(f"  {rank}. {c}  C={result['scores'][c]}")
    print(f"\n写入 {out_path}")


# ── Track 2：专家小组两两比较 + 分歧熵 ─────────────────────────────────────────

def cmd_panel_vote(args):
    content = {
        "judge_id": args.judge_id,
        "candidate_a": args.candidate_a,
        "candidate_b": args.candidate_b,
        "dimension": args.dimension,
        "preference": args.preference,
        "rationale": args.rationale,
        "round": args.round,  # RAND Delphi 多轮收敛用，见 delphi-summary/panel-entropy --round
    }
    msg = bus.append_message(
        problem_n=args.problem_n,
        performative="VOTE",
        sender=args.judge_id,
        receiver="adjudicate.panel-entropy",
        content=content,
    )
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    if args.preference not in ("A", "B", "TIE"):
        print("⚠ preference 应为 A / B / TIE 之一", file=sys.stderr)


def _shannon_entropy_normalized(counts: list[int]) -> float:
    """3 类结果（A胜/B胜/平局）的归一化 Shannon 熵，[0,1]，0=完全一致，1=完全分歧。"""
    total = sum(counts)
    if total == 0:
        return 0.0
    base = math.log2(3)  # 固定按 3 种可能结果归一化（DESIGN §8.4）
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h / base if base > 0 else 0.0


def panel_entropy(problem_n: int, entropy_threshold: float, round_n: int | None = None) -> dict:
    votes = bus.read_messages(problem_n, "VOTE")
    if round_n is not None:
        votes = [m for m in votes if m["content"].get("round", 1) == round_n]
    if not votes:
        return {"pairs": {}, "ranking": [], "avg_entropy": 0.0, "escalate": False,
                "round": round_n, "reason": "无投票记录"}

    pairs: dict[tuple, list[dict]] = defaultdict(list)
    for m in votes:
        c = m["content"]
        key = tuple(sorted([c["candidate_a"], c["candidate_b"]]))
        pairs[key].append(c)

    candidates: set[str] = set()
    pair_results = {}
    entropies = []

    for (a, b), records in pairs.items():
        candidates.update([a, b])
        a_wins = b_wins = ties = 0
        for r in records:
            pref = r["preference"]
            winner = r["candidate_a"] if pref == "A" else (r["candidate_b"] if pref == "B" else None)
            if winner == a:
                a_wins += 1
            elif winner == b:
                b_wins += 1
            else:
                ties += 1
        h = _shannon_entropy_normalized([a_wins, b_wins, ties])
        entropies.append(h)
        if a_wins > b_wins:
            pair_winner = a
        elif b_wins > a_wins:
            pair_winner = b
        else:
            pair_winner = None
        pair_results[f"{a}__vs__{b}"] = {
            "a": a, "b": b, "a_wins": a_wins, "b_wins": b_wins, "ties": ties,
            "disagreement_entropy": round(h, 4), "pair_winner": pair_winner,
        }

    # Copeland：赢一场 +1，输一场 -1，平局/无结论 0
    copeland: dict[str, int] = {c: 0 for c in candidates}
    for res in pair_results.values():
        if res["pair_winner"] == res["a"]:
            copeland[res["a"]] += 1
            copeland[res["b"]] -= 1
        elif res["pair_winner"] == res["b"]:
            copeland[res["b"]] += 1
            copeland[res["a"]] -= 1

    ranking = sorted(candidates, key=lambda c: copeland[c], reverse=True)
    avg_entropy = sum(entropies) / len(entropies) if entropies else 0.0

    return {
        "pairs": pair_results,
        "copeland": copeland,
        "ranking": ranking,
        "avg_entropy": round(avg_entropy, 4),
        "escalate": avg_entropy > entropy_threshold,
        "threshold": entropy_threshold,
        "round": round_n,
        "n_votes": len(votes),
    }


def cmd_panel_entropy(args):
    result = panel_entropy(args.problem_n, args.entropy_threshold, round_n=args.round)

    suffix = f"_r{args.round}" if args.round else ""
    out_path = STATE_DIR / f"track2_result_{args.problem_n}{suffix}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"轮次: {args.round or '(全部合并)'}  投票数: {result.get('n_votes', 0)}")
    print(f"Copeland 排名: {result['ranking']}")
    print(f"平均分歧熵: {result['avg_entropy']}（阈值 {args.entropy_threshold}）")
    print(f"是否需升级 Checkpoint LA: {'是' if result['escalate'] else '否'}")
    if result['escalate']:
        print(f"提示：分歧熵超阈值时，先跑 'adjudicate.py delphi-summary --problem-n {args.problem_n} "
              f"--round {args.round or 1}' 产出匿名聚合摘要给评审看，再收一轮投票"
              f"（--round {(args.round or 1) + 1}），而不是立刻升级人类终审——见 RAND Delphi 法。")
    print(f"\n写入 {out_path}")


# ── RAND Delphi：分歧熵过高时，先做匿名聚合摘要收敛一轮，而不是立刻升级人类 ─────

def delphi_summary(problem_n: int, round_n: int) -> dict:
    """
    汇总某一轮的全部投票，按 (候选对, 维度) 分组，产出匿名聚合摘要
    （只给票数分布 + 理由列表，不带 judge_id）。评审小组下一轮投票前先读这份
    摘要，看到"别人怎么想"再重新判断——这是 Delphi 法"匿名反馈"的核心机制，
    区别于普通会议讨论（会暴露身份、容易从众或固执）。
    """
    votes = bus.read_messages(problem_n, "VOTE")
    round_votes = [m for m in votes if m["content"].get("round", 1) == round_n]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for m in round_votes:
        c = m["content"]
        key = (tuple(sorted([c["candidate_a"], c["candidate_b"]])), c["dimension"])
        groups[key].append(c)

    summary = {"problem_n": problem_n, "round": round_n, "groups": []}
    for (pair, dimension), records in groups.items():
        a, b = pair
        counts = {"A": 0, "B": 0, "TIE": 0}
        rationales = []
        for r in records:
            counts[r["preference"]] = counts.get(r["preference"], 0) + 1
            # 匿名化：不带 judge_id，只留偏好和理由
            side = a if r["preference"] == "A" else (b if r["preference"] == "B" else "平局")
            rationales.append(f"（认为 {side} 更优）{r['rationale']}")
        summary["groups"].append({
            "candidate_a": a, "candidate_b": b, "dimension": dimension,
            "vote_counts": counts, "anonymous_rationales": rationales,
        })
    return summary


def cmd_delphi_summary(args):
    summary = delphi_summary(args.problem_n, args.round)

    lines = [f"# Delphi 第 {args.round} 轮匿名聚合摘要（问题 {args.problem_n}）", ""]
    if not summary["groups"]:
        lines.append(f"_（第 {args.round} 轮暂无投票记录）_")
    for g in summary["groups"]:
        lines.append(f"## {g['candidate_a']} vs {g['candidate_b']} — {g['dimension']}")
        lines.append(f"票数：A={g['vote_counts'].get('A',0)} "
                      f"B={g['vote_counts'].get('B',0)} 平局={g['vote_counts'].get('TIE',0)}")
        lines.append("匿名理由：")
        for r in g["anonymous_rationales"]:
            lines.append(f"- {r}")
        lines.append("")

    out_path = STATE_DIR / f"delphi_round_{args.round}_{args.problem_n}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    bus.append_message(
        problem_n=args.problem_n,
        performative="STATUS_REPORT",
        sender="adjudicate.delphi-summary",
        receiver="Director",
        content={"delphi_round": args.round, "summary_file": str(out_path)},
    )

    print("\n".join(lines))
    print(f"\n写入 {out_path}")
    print(f"下一步：把这份摘要交给评审小组读，然后收第 {args.round + 1} 轮投票"
          f"（panel-vote --round {args.round + 1}），再跑一次 panel-entropy --round "
          f"{args.round + 1} 看分歧熵有没有收敛。")


# ── 汇总：Track 1 + Track 2 → leaderboard / Checkpoint LA 判定 ────────────────

def cmd_combine(args):
    t1_path = STATE_DIR / f"track1_result_{args.problem_n}.json"
    t2_path = STATE_DIR / f"track2_result_{args.problem_n}.json"
    if not t1_path.exists() or not t2_path.exists():
        sys.exit(f"缺少 Track1/Track2 结果文件，请先运行 entropy-weight 和 panel-entropy"
                  f"（期望：{t1_path}, {t2_path}）")

    t1 = json.loads(t1_path.read_text(encoding="utf-8"))
    t2 = json.loads(t2_path.read_text(encoding="utf-8"))

    t1_top = t1["ranking"][0] if t1["ranking"] else None
    t2_top = t2["ranking"][0] if t2["ranking"] else None

    agree = t1_top is not None and t1_top == t2_top
    low_entropy = t2["avg_entropy"] <= t2["threshold"]

    # 方向性矛盾检测：Track1 冠军在 Track2 里 Copeland 分数为负（多数对决都输了）
    contradiction = False
    if t1_top and t1_top in t2.get("copeland", {}):
        contradiction = t2["copeland"][t1_top] < 0

    champion = t1_top if (agree and low_entropy and not contradiction) else None
    escalate = not (agree and low_entropy) or contradiction

    lines = [
        "## 候选方案汇总（Los Alamos Track1+Track2）\n",
        "| 候选 | Track1(TOPSIS) | Track1排名 | Track2(Copeland) | Track2排名 | 分歧熵 |",
        "|------|-----------------|------------|-------------------|------------|--------|",
    ]
    all_candidates = list(dict.fromkeys(t1["ranking"] + t2["ranking"]))
    for c in all_candidates:
        t1_rank = t1["ranking"].index(c) + 1 if c in t1["ranking"] else "—"
        t2_rank = t2["ranking"].index(c) + 1 if c in t2["ranking"] else "—"
        t1_score = t1["scores"].get(c, "—")
        t2_score = t2.get("copeland", {}).get(c, "—")
        lines.append(f"| {c} | {t1_score} | {t1_rank} | {t2_score} | {t2_rank} | {t2['avg_entropy']} |")

    lines.append("")
    if champion:
        lines.append(f"**结论：两轨一致胜出 → 冠军 = `{champion}`。分歧熵 {t2['avg_entropy']} "
                      f"≤ 阈值 {t2['threshold']}，AP 模式可自动晋级；MANUAL 模式仍需人类批准。**")
    else:
        reasons = []
        if not agree:
            reasons.append(f"Track1 冠军（{t1_top}）与 Track2 冠军（{t2_top}）不一致")
        if not low_entropy:
            reasons.append(f"Track2 平均分歧熵 {t2['avg_entropy']} 超过阈值 {t2['threshold']}")
        if contradiction:
            reasons.append(f"⚠ 方向性矛盾：Track1 冠军 {t1_top} 在 Track2 两两对决中 Copeland "
                            f"分数为负（多数对决落败），数值好看但可能站不住脚，最高优先级")
        lines.append("**结论：存疑，强制升级 Checkpoint LA，需人类终审。原因：**")
        for r in reasons:
            lines.append(f"- {r}")

    leaderboard_path = STATE_DIR / f"leaderboard_{args.problem_n}.md"
    leaderboard_path.write_text("\n".join(lines), encoding="utf-8")

    bus.append_message(
        problem_n=args.problem_n,
        performative="STATUS_REPORT",
        sender="adjudicate.combine",
        receiver="Director",
        content={"champion": champion, "escalate": escalate, "leaderboard": str(leaderboard_path)},
    )

    print("\n".join(lines))
    print(f"\n写入 {leaderboard_path}")
    sys.exit(0 if champion else 1)  # 非 0 = 需要 Checkpoint LA，供上层脚本判断分支


def main():
    p = argparse.ArgumentParser(description="Los Alamos 四层评估机制")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("screen", help="Track 0：记录语义筛选裁定")
    ps.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    ps.add_argument("--node-id", required=True, dest="node_id")
    ps.add_argument("--sender", default="Director")
    ps.add_argument("--coherence", type=float, required=True)
    ps.add_argument("--plausibility", type=float, required=True)
    ps.add_argument("--novelty", type=float, required=True)
    ps.add_argument("--problem-alignment", type=float, required=True, dest="problem_alignment")
    ps.add_argument("--verdict", required=True)
    ps.add_argument("--rationale", required=True)

    pr = sub.add_parser("redteam", help="Track R：记录红队攻击报告")
    pr.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pr.add_argument("--node-id", required=True, dest="node_id")
    pr.add_argument("--sender", default="Bletchley")
    pr.add_argument("--attacks-json", default="[]", dest="attacks_json")
    pr.add_argument("--verdict", required=True)
    pr.add_argument("--severity", default="none")
    pr.add_argument("--rationale", required=True)

    pe = sub.add_parser("entropy-weight", help="Track 1：熵权法 + TOPSIS")
    pe.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pe.add_argument("--matrix-file", required=True, dest="matrix_file",
                     help="JSON: {candidates:[...], criteria:{name:{direction,values:{cand:val}}}}")

    pv = sub.add_parser("panel-vote", help="Track 2：记录一次两两比较投票")
    pv.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pv.add_argument("--judge-id", required=True, dest="judge_id")
    pv.add_argument("--candidate-a", required=True, dest="candidate_a")
    pv.add_argument("--candidate-b", required=True, dest="candidate_b")
    pv.add_argument("--dimension", required=True)
    pv.add_argument("--preference", required=True, choices=["A", "B", "TIE"])
    pv.add_argument("--rationale", required=True)
    pv.add_argument("--round", type=int, default=1, help="RAND Delphi 轮次，默认第 1 轮")

    ppe = sub.add_parser("panel-entropy", help="Track 2：汇总投票为 Copeland 排名 + 分歧熵")
    ppe.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    ppe.add_argument("--entropy-threshold", type=float, default=0.3, dest="entropy_threshold")
    ppe.add_argument("--round", type=int, default=None,
                      help="只统计指定轮次的投票；不传则合并全部轮次（向后兼容旧用法）")

    pds = sub.add_parser("delphi-summary",
                          help="RAND Delphi：产出某轮投票的匿名聚合摘要，供评审下一轮参考")
    pds.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pds.add_argument("--round", type=int, required=True, help="要汇总的轮次")

    pcm = sub.add_parser("combine", help="合并 Track1+Track2，产出 leaderboard")
    pcm.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    args = p.parse_args()
    dispatch = {
        "screen": cmd_screen, "redteam": cmd_redteam, "entropy-weight": cmd_entropy_weight,
        "panel-vote": cmd_panel_vote, "panel-entropy": cmd_panel_entropy,
        "delphi-summary": cmd_delphi_summary, "combine": cmd_combine,
    }
    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
