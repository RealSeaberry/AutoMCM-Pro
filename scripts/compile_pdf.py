#!/usr/bin/env python3
"""
AutoMCM-Pro — LaTeX 编译脚本（跨平台，替代 compile_pdf.sh）
用法：
  python scripts/compile_pdf.py              # 自动检测模式
  python scripts/compile_pdf.py --mode cumcm
  python scripts/compile_pdf.py --mode mcm
  python scripts/compile_pdf.py --mode mcm --memo
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LATEX_DIR  = Path("CUMCM_Workspace/latex")
OUTPUT_DIR = Path("CUMCM_Workspace/output")
ITER_JSON  = Path("CUMCM_Workspace/memory/iteration.json")
MAIN_TEX   = "main.tex"


def find_latex_engine():
    """按优先级查找可用的 LaTeX 引擎：xelatex > pdflatex"""
    for engine in ("xelatex", "pdflatex"):
        if shutil.which(engine):
            return engine
    return None


def run(cmd: list, cwd: Path = None):
    """运行命令，打印关键输出行，不因编译警告中断。"""
    print(f"[compile] > {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # 只打印错误相关行（避免刷屏）
    for line in (result.stdout + result.stderr).splitlines():
        if any(k in line for k in ("Error", "error", "!", "Warning", "Undefined", "Overfull")):
            print(f"  {line}")
    return result.returncode


def load_iter():
    if ITER_JSON.exists():
        try:
            return json.loads(ITER_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# 附录/代码起始章节的常见标题关键词，用来在 PDF 书签里定位"正文到哪页为止"
_APPENDIX_TITLE_KEYWORDS = ("附录", "核心代码", "appendix", "report on use of ai")


def report_page_count(pdf_path: Path, mode: str) -> None:
    """编译成功后报告页数，并按赛制给出正文/总页数的软性目标提醒（不是门控，
    不会让编译失败——页数控制是写作阶段该做的事，这里只是让 Agent 看得到
    有没有超标，超标了应该回 latex_draft 精简附录核心代码，见
    AutoMCM_SOP.md §17.4）。CUMCM：正文（不含附录）目标 20~25 页、硬上限 30 页，
    附录不限；MCM/ICM：正文+参考文献+附录代码合计硬上限 25 页（AI 使用报告
    单独不计）。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        print("[compile] （未安装 pypdf，跳过页数统计——不影响 PDF 本身）")
        return

    try:
        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
    except Exception as e:
        print(f"[compile] （页数统计失败: {e}，不影响 PDF 本身）")
        return

    # 尝试用大纲书签定位附录起始页（hyperref 会自动把 \section 加进书签）
    appendix_start = None
    try:
        def _walk(outline, depth=0):
            nonlocal appendix_start
            for item in outline:
                if isinstance(item, list):
                    _walk(item, depth + 1)
                    continue
                title = str(getattr(item, "title", "")).lower()
                if any(kw in title for kw in _APPENDIX_TITLE_KEYWORDS):
                    try:
                        page_idx = reader.get_destination_page_number(item)
                        if appendix_start is None or page_idx < appendix_start:
                            appendix_start = page_idx
                    except Exception:
                        pass
        _walk(reader.outline)
    except Exception:
        pass

    body_pages = appendix_start if appendix_start is not None else total_pages

    print(f"[compile] 页数统计：总计 {total_pages} 页"
          + (f"，正文（附录前）约 {body_pages} 页" if appendix_start is not None else ""))

    if mode in ("mcm", "icm"):
        if total_pages > 25:
            print(f"[compile] ⚠ 总页数 {total_pages} 超过 MCM/ICM 官方硬上限 25 页"
                  f"（Report on Use of AI Tools 单独一节不计入，其余全部计入）——"
                  f"请回 latex_draft 精简附录核心代码（只保留核心求解逻辑，"
                  f"去掉样板 import/绘图美化代码），或删减非核心章节内容")
        elif total_pages > 22:
            print(f"[compile] 提示：总页数 {total_pages}，接近 25 页硬上限，建议关注")
    else:
        if body_pages and body_pages > 30:
            print(f"[compile] ⚠ 正文 {body_pages} 页超过 CUMCM 官方硬上限 30 页，"
                  f"请回 latex_draft 精简正文内容")
        elif body_pages and body_pages > 25:
            print(f"[compile] 提示：正文 {body_pages} 页，超出建议目标区间 20~25 页"
                  f"（未超硬上限 30 页，不强制处理，篇幅富余时可考虑精简）")


def main():
    parser = argparse.ArgumentParser(description="AutoMCM-Pro LaTeX 编译器")
    parser.add_argument("--mode", choices=["cumcm", "mcm", "icm"], default=None)
    parser.add_argument("--memo", action="store_true", help="同时编译 memo.tex（MCM）")
    args = parser.parse_args()

    # 自动检测模式
    mode = args.mode
    if not mode:
        mode = load_iter().get("mode", "cumcm").lower()
        if mode not in ("cumcm", "mcm", "icm"):
            mode = "cumcm"

    print(f"[compile] 模式: {mode.upper()}")

    # 检查 LaTeX 目录
    main_tex_path = LATEX_DIR / MAIN_TEX
    if not LATEX_DIR.exists():
        sys.exit(f"[错误] LaTeX 目录不存在: {LATEX_DIR}")
    if not main_tex_path.exists():
        sys.exit(f"[错误] {MAIN_TEX} 不存在，请先完成论文撰写")

    # 检查 LaTeX 引擎
    engine = find_latex_engine()
    if not engine:
        print("[错误] 未找到 LaTeX 引擎（xelatex / pdflatex）")
        print()
        print("Windows 安装方法（选一）：")
        print("  1. MiKTeX（推荐，自动下载缺失宏包）：")
        print("     https://miktex.org/download")
        print("  2. TeX Live（完整版，~5GB）：")
        print("     https://tug.org/texlive/")
        print("  3. Docker（无需本地安装，使用项目自带容器）：")
        print("     docker-compose up cumcm-agent")
        print("     docker exec -it cumcm-agent python scripts/compile_pdf.py")
        sys.exit(1)

    print(f"[compile] 使用引擎: {engine}")
    print(f"[compile] LaTeX 目录: {LATEX_DIR}")

    latex_cmd = [engine, "-interaction=nonstopmode", MAIN_TEX]
    bibtex_cmd = ["bibtex", MAIN_TEX.replace(".tex", "")]

    # ── 编译主论文 ────────────────────────────────────────────────────────────
    if mode in ("mcm", "icm"):
        # mcmthesis 需要：xelatex → bibtex → xelatex → xelatex
        run(latex_cmd, cwd=LATEX_DIR)
        run(bibtex_cmd, cwd=LATEX_DIR)
        run(latex_cmd, cwd=LATEX_DIR)
        run(latex_cmd, cwd=LATEX_DIR)
    else:
        # CUMCM：两次即可（处理交叉引用）
        run(latex_cmd, cwd=LATEX_DIR)
        run(latex_cmd, cwd=LATEX_DIR)

    # ── 复制主论文 PDF ────────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    src_pdf = LATEX_DIR / MAIN_TEX.replace(".tex", ".pdf")

    if src_pdf.exists():
        if mode in ("mcm", "icm"):
            d = load_iter()
            tcn    = d.get("tcn", "0000000")
            choice = d.get("problem_choice", "X")
            out_name = f"mcm_{tcn}_Problem{choice}.pdf"
        else:
            out_name = f"final_paper_{datetime.now().strftime('%Y%m%d')}.pdf"

        out_path = OUTPUT_DIR / out_name
        shutil.copy2(src_pdf, out_path)
        print(f"[compile] ✓ 主论文 PDF → {out_path}")
        report_page_count(out_path, mode)
    else:
        sys.exit(f"[compile] ✗ 编译失败，检查 {LATEX_DIR / MAIN_TEX}")

    # ── 编译 Memo（MCM 实用性文件，可选）────────────────────────────────────
    if args.memo:
        memo_tex = LATEX_DIR / "memo.tex"
        if memo_tex.exists():
            print("[compile] 编译 memo.tex...")
            run([engine, "-interaction=nonstopmode", "memo.tex"], cwd=LATEX_DIR)
            memo_pdf = LATEX_DIR / "memo.pdf"
            if memo_pdf.exists():
                shutil.copy2(memo_pdf, OUTPUT_DIR / "memo.pdf")
                print(f"[compile] ✓ Memo PDF → {OUTPUT_DIR / 'memo.pdf'}")
            else:
                print("[compile] ✗ memo.tex 编译失败")
        else:
            print("[compile] 跳过 memo（memo.tex 不存在）")

    # ── 收尾 ──────────────────────────────────────────────────────────────────
    try:
        subprocess.run(
            [sys.executable, "scripts/agent_memory_manager.py", "complete"],
            capture_output=True
        )
    except Exception:
        pass

    print(f"[compile] 全部完成。输出目录: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
