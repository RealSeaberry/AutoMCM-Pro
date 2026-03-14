#!/usr/bin/env bash
# =============================================================================
#  CUMCM-Master / MCM-Master — LaTeX 编译脚本
#  用法：bash scripts/compile_pdf.sh [--mode cumcm|mcm] [--memo]
#
#  --mode mcm   : 使用 xelatex × 3（mcmthesis 需要多次编译）+ bibtex
#  --memo       : 额外编译 memo.tex（MCM 实用性文件）
# =============================================================================

set -e

LATEX_DIR="CUMCM_Workspace/latex"
OUTPUT_DIR="CUMCM_Workspace/output"
MAIN_TEX="main.tex"
MODE="cumcm"
COMPILE_MEMO=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)  MODE="$2"; shift 2 ;;
        --memo)  COMPILE_MEMO=1; shift ;;
        *) shift ;;
    esac
done

# 从 iteration.json 自动检测模式（若未指定）
if [[ -f "CUMCM_Workspace/memory/iteration.json" ]]; then
    auto_mode=$(python -c "
import json,sys
s=json.load(open('CUMCM_Workspace/memory/iteration.json'))
print(s.get('mode','cumcm'))
" 2>/dev/null || echo "cumcm")
    [[ -z "$MODE" ]] && MODE="$auto_mode"
fi

echo "[compile] 模式: $MODE"
echo "[compile] 切换到 LaTeX 目录: $LATEX_DIR"
cd "$LATEX_DIR"

if [[ ! -f "$MAIN_TEX" ]]; then
    echo "[错误] $MAIN_TEX 不存在，请先完成论文撰写"
    exit 1
fi

# ── 编译主论文 ────────────────────────────────────────────────────────────
_xelatex() {
    echo "[compile] xelatex pass $1..."
    xelatex -interaction=nonstopmode "$MAIN_TEX" 2>&1 \
        | grep -E "(Error|error|Warning|!|Overfull|Undefined)" || true
}

if [[ "$MODE" == "mcm" ]]; then
    # MCM: xelatex → bibtex → xelatex → xelatex（确保目录、引用、摘要页正确）
    _xelatex 1
    bibtex "${MAIN_TEX%.tex}" 2>&1 || true
    _xelatex 2
    _xelatex 3
else
    # CUMCM: 两次编译即可
    _xelatex 1
    _xelatex 2
fi

# ── 复制主论文 PDF ────────────────────────────────────────────────────────
PDF_NAME="${MAIN_TEX%.tex}.pdf"
cd - > /dev/null
mkdir -p "$OUTPUT_DIR"

if [[ -f "$LATEX_DIR/$PDF_NAME" ]]; then
    # 命名规则：MCM 带队号，CUMCM 带日期
    if [[ "$MODE" == "mcm" ]]; then
        TCN=$(python -c "
import json; s=json.load(open('CUMCM_Workspace/memory/iteration.json'))
print(s.get('tcn','0000000'))" 2>/dev/null || echo "0000000")
        CHOICE=$(python -c "
import json; s=json.load(open('CUMCM_Workspace/memory/iteration.json'))
print(s.get('problem_choice','X'))" 2>/dev/null || echo "X")
        OUT_NAME="mcm_${TCN}_Problem${CHOICE}.pdf"
    else
        OUT_NAME="final_paper_$(date +%Y%m%d).pdf"
    fi

    cp "$LATEX_DIR/$PDF_NAME" "$OUTPUT_DIR/$OUT_NAME"
    echo "[compile] ✓ 主论文 PDF → $OUTPUT_DIR/$OUT_NAME"
else
    echo "[compile] ✗ 主论文编译失败，检查 $LATEX_DIR/$MAIN_TEX"
    exit 1
fi

# ── 编译 Memo（MCM 实用性文件，可选）────────────────────────────────────
if [[ "$COMPILE_MEMO" -eq 1 && -f "$LATEX_DIR/memo.tex" ]]; then
    echo "[compile] 编译 memo.tex..."
    cd "$LATEX_DIR"
    xelatex -interaction=nonstopmode memo.tex 2>&1 \
        | grep -E "(Error|error|!)" || true
    cd - > /dev/null

    if [[ -f "$LATEX_DIR/memo.pdf" ]]; then
        cp "$LATEX_DIR/memo.pdf" "$OUTPUT_DIR/memo.pdf"
        echo "[compile] ✓ Memo PDF → $OUTPUT_DIR/memo.pdf"
    else
        echo "[compile] ✗ Memo 编译失败"
    fi
elif [[ "$COMPILE_MEMO" -eq 1 ]]; then
    echo "[compile] 跳过 memo（memo.tex 不存在）"
fi

# ── 收尾 ──────────────────────────────────────────────────────────────────
python scripts/agent_memory_manager.py complete 2>/dev/null || true
echo "[compile] 全部完成。输出目录: $OUTPUT_DIR/"
