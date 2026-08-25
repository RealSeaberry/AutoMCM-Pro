#!/usr/bin/env python3
"""
bus.py — Los Alamos 探索层：Agent 间格式化报文总线

单一来源：CUMCM_Workspace/state/messages/problem{N}.jsonl（append-only，事件溯源）。
所有其他 addon（groves_monitor.py / adjudicate.py / hypothesis_tree.py）都通过本模块
读写消息，不直接碰 jsonl 文件，保证格式统一、可校验。

设计依据：LOS_ALAMOS_DESIGN.md §7（格式化报文协议）。

用法（CLI，供 Agent 直接从 Bash 调用）：
  python scripts/los_alamos/bus.py send --problem-n 1 \
      --performative INTEL_REQUEST --sender T-Division --receiver Alsos \
      --ref-assumption-id A-P1-T-03 \
      --content '{"query": "残差非正态情形的处理惯例", "justification": "验证 A-P1-T-03"}'

  python scripts/los_alamos/bus.py read --problem-n 1 [--performative INTEL_REQUEST]

  python scripts/los_alamos/bus.py validate --problem-n 1

也可作为库导入：
  from scripts.los_alamos.bus import append_message, read_messages, validate_file
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE  = Path("CUMCM_Workspace")
MSG_DIR    = WORKSPACE / "state" / "messages"

# ── Performative 词表（LOS_ALAMOS_DESIGN.md §7.2）──────────────────────────────
# 已知 performative 会做全量结构校验；未知 performative 只做基础信封校验并给出
# WARN（addon 可以自行扩展新的 performative，不强制先改这份词表才能用）。
KNOWN_PERFORMATIVES = {
    "INTEL_REQUEST", "INTEL_RESPONSE",
    "EXPAND_NODE", "SCREEN_VERDICT", "MERGE_NODES", "BACKTRACK",
    "RED_TEAM_REPORT",
    "STATUS_REPORT", "DRIFT_ALERT", "BUDGET_ALERT",
    "APPROVAL_REQUEST", "APPROVED", "REJECTED",
    "VOTE",
    "AMEND_ANCHOR",
    "CHECKPOINT_REQUEST", "REWORK",
}

# 要求 ref_assumption_id / new_assumption_proposal 二选一（防漂移挂靠规则，§5.2）
DAG_LINK_REQUIRED = {"INTEL_REQUEST"}


def messages_path(problem_n: int) -> Path:
    return MSG_DIR / f"problem{problem_n}.jsonl"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _load_lines(problem_n: int) -> list[dict]:
    path = messages_path(problem_n)
    if not path.exists():
        return []
    msgs = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError as e:
            msgs.append({"_parse_error": f"line {i}: {e}", "_raw": line})
    return msgs


def next_msg_id(problem_n: int) -> str:
    existing = _load_lines(problem_n)
    seq = sum(1 for m in existing if "_parse_error" not in m) + 1
    return f"MSG-P{problem_n}-{seq:06d}"


def append_message(
    problem_n: int,
    performative: str,
    sender: str,
    receiver: str,
    content: dict | None = None,
    ref_assumption_id: str | None = None,
    new_assumption_proposal: str | None = None,
    in_reply_to: str | None = None,
) -> dict:
    """构造并追加一条消息，返回写入的完整消息体。"""
    path = messages_path(problem_n)
    path.parent.mkdir(parents=True, exist_ok=True)

    msg = {
        "msg_id": next_msg_id(problem_n),
        "timestamp": _now(),
        "performative": performative,
        "sender": sender,
        "receiver": receiver,
        "in_reply_to": in_reply_to,
        "ref_assumption_id": ref_assumption_id,
        "new_assumption_proposal": new_assumption_proposal,
        "content": content or {},
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    return msg


def read_messages(problem_n: int, performative: str | None = None) -> list[dict]:
    msgs = [m for m in _load_lines(problem_n) if "_parse_error" not in m]
    if performative:
        msgs = [m for m in msgs if m.get("performative") == performative]
    return msgs


# ── 校验 ─────────────────────────────────────────────────────────────────────

_REQUIRED_FIELDS = ["msg_id", "timestamp", "performative", "sender", "receiver", "content"]


def validate_message(msg: dict) -> list[str]:
    """校验单条消息，返回问题列表（空 = 合法）。"""
    problems = []

    if "_parse_error" in msg:
        return [f"JSON 解析失败：{msg['_parse_error']}"]

    for field in _REQUIRED_FIELDS:
        if field not in msg:
            problems.append(f"缺少必填字段: {field}")
    if problems:
        return problems  # 缺字段时后续检查没有意义

    performative = msg["performative"]
    if performative not in KNOWN_PERFORMATIVES:
        problems.append(f"WARN: 未识别的 performative '{performative}'（仅做基础信封校验，"
                         f"addon 若确实需要新 performative，请追加进 bus.KNOWN_PERFORMATIVES）")

    if performative in DAG_LINK_REQUIRED:
        ref = msg.get("ref_assumption_id")
        new = msg.get("new_assumption_proposal")
        if not ref and not new:
            problems.append(
                f"{performative} 既未挂靠已有假设(ref_assumption_id)，也未声明为新方向"
                f"(new_assumption_proposal)——违反防漂移挂靠规则（DESIGN §5.2），应被拒绝"
            )
        elif ref and new:
            problems.append(
                f"{performative} 同时填写了 ref_assumption_id 和 new_assumption_proposal，"
                f"应二选一（DESIGN §5.2）"
            )

    if not isinstance(msg.get("content"), dict):
        problems.append("content 字段必须是对象（dict）")

    return problems


def validate_file(problem_n: int) -> tuple[bool, list[str]]:
    """
    校验整份消息日志：逐条结构校验 + msg_id 唯一性 + 时间戳单调递增。
    返回 (是否全部通过, 报告行列表)。WARN 不计入失败，仅提示。
    """
    msgs = _load_lines(problem_n)
    report: list[str] = []
    hard_fail = False

    if not msgs:
        return True, [f"（无消息记录：{messages_path(problem_n)} 不存在或为空，视为通过）"]

    seen_ids: set[str] = set()
    last_ts: str | None = None

    for i, msg in enumerate(msgs, 1):
        problems = validate_message(msg)
        errors = [p for p in problems if not p.startswith("WARN:")]
        warns = [p for p in problems if p.startswith("WARN:")]

        if errors:
            hard_fail = True
            report.append(f"✗ 第 {i} 行 [{msg.get('msg_id', '?')}] " + "；".join(errors))
        for w in warns:
            report.append(f"  第 {i} 行 [{msg.get('msg_id', '?')}] {w}")

        if "_parse_error" not in msg:
            mid = msg.get("msg_id")
            if mid in seen_ids:
                hard_fail = True
                report.append(f"✗ 第 {i} 行 msg_id 重复: {mid}")
            seen_ids.add(mid)

            ts = msg.get("timestamp")
            if last_ts and ts and ts < last_ts:
                hard_fail = True
                report.append(f"✗ 第 {i} 行 时间戳非单调递增: {ts} < {last_ts}")
            if ts:
                last_ts = ts

    if not hard_fail:
        report.append(f"✓ {len(msgs)} 条消息全部通过结构校验")

    return not hard_fail, report


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_send(args):
    content = json.loads(args.content) if args.content else {}
    msg = append_message(
        problem_n=args.problem_n,
        performative=args.performative,
        sender=args.sender,
        receiver=args.receiver,
        content=content,
        ref_assumption_id=args.ref_assumption_id,
        new_assumption_proposal=args.new_assumption_proposal,
        in_reply_to=args.in_reply_to,
    )
    problems = validate_message(msg)
    errors = [p for p in problems if not p.startswith("WARN:")]
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    if errors:
        print("✗ 消息未通过校验（已写入，但请修正后续行为）：", "；".join(errors), file=sys.stderr)
        sys.exit(1)


def _cmd_read(args):
    msgs = read_messages(args.problem_n, performative=args.performative)
    print(json.dumps(msgs, ensure_ascii=False, indent=2))


def _cmd_validate(args):
    ok, report = validate_file(args.problem_n)
    for line in report:
        print(line)
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(description="Los Alamos 报文总线")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("send", help="追加一条消息")
    ps.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    ps.add_argument("--performative", required=True)
    ps.add_argument("--sender", required=True)
    ps.add_argument("--receiver", required=True)
    ps.add_argument("--content", default="", help="JSON 字符串")
    ps.add_argument("--ref-assumption-id", dest="ref_assumption_id", default=None)
    ps.add_argument("--new-assumption-proposal", dest="new_assumption_proposal", default=None)
    ps.add_argument("--in-reply-to", dest="in_reply_to", default=None)

    pr = sub.add_parser("read", help="读取消息（可按 performative 过滤）")
    pr.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pr.add_argument("--performative", default=None)

    pv = sub.add_parser("validate", help="校验整份消息日志")
    pv.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    args = p.parse_args()
    if args.cmd == "send":
        _cmd_send(args)
    elif args.cmd == "read":
        _cmd_read(args)
    elif args.cmd == "validate":
        _cmd_validate(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
