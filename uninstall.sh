#!/usr/bin/env bash
# =============================================================================
#  AutoMCM-Pro  uninstall.sh
#  从 Claude Code 中彻底移除 auto-mcm-pro 插件
# =============================================================================

PLUGIN_NAME="auto-mcm-pro"
PLUGIN_DIR="${HOME}/.claude/skills/${PLUGIN_NAME}"

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'

echo ""
echo "  AutoMCM-Pro 卸载程序"
echo ""

if [[ ! -d "$PLUGIN_DIR" ]]; then
    echo -e "  ${Y}未安装${N}  ${PLUGIN_DIR} 不存在，无需卸载"
    exit 0
fi

read -r -p "  确认删除 ${PLUGIN_DIR}？[y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "  已取消"
    exit 0
fi

rm -rf "$PLUGIN_DIR"
echo -e "  ${G}✓${N} 已删除 ${PLUGIN_DIR}"
echo ""
echo -e "  ${G}卸载完成。${N}/auto-mcm /cumcm-master /mcm-master 已从 Claude Code 中移除。"
echo ""
