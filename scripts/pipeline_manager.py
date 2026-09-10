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

  # AP 多 Agent 并行辅助
  suggest-parallel                      输出当前可并行的下一批阶段名（供 AP 模式决策）
"""

import argparse
import json
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worklog  # noqa: E402

# 竞赛工作区 Git（可选）
try:
    import contest_git as _cgit
    _CGIT_AVAILABLE = True
except ImportError:
    _CGIT_AVAILABLE = False
    import warnings as _warnings
    _warnings.warn("[pipeline] contest_git 模块不可用，版本控制功能已禁用", stacklevel=1)

# 用于防止 Markdown 注入的控制标记
_INJECTION_PATTERNS = ["[APPROVED]", "[REWORK]", "[MANUAL_SPEC]"]

def _sanitize(text: str) -> str:
    """去除可能注入流水线控制标记的内容。"""
    for pat in _INJECTION_PATTERNS:
        text = text.replace(pat, pat.replace("[", "⟦").replace("]", "⟧"))
    text = re.sub(r"\[(APPROVED|REWORK):[A-Za-z0-9_-]+:[0-9]+\]",
                  lambda match: match.group(0).replace("[", "⟦").replace("]", "⟧"), text)
    return text

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
    try:
        return json.loads(PIPELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[pipeline] pipeline.json 损坏，无法解析: {e}\n"
                 f"  请检查文件或从备份恢复: {PIPELINE}")


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

    git_enabled   = bool(getattr(args, "git", False))
    problem_count = int(getattr(args, "problems", 1))
    max_reworks   = int(getattr(args, "max_reworks", 5))
    skunk_works   = bool(getattr(args, "skunk_works", False))
    kaizen_max_rounds = int(getattr(args, "kaizen_max_rounds", 2))
    lean_policy = getattr(args, "lean_policy", "off")

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
        "problem_count": problem_count,
        "max_reworks":   max_reworks,
        "skunk_works":   skunk_works,   # Project Skunk Works：轻量快速模式，见 AutoMCM_SOP.md §10
        "lean_formal": {
            "enabled": lean_policy != "off",
            "policy": lean_policy,
            "proof_timeout_seconds": 300,
            "problems": {},
            "obligation_ids": [],
            "obligation_baseline": [],
            "required_claim_ids": [],
            "assessment_sealed": False,
            "assessment_baseline": [],
        },
        "andon": {                       # Andon Cord：任何 Agent 可拉的紧急停止信号，见 §11
            "pulled": False,
            "reason": "",
            "pulled_by": "",
            "pulled_at": None,
            "cleared_at": None,
            "resolution": "",
        },
        "kaizen": {                      # Project Kaizen：主动质量打磨循环，见 §13
            "max_rounds": kaizen_max_rounds,
            "problems": {},
        },
    }
    if lean_policy != "off":
        command = [sys.executable, str(Path(__file__).resolve().parent / "leangate.py"),
                   "--workspace", str(WORKSPACE), "init", "--policy", lean_policy]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            sys.exit(f"[pipeline] LeanGate 初始化失败:\n{result.stderr or result.stdout}")
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
    print(f"  子问题数 : {problem_count}  {'→ AP 多 Agent 并行已开启' if problem_count > 1 else '(单问题，顺序执行)'}")
    print(f"  最大返工 : {max_reworks} 次/阶段")
    print(f"  版本控制 : {'✓ 已启用 (contest_git)' if git_enabled else '✗ 未启用 (可用 --git 开启)'}")
    print(f"  LeanGate: {lean_policy}")

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
        f"_(AI 停下来时，按 review_request.md 给出的阶段与轮次填写批准或返工标记)_\n"
        f"{manual_spec}",
        encoding="utf-8"
    )


def cmd_status(args):
    state = load()
    mode_badge = "🤖 AP" if state["mode"] == "AP" else "👤 MANUAL"
    sw_badge = "  [🦨 SKUNK WORKS]" if state.get("skunk_works") else ""
    print(f"\n{'═'*58}")
    print(f"  AutoMCM-Pro Pipeline  [{mode_badge}]  {state['contest']}{sw_badge}")
    print(f"  会话: {state['session_id']}  更新: {state['updated_at']}")
    print(f"{'═'*58}")
    andon = state.get("andon", {})
    if andon.get("pulled"):
        print(f"  🔴 ANDON 已拉下！全流水线冻结，禁止 advance，直到 andon-clear")
        print(f"     原因: {andon.get('reason', '')}")
        print(f"     拉绳者: {andon.get('pulled_by', '?')}  时间: {andon.get('pulled_at', '?')}")
    print(f"  当前阶段: {state['current_stage']}")
    if state.get("blocked_at"):
        print(f"  ⏸ 阻塞于: {state['blocked_at']}  ({state['block_reason']})")
    print(f"\n  阶段一览:")
    for stage, info in state["stages"].items():
        sym = STATUS_COLORS.get(info["status"], "?")
        rw = f" (rework×{info['review_round']})" if info["review_round"] > 0 else ""
        print(f"    {sym}  {stage:<30} {info['status']}{rw}")
    print(f"{'═'*58}\n")


# ── Andon Cord：任意 Agent 可拉的紧急停止信号（AutoMCM_SOP.md §11）────────────

def cmd_andon_pull(args):
    state = load()
    andon = state.setdefault("andon", {})
    if andon.get("pulled"):
        print(f"[andon] ⚠ 已经处于拉下状态（{andon.get('pulled_at')}，原因：{andon.get('reason')}），"
              f"本次调用忽略。先 andon-clear 再重新拉。")
        sys.exit(1)
    andon["pulled"] = True
    andon["reason"] = args.reason
    andon["pulled_by"] = args.by or "unknown"
    andon["pulled_at"] = now()
    andon["cleared_at"] = None
    andon["resolution"] = ""
    save(state)
    print(f"[andon] 🔴 已拉下 ANDON CORD。全流水线冻结，advance 一律被拒绝，直到人工确认并 andon-clear。")
    print(f"  拉绳者: {andon['pulled_by']}")
    print(f"  原因  : {andon['reason']}")
    worklog.log("系统", f"🔴 Andon 拉下（{andon['pulled_by']}）：{andon['reason']}")


def cmd_andon_clear(args):
    state = load()
    andon = state.setdefault("andon", {})
    if not andon.get("pulled"):
        print("[andon] 当前没有拉下的 andon，无需清除。")
        sys.exit(0)
    andon["pulled"] = False
    andon["cleared_at"] = now()
    andon["resolution"] = args.resolution
    save(state)
    print(f"[andon] ✓ 已清除。解决方案：{args.resolution}")
    print(f"  （原告警原因 '{andon.get('reason')}' 已存档，未被覆盖，供事后审计）")
    worklog.log("系统", f"🟢 Andon 清除：{args.resolution}")


def cmd_andon_status(args):
    state = load()
    andon = state.get("andon", {})
    if andon.get("pulled"):
        print(f"🔴 PULLED — {andon.get('reason')}（{andon.get('pulled_by')} @ {andon.get('pulled_at')}）")
        sys.exit(1)
    else:
        last = f"（上次：{andon.get('resolution')} @ {andon.get('cleared_at')}）" if andon.get("cleared_at") else ""
        print(f"✓ 正常 {last}")
        sys.exit(0)
    # Machine-readable return for shell scripts
    return state["current_stage"], state["stages"].get(
        state["current_stage"], {}
    ).get("status", "unknown")


_KAIZEN_DIMS = ("significance", "robustness", "assumptions", "completeness")
_KAIZEN_THRESHOLD = 4.0   # 均分 ≥ 此值视为质量已达标，见 AutoMCM_SOP.md §13.2


def cmd_kaizen_assess(args):
    """记录一次 Kaizen 质量自评，返回是否建议再打磨一轮。

    四个维度均为 1-5 分（1=明显薄弱，5=充分令人信服），只在 sensitivity_analysis
    已 approved 之后才有意义调用——Kaizen 打磨的是"已经正确的结果"，不是修 bug。
    退出码 0 = PROCEED（放行，无需/无法再打磨），1 = ROUND_RECOMMENDED（建议打磨）。
    """
    for dim in _KAIZEN_DIMS:
        score = getattr(args, dim)
        if not 1 <= score <= 5:
            sys.exit(f"[kaizen] --{dim} 必须在 1-5 之间，收到 {score}")

    state = load()
    kz = state.setdefault("kaizen", {"max_rounds": 2, "problems": {}})
    pkey = str(args.problem_n)
    prec = kz["problems"].setdefault(pkey, {"rounds_used": 0, "history": []})

    scores = {dim: getattr(args, dim) for dim in _KAIZEN_DIMS}
    avg = sum(scores.values()) / len(scores)
    rounds_used = prec["rounds_used"]
    max_rounds = kz.get("max_rounds", 2)

    if avg >= _KAIZEN_THRESHOLD:
        decision = "PROCEED"
        reason = f"均分 {avg:.2f} ≥ 达标线 {_KAIZEN_THRESHOLD}，质量已足够，放行"
    elif rounds_used >= max_rounds:
        decision = "PROCEED"
        reason = (f"均分 {avg:.2f} < {_KAIZEN_THRESHOLD}，但已达轮数上限 "
                   f"({rounds_used}/{max_rounds})，强制放行，如实记录仍不够理想")
    else:
        decision = "ROUND_RECOMMENDED"
        reason = (f"均分 {avg:.2f} < {_KAIZEN_THRESHOLD}，时间预算允许时建议打磨一轮"
                   f"（{rounds_used}/{max_rounds} 轮已用）")

    record = {
        "time": now(), "scores": scores, "avg": round(avg, 2),
        "weakest": args.weakest, "decision": decision,
        "rounds_used_at_assess": rounds_used,
    }
    prec["history"].append(record)
    prec["last_avg"] = record["avg"]
    prec["last_decision"] = decision
    save(state)

    icon = "🟢" if decision == "PROCEED" else "🟡"
    print(f"[kaizen] {icon} 问题 {args.problem_n} 质量自评：均分 {avg:.2f}/5"
          f"（显著性{scores['significance']} 稳健性{scores['robustness']} "
          f"假设合理性{scores['assumptions']} 论证完整性{scores['completeness']}）")
    print(f"  最弱点：{args.weakest}")
    print(f"  裁定：{decision} —— {reason}")
    worklog.log("Agent", f"Kaizen 自评 问题{args.problem_n} 均分{avg:.2f} {decision}，最弱：{args.weakest}")
    sys.exit(0 if decision == "PROCEED" else 1)


def cmd_kaizen_round_start(args):
    """登记开始一轮打磨。轮数上限内才允许，到顶直接拒绝（exit 1），逼迫放行而非无限打磨。"""
    state = load()
    kz = state.setdefault("kaizen", {"max_rounds": 2, "problems": {}})
    pkey = str(args.problem_n)
    prec = kz["problems"].setdefault(pkey, {"rounds_used": 0, "history": []})
    max_rounds = kz.get("max_rounds", 2)

    if prec["rounds_used"] >= max_rounds:
        print(f"[kaizen] ⚠ 问题 {args.problem_n} 已用满 {max_rounds} 轮打磨上限，"
              f"不得再开新一轮，请直接放行进入下一阶段。", file=sys.stderr)
        sys.exit(1)

    prec["rounds_used"] += 1
    prec.setdefault("rounds", []).append({
        "round": prec["rounds_used"], "started_at": now(), "plan": args.plan,
    })
    save(state)
    remaining = max_rounds - prec["rounds_used"]
    print(f"[kaizen] ↻ 问题 {args.problem_n} 第 {prec['rounds_used']} 轮打磨开始"
          f"（还剩 {remaining} 轮额度）")
    print(f"  计划：{args.plan}")
    print(f"  提醒：改进后仍必须重新走 §4 强制验证协议，verify 不通过不得写入论文。")
    worklog.log("Agent", f"Kaizen 第{prec['rounds_used']}轮打磨开始 问题{args.problem_n}：{args.plan}")


def cmd_kaizen_status(args):
    state = load()
    kz = state.get("kaizen", {})
    problems = kz.get("problems", {})
    target = str(args.problem_n) if args.problem_n else None

    if not problems or (target and target not in problems):
        print(f"[kaizen] 问题 {target or '(全部)'} 暂无 Kaizen 记录。")
        sys.exit(0)

    max_rounds = kz.get("max_rounds", 2)
    for pkey, prec in sorted(problems.items()):
        if target and pkey != target:
            continue
        print(f"问题 {pkey}：{prec['rounds_used']}/{max_rounds} 轮已用，"
              f"最近一次均分 {prec.get('last_avg', '—')}，裁定 {prec.get('last_decision', '—')}")
    sys.exit(0)


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

    round_n  = state["stages"][stage]["review_round"]
    summary  = _sanitize(args.summary)
    results  = _sanitize(args.results)
    concerns = _sanitize(args.concerns or "（无）")
    next_s   = _sanitize(args.next or "（待定）")
    report = f"""# Review Request — Round {round_n}

**阶段**: `{stage}`
**时间**: {now()}
**模式**: {state['mode']}
**状态**: AWAITING HUMAN APPROVAL

---

## 本阶段工作摘要

{summary}

---

## 关键结果 / 验证数据

{results}

---

## 问题与不确定点

{concerns}

---

## 拟进入的下一阶段

{next_s}

---

## 审查指引

请阅读上述报告，然后在 `state/human_intervention.md` 中填写：

- 同意继续 → `[APPROVED:{stage}:{round_n}]`
- 需要修改 → `[REWORK:{stage}:{round_n}]`，并在下方写明具体修改意见

填写完毕后，在终端输入「**继续**」并按 Enter 唤醒 AI。
"""
    REVIEW_REQ.write_text(report, encoding="utf-8")
    if state["mode"] == "AP":
        with HUMAN_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[APPROVED:{stage}:{round_n}]\n"
                         f"AI 自评：{summary}\n验证结果：{results}\n")

    # Append to eval log
    entry = (
        f"\n\n---\n\n## [{now()}] Review 请求 — {stage} (Round {round_n})\n\n"
        f"### 摘要\n{summary}\n\n"
        f"### 结果\n{results}\n"
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

    state = load()
    stage = args.stage or state.get("current_stage")
    if not stage or stage not in state["stages"]:
        print("PENDING"); return "PENDING"
    round_n = state["stages"][stage].get("review_round", 0)
    content = HUMAN_FILE.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(APPROVED|REWORK):{re.escape(stage)}:{round_n}\]")
    decisions = list(pattern.finditer(content))
    if not decisions:
        print("PENDING"); return "PENDING"
    latest = decisions[-1]
    if latest.group(1) == "APPROVED":
        print("APPROVED"); return "APPROVED"
    feedback = content[latest.end():].strip()
    print(f"REWORK\n{feedback}"); return "REWORK"


def cmd_advance(args):
    state = load()
    andon = state.get("andon", {})
    if andon.get("pulled"):
        sys.exit(f"[pipeline] 🔴 ANDON 已拉下，禁止 advance。原因：{andon.get('reason')}"
                 f"（拉绳者：{andon.get('pulled_by')}）。先处理问题并执行 andon-clear。")
    stage = args.stage
    if stage not in state["stages"]:
        sys.exit(f"[pipeline] 未知阶段: {stage}")

    if stage == "problem_analysis" and state.get("lean_formal", {}).get("enabled"):
        assessment = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "quality_gate.py"),
             "formal-assessment"], check=False)
        if assessment.returncode != 0:
            sys.exit("[pipeline] formal applicability assessment failed; refusing to leave problem_analysis")

    if stage == "latex_draft":
        launch = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "quality_gate.py"),
             "launch-check"], check=False)
        if launch.returncode != 0:
            sys.exit("[pipeline] launch-check failed; refusing to enter final_compile")

    # LeanGate gate is evaluated before any stage state is mutated. Exit 2 means the
    # optional addon is off/not applicable; exit 1 is a hard stop.
    match = re.match(r"^model_(\d+)_verify$", stage)
    if match and state.get("lean_formal", {}).get("enabled"):
        if not args.verify_script:
            sys.exit("[pipeline] LeanGate-enabled verify stage requires --verify-script so Python evidence is executed, not trusted as text")
        raw_verify_script = Path(args.verify_script)
        if not raw_verify_script.is_absolute():
            raw_verify_script = Path.cwd() / raw_verify_script
        current = Path(raw_verify_script.anchor)
        if any((current := current / part).is_symlink()
               for part in raw_verify_script.parts[1:]):
            sys.exit("[pipeline] --verify-script cannot contain symlink components")
        verify_script = raw_verify_script.resolve()
        verification_root = (WORKSPACE / "src" / "verifications").resolve()
        if verification_root not in verify_script.parents or not verify_script.is_file():
            sys.exit(f"[pipeline] --verify-script must be a regular file under {verification_root}")
        python_result = subprocess.run([sys.executable, str(verify_script)], text=True,
                                       capture_output=True, check=False)
        evidence = STATE_DIR / f"leangate_python_verify_{match.group(1)}.txt"
        evidence.write_text(python_result.stdout + python_result.stderr, encoding="utf-8")
        python_gate = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "quality_gate.py"),
             "verify", "--stage", stage, "--report-file", str(evidence)], check=False)
        if python_result.returncode != 0 or python_gate.returncode != 0:
            sys.exit(f"[pipeline] Python verification failed for {stage}; advance refused")
        gate = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "quality_gate.py"),
             "formal", "--problem-n", match.group(1)], check=False)
        if gate.returncode not in (0, 2):
            sys.exit(f"[pipeline] LeanGate formal gate failed for {stage}; advance refused")

    if state["stages"][stage].get("status") != "pending_review":
        sys.exit(f"[pipeline] {stage} 尚未处于 pending_review，禁止 advance")
    if cmd_check_approval(argparse.Namespace(stage=stage)) != "APPROVED":
        sys.exit(f"[pipeline] {stage} 当前轮次尚无人类批准，禁止 advance")

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
            worklog.log("Agent", f"{stage} → approved，推进至 {next_stage}")
        else:
            state["current_stage"] = "complete"
            print(f"[pipeline] ✓ {stage} → approved")
            print(f"[pipeline] 🏁 流水线全部完成！")
            worklog.log("Agent", f"{stage} → approved，流水线全部完成")
    save(state)

    # Clear APPROVED marker from human_intervention.md so it's ready for next round
    # Use count=1 to preserve history of earlier approvals
    if HUMAN_FILE.exists():
        content = HUMAN_FILE.read_text(encoding="utf-8")
        round_n = state["stages"][stage].get("review_round", 0)
        content = content.replace(f"[APPROVED:{stage}:{round_n}]",
                                  f"[APPROVED-CONSUMED:{stage}:{round_n} @ {now()}]", 1)
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

    current_round = state["stages"][stage].get("review_round", 0)
    max_reworks   = state.get("max_reworks", 5)
    if current_round >= max_reworks:
        print(f"[pipeline] ⚠ {stage} 已达返工上限 ({max_reworks} 次)。", file=sys.stderr)
        print(f"[pipeline]   请人工介入解决根本问题，或使用 --max-reworks 提高上限重新初始化。",
              file=sys.stderr)
        sys.exit(2)

    state["stages"][stage]["status"] = "rework"
    state["total_reworks"] = state.get("total_reworks", 0) + 1
    state["current_stage"] = stage
    state["blocked_at"] = None
    if stage == "problem_analysis" and state.get("lean_formal", {}).get("enabled"):
        state["lean_formal"]["assessment_sealed"] = False
        state["lean_formal"].pop("assessment_sealed_at", None)
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
    worklog.log("Agent", f"{stage} → rework（第{current_round + 1}次）"
                + (f"，意见：{args.feedback}" if args.feedback else ""))

    # Clear REWORK marker (count=1 preserves history)
    if HUMAN_FILE.exists():
        content = HUMAN_FILE.read_text(encoding="utf-8")
        round_n = state["stages"][stage].get("review_round", 0)
        content = content.replace(f"[REWORK:{stage}:{round_n}]",
                                  f"[REWORK-CONSUMED:{stage}:{round_n} @ {now()}]", 1)
        HUMAN_FILE.write_text(content, encoding="utf-8")

    # rework 起始标记提交
    if state.get("git_enabled") and _CGIT_AVAILABLE and _cgit.is_enabled():
        round_n = state["stages"][stage].get("review_round", 1) + 1
        _cgit.rework_start(stage, round_n)


def cmd_checkpoint_banner(args):
    stage = getattr(args, "stage", "unknown")
    try:
        round_n = load()["stages"][stage].get("review_round", 0)
    except (KeyError, SystemExit):
        round_n = 0
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
║     • 同意 → [APPROVED:{stage}:{round_n}]
║     • 修改 → [REWORK:{stage}:{round_n}] + 具体指令
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


def cmd_suggest_parallel(args):
    """
    根据当前流水线状态，输出下一批可并行启动的阶段名（空格分隔）。

    退出码 0 = 有可并行阶段，stdout 为阶段列表
    退出码 1 = 无可并行阶段（problem_count=1、条件未满足或全部已完成）

    AP 模式中用法：
      STAGES=$(python scripts/pipeline_manager.py suggest-parallel) && \\
        python scripts/pipeline_manager.py parallel-start $STAGES
    """
    state = load()
    n = state.get("problem_count", 1)

    if n <= 1:
        sys.exit(1)

    builds   = [f"model_{i}_build"  for i in range(1, n + 1)]
    verifies = [f"model_{i}_verify" for i in range(1, n + 1)]

    def st(stage):
        return state["stages"].get(stage, {}).get("status", "not_started")

    # 阶段一：data_preprocessing 完成，所有 build 尚未启动
    if st("data_preprocessing") == "approved" and all(st(s) == "not_started" for s in builds):
        print(" ".join(builds))
        sys.exit(0)

    # 阶段二：所有 build 完成，所有 verify 尚未启动
    if all(st(s) == "approved" for s in builds) and all(st(s) == "not_started" for s in verifies):
        print(" ".join(verifies))
        sys.exit(0)

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
    pi.add_argument("--problems",    type=int, default=1,
                    help="子问题数量，开启 AP 多 Agent 并行（默认 1）")
    pi.add_argument("--max-reworks", type=int, default=5, dest="max_reworks",
                    help="每阶段最大返工次数，超出后流水线暂停等待人工介入（默认 5）")
    pi.add_argument("--git",         action="store_true",
                    help="在 CUMCM_Workspace/ 下初始化竞赛 Git 仓库")
    pi.add_argument("--skunk-works", action="store_true", dest="skunk_works",
                    help="Project Skunk Works：轻量快速模式，见 AutoMCM_SOP.md §10")
    pi.add_argument("--kaizen-max-rounds", type=int, default=2, dest="kaizen_max_rounds",
                    help="Project Kaizen 每个子问题的最大打磨轮数，见 AutoMCM_SOP.md §13（默认 2）")
    pi.add_argument("--lean-policy", choices=["off", "selected", "required"], default="off",
                    dest="lean_policy", help="LeanGate policy（默认 off）")

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
    pav.add_argument("--verify-script", default="",
                     help="LeanGate 启用时，model_N_verify 阶段必须提供并实际执行的独立 Python 验证脚本")

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

    # suggest-parallel — AP 多 Agent 并行决策辅助
    sub.add_parser("suggest-parallel",
                   help="输出当前可并行启动的阶段名（AP 模式用）")

    # andon-pull / andon-clear / andon-status — Andon Cord 紧急停止信号
    pap = sub.add_parser("andon-pull", help="任意 Agent 拉下紧急停止信号，冻结流水线")
    pap.add_argument("--reason", required=True, help="发现的问题，一句话说清楚")
    pap.add_argument("--by", default="", help="拉绳的角色/Agent 名（如 Bletchley、Division-2）")

    pac = sub.add_parser("andon-clear", help="人工确认问题已处理，解除冻结")
    pac.add_argument("--resolution", required=True, help="怎么解决的，一句话说清楚")

    sub.add_parser("andon-status", help="查看当前 andon 状态，退出码 0=正常 1=已拉下")

    # kaizen-assess / kaizen-round-start / kaizen-status — Project Kaizen 质量打磨循环
    pka = sub.add_parser("kaizen-assess", help="记录一次质量自评，退出码 0=放行 1=建议打磨")
    pka.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pka.add_argument("--significance", type=int, required=True, help="结果显著性/说服力，1-5")
    pka.add_argument("--robustness", type=int, required=True, help="灵敏度稳健性，1-5")
    pka.add_argument("--assumptions", type=int, required=True, help="假设合理性，1-5")
    pka.add_argument("--completeness", type=int, required=True, help="论证完整性，1-5")
    pka.add_argument("--weakest", required=True, help="最弱维度的一句话说明")

    pkr = sub.add_parser("kaizen-round-start", help="登记开始一轮打磨，到轮数上限则拒绝")
    pkr.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pkr.add_argument("--plan", required=True, help="这一轮打算改进什么")

    pks = sub.add_parser("kaizen-status", help="查看 Kaizen 打磨轮数与自评记录")
    pks.add_argument("--problem-n", type=int, default=None, dest="problem_n")

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
        "suggest-parallel":   cmd_suggest_parallel,
        "contest-git":        cmd_contest_git,
        "andon-pull":         cmd_andon_pull,
        "andon-clear":        cmd_andon_clear,
        "andon-status":       cmd_andon_status,
        "kaizen-assess":      cmd_kaizen_assess,
        "kaizen-round-start": cmd_kaizen_round_start,
        "kaizen-status":      cmd_kaizen_status,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
