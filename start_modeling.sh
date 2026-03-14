#!/usr/bin/env bash
# =============================================================================
#  CUMCM-Master / MCM-Master — 统一启动脚本
#  用法：./start_modeling.sh
#  带参数：./start_modeling.sh --contest mcm -p problem.pdf -d ./data
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 解析命令行参数 ────────────────────────────────────────────────────────
CONTEST=""          # cumcm | mcm
PROBLEM_PATH=""
DATA_PATH=""
LATEX_TEMPLATE=""
TCN=""              # MCM Team Control Number
PROB_CHOICE=""      # MCM Problem A-F

while [[ $# -gt 0 ]]; do
    case "$1" in
        --contest|-c)  CONTEST="$2";       shift 2 ;;
        -p|--problem)  PROBLEM_PATH="$2";  shift 2 ;;
        -d|--data)     DATA_PATH="$2";     shift 2 ;;
        -t|--template) LATEX_TEMPLATE="$2";shift 2 ;;
        --tcn)         TCN="$2";           shift 2 ;;
        --choice)      PROB_CHOICE="$2";   shift 2 ;;
        *) echo "未知参数: $1"; shift ;;
    esac
done

# ── Banner ────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         CUMCM-Master / MCM-Master  Agent  v1.1          ║"
echo "║         全栈自动化数学建模竞赛智能体                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: 选择竞赛类型 ─────────────────────────────────────────────────
if [[ -z "$CONTEST" ]]; then
    echo "请选择竞赛类型："
    echo "  1) 🇨🇳 CUMCM — 全国大学生数学建模竞赛（中文论文）"
    echo "  2) 🌐 MCM/ICM — 美国大学生数学建模竞赛（English paper）"
    echo ""
    read -r -p "请输入选项 [1/2]: " contest_choice

    case "$contest_choice" in
        1) CONTEST="cumcm" ;;
        2) CONTEST="mcm"   ;;
        *) echo "[警告] 无效选项，默认使用 CUMCM"; CONTEST="cumcm" ;;
    esac
fi

echo ""
if [[ "$CONTEST" == "mcm" ]]; then
    echo "━━━  MCM/ICM 模式  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ -z "$TCN" ]]; then
        read -r -p "请输入队伍控制号 Team Control Number (7位，如 2400001): " TCN
    fi

    if [[ -z "$PROB_CHOICE" ]]; then
        echo ""
        echo "请选择参赛题目："
        echo "  MCM:  A (Continuous)   B (Discrete)      C (Data Insights)"
        echo "  ICM:  D (Operations)   E (Sustainability) F (Policy)"
        read -r -p "题目选项 [A/B/C/D/E/F]: " PROB_CHOICE
        PROB_CHOICE="${PROB_CHOICE^^}"
    fi

    [[ -z "$LATEX_TEMPLATE" ]] && LATEX_TEMPLATE="./templates/mcm_template.tex"

    echo "  队号 (TCN) : $TCN"
    echo "  选题       : Problem $PROB_CHOICE"
    echo ""
else
    echo "━━━  CUMCM 国赛模式  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    [[ -z "$LATEX_TEMPLATE" ]] && LATEX_TEMPLATE="./templates/latex_template.tex"
    echo ""
fi

# ── 题目与数据路径 ────────────────────────────────────────────────────────
if [[ -z "$PROBLEM_PATH" ]]; then
    read -r -p "题目文件路径（PDF 或 TXT，如 ./problem.pdf）: " PROBLEM_PATH
fi

if [[ -z "$DATA_PATH" ]]; then
    read -r -p "数据文件路径（目录或文件，无则回车跳过）: " DATA_PATH
fi

# ── 环境检查 ──────────────────────────────────────────────────────────────
echo ""
echo "[检查] 竞赛类型   : $([ "$CONTEST" = "mcm" ] && echo "MCM/ICM (English)" || echo "CUMCM (中文)")"
[[ "$CONTEST" == "mcm" ]] && echo "[检查] TCN        : $TCN"
[[ "$CONTEST" == "mcm" ]] && echo "[检查] 题目选项   : Problem $PROB_CHOICE"
echo "[检查] 题目文件   : ${PROBLEM_PATH:-（未提供）}"
echo "[检查] 数据路径   : ${DATA_PATH:-（无附件数据）}"
echo "[检查] LaTeX 模板 : $LATEX_TEMPLATE"
[[ -n "$PROBLEM_PATH" && ! -f "$PROBLEM_PATH" ]] && \
    echo "[警告] 题目文件不存在，智能体将在对话中请求提供题目内容"

# ── 初始化工作区 ──────────────────────────────────────────────────────────
echo ""
echo "[初始化] 创建工作区结构..."
python scripts/setup_workspace.py --mode "$CONTEST"

# 若为 MCM，将 TCN 和题目写入 iteration.json
if [[ "$CONTEST" == "mcm" && -n "$TCN" ]]; then
    python - <<PYEOF
import json
from pathlib import Path
f = Path("CUMCM_Workspace/memory/iteration.json")
if f.exists():
    s = json.loads(f.read_text(encoding="utf-8"))
    s["tcn"] = "$TCN"
    s["problem_choice"] = "$PROB_CHOICE"
    f.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  [更新] iteration.json  TCN=$TCN  Problem=$PROB_CHOICE")
PYEOF
fi

# ── 启动提示 ──────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
if [[ "$CONTEST" == "mcm" ]]; then
    echo "║  Starting MCM-Master Agent...                           ║"
    echo "║  Pipeline: Analysis → Coding → English Paper → PDF     ║"
else
    echo "║  正在启动 CUMCM-Master Agent...                          ║"
    echo "║  流程: 破题 → 编码 → 中文论文 → PDF                      ║"
fi
echo "║  Mind-Reader UI → http://localhost:8080                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 构建 Prompt ──────────────────────────────────────────────────────────
if [[ "$CONTEST" == "mcm" ]]; then
    PROMPT="/mcm-master

Contest metadata:
- Type: MCM/ICM
- Team Control Number: ${TCN}
- Problem Choice: ${PROB_CHOICE}
- Problem file: ${PROBLEM_PATH:-none}
- Data path: ${DATA_PATH:-none}
- LaTeX template: ${LATEX_TEMPLATE}
- Memo template: ./templates/mcm_memo_template.tex

Please follow the MCM-Master SOP. Begin with Step 2: read the problem,
detect if a practical deliverable (memo/letter) is required, ask me about it,
then proceed to Phase 1 analysis. Record all reasoning to memory/thought_process.md."
else
    PROMPT="/cumcm-master

任务信息：
- 竞赛类型：CUMCM 国赛
- 赛题文件：${PROBLEM_PATH:-（待提供）}
- 数据路径：${DATA_PATH:-无附件数据}
- LaTeX 模板：${LATEX_TEMPLATE}

请严格按照 CUMCM-Master SOP，立即开始 Phase 1 破题分析，读取赛题内容，
在 memory/thought_process.md 中记录初步理解，然后推进至 Phase 2 编码阶段。"
fi

# ── 启动 Claude Code ──────────────────────────────────────────────────────
claude --print "$PROMPT"
