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
