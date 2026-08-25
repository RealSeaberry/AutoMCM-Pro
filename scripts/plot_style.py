#!/usr/bin/env python3
"""
plot_style.py — AutoMCM-Pro 统一图表风格模块

给所有 matplotlib 图表（EDA、模型结果、灵敏度分析……）提供一致、耐看、可正确显示
中文的默认风格，不需要每个 model 脚本各自摸索字体和配色。调色板依据 Anthropic
dataviz skill 的验证色板（`references/palette.md`）——分类色按固定顺序取用、经过
色盲安全性校验，不是随手挑的颜色。

用法（在任何要画图的脚本最上面）：
    import sys
    sys.path.insert(0, "scripts")  # 视脚本相对路径调整
    import plot_style
    plot_style.apply()

    fig, ax = plt.subplots()
    ax.plot(x, y, color=plot_style.CATEGORICAL[0], label="问题一预测值")
    ...
    plot_style.save(fig, "CUMCM_Workspace/latex/images/fig01_prediction.png")

也可作为 CLI 自检工具：
    python scripts/plot_style.py check          # 只检测中文字体，不出图
    python scripts/plot_style.py demo [OUT_PATH] # 生成一张含中文标签的示例图，人工核验
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  色板（LOS_ALAMOS 无关，通用于全流水线；数值来自 dataviz skill 的验证色板）
# ─────────────────────────────────────────────────────────────────────────────

# 分类色：固定顺序使用，不要按需生成新颜色。散点/气泡/小倍数等"全两两比较"场景
# 只用前 3 个（已验证全两两配对色盲安全）；柱状/折线/堆叠等"相邻比较"场景可用全部 8 个。
CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]
CATEGORICAL_ALL_PAIRS_SAFE = CATEGORICAL[:3]  # 散点/气泡图等两两都可能相邻时用这 3 个

# 顺序色（单一量级渐变，浅→深），用于热力图等连续数值场景
SEQUENTIAL_BLUE = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

# 发散色（两极 + 中性灰中点），用于"正负偏差""高于/低于基准"类图
DIVERGING_NEUTRAL = "#f0efec"
DIVERGING_LOW = "#2a78d6"   # blue（冷/低/负）
DIVERGING_HIGH = "#e34948"  # red（暖/高/正）

# 状态色（固定含义，不挪用作第 N 个分类色）
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# 图表基调（印刷/PDF 场景固定用浅色，不做深色模式）
CHROME = {
    "surface": "#fcfcfb",
    "text_primary": "#0b0b0b",
    "text_secondary": "#52514e",
    "text_muted": "#898781",
    "gridline": "#e1e0d9",
    "baseline": "#c3c2b7",
}


def categorical(n: int) -> list[str]:
    """取前 n 个分类色。n > 8 时发出警告——按设计不应该有超过 8 个系列同屏，
    应该合并为"其他"或改用小倍数图。"""
    if n > len(CATEGORICAL):
        print(f"[plot_style] ⚠ 请求 {n} 个分类色，超过验证过色盲安全性的 8 个上限。"
              f"建议把多余系列合并为'其他'，或改用小倍数图（facet），而不是继续取色。",
              file=sys.stderr)
    return (CATEGORICAL * ((n // len(CATEGORICAL)) + 1))[:n]


def sequential_cmap(name: str = "automcm_seq"):
    """返回 matplotlib Colormap：单一蓝色渐变，用于热力图等连续量级场景。"""
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list(name, SEQUENTIAL_BLUE)


def diverging_cmap(name: str = "automcm_div"):
    """返回 matplotlib Colormap：blue ↔ red，中性灰中点，用于"偏差/相对基准"图。"""
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list(
        name, [DIVERGING_LOW, DIVERGING_NEUTRAL, DIVERGING_HIGH]
    )


# ─────────────────────────────────────────────────────────────────────────────
#  中文字体检测与配置
# ─────────────────────────────────────────────────────────────────────────────

# 按常见程度排序的候选字体名（跨 Linux/Windows/macOS）
_CJK_FONT_PREFERENCE = [
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans SC", "Noto Sans TC",
    "Source Han Sans SC", "Source Han Sans CN", "Source Han Sans TC",
    "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Droid Sans Fallback",
    "Microsoft YaHei", "SimHei", "SimSun",
    "PingFang SC", "PingFang TC", "Heiti SC", "STHeiti",
]

# 用于兜底模糊匹配的关键词（font family 名包含任一即视为疑似 CJK 字体）
_CJK_HINT_KEYWORDS = [
    "cjk", "han", "hei", "song", "kai", "fangsong", "yahei", "pingfang",
    "heiti", "songti", "kaiti", "wqy", "wenquanyi", "droid sans fallback",
    "noto sans sc", "noto sans tc", "noto serif cjk", "sc", "tc",
]

# 可选自动下载兜底（默认关闭，需显式传 allow_download=True）
_FALLBACK_FONT_URL = (
    "https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/OTF/"
    "SimplifiedChinese/NotoSansCJKsc-Regular.otf"
)
_FALLBACK_FONT_CACHE = Path.home() / ".cache" / "automcm-pro" / "NotoSansCJKsc-Regular.otf"


def _available_font_names() -> list[str]:
    from matplotlib import font_manager
    return [f.name for f in font_manager.fontManager.ttflist]


def _match_preference(available_lower: dict[str, str]) -> str | None:
    for pref in _CJK_FONT_PREFERENCE:
        if pref.lower() in available_lower:
            return available_lower[pref.lower()]
        # 部分环境注册名带后缀（如 "Noto Sans CJK SC Regular"），做子串匹配
        for name_lower, name in available_lower.items():
            if pref.lower() in name_lower:
                return name

    # 兜底：关键词模糊匹配（避免把英文字体如 "Source Sans Pro" 误判为 CJK，
    # 关键词本身已经足够特定，不含泛用词）
    specific_keywords = [k for k in _CJK_HINT_KEYWORDS if k not in ("sc", "tc")]
    for name_lower, name in available_lower.items():
        if any(kw in name_lower for kw in specific_keywords):
            return name
    return None


def _rescan_system_fonts() -> None:
    """matplotlib 的 fontManager.ttflist 是启动时/上次建缓存时的快照——新装的
    系统字体（比如 apt 装完 fonts-noto-cjk）不会自动出现在里面。这里做一次
    实际的文件系统扫描（findSystemFonts 直接查 OS 标准字体目录/fontconfig，
    不依赖 matplotlib 自己的缓存）并逐个注册进 fontManager，让本次进程能看到
    刚装好的字体，不需要重启 Python。"""
    from matplotlib import font_manager
    for path in font_manager.findSystemFonts():
        try:
            font_manager.fontManager.addfont(path)
        except Exception:  # noqa: BLE001 — 单个损坏字体文件不应该中断整体检测
            continue


def detect_cjk_font(rescan: bool = True) -> str | None:
    """按优先级列表查找系统已安装的中文字体，返回 matplotlib 能识别的 family 名。
    找不到精确匹配时退化为关键词模糊匹配。都找不到返回 None。

    rescan=True（默认）时会先做一次系统字体目录的实时扫描——matplotlib 自带的
    ttflist 缓存可能建立于字体安装之前，只查缓存会漏掉刚装好的字体（实测：本机
    确实装了 Droid Sans Fallback，但不 rescan 检测不到）。
    """
    available_lower = {a.lower(): a for a in _available_font_names()}
    found = _match_preference(available_lower)
    if found:
        return found

    if rescan:
        _rescan_system_fonts()
        available_lower = {a.lower(): a for a in _available_font_names()}
        found = _match_preference(available_lower)
        if found:
            return found

    return None


def _try_download_fallback_font() -> str | None:
    """显式 opt-in 才会调用：从 Google Fonts 官方 noto-cjk 仓库下载一份 Noto Sans
    CJK SC 缓存到本地，注册进 matplotlib。失败时返回 None，不抛异常（不阻塞主流程）。
    """
    try:
        _FALLBACK_FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        if not _FALLBACK_FONT_CACHE.exists():
            print(f"[plot_style] 正在下载中文字体兜底文件（一次性，约 10~15MB）：\n"
                  f"  {_FALLBACK_FONT_URL}\n  → {_FALLBACK_FONT_CACHE}", file=sys.stderr)
            urllib.request.urlretrieve(_FALLBACK_FONT_URL, _FALLBACK_FONT_CACHE)  # noqa: S310

        from matplotlib import font_manager
        font_manager.fontManager.addfont(str(_FALLBACK_FONT_CACHE))
        prop = font_manager.FontProperties(fname=str(_FALLBACK_FONT_CACHE))
        return prop.get_name()
    except (OSError, urllib.error.URLError) as e:
        print(f"[plot_style] ⚠ 中文字体自动下载失败：{e}", file=sys.stderr)
        return None


def setup_cjk_font(allow_download: bool = False) -> str | None:
    """检测并配置中文字体，同时关闭 unicode 负号（CJK 字体下负号常常不显示/变方框，
    这是最容易被忽略的一个坑）。返回实际使用的字体名，找不到时返回 None 并打印
    可操作的安装建议。"""
    import matplotlib.pyplot as plt

    font_name = detect_cjk_font()
    if font_name is None and allow_download:
        font_name = _try_download_fallback_font()

    plt.rcParams["axes.unicode_minus"] = False  # 关键：否则负号在 CJK 字体下常显示异常

    if font_name:
        # 关键坑：很多中文字体（尤其是 Droid Sans Fallback 这类"仅 CJK 兜底"字体）
        # 不含拉丁字母/数字/标点字形。必须把 font.family 设成"CJK 字体 + DejaVu Sans"
        # 的显式列表（而不是通用的 "sans-serif" + font.sans-serif 间接列表），
        # matplotlib 才会真正做到"中文找 CJK 字体、西文数字找 DejaVu"的逐字形回退——
        # 实测过：只设 font.sans-serif 不会触发这个回退，西文字符会直接报缺字警告。
        plt.rcParams["font.family"] = [font_name, "DejaVu Sans"]
        return font_name

    print(
        "[plot_style] ⚠ 未检测到可用的中文字体，图表中的中文字符可能显示为方框。\n"
        "  建议按当前系统安装一款开源中文字体后重跑：\n"
        "    Debian/Ubuntu : sudo apt-get install -y fonts-noto-cjk\n"
        "    macOS         : 系统自带 PingFang SC，通常无需安装（若仍失败请检查字体缓存）\n"
        "    或调用 setup_cjk_font(allow_download=True) 自动下载一份 Noto Sans CJK SC 兜底\n"
        "  临时应急方案：图表标题/标签改用英文，避免中文乱码进入论文。",
        file=sys.stderr,
    )
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  统一风格应用
# ─────────────────────────────────────────────────────────────────────────────

def apply(allow_font_download: bool = False) -> str | None:
    """一次性设置全局 matplotlib rcParams：中文字体、配色基调、网格/坐标轴规范、
    印刷级 DPI。返回实际使用的中文字体名（供日志/自检使用）。"""
    import matplotlib.pyplot as plt

    font_name = setup_cjk_font(allow_download=allow_font_download)

    plt.rcParams.update({
        # 字号：匹配 CUMCM/MCM 论文正文字号量级，图表缩放进正文栏宽后仍可读
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 13,

        # 输出质量：论文用图，300dpi 起步，白底（不用透明背景，避免 LaTeX 里被
        # 页面色"透出"）
        "figure.dpi": 150,          # 屏幕预览
        "savefig.dpi": 300,         # 实际存盘（save() 里会再强制一次，双保险）
        "figure.figsize": (8, 5),
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "axes.facecolor": CHROME["surface"],

        # 克制的图表铬件：细网格线、无边框、粗细一致的 hairline
        "axes.grid": True,
        "axes.axisbelow": True,      # 网格线沉在柱状图/散点之下，不能盖在数据上面
        "grid.color": CHROME["gridline"],
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",       # 从不用虚线网格（dataviz skill 明确禁止）
        "axes.edgecolor": CHROME["baseline"],
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": CHROME["text_muted"],
        "ytick.color": CHROME["text_muted"],
        "text.color": CHROME["text_primary"],
        "axes.labelcolor": CHROME["text_secondary"],
        "axes.titlecolor": CHROME["text_primary"],

        # 线/点：细线、圆头，不额外描边（呼应 dataviz skill 的 mark specs）
        "lines.linewidth": 1.8,
        "lines.markersize": 6,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "patch.edgecolor": "none",   # 柱状图默认不描边，靠色块本身和留白分隔

        # 分类色循环：固定顺序，不随机
        "axes.prop_cycle": plt.cycler(color=CATEGORICAL),
    })

    return font_name


def save(fig, path: str | Path, dpi: int = 300) -> Path:
    """标准化存图：确保目录存在、白底、300dpi、裁掉多余留白。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight", facecolor="white")
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  CLI 自检
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_check(_args):
    font = detect_cjk_font()
    if font:
        print(f"✓ 检测到中文字体：{font}")
        sys.exit(0)
    else:
        setup_cjk_font(allow_download=False)  # 打印安装建议
        sys.exit(1)


def _cmd_demo(args):
    import matplotlib.pyplot as plt
    import numpy as np

    apply(allow_font_download=args.allow_download)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    x = np.linspace(0, 10, 60)
    for i, label in enumerate(["问题一：预测值", "问题二：仿真值", "问题三：优化值"]):
        axes[0].plot(x, np.sin(x + i) * (i + 1), color=CATEGORICAL[i], label=label)
    axes[0].set_title("折线图示例（中文标签 + 负号 -3.5 应正常显示）")
    axes[0].set_xlabel("时间 t / 年")
    axes[0].set_ylabel("数值偏差")
    axes[0].axhline(0, color=CHROME["baseline"], linewidth=0.8)
    axes[0].set_ylim(-4, 4)
    axes[0].legend()

    categories = ["方案A", "方案B", "方案C", "方案D"]
    values = [3.2, 4.8, 2.1, 3.9]
    axes[1].bar(categories, values, color=categorical(len(categories)), width=0.6)
    axes[1].set_title("柱状图示例")
    axes[1].set_ylabel("综合评分")

    fig.suptitle("AutoMCM-Pro 图表风格自检")
    out = save(fig, args.out)
    plt.close(fig)
    print(f"✓ 示例图已生成：{out}\n  请人工打开确认中文正常显示、无方框乱码。")


def main():
    p = argparse.ArgumentParser(description="AutoMCM-Pro 统一图表风格模块")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("check", help="只检测中文字体是否可用")

    pd = sub.add_parser("demo", help="生成一张含中文标签的示例图供人工核验")
    pd.add_argument("out", nargs="?", default="/tmp/automcm_plot_style_demo.png")
    pd.add_argument("--allow-download", action="store_true", dest="allow_download",
                     help="未检测到中文字体时，允许自动下载 Noto Sans CJK SC 兜底")

    args = p.parse_args()
    if args.cmd == "check":
        _cmd_check(args)
    elif args.cmd == "demo":
        _cmd_demo(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
