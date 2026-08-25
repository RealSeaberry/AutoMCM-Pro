#!/usr/bin/env python3
"""
worklog.py —— 完整 AI 工作记录（单文件、追加写、简体中文）

设计目标（用户需求原话："保留完整的ai工作記錄，使用最便宜，最節約token的方式，
存一個單獨的文件，保留用戶-ai交互記錄以及agent工作記錄、程式碼執行結果"）：

1. **完整**：用户消息、Agent 关键决策、代码/门控执行结果三类都要有记录，不遗漏
   任何一类；覆盖的是"类别"，不是要求逐字复刻所有中间推理过程。
2. **最省 token**：不靠额外一轮 LLM 生成来"总结"日志内容——日志内容就是本来就
   会自然产生的短句（阶段名/exit code/一句话理由），机械追加。`pipeline_manager.py`
   / `quality_gate.py` / `los_alamos/*.py` 在自己的关键动作发生时顺手调用
   `log()` 函数写一行，**不需要 Agent 额外调用、不占用额外的生成轮次**；只有
   "用户说了什么""Agent 做了什么决定"这两类脚本本身看不到的信息，才需要 Agent
   自己调 `worklog.py append`，且要求一句话、不铺陈。
3. **单文件、纯文本、简体中文、时间顺序**：`CUMCM_Workspace/memory/worklog.md`，
   人类可以直接打开阅读，不需要额外工具解析；不是 JSON，不是事件溯源系统——
   本项目已经有 `los_alamos/bus.py` 承担结构化事件溯源，worklog 定位不同，是给
   人事后快速翻阅"这次到底发生了什么"用的流水账，两者不重复。

子命令：
  append   追加一行记录（Agent 用于记录用户消息/自己的关键决策）
  tail     查看最近 N 行（快速回顾用）

其他脚本内 import worklog 后直接调用 log(role, text) 函数写入，不经过 CLI。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("CUMCM_Workspace")
WORKLOG = WORKSPACE / "memory" / "worklog.md"

# 角色标签，供其他脚本以更口语化的 key 调用也能落到统一的中文标签
_ROLE_LABELS = {
    "user": "用户", "用户": "用户",
    "agent": "Agent", "Agent": "Agent",
    "exec": "执行", "执行": "执行", "code": "执行",
    "gate": "门控", "门控": "门控",
    "system": "系统", "系统": "系统",
}

_MAX_LINE_CHARS = 300   # 单行记录长度上限，超出截断——保持"省 token"，不是逐字全文转录


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(role: str, text: str) -> None:
    """供其他脚本 import 后直接调用的最小接口。一次一行，不做除标签/截断以外
    的加工——调用方自己已经有现成的短句（阶段名/exit code/理由），直接传进来。
    """
    label = _ROLE_LABELS.get(role, role)
    text = " ".join(text.split())  # 折叠换行/多余空白，保证一条记录一行
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS] + "……（截断）"
    WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    with open(WORKLOG, "a", encoding="utf-8") as f:
        f.write(f"[{_now()}] [{label}] {text}\n")


def cmd_append(args):
    log(args.role, args.text)
    print(f"[worklog] 已追加一行（{_ROLE_LABELS.get(args.role, args.role)}）")


def cmd_tail(args):
    if not WORKLOG.exists():
        print("[worklog] 尚无记录（工作日志文件还不存在）")
        return
    lines = WORKLOG.read_text(encoding="utf-8").splitlines()
    for line in lines[-args.n:]:
        print(line)
    if not lines:
        print("[worklog] 文件存在但为空")


def main():
    p = argparse.ArgumentParser(
        description="AutoMCM-Pro 工作日志——单文件、简体中文、完整覆盖用户消息/"
                    "Agent 决策/代码执行结果",
    )
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("append", help="追加一行记录")
    pa.add_argument("--role", required=True,
                     help="user/agent/exec/gate/system（或直接传中文：用户/Agent/执行/门控/系统）")
    pa.add_argument("--text", required=True, help="记录内容，一句话，简体中文，不铺陈")

    pt = sub.add_parser("tail", help="查看最近 N 行")
    pt.add_argument("-n", type=int, default=20)

    args = p.parse_args()
    if args.cmd == "append":
        cmd_append(args)
    elif args.cmd == "tail":
        cmd_tail(args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
