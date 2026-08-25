#!/usr/bin/env python3
"""
quality_gate.py — 建模质量门控脚本

在 pipeline_manager.py advance 之前调用，强制执行质量检查（门控 1~4 为主流水线
基础门控；门控 5~7 是 Los Alamos 探索层的可选 addon，仅在该模式启用时调用）。
退出码：
  0 = 全部通过，可以 advance
  1 = 有门控失败，禁止 advance
  2 = 跳过（门控不适用当前阶段）

用法（由 Agent 调用，用户无需直接使用）：
  python scripts/quality_gate.py verify   --stage model_1_verify --report-file REPORT_PATH
  python scripts/quality_gate.py sanity   --stage model_1_build  --output-file OUTPUT_PATH
  python scripts/quality_gate.py lit      --stage model_1_build  --problem-n 1
  python scripts/quality_gate.py consist  --problems 3
  python scripts/quality_gate.py all      --stage model_1_verify --report-file REPORT_PATH

  # Los Alamos 探索层专用（门控 5/6/7，见 scripts/los_alamos/）：
  python scripts/quality_gate.py message  --problem-n 1
  python scripts/quality_gate.py ledger   --problem-n 1
  python scripts/quality_gate.py red-team --problem-n 1 --node-id N-P1-014
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worklog  # noqa: E402

WORKSPACE      = Path("CUMCM_Workspace")
THOUGHT_FILE   = WORKSPACE / "memory" / "thought_process.md"

# Los Alamos addon（可选）：仅在调用 message/ledger/red-team 门控时才需要，
# 不影响原有四个门控在没有 los_alamos/ 时也能正常工作。
sys.path.insert(0, str(Path(__file__).resolve().parent / "los_alamos"))


# ── 门控 1：验证报告解析 ─────────────────────────────────────────────────────

def gate_verify_report(report_file: str) -> tuple[bool, str]:
    """
    解析 verify_*.py 输出的结构化报告，提取 Result: PASS|FAIL。
    返回 (passed, message)。
    """
    path = Path(report_file)
    if not path.exists():
        return False, f"验证报告文件不存在: {path}"

    text = path.read_text(encoding="utf-8", errors="replace")

    # 查找结构化报告块
    report_block = re.search(
        r"={5,}\s*VERIFICATION REPORT\s*={5,}(.*?)={5,}",
        text, re.DOTALL | re.IGNORECASE
    )
    if not report_block:
        return False, (
            "验证报告格式不符合规范：未找到 '===VERIFICATION REPORT===' 块。\n"
            "verify_*.py 末尾必须打印结构化报告，格式见 auto-mcm/SKILL.md § 【建模质量门控】门控 3。"
        )

    block = report_block.group(1)

    result_match = re.search(r"Result\s*:\s*(PASS|FAIL)", block, re.IGNORECASE)
    if not result_match:
        return False, "验证报告中未找到 'Result : PASS' 或 'Result : FAIL' 行。"

    result = result_match.group(1).upper()
    if result == "FAIL":
        # 提取失败的检查项
        fail_items = re.findall(r"✗\s+(.+)", block)
        detail = "\n  ".join(fail_items) if fail_items else "（见报告详情）"
        return False, f"验证结果 FAIL。失败项：\n  {detail}"

    return True, "验证结果 PASS ✓"


# ── 门控 2：数值合理性检查 ────────────────────────────────────────────────────

_BAD_PATTERNS = [
    (re.compile(r'\binf\b', re.IGNORECASE),   "输出包含 inf"),
    (re.compile(r'\bnan\b', re.IGNORECASE),   "输出包含 nan"),
    (re.compile(r'1\.?\d*[eE][+]?[23][0-9]{2,}'), "数值量级异常（≥1e200）"),
    (re.compile(r'-1\.?\d*[eE][+]?[23][0-9]{2,}'), "负数量级异常（≤-1e200）"),
]

def gate_numerical_sanity(output_file: str) -> tuple[bool, str]:
    """
    扫描模型脚本的标准输出文件，检测 inf/nan 和极端量级。
    output_file: 运行模型脚本时重定向的 stdout 文件，由 Agent 提供。
    """
    path = Path(output_file)
    if not path.exists():
        return True, "输出文件不存在，跳过数值检查（如已在终端输出，请手工确认无 inf/nan）"

    text = path.read_text(encoding="utf-8", errors="replace")
    issues = []
    for pat, desc in _BAD_PATTERNS:
        matches = pat.findall(text)
        if matches:
            issues.append(f"{desc}（出现 {len(matches)} 次）")

    if issues:
        return False, "数值合理性检查失败：\n  " + "\n  ".join(issues)
    return True, "数值合理性检查通过 ✓"


# ── 门控 3：文献引用计数 ──────────────────────────────────────────────────────

def _count_verified_citations(problem_n: int) -> int:
    """读 citations.bib，统计标记为 problem{N} 且 verified=verified 的条目数
    （真实性已用 cite_check.py verify 核验过，不是仅格式匹配）。文件不存在或
    解析失败一律按 0 处理，不影响下方 thought_process.md 的回退检查。"""
    try:
        import cite_check
        entries = cite_check._load_entries()
    except Exception:
        return 0
    tag = f"problem{problem_n}"
    return sum(
        1 for e in entries.values()
        if tag in (e.get("note") or "") and e.get("verified") == "verified"
    )


def gate_literature(problem_n: int) -> tuple[bool, str]:
    """
    检查文献引用数量（≥2，Skunk Works ≥1）。优先信任 citations.bib 里已经用
    cite_check.py verify 核验过真实性的条目（AutoMCM_SOP.md §15）；如果还没有
    迁移到 cite_check.py，回退到 thought_process.md 里的格式匹配（DOI/arxiv/
    URL/角标），但只是"形状像引用"，没有核验过是不是真的存在——两条路径都够
    数才算合格时优先用真实性有保障的那一条，格式匹配不够时才提示迁移。
    """
    required = 1 if _is_skunk_works() else 2
    verified_count = _count_verified_citations(problem_n)
    if verified_count >= required:
        return True, (f"文献引用检查通过 ✓（citations.bib 已验证 {verified_count} 条真实文献，"
                       f"要求 ≥{required}）")

    if not THOUGHT_FILE.exists():
        return False, f"thought_process.md 不存在，无法验证文献引用。"

    text = THOUGHT_FILE.read_text(encoding="utf-8", errors="replace")

    # 找到问题 N 对应的段落（宽松匹配）
    section_pattern = re.compile(
        rf"问题\s*{problem_n}|problem\s*{problem_n}|sub[- ]?problem\s*{problem_n}",
        re.IGNORECASE
    )
    lines = text.splitlines()
    relevant_lines = []
    in_section = False
    for line in lines:
        if section_pattern.search(line):
            in_section = True
        elif re.match(r'^#{1,3}\s', line) and in_section:
            break   # 遇到下一个标题，停止
        if in_section:
            relevant_lines.append(line)

    section_text = "\n".join(relevant_lines) if relevant_lines else text

    # 计算文献引用数
    ref_patterns = [
        re.compile(r'doi\.org/\S+', re.IGNORECASE),
        re.compile(r'\bdoi\s*:\s*10\.\d{4}', re.IGNORECASE),
        re.compile(r'arxiv\.org/\S+', re.IGNORECASE),
        re.compile(r'https?://[^\s\)]{15,}'),  # 一般 URL
        re.compile(r'\[\d+\]'),                 # 文献角标 [1], [2] ...
    ]
    found = set()
    for pat in ref_patterns:
        found.update(pat.findall(section_text))

    count = len(found)
    if count < required:
        return False, (
            f"问题 {problem_n} 引用不足：citations.bib 已验证 {verified_count} 条、"
            f"thought_process.md 格式匹配 {count} 处（要求 ≥{required}"
            f"{'，Skunk Works 模式已放宽' if required == 1 else ''}）。\n"
            "请用 scripts/cite_check.py register 补充真实文献并 verify 核验，"
            "或至少在 thought_process.md 中补充 DOI/URL。"
        )
    return True, (
        f"文献引用检查通过 ✓（thought_process.md 找到 {count} 处引用格式，要求 ≥{required}，"
        f"但未做真实性核验——建议改用 scripts/cite_check.py register/verify，见 AutoMCM_SOP.md §15）"
    )


def _is_skunk_works() -> bool:
    """读 pipeline.json 的 skunk_works 标志。文件不存在/字段缺失一律按 False 处理，
    不影响默认（Project Apollo）行为，见 AutoMCM_SOP.md §10。"""
    pipeline_file = WORKSPACE / "state" / "pipeline.json"
    if not pipeline_file.exists():
        return False
    try:
        return bool(json.loads(pipeline_file.read_text(encoding="utf-8")).get("skunk_works", False))
    except json.JSONDecodeError:
        return False


# ── 门控 4：多问题一致性 ──────────────────────────────────────────────────────

_CONST_PATTERN = re.compile(
    r'(?:g|gravity|rho|density|air_density|mu|viscosity)\s*=\s*([0-9.eE+\-]+)',
    re.IGNORECASE
)

def gate_consistency(problem_count: int) -> tuple[bool, str]:
    """
    检查各子问题模型代码中的物理常数是否一致。
    扫描 src/models/ 下所有 problem*.py。
    """
    models_dir = WORKSPACE / "src" / "models"
    if not models_dir.exists():
        return True, "models/ 目录不存在，跳过一致性检查"

    const_map: dict[str, dict[str, str]] = {}  # {const_name: {file: value}}
    for py_file in sorted(models_dir.glob("problem*.py")):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for m in _CONST_PATTERN.finditer(text):
            name = m.group(0).split("=")[0].strip().lower()
            value = m.group(1)
            const_map.setdefault(name, {})[py_file.name] = value

    conflicts = []
    for name, file_vals in const_map.items():
        unique_vals = set(file_vals.values())
        if len(unique_vals) > 1:
            detail = ", ".join(f"{f}={v}" for f, v in file_vals.items())
            conflicts.append(f"  {name}: {detail}")

    if conflicts:
        return False, (
            "多问题一致性检查失败，以下物理常数在不同子问题中取值不同：\n"
            + "\n".join(conflicts)
            + "\n请统一后重新运行。"
        )
    return True, f"多问题一致性检查通过 ✓（扫描 {len(const_map)} 个物理常数）"


# ── 门控 8a：匿名性检查（AutoMCM_SOP.md §17，2026 格式规范第六条）─────────────

_ANON_LEAK_PATTERNS = [
    (re.compile(r'我校|本校|我们学校'), '自指性校名词（"我校"/"本校"/"我们学校"）'),
    (re.compile(r'参赛队号|参赛证号|报名序号'), '参赛编号相关字样'),
    (re.compile(r'指导老师|指导教师'), '"指导老师/指导教师"字样'),
    (re.compile(r'本队队员|我队队员'), '"本队队员/我队队员"字样'),
]


def gate_anon_check() -> tuple[bool, str]:
    """
    启发式扫描论文正文有没有暴露参赛者身份/学校信息（规范第六条：论文摘要页、
    正文和附录任何地方不能有显示参赛者身份和所在学校及赛区的信息）。

    这是关键词匹配，不是语义理解——能抓到"我校""指导老师"这类自指性/标签性
    强信号，抓不到"XX大学"这种需要维护全量校名清单才能覆盖的情形，也不代表
    过了这个检查就一定合规，仍需要人工复查一遍。
    """
    latex_dir = WORKSPACE / "latex"
    tex_files = list(latex_dir.glob("*.tex")) if latex_dir.exists() else []
    if not tex_files:
        return True, "未找到 .tex 文件，跳过匿名性检查"

    hits = []
    for tf in tex_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        for pat, desc in _ANON_LEAK_PATTERNS:
            for m in pat.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                hits.append(f"{tf.name}:{line_no} {desc}")

    if hits:
        return False, (
            "疑似暴露参赛者身份/学校信息：\n    " + "\n    ".join(hits[:10])
            + "\n请检查并删除这类自指性表述——数学建模国赛要求匿名评审。"
        )
    return True, "匿名性检查通过 ✓（未发现常见的自指性身份/校名字样，仍建议人工复查一遍）"


# ── 门控 8：Go/No-Go 发射前检查（NASA Mission Control 式，final_compile 前用）──

_LATEX_IMAGE_PATTERN = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}')
_PLACEHOLDER_PATTERN = re.compile(
    r'\bTODO\b|\bFIXME\b|\bXXX\b|\\missingfigure|占位|待补充|待填写', re.IGNORECASE
)


def gate_launch_check() -> tuple[bool, str]:
    """
    模拟 NASA Mission Control 的 go/no-go poll：每个"分系统"独立回报，
    Flight Director（本函数）逐一点名，全部 go 才允许进入 final_compile。
    不是重新做验证，是复核"该做的事有没有真的做完"，抓遗漏而不是抓新错误。
    """
    polls: list[tuple[str, bool, str]] = []  # (subsystem, go, detail)

    # 分系统 1：Andon —— 有没有未解决的紧急停止
    pipeline_file = WORKSPACE / "state" / "pipeline.json"
    state = {}
    if pipeline_file.exists():
        try:
            state = json.loads(pipeline_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            polls.append(("Andon", False, "pipeline.json 解析失败，无法确认 andon 状态"))
    andon = state.get("andon", {})
    if andon.get("pulled"):
        polls.append(("Andon", False, f"andon 仍处于拉下状态：{andon.get('reason')}"))
    elif state:
        polls.append(("Andon", True, "无未解决的紧急停止"))

    # 分系统 2：阶段完整性 —— model_build/verify 是否全部 approved（不含 skipped）
    # 注意：pipeline.json 的 stages 固定预置 model_1~model_3，不论 problem_count；
    # 只检查实际题目数范围内的 model_N（N <= problem_count），否则单/双问题竞赛
    # 会被 model_2/model_3 这类根本不会被 advance 到的阶段永久判 NO-GO。
    problem_count = int(state.get("problem_count", 1))
    stages = state.get("stages", {})
    _model_re = re.compile(r"^model_(\d+)_")
    unfinished = [
        name for name, info in stages.items()
        if (m := _model_re.match(name)) and int(m.group(1)) <= problem_count
        and info.get("status") not in ("approved", "skipped")
    ]
    if state:
        if unfinished:
            polls.append(("阶段完整性", False, f"以下阶段未 approved: {', '.join(unfinished)}"))
        else:
            polls.append(("阶段完整性", True, "所有 model_*_build/verify 均已 approved"))

    # 分系统 3：图片完整性 —— main.tex 引用的图片是否物理存在
    latex_dir = WORKSPACE / "latex"
    tex_files = list(latex_dir.glob("*.tex")) if latex_dir.exists() else []
    missing_images = []
    for tf in tex_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        for ref in _LATEX_IMAGE_PATTERN.findall(text):
            candidates = [latex_dir / ref, latex_dir / f"{ref}.png", latex_dir / f"{ref}.pdf"]
            if not any(c.exists() for c in candidates):
                missing_images.append(f"{tf.name}: {ref}")
    if tex_files:
        if missing_images:
            polls.append(("图片完整性", False, "以下引用的图片文件不存在：\n    " + "\n    ".join(missing_images)))
        else:
            polls.append(("图片完整性", True, f"扫描 {len(tex_files)} 个 .tex 文件，引用图片全部存在"))

    # 分系统 4：占位符残留 —— TODO/FIXME/missingfigure/占位 等字样
    placeholder_hits = []
    for tf in tex_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        for m in _PLACEHOLDER_PATTERN.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            placeholder_hits.append(f"{tf.name}:{line_no} '{m.group(0)}'")
    if tex_files:
        if placeholder_hits:
            polls.append(("占位符残留", False, "发现残留占位标记：\n    " + "\n    ".join(placeholder_hits[:10])))
        else:
            polls.append(("占位符残留", True, "未发现 TODO/FIXME/占位标记"))

    # 分系统 4b：匿名性（国赛格式规范第六条，见 AutoMCM_SOP.md §17）
    if tex_files:
        anon_ok, anon_msg = gate_anon_check()
        polls.append(("匿名性", anon_ok, anon_msg))

    # 分系统 5：假设 ledger（若存在 Los Alamos 探索层产物才检查，逐个 problem_n 复核）
    ledger_dir = WORKSPACE / "memory" / "ledgers"
    if ledger_dir.exists() and any(ledger_dir.iterdir()):
        problem_ns = sorted({
            int(m.group(1)) for f in ledger_dir.glob("problem*_*.json")
            if (m := re.match(r"problem(\d+)_", f.name))
        })
        ledger_msgs = []
        ledger_all_ok = True
        for n in problem_ns:
            ok, msg = gate_ledger(n)
            ledger_all_ok = ledger_all_ok and ok
            ledger_msgs.append(f"[problem {n}] {msg}")
        if problem_ns:
            polls.append(("假设 Ledger（Los Alamos）", ledger_all_ok, "\n    ".join(ledger_msgs)))

    if not polls:
        return False, "未找到 pipeline.json 或工作区为空，无法执行发射前检查"

    lines = ["", "╔══════════════════ GO/NO-GO POLL ══════════════════╗"]
    all_go = True
    for name, go, detail in polls:
        status = "🟢 GO   " if go else "🔴 NO-GO"
        lines.append(f"║ {status}  {name}")
        if not go:
            all_go = False
            for dl in detail.split("\n"):
                lines.append(f"║          {dl}")
    lines.append("╚═════════════════════════════════════════════════════╝")
    lines.append(f"最终裁定：{'🟢 GO —— 可以进入 final_compile' if all_go else '🔴 NO-GO —— 修复上述 NO-GO 项后重跑'}")

    return all_go, "\n".join(lines)


# ── 门控 5/6/7：Los Alamos 探索层专用（可选 addon，见 scripts/los_alamos/）───────

def gate_message(problem_n: int) -> tuple[bool, str]:
    """校验 messages.jsonl 报文格式（门控 5，LOS_ALAMOS_DESIGN.md §7.3）。"""
    import bus
    ok, report = bus.validate_file(problem_n)
    return ok, "\n  ".join(report)


def gate_ledger(problem_n: int) -> tuple[bool, str]:
    """
    假设 ledger DAG 校验（门控 6，LOS_ALAMOS_DESIGN.md §9.2）：
    悬空 depends_on 引用、依赖环、literature 来源的 citation_id 是否真实存在。
    孤儿假设（downstream_impact 为空）只报告不算失败——这是 Groves 的监控范畴，
    不是硬性门控（探索本身有正当性，见 DESIGN §5.3）。
    """
    ledger_dir = WORKSPACE / "memory" / "ledgers"
    files = sorted(ledger_dir.glob(f"problem{problem_n}_*.json")) if ledger_dir.exists() else []
    if not files:
        return True, f"未找到问题 {problem_n} 的假设 ledger 文件，跳过 DAG 校验"

    entries: dict[str, dict] = {}
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, f"ledger 文件解析失败: {f.name}: {e}"
        if isinstance(data, dict):
            data = [data]
        for e in data:
            if "id" not in e:
                return False, f"{f.name} 中存在缺少 'id' 字段的假设条目"
            entries[e["id"]] = e

    problems: list[str] = []

    for aid, e in entries.items():
        for dep in e.get("depends_on", []):
            if dep not in entries:
                problems.append(f"假设 {aid} 的 depends_on 引用了不存在的 {dep}")

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {aid: WHITE for aid in entries}

    def has_cycle(aid, stack):
        color[aid] = GRAY
        for dep in entries[aid].get("depends_on", []):
            if dep not in entries:
                continue
            if color[dep] == GRAY:
                return True, stack + [dep]
            if color[dep] == WHITE:
                found, path = has_cycle(dep, stack + [dep])
                if found:
                    return True, path
        color[aid] = BLACK
        return False, []

    for aid in list(entries):
        if color[aid] == WHITE:
            found, path = has_cycle(aid, [aid])
            if found:
                problems.append(f"检测到假设依赖环: {' → '.join(path)}")

    pool_path = WORKSPACE / "memory" / f"paradigm_pool_{problem_n}.json"
    pool_available = pool_path.exists()
    pool_ids: set = set()
    if pool_available:
        try:
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool_ids = {p.get("paradigm_id") for p in pool} if isinstance(pool, list) else set()
        except json.JSONDecodeError:
            pool_available = False

    orphans = []
    for aid, e in entries.items():
        if e.get("source") == "literature":
            cid = e.get("citation_id")
            if not cid:
                problems.append(f"假设 {aid} source=literature 但缺少 citation_id")
            elif pool_available and cid not in pool_ids:
                problems.append(
                    f"假设 {aid} 的 citation_id={cid} 在 paradigm_pool_{problem_n}.json "
                    f"中不存在（疑似编造文献依据）"
                )
        if not e.get("downstream_impact"):
            orphans.append(aid)

    if problems:
        return False, "假设 ledger 校验失败：\n  " + "\n  ".join(problems)

    msg = f"假设 ledger 校验通过 ✓（{len(entries)} 条假设，来自 {len(files)} 个文件）"
    if orphans:
        msg += f"\n  ⚠ 孤儿假设（downstream_impact 为空，仅供参考不算失败）: {', '.join(orphans)}"
    if not pool_available:
        msg += f"\n  ⚠ 未找到 paradigm_pool_{problem_n}.json，literature 来源的 citation_id 未做存在性核验"
    return True, msg


def gate_red_team(problem_n: int, node_id: str) -> tuple[bool, str]:
    """
    Los Alamos 模式黄金律（门控 7，LOS_ALAMOS_DESIGN.md §8.2）：
    候选节点必须有 verdict ∈ {survived, weakened} 的 RED_TEAM_REPORT 才能进入决赛圈。
    """
    import adjudicate as la_adjudicate
    verdict = la_adjudicate.red_team_verdict(problem_n, node_id)
    if verdict is None:
        return False, f"节点 {node_id} 未找到 RED_TEAM_REPORT 记录，Los Alamos 模式下不得进入决赛圈"
    if verdict == "broken":
        return False, f"节点 {node_id} 红队裁定为 broken，需修复后重新红队复核"
    return True, f"节点 {node_id} 红队裁定为 {verdict}，可进入决赛圈 ✓"


# ── 综合入口 ─────────────────────────────────────────────────────────────────

def run_gate(name: str, args) -> bool:
    """运行单个门控，打印结果，返回是否通过。"""
    if name == "verify":
        passed, msg = gate_verify_report(args.report_file)
    elif name == "sanity":
        passed, msg = gate_numerical_sanity(args.output_file)
    elif name == "lit":
        passed, msg = gate_literature(args.problem_n)
    elif name == "consist":
        passed, msg = gate_consistency(args.problems)
    elif name == "message":
        passed, msg = gate_message(args.problem_n)
    elif name == "ledger":
        passed, msg = gate_ledger(args.problem_n)
    elif name == "red-team":
        passed, msg = gate_red_team(args.problem_n, args.node_id)
    elif name == "launch-check":
        passed, msg = gate_launch_check()
    elif name == "anon-check":
        passed, msg = gate_anon_check()
    else:
        return True

    prefix = "✓ GATE" if passed else "✗ GATE"
    print(f"{prefix} [{name}] {msg}")
    worklog.log("门控", f"{'PASS' if passed else 'FAIL'} [{name}] " + msg.splitlines()[0])
    return passed


def main():
    p = argparse.ArgumentParser(
        description="AutoMCM-Pro 建模质量门控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="gate")

    # verify
    pv = sub.add_parser("verify", help="解析结构化验证报告（门控 3）")
    pv.add_argument("--stage",       required=True)
    pv.add_argument("--report-file", required=True,
                    help="包含 VERIFICATION REPORT 块的文件路径（通常是 verify_*.py 的输出）")

    # sanity
    ps = sub.add_parser("sanity", help="数值合理性检查（门控 2）")
    ps.add_argument("--stage",       required=True)
    ps.add_argument("--output-file", required=True,
                    help="模型脚本 stdout 重定向的文件路径")

    # lit
    pl = sub.add_parser("lit", help="文献引用数量检查（门控 1）")
    pl.add_argument("--stage",    required=True)
    pl.add_argument("--problem-n", type=int, required=True, dest="problem_n",
                    help="子问题编号（1, 2, 3 …）")

    # consist
    pc = sub.add_parser("consist", help="多问题物理常数一致性检查（门控 4）")
    pc.add_argument("--problems", type=int, required=True,
                    help="子问题总数")

    # message（Los Alamos 探索层 addon）
    pmsg = sub.add_parser("message", help="报文格式校验（门控 5，Los Alamos 探索层）")
    pmsg.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    # ledger（Los Alamos 探索层 addon）
    pled = sub.add_parser("ledger", help="假设 ledger DAG 校验（门控 6，Los Alamos 探索层）")
    pled.add_argument("--problem-n", type=int, required=True, dest="problem_n")

    # red-team（Los Alamos 探索层 addon）
    pred = sub.add_parser("red-team", help="红队复核校验（门控 7，Los Alamos 探索层）")
    pred.add_argument("--problem-n", type=int, required=True, dest="problem_n")
    pred.add_argument("--node-id", required=True, dest="node_id")

    # launch-check（门控 8，NASA Mission Control 式 Go/No-Go，final_compile 前用）
    sub.add_parser("launch-check", help="发射前总检查（门控 8）：Andon/阶段完整性/图片/占位符/匿名性/ledger")
    sub.add_parser("anon-check", help="匿名性启发式检查（门控 8a，国赛格式规范第六条）")

    # all（一次运行所有适用门控）
    pa = sub.add_parser("all", help="运行所有适用门控")
    pa.add_argument("--stage",       required=True)
    pa.add_argument("--report-file", default="",
                    help="verify 报告文件（verify 阶段必须）")
    pa.add_argument("--output-file", default="",
                    help="模型输出文件（build 阶段可选）")
    pa.add_argument("--problem-n",   type=int, default=0, dest="problem_n")
    pa.add_argument("--problems",    type=int, default=1)

    args = p.parse_args()

    if args.gate in ("verify", "sanity", "lit", "consist", "message", "ledger", "red-team",
                     "launch-check", "anon-check"):
        passed = run_gate(args.gate, args)
        sys.exit(0 if passed else 1)

    elif args.gate == "all":
        results = []
        stage = args.stage

        if "_verify" in stage and args.report_file:
            results.append(run_gate("verify", args))
        if "_build" in stage and args.output_file:
            results.append(run_gate("sanity", args))
        if args.problem_n > 0:
            results.append(run_gate("lit", args))
        if args.problems > 1 and "_verify" in stage:
            results.append(run_gate("consist", args))

        if not results:
            print("[quality_gate] 当前阶段无适用门控，跳过。")
            sys.exit(2)

        all_passed = all(results)
        print(f"\n{'✓ 全部门控通过' if all_passed else '✗ 有门控未通过，禁止 advance'}")
        sys.exit(0 if all_passed else 1)

    else:
        p.print_help()


if __name__ == "__main__":
    main()
