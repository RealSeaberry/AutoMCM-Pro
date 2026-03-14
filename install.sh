#!/usr/bin/env bash
# =============================================================================
#  AutoMCM-Pro  install.sh
#  将 Skill 安装到 Claude Code，支持全局安装（符号链接）和卸载
#
#  用法：
#    bash install.sh          # 全局安装（推荐，使用符号链接，git pull 即更新）
#    bash install.sh --copy   # 全局安装（文件拷贝，适合无 git 环境）
#    bash install.sh --check  # 检查安装状态
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="auto-mcm-pro"
CLAUDE_SKILLS_DIR="${HOME}/.claude/skills"
PLUGIN_DIR="${CLAUDE_SKILLS_DIR}/${PLUGIN_NAME}"
SKILLS=("auto-mcm" "cumcm-master" "mcm-master")
USE_COPY=0

# ── 参数 ─────────────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --copy)  USE_COPY=1 ;;
        --check) _check_only=1 ;;
    esac
done

# ── 颜色 ─────────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; R='\033[0;31m'; B='\033[1m'; N='\033[0m'

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${C}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║   AutoMCM-Pro  Skill 安装器                         ║"
echo "  ║   插件名称: ${PLUGIN_NAME}                      ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${N}"

# ── --check 模式 ──────────────────────────────────────────────────────────────
if [[ -n "$_check_only" ]]; then
    echo -e "${B}安装状态检查${N}"
    echo ""
    if [[ -d "$PLUGIN_DIR" ]]; then
        echo -e "  插件目录  ${G}✓ 存在${N}  →  ${PLUGIN_DIR}"
    else
        echo -e "  插件目录  ${R}✗ 未安装${N}"
    fi
    echo ""
    for skill in "${SKILLS[@]}"; do
        skill_path="${PLUGIN_DIR}/skills/${skill}/SKILL.md"
        if [[ -L "${PLUGIN_DIR}/skills/${skill}" ]]; then
            target=$(readlink "${PLUGIN_DIR}/skills/${skill}")
            echo -e "  /$(printf '%-16s' $skill)  ${G}✓ 符号链接${N}  →  ${target}"
        elif [[ -f "$skill_path" ]]; then
            echo -e "  /$(printf '%-16s' $skill)  ${Y}✓ 文件拷贝${N}"
        else
            echo -e "  /$(printf '%-16s' $skill)  ${R}✗ 未找到${N}"
        fi
    done
    echo ""
    # 检查 Claude Code 是否在 PATH
    if command -v claude &>/dev/null; then
        echo -e "  claude CLI  ${G}✓ 已安装${N}  →  $(command -v claude)"
    else
        echo -e "  claude CLI  ${R}✗ 未找到${N}  （需要先安装 Claude Code）"
    fi
    echo ""
    exit 0
fi

# ── 检查前置条件 ──────────────────────────────────────────────────────────────
if [[ ! -d "${CLAUDE_SKILLS_DIR}" ]]; then
    echo -e "${R}[错误]${N} ~/.claude/skills 不存在，请先安装 Claude Code"
    echo "       安装地址：https://claude.ai/code"
    exit 1
fi

if [[ ! -d "${SCRIPT_DIR}/.claude/skills" ]]; then
    echo -e "${R}[错误]${N} 请从 CUMCM-MASTER 项目根目录运行此脚本"
    exit 1
fi

# ── 创建插件目录结构 ───────────────────────────────────────────────────────────
echo -e "${B}【安装步骤】${N}"
echo ""

mkdir -p "${PLUGIN_DIR}/skills"
echo -e "  ${G}✓${N} 创建插件目录  ${PLUGIN_DIR}"

# 写入插件 README
cat > "${PLUGIN_DIR}/README.md" << PLUGINREADME
# auto-mcm-pro

AutoMCM-Pro：全栈自动化数学建模竞赛智能体

支持 CUMCM（国赛）和 MCM/ICM（美赛），AP/Manual 双模式，
GitOps 检查点，强制代码自证。

## 包含的 Skills

- \`/auto-mcm\`     — 统一入口（AP/Manual 双模式，GitOps 流水线）
- \`/cumcm-master\` — 国赛专用（中文论文）
- \`/mcm-master\`   — 美赛专用（英文论文，mcmthesis 模板）

## 项目源码

$([ -d "${SCRIPT_DIR}/.git" ] && echo "本地仓库：${SCRIPT_DIR}" || echo "本地路径：${SCRIPT_DIR}")

## 更新

$([ "$USE_COPY" -eq 0 ] && echo "符号链接安装 — 在项目目录执行 git pull 即可自动更新" || echo "拷贝安装 — 重新运行 install.sh 覆盖更新")
PLUGINREADME

echo -e "  ${G}✓${N} 写入插件 README"

# ── 安装各 Skill ──────────────────────────────────────────────────────────────
echo ""
install_method=$([ "$USE_COPY" -eq 0 ] && echo "符号链接" || echo "文件拷贝")
echo -e "  安装方式: ${C}${install_method}${N}"
echo ""

for skill in "${SKILLS[@]}"; do
    src="${SCRIPT_DIR}/.claude/skills/${skill}"
    dst="${PLUGIN_DIR}/skills/${skill}"

    if [[ ! -d "$src" ]]; then
        echo -e "  ${Y}⚠ 跳过${N}  ${skill}  （源目录不存在）"
        continue
    fi

    # 清理旧安装
    [[ -L "$dst" ]] && rm "$dst"
    [[ -d "$dst" ]] && rm -rf "$dst"

    if [[ "$USE_COPY" -eq 0 ]]; then
        ln -s "$src" "$dst"
        echo -e "  ${G}✓${N} 链接  /${skill}"
        echo -e "       ${src}"
        echo -e "       → ${dst}"
    else
        cp -r "$src" "$dst"
        echo -e "  ${G}✓${N} 拷贝  /${skill}"
    fi
done

# ── 验证安装 ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${B}【验证】${N}"
all_ok=1
for skill in "${SKILLS[@]}"; do
    skill_md="${PLUGIN_DIR}/skills/${skill}/SKILL.md"
    if [[ -f "$skill_md" ]]; then
        name=$(grep "^name:" "$skill_md" | head -1 | awk '{print $2}')
        echo -e "  ${G}✓${N}  /${name}"
    else
        echo -e "  ${R}✗${N}  /${skill}  —  SKILL.md 未找到"
        all_ok=0
    fi
done

echo ""
if [[ "$all_ok" -eq 1 ]]; then
    echo -e "${G}  安装成功！${N}"
    echo ""
    echo -e "  在任意目录的 Claude Code 对话中，输入："
    echo -e "  ${C}  /auto-mcm${N}       — 启动（AP/Manual 双模式）"
    echo -e "  ${C}  /cumcm-master${N}   — 国赛专用"
    echo -e "  ${C}  /mcm-master${N}     — 美赛专用"
    echo ""
    if [[ "$USE_COPY" -eq 0 ]]; then
        echo -e "  ${Y}更新方式${N}：在项目目录执行 git pull，技能自动更新"
    else
        echo -e "  ${Y}更新方式${N}：重新运行 bash install.sh"
    fi
    echo ""
    echo -e "  ${Y}卸载方式${N}：bash uninstall.sh"
    echo ""
else
    echo -e "${R}  安装存在问题，请检查上方错误${N}"
    exit 1
fi
