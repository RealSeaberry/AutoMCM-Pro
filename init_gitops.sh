#!/usr/bin/env bash
# =============================================================================
#  AutoMCM-Pro  init_gitops.sh
#  GitOps 工作流初始化 — 选择竞赛类型、AP/Manual 模式、写入流水线状态
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 颜色定义 ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ── Banner ────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════════╗
  ║   AutoMCM-Pro  v2.0  —  GitOps 工业级建模流水线          ║
  ║   "人类作为 Router，AI 作为全栈引擎"                      ║
  ╚══════════════════════════════════════════════════════════╝
BANNER
echo -e "${RESET}"

# ── Step 1: 竞赛类型 ─────────────────────────────────────────────────────
echo -e "${BOLD}【第一步】选择竞赛类型${RESET}"
echo "  1) 🇨🇳 CUMCM — 全国大学生数学建模竞赛"
echo "  2) 🌐 MCM    — 美国大学生数学建模竞赛"
echo "  3) 🌐 ICM    — 美国大学生交叉学科建模竞赛"
echo ""
read -r -p "  请选择 [1/2/3]: " c_choice

case "$c_choice" in
    1) CONTEST="CUMCM"; TCN=""; PROB_CHOICE="" ;;
    2) CONTEST="MCM" ;;
    3) CONTEST="ICM" ;;
    *) echo -e "${RED}无效选项，使用 CUMCM${RESET}"; CONTEST="CUMCM"; TCN=""; PROB_CHOICE="" ;;
esac

if [[ "$CONTEST" == "MCM" || "$CONTEST" == "ICM" ]]; then
    echo ""
    read -r -p "  队伍控制号 Team Control Number (7位): " TCN
    echo ""
    echo "  题目选项  MCM: A B C    ICM: D E F"
    read -r -p "  选题 [A-F]: " PROB_CHOICE
    PROB_CHOICE="${PROB_CHOICE^^}"
fi

echo ""
echo -e "  ✓ 竞赛: ${GREEN}${CONTEST}${RESET}  ${TCN:+TCN: ${CYAN}$TCN${RESET}  }${PROB_CHOICE:+Problem: ${YELLOW}$PROB_CHOICE${RESET}}"

# ── Step 2: AP / Manual 模式 ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}【第二步】选择工作模式${RESET}"
echo ""
echo -e "  ${CYAN}[1] AP 模式 (Autopilot)${RESET} — AI 主导"
echo "      AI 自主提出模型、推导公式、编写代码。"
echo "      你作为 Copilot，在 Checkpoint 审批方向。"
echo "      适合：信任 AI 判断 / 时间紧张 / 探索性建模"
echo ""
echo -e "  ${YELLOW}[2] Manual 模式${RESET} — 你主导"
echo "      你在 human_intervention.md 中指定数学模型和公式。"
echo "      AI 100% 忠实转化为代码和 LaTeX，绝对不发散。"
echo "      适合：你已有明确的建模思路 / 不希望 AI 产生幻觉"
echo ""
read -r -p "  请选择 [1/2]: " m_choice

case "$m_choice" in
    1) MODE="AP" ;;
    2) MODE="MANUAL" ;;
    *) echo -e "${RED}无效选项，使用 AP 模式${RESET}"; MODE="AP" ;;
esac

echo -e "  ✓ 模式: ${GREEN}${MODE}${RESET}"

# ── Step 3: 题目文件路径 ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}【第三步】题目与数据${RESET}"
read -r -p "  题目文件路径（PDF/TXT，回车跳过）: " PROBLEM_PATH
read -r -p "  数据文件路径（目录/文件，回车跳过）: " DATA_PATH

# ── Step 4: 初始化工作区 ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}【第四步】初始化工作区${RESET}"

# 创建目录
python scripts/setup_workspace.py \
    --mode "$(echo "$CONTEST" | tr '[:upper:]' '[:lower:]')" 2>&1 | sed 's/^/  /'

# 初始化流水线
python scripts/pipeline_manager.py init \
    --mode "$MODE" \
    --contest "$CONTEST" \
    --tcn "${TCN:-}" \
    --choice "${PROB_CHOICE:-}" 2>&1 | sed 's/^/  /'

echo ""

# ── Step 5: Manual 模式 — 等待人类填写规格 ───────────────────────────────
if [[ "$MODE" == "MANUAL" ]]; then
    echo -e "${YELLOW}┌──────────────────────────────────────────────────────┐${RESET}"
    echo -e "${YELLOW}│  Manual 模式：请先填写数学规格，再启动 AI             │${RESET}"
    echo -e "${YELLOW}└──────────────────────────────────────────────────────┘${RESET}"
    echo ""
    echo "  已在以下文件创建规格模板："
    echo -e "  ${CYAN}CUMCM_Workspace/state/human_intervention.md${RESET}"
    echo ""
    echo "  请在 [MANUAL_SPEC] 区块中填写每个问题的："
    echo "    • 模型类型（LP / NLP / ODE / 回归 / 图论 / ...）"
    echo "    • 决策变量和目标函数（精确数学表达式）"
    echo "    • 约束条件（每条一行）"
    echo "    • 求解方法和特殊处理"
    echo ""
    read -r -p "  填写完毕后按 Enter 继续，或输入 'skip' 稍后填写: " spec_done
    if [[ "$spec_done" == "skip" ]]; then
        echo -e "  ${YELLOW}⚠ 已跳过，请在启动 AI 前填写 human_intervention.md${RESET}"
    fi
fi

# ── Step 6: 确认并启动 ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}【确认信息】${RESET}"
echo "  ┌──────────────────────────────────────────┐"
echo "  │  竞赛  : $CONTEST $([ -n "$TCN" ] && echo "  TCN: $TCN  Problem: $PROB_CHOICE")"
echo "  │  模式  : $MODE"
echo "  │  题目  : ${PROBLEM_PATH:-（待提供）}"
echo "  │  数据  : ${DATA_PATH:-（无）}"
echo "  │  Mind-Reader: http://localhost:8080"
echo "  └──────────────────────────────────────────┘"
echo ""

read -r -p "  确认以上信息，启动 AI？[y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "  已取消。稍后运行 'claude' 并手动触发 /auto-mcm 开始。"
    exit 0
fi

# ── Step 7: 构建并发射 Prompt ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}  启动 AutoMCM-Pro Agent...${RESET}"
echo ""

PROMPT="/auto-mcm

## 初始化参数
- 竞赛类型: ${CONTEST}
- 工作模式: ${MODE}
- 题目文件: ${PROBLEM_PATH:-（未提供，请向用户索取）}
- 数据路径: ${DATA_PATH:-（无）}
$([ "$CONTEST" != "CUMCM" ] && echo "- Team Control Number: ${TCN}" || true)
$([ "$CONTEST" != "CUMCM" ] && echo "- Problem Choice: ${PROB_CHOICE}" || true)

## 启动指令
请立即执行：\`python scripts/pipeline_manager.py status\` 确认流水线状态。
然后严格按照 AutoMCM_SOP.md 的规定开始 [problem_analysis] 阶段。
$([ "$MODE" = "MANUAL" ] && echo "注意：当前为 MANUAL 模式，请先读取 state/human_intervention.md 中的 [MANUAL_SPEC]。" || true)"

claude --print "$PROMPT"
