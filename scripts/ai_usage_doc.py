#!/usr/bin/env python3
"""
ai_usage_doc.py — 生成《全国大学生数学建模竞赛人工智能工具使用规定（2025年试行）》
要求的支撑材料文档（AutoMCM_SOP.md §17）。

官方规定要求的支撑材料文件（PDF，文件名固定为"AI工具使用详情"）须包含：
  1. 所用 AI 工具名称和版本
  2. 具体使用目的和环节
  3. 关键交互记录
  4. 采纳和人工修改情况

本脚本从 worklog.md（AutoMCM_SOP.md §14，已完整记录全程用户消息/Agent 决策/
门控结果）取材生成前三项；第四项（人工修改情况）如实陈述当前流水线模式
（AP/MANUAL）下人工介入的真实程度，不夸大人工参与，也不隐瞒 AI 自主程度。

**参考文献里的 AI 工具引用条目，按用户明确要求默认不自动插入论文**——
`cite-format` 子命令只打印格式化后的单行文本，需要显式决定要不要手动粘贴进
`main.tex` 的 `thebibliography`，不像 `cite_check.py export-bibitems` 那样是
latex_draft 阶段的常规自动步骤。

子命令：
  generate      生成《AI工具使用详情》PDF（含四项必需内容）
  cite-format   打印按官方格式排版的单行 AI 工具引用文本（不自动插入任何文件）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

WORKSPACE = Path("CUMCM_Workspace")
WORKLOG = WORKSPACE / "memory" / "worklog.md"
PIPELINE = WORKSPACE / "state" / "pipeline.json"
OUT_DIR = WORKSPACE / "output"

_STAGE_LABELS = [
    ("problem_analysis", "问题分析/文献调研"),
    ("data_preprocessing", "数据预处理"),
    ("model_", "建模与验证（model_* 各阶段）"),
    ("sensitivity_analysis", "灵敏度分析"),
    ("latex_draft", "论文写作"),
    ("final_compile", "最终编译"),
]


def _load_worklog_lines() -> list[str]:
    if not WORKLOG.exists():
        return []
    return [l for l in WORKLOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_pipeline_state() -> dict:
    if not PIPELINE.exists():
        return {}
    try:
        return json.loads(PIPELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _tex_escape(s: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}")):
        s = s.replace(a, b)
    return s


def _render_interaction_records(lines: list[str], max_n: int) -> list[str]:
    """从 worklog 里挑关键交互记录：全部用户消息 + 阶段推进/裁决类 Agent 记录，
    跳过门控的逐条 PASS/FAIL（太琐碎，篇幅不允许），最多取 max_n 条。"""
    picked = []
    for line in lines:
        if "[用户]" in line or "推进至" in line or "裁决" in line or "Kaizen" in line \
                or "Andon" in line or "触发" in line:
            picked.append(line)
    return picked[:max_n]


def cmd_generate(args):
    lines = _load_worklog_lines()
    state = _load_pipeline_state()
    mode = state.get("mode", "未知")
    problem_count = state.get("problem_count", "未知")

    if not lines:
        print("[ai-usage-doc] ⚠ worklog.md 为空或不存在，生成的文档内容会很单薄，"
              "建议先确认工作日志（AutoMCM_SOP.md §14）功能有正常运作", file=sys.stderr)

    # 2. 使用目的与环节——按 worklog 出现过的阶段关键词归类
    stage_summary = []
    for keyword, label in _STAGE_LABELS:
        if any(keyword in l for l in lines):
            stage_summary.append(label)

    # 3. 关键交互记录
    records = _render_interaction_records(lines, args.max_records)

    # 4. 人工修改情况——如实陈述，不夸大也不隐瞒
    if mode.upper() == "MANUAL":
        human_note = (
            "本次流水线为 MANUAL 模式：每个阶段的 Checkpoint 均等待人工审查后"
            "填写 [APPROVED] 或 [REWORK] 才能推进，人工对每一阶段产出有实质审核；"
            "具体审查意见见 human_intervention.md。"
        )
    else:
        andon = state.get("andon", {})
        andon_note = "过程中有人工/系统拉下 Andon 紧急停止" if andon.get("cleared_at") else "过程中无人工中途介入（Andon 未被拉下）"
        human_note = (
            f"本次流水线为 AP（AI 主导）模式：AI 在各 Checkpoint 自评自批、自动推进，"
            f"人工的实质介入仅限于任务发起时的初始参数配置（题目、竞赛类型、模式选择）；"
            f"{andon_note}。凡触发 Los Alamos 探索层两轨冲突（Checkpoint LA）等按规则"
            f"必须真人终审的环节，如实执行情况见 worklog.md 与 human_intervention.md 原始记录，"
            f"不做美化。"
        )

    date_str = args.date or date.today().isoformat()

    md = f"""# AI 工具使用详情

## 一、所用 AI 工具名称和版本

- 工具名称：{args.tool_name}
- 版本/型号：{args.tool_version}
- 开发机构/公司：{args.org}
- 使用日期：{date_str}

## 二、具体使用目的和环节

本次任务为 CUMCM（全国大学生数学建模竞赛）建模全流程，AI 工具参与的环节包括：

{chr(10).join(f"- {s}" for s in stage_summary) if stage_summary else "（worklog.md 无阶段记录，无法归纳）"}

流水线模式：{mode}；子问题数：{problem_count}。

## 三、关键交互记录

以下摘自 `CUMCM_Workspace/memory/worklog.md`（完整记录见该文件原文，此处摘录
用户消息与关键决策/推进节点，门控逐条 PASS/FAIL 明细从略）：

```
{chr(10).join(records) if records else "（无记录）"}
```

## 四、采纳和人工修改情况

{human_note}

---

*本文档由 `scripts/ai_usage_doc.py` 根据 `worklog.md` 自动生成，
依据《全国大学生数学建模竞赛人工智能工具使用规定（2025年试行）》第七条要求。*
"""

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / "AI工具使用详情.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[ai-usage-doc] ✓ Markdown 已生成: {md_path}")

    if args.no_pdf:
        return

    tex_path = OUT_DIR / "_ai_usage_doc_tmp.tex"
    tex_body = "\n\n".join(
        "\\section*{" + _tex_escape(sec.split("\n")[0].lstrip("# ")) + "}\n" +
        "\n\n".join(_tex_escape(p) if not p.startswith("```") else ""
                     for p in sec.split("\n")[1:] if p.strip() and not p.startswith("```"))
        for sec in md.split("\n## ")
    )
    tex = (
        "\\documentclass[12pt,a4paper]{article}\n"
        "\\usepackage[fontset=none]{ctex}\n"
        "\\setCJKmainfont{Droid Sans Fallback}\n"
        "\\setCJKsansfont{Droid Sans Fallback}\n"
        "\\setCJKmonofont{Droid Sans Fallback}\n"
        "\\usepackage[margin=2.5cm]{geometry}\n"
        "\\usepackage{verbatim}\n"
        "\\title{AI \\textzh{工具使用详情}}\n\\date{}\n\\author{}\n"
        "\\begin{document}\n\\maketitle\n"
        + tex_body +
        "\n\\end{document}\n"
    )
    tex_path.write_text(tex, encoding="utf-8")
    result = subprocess.run(
        ["xelatex", "-interaction=nonstopmode", "-output-directory", str(OUT_DIR), str(tex_path)],
        capture_output=True, text=True,
    )
    pdf_tmp = OUT_DIR / "_ai_usage_doc_tmp.pdf"
    pdf_final = OUT_DIR / "AI工具使用详情.pdf"
    if pdf_tmp.exists():
        pdf_tmp.rename(pdf_final)
        print(f"[ai-usage-doc] ✓ PDF 已生成: {pdf_final}")
    else:
        print(f"[ai-usage-doc] ⚠ PDF 编译失败（xelatex exit={result.returncode}），"
              f"Markdown 版本仍可用，可手动转换或检查 {tex_path}", file=sys.stderr)
    for tmp in OUT_DIR.glob("_ai_usage_doc_tmp.*"):
        if tmp.suffix not in (".pdf",):
            tmp.unlink(missing_ok=True)


def cmd_cite_format(args):
    date_str = args.date or date.today().isoformat()
    idx = f"[{args.index}] " if args.index else "[编号] "
    line = f"{idx}{args.tool_name}, {args.tool_version}, {args.org}, {date_str}"
    print(line)
    print("\n（这一行需要你自己判断要不要、以及放在参考文献列表的哪个位置手动"
          "粘贴进 main.tex——本脚本不会自动插入任何文件，见 AutoMCM_SOP.md §17）",
          file=sys.stderr)


def cmd_mcm_entry(args):
    """COMAP 官方格式（Contest_AI_Policy）：工具名 (版本/日期) + 一句话用途，
    或 Query/Output 逐字记录——跟 cite-format 一样，只打印，不自动插入
    mcm_template.tex 里那段默认注释掉的 \\section*{Report on Use of AI Tools}。"""
    date_str = args.date or date.today().isoformat()
    print(f"\\item \\textit{{{args.tool_name}}} ({args.tool_version}, {date_str}) \\\\")
    if args.usage_statement:
        print(f"      {args.usage_statement}")
    else:
        print("      Query: <exact wording you input into the tool> \\\\")
        print("      Output: <complete output from the tool, or a faithful summary if very long>")
    print("\n（COMAP 要求这一节附在 25 页正文之后、且不计入 25 页限制，同时"
          "\\textbf{仍要}在正文相应处用 inline citation 标注、并在正文自己的"
          "参考文献列表里也列一条——两处都要，只加这一节不够，见 AutoMCM_SOP.md §17）",
          file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="生成数学建模国赛 AI 工具使用合规文档")
    sub = p.add_subparsers(dest="cmd")

    pg = sub.add_parser("generate", help="生成《AI工具使用详情》PDF")
    pg.add_argument("--tool-name", required=True, dest="tool_name")
    pg.add_argument("--tool-version", required=True, dest="tool_version")
    pg.add_argument("--org", required=True)
    pg.add_argument("--date", default=None)
    pg.add_argument("--max-records", type=int, default=60, dest="max_records")
    pg.add_argument("--no-pdf", action="store_true", dest="no_pdf",
                     help="只生成 Markdown，不编译 PDF")

    pc = sub.add_parser("cite-format", help="[CUMCM] 打印格式化的 AI 工具引用行（不自动插入）")
    pc.add_argument("--tool-name", required=True, dest="tool_name")
    pc.add_argument("--tool-version", required=True, dest="tool_version")
    pc.add_argument("--org", required=True)
    pc.add_argument("--date", default=None)
    pc.add_argument("--index", default=None)

    pm = sub.add_parser("mcm-entry", help="[MCM/ICM] 打印 COMAP 格式的 Report on Use of AI 条目（不自动插入）")
    pm.add_argument("--tool-name", required=True, dest="tool_name")
    pm.add_argument("--tool-version", required=True, dest="tool_version")
    pm.add_argument("--date", default=None)
    pm.add_argument("--usage-statement", default=None, dest="usage_statement",
                     help="简短用途说明（如翻译类用途）；不给则输出 Query/Output 占位模板")

    args = p.parse_args()
    if args.cmd == "generate":
        cmd_generate(args)
    elif args.cmd == "cite-format":
        cmd_cite_format(args)
    elif args.cmd == "mcm-entry":
        cmd_mcm_entry(args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
