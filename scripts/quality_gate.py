#!/usr/bin/env python3
"""
quality_gate.py — 建模质量门控脚本

在 pipeline_manager.py advance 之前调用，强制执行五层质量检查。
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
"""

import argparse
import re
import sys
from pathlib import Path

WORKSPACE      = Path("CUMCM_Workspace")
THOUGHT_FILE   = WORKSPACE / "memory" / "thought_process.md"


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

def gate_literature(problem_n: int) -> tuple[bool, str]:
    """
    检查 thought_process.md 中与 problem_n 相关的文献引用数量（≥2）。
    通过扫描 DOI、arxiv、doi.org、http(s) 链接等判断。
    """
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
    if count < 2:
        return False, (
            f"问题 {problem_n} 在 thought_process.md 中只找到 {count} 处文献引用（要求 ≥2）。\n"
            "请补充学术文献支撑（含 DOI 或 URL）后再开始编码。"
        )
    return True, f"文献引用检查通过 ✓（找到 {count} 处引用）"


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
    else:
        return True

    prefix = "✓ GATE" if passed else "✗ GATE"
    print(f"{prefix} [{name}] {msg}")
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

    if args.gate in ("verify", "sanity", "lit", "consist"):
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
