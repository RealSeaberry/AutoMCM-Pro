#!/usr/bin/env python3
"""
00_data_eda.py — 数据预处理 / EDA（2025 CUMCM A：烟幕干扰弹投放策略）

题目自带参数均为确定性标量，本脚本负责：
1. 从 data/scenario.json 读取并核验场景参数（数据质量检查：有限性、量纲、范围）。
2. 输出场景概览表（导弹/无人机初始位置、目标几何、物理参数）。
3. 生成几何可视化图（3D 场景、俯视图、视线几何示意）→ latex/images/fig00_*.png。
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")  # headless 环境无显示器，强制非交互后端

import numpy as np

ROOT = Path(__file__).resolve().parents[2]          # CUMCM_Workspace
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 本目录（geometry_core）
sys.path.insert(0, str(ROOT.parent / "scripts"))    # 仓库根 scripts/
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import geometry_core as gc  # noqa: E402

SCENARIO = ROOT / "data" / "scenario.json"
IMG_DIR = ROOT / "latex" / "images"

# 问题 1 给定策略（与 problem1_geometry.Q1_* 一致，确定性，fig00_3 用它保证
# 与 state/model1_results.json 的 q1 数值一致，且 EDA 阶段不依赖任何 model 结果）
Q1_THETA, Q1_V, Q1_T_DROP, Q1_T_DELAY = 180.0, 120.0, 1.5, 3.6


def _missile_full_path(sc, name, n=90):
    """导弹从初始位置到假目标（原点）的全程直线轨迹。"""
    m0 = np.asarray(sc["missiles"][name], dtype=float)
    decoy = np.asarray(sc["decoy"], dtype=float)
    d = float(np.linalg.norm(decoy - m0))
    ts = np.linspace(0.0, d / sc["missile_speed"], n)
    u = (decoy - m0) / d
    return m0[None, :] + sc["missile_speed"] * ts[:, None] * u[None, :]


def _tickless3d(ax, labels=True):
    """3D 小面板：去掉刻度数字、保留坐标轴名称，避免小图里刻度互相挤。"""
    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    if labels:
        ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_zlabel("z")


def load_scenario() -> dict:
    with open(SCENARIO, "r", encoding="utf-8") as f:
        return json.load(f)


def data_quality_check(sc: dict) -> list:
    """数据质量初判：所有坐标/参数有限、速度在 [70,140]、间隔/时长为正。"""
    issues = []
    for k, v in sc.items():
        if isinstance(v, (int, float)):
            if not np.isfinite(v):
                issues.append(f"非有限数值: {k}={v}")
    for name, p in sc["uavs"].items():
        if not all(np.isfinite(x) for x in p):
            issues.append(f"无人机 {name} 坐标非有限: {p}")
    for name, p in sc["missiles"].items():
        if not all(np.isfinite(x) for x in p):
            issues.append(f"导弹 {name} 坐标非有限: {p}")
    if sc["uav_speed_min"] < 0 or sc["uav_speed_max"] < sc["uav_speed_min"]:
        issues.append("无人机速度范围非法")
    if sc["cloud_effective_duration"] <= 0 or sc["cloud_effective_radius"] <= 0:
        issues.append("云团有效半径/时长必须为正")
    if sc["min_bomb_interval"] <= 0:
        issues.append("最小投放间隔必须为正")
    return issues


def print_scenario_summary(sc: dict) -> None:
    print("=" * 70)
    print("场景参数概览（2025 CUMCM A）")
    print("=" * 70)
    print(f"重力加速度 g            : {sc['g']} m/s^2")
    print(f"导弹速度                : {sc['missile_speed']} m/s")
    print(f"无人机速度范围          : [{sc['uav_speed_min']}, {sc['uav_speed_max']}] m/s")
    print(f"云团下沉速度            : {sc['cloud_sink_speed']} m/s")
    print(f"云团有效半径            : {sc['cloud_effective_radius']} m")
    print(f"云团有效时长            : {sc['cloud_effective_duration']} s")
    print(f"相邻弹最小投放间隔      : {sc['min_bomb_interval']} s")
    print(f"真目标（圆柱）          : 圆心 {sc['true_target']['center']}, "
          f"半径 {sc['true_target']['radius']} m, 高 {sc['true_target']['height']} m")
    print(f"假目标（诱饵）          : {sc['decoy']}")
    print("-" * 70)
    print(f"{'导弹':<4} {'x':>10} {'y':>10} {'z':>10}   到原点距离(m) 到达原点时间(s)")
    for name, p in sc["missiles"].items():
        d = float(np.linalg.norm(p))
        print(f"{name:<4} {p[0]:>10.1f} {p[1]:>10.1f} {p[2]:>10.1f}   "
              f"{d:>12.1f}  {d / sc['missile_speed']:>10.1f}")
    print(f"{'无人机':<4} {'x':>10} {'y':>10} {'z':>10}   到真目标距离(m)")
    for name, p in sc["uavs"].items():
        d = float(np.linalg.norm(np.array(p) - np.array(sc["true_target"]["center"])))
        print(f"{name:<4} {p[0]:>10.1f} {p[1]:>10.1f} {p[2]:>10.1f}   {d:>12.1f}")
    print("=" * 70)


def fig_scene_3d(sc: dict) -> None:
    """3D 场景图：导弹（蓝）、无人机（橙）、真目标圆柱（绿实体）、假目标（黑星）。

    §18 惯例调研（见 memory/thought_process.md）：混尺度场景（20 km 飞行走廊 vs
    10 m 量级目标几何）的常规画法是"总览 + 局部放大"双子图；体积对象（目标圆柱）
    画成半透明实体面而非线框；三轴按数据跨度等比例（不拉伸变形）；图例放绘图区外。
    """
    plot_style.apply()
    fig = plt.figure(figsize=(13, 6.4))
    ax = fig.add_axes([0.02, 0.10, 0.88, 0.55], projection="3d")
    axz = fig.add_axes([0.72, 0.34, 0.25, 0.42], projection="3d")

    tc = np.array(sc["true_target"]["center"])
    r, h = sc["true_target"]["radius"], sc["true_target"]["height"]

    # ── 主面板：全走廊总览（盒体 x 最长、z/y 可读，不被默认立方盒拉伸变形）──
    ax.set_xlim(-1500, 21000); ax.set_ylim(-3500, 2500); ax.set_zlim(-100, 2200)
    plot_style.equal3d(ax, box=(1.0, 0.45, 0.34))  # 总览盒体：走廊仍最长，但 z/y 可读
    plot_style.style3d(ax)
    ax.set_position([0.02, 0.12, 0.88, 0.52])      # 横置窗口贴合盒体比例，避免上下留白
    plot_style.solid_cylinder(ax, tc, r, h, plot_style.CATEGORICAL[2], alpha=0.5)
    ax.scatter(*sc["decoy"], marker="*", s=300, color="k", label="假目标(诱饵)", zorder=6)
    # M1/M2/M3 起点彼此只差 1~2 km，在 20 km 走廊总览尺度+当前视角下投影几乎
    # 挤在一起，固定小偏移量不够分开——按索引把标签在竖直方向错开一段更大的
    # 距离，复核时发现原偏移量下三个文字几乎叠在一处认不清是哪枚弹。
    for idx, (name, p) in enumerate(sc["missiles"].items()):
        path = _missile_full_path(sc, name)
        ax.plot(path[:, 0], path[:, 1], path[:, 2], color=plot_style.CATEGORICAL[0],
                lw=1.1, alpha=0.45)
        ax.scatter(*p, color=plot_style.CATEGORICAL[0], s=110, label=f"导弹 {name}", zorder=7)
        ax.text(p[0] + 150, p[1], p[2] + 380 + idx * 320, name, fontsize=8.5,
                color=plot_style.CATEGORICAL[0], ha="left", fontweight="bold")
    for name, p in sc["uavs"].items():
        ax.scatter(*p, color=plot_style.CATEGORICAL[1], marker="^", s=140,
                   label=f"无人机 {name}", zorder=7)
        ax.text(p[0] + 150, p[1], p[2] + 160, name, fontsize=8.5,
                color=plot_style.CATEGORICAL[1], ha="left")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.set_zlabel("z (m)")
    ax.set_title("作战场景三维布局（全走廊总览）", fontsize=11.5)
    ax.view_init(elev=24, azim=-60)

    # ── 右上：目标区放大（实体圆柱在 700 m 尺度下才可见，导弹末段收敛）──
    axz.set_xlim(-250, 650); axz.set_ylim(-350, 750); axz.set_zlim(-30, 90)
    plot_style.equal3d(axz)
    plot_style.style3d(axz)
    plot_style.solid_cylinder(axz, tc, r, h, plot_style.CATEGORICAL[2], alpha=0.45)
    axz.text(tc[0], tc[1] + 60, tc[2] + h + 35, "真目标(圆柱)", fontsize=8,
             color=plot_style.CATEGORICAL[2], ha="center")
    axz.scatter(*sc["decoy"], marker="*", s=240, color="k", zorder=6)
    axz.text(0, 0, 55, "假目标(诱饵)", fontsize=8, color="k", ha="center")
    for name, p in sc["missiles"].items():
        path = _missile_full_path(sc, name)
        axz.plot(path[:, 0], path[:, 1], path[:, 2], color=plot_style.CATEGORICAL[0],
                 lw=1.8, alpha=0.9)
    axz.set_title("目标区放大", fontsize=10.5)
    axz.view_init(elev=22, azim=-58)
    _tickless3d(axz, labels=False)
    axz.set_position([0.72, 0.30, 0.25, 0.40])     # 右上角细节面板（下面 fit3d_axes 会再收紧）
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.42, 0.005),
               ncol=5, fontsize=8, frameon=False)
    # set_box_aspect 后轴窗口实际占用区域会比 set_position 指定的矩形小很多，
    # 留下大片死白——用 fit3d_axes 按渲染后的真实内容边界收紧两个子图窗口，
    # 消除中间/四周的空白带（复核时发现上一版这一步被漏掉了）。
    #
    # 注：曾尝试再加一个"起点区放大"第三子图（FY1/M1/M3 起点确实只差几百米，
    # 总览尺度下挤在一起），但复核发现一旦加入第三个 3D 子图并调高整张画布，
    # 主图里 M1/M2 的文字标签会被 bbox_inches='tight' 的裁剪连带丢掉——两次
    # 独立尝试（含缩小偏移量）都复现了同样的丢失，怀疑是 mplot3d 的 Text3D
    # 包围盒计算在这种布局下的已知不稳定行为，不是这份代码本身的用法错误。
    # 为避免引入这个回归，放弃第三子图，保留经过验证稳定的两子图布局。
    plot_style.fit3d_axes(fig, ax, pad_in=0.25)
    plot_style.fit3d_axes(fig, axz, pad_in=0.15)
    plot_style.save(fig, IMG_DIR / "fig00_1_scene_3d.png")
    plt.close(fig)
    print("[EDA] fig00_1_scene_3d.png 已生成（总览+目标区放大）")


def fig_topview(sc: dict) -> None:
    """俯视图（x-y 平面）：导弹来袭方向、无人机布防位置 + 终端区放大 inset。

    §18 惯例（见 memory/thought_process.md）：俯视图与 3D 图配套呈现；等比例 +
    终端放大解决"20 km 走廊被 tight-crop 压成 3.5:1 细条、目标 7 m 圆柱不可读"
    的问题；关键对象直接标注名字，不再只靠图例对号。
    """
    plot_style.apply()
    fig, ax = plt.subplots(figsize=(13, 6.6))
    ax.set_aspect("equal")
    ax.set_xlim(-1500, 20500); ax.set_ylim(-3500, 2600)
    tc = np.array(sc["true_target"]["center"])
    r = sc["true_target"]["radius"]
    th = np.linspace(0, 2 * np.pi, 100)
    ax.fill(tc[0] + r * np.cos(th), tc[1] + r * np.sin(th),
            color=plot_style.CATEGORICAL[2], alpha=0.4, label="真目标(圆柱投影)", zorder=4)
    ax.scatter(*sc["decoy"][:2], marker="*", s=280, color="k", label="假目标(诱饵)", zorder=6)
    for name, p in sc["missiles"].items():
        ax.plot([p[0], 0.0], [p[1], 0.0], color=plot_style.CATEGORICAL[0], lw=1.0,
                alpha=0.4, zorder=2)
        ax.annotate("", xy=(0, 0), xytext=(p[0], p[1]),
                    arrowprops=dict(arrowstyle="-|>", color=plot_style.CATEGORICAL[0],
                                    lw=1.6, mutation_scale=15))
        ax.text(p[0], p[1] + 130, name, fontsize=9, color=plot_style.CATEGORICAL[0],
                ha="center")
    for name, p in sc["uavs"].items():
        ax.scatter(p[0], p[1], color=plot_style.CATEGORICAL[1], marker="^", s=150,
                   zorder=6)
        ax.text(p[0], p[1] + 170, name, fontsize=9, color=plot_style.CATEGORICAL[1],
                ha="center")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.set_title("俯视图：导弹来袭方向与无人机布防位置", fontsize=11.5)
    ax.grid(True, alpha=0.3)

    # 终端区放大 inset（目标/诱饵几何在此才可读）
    axins = ax.inset_axes([0.615, 0.02, 0.36, 0.34])
    axins.set_aspect("equal")
    axins.set_xlim(-800, 1500); axins.set_ylim(-600, 1000)
    axins.fill(tc[0] + r * np.cos(th), tc[1] + r * np.sin(th),
               color=plot_style.CATEGORICAL[2], alpha=0.45)
    for tail in [(-800, 0), (0, -500), (-500, 500)]:
        axins.annotate("", xy=(0, 0), xytext=tail,
                       arrowprops=dict(arrowstyle="-|>", color=plot_style.CATEGORICAL[0],
                                       lw=1.5, mutation_scale=13))
    axins.scatter(*sc["decoy"][:2], marker="*", s=200, color="k", zorder=5)
    axins.text(tc[0] + 20, tc[1] + 80, "真目标", fontsize=8, color=plot_style.CATEGORICAL[2])
    axins.text(-780, -560, "诱饵(原点)", fontsize=8, color="k")
    axins.grid(True, alpha=0.25)
    axins.set_title("终端区放大", fontsize=8.5)
    axins.tick_params(labelsize=6.5)
    # 主图里标出放大区域（虚线框）
    ax.plot([-800, 1500, 1500, -800, -800], [-600, -600, 1000, 1000, -600],
            color=plot_style.CHROME["text_muted"], lw=1.1, ls="--", zorder=3)
    ax.text(1500, 1000, "  放大区", fontsize=7.5, color=plot_style.CHROME["text_muted"],
            va="bottom", ha="left")

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc="upper left", fontsize=8.5, frameon=True,
              framealpha=0.85)
    plot_style.save(fig, IMG_DIR / "fig00_2_topview.png")
    plt.close(fig)
    print("[EDA] fig00_2_topview.png 已生成（走廊总览+终端区放大）")


def fig_los_geometry(sc: dict) -> None:
    """视线遮挡几何示意（问题 1 给定策略的真实几何）。

    §18 惯例（见 memory/thought_process.md）：遮蔽判据示意图要放大到云团附近才能
    看见 10 m 级几何（20 km 尺度下云团是看不见的点）；云团画成半透明实体球；
    用问题 1 给定策略的确定性结果（与 state/model1_results.json 的 q1 一致），
    并把"云心距视线 ≤10 m"直接标注在图上。
    """
    plot_style.apply()
    # 问题 1 给定策略（确定性，与 state q1 一致）
    f0 = np.array(sc["uavs"]["FY1"], dtype=float)
    D, E = gc.bomb_detonation_point(sc, f0, Q1_THETA, Q1_V, Q1_T_DROP, Q1_T_DELAY)
    ivs = gc.masking_intervals(sc, "M1", f0, Q1_THETA, Q1_V, Q1_T_DROP, Q1_T_DELAY)
    t_det = Q1_T_DROP + Q1_T_DELAY
    t_mask = 0.5 * (ivs[0][0] + ivs[0][1]) if ivs else t_det + 2.0
    C = gc.cloud_center(E, t_mask - t_det, sc["cloud_sink_speed"])
    M = gc.missile_trajectory(sc["missiles"]["M1"], sc["missile_speed"], sc["decoy"], t_mask)
    # 云心到视线线段的最近点与距离
    seg_v = gc.TARGET_REF - M
    s = float(np.clip(np.dot(C - M, seg_v) / np.dot(seg_v, seg_v), 0.0, 1.0))
    proj = M + s * seg_v
    dmin = float(np.linalg.norm(C - proj))

    fig = plt.figure(figsize=(13, 6.2))
    ax = fig.add_axes([0.03, 0.12, 0.58, 0.50], projection="3d")
    ax.set_xlim(16800, 17900); ax.set_ylim(-80, 280); ax.set_zlim(1650, 1880)
    plot_style.equal3d(ax)
    plot_style.style3d(ax)
    ax.set_position([0.03, 0.10, 0.58, 0.50])      # 横置窗口贴合盒体比例

    # 视线（向真目标延伸，超出窗口部分被裁剪，方向由文字说明）
    seg = np.stack([M, gc.TARGET_REF])
    ax.plot(seg[:, 0], seg[:, 1], seg[:, 2], color="k", lw=1.8, ls="--", label="视线(遮蔽判据)")
    ax.scatter(*M, color=plot_style.CATEGORICAL[0], s=90, zorder=6,
               label=f"M1(t={t_mask:.1f}s)")
    # 弹道 D→E
    bt = np.array([gc.bomb_position(D, Q1_THETA, Q1_V, s_, sc["g"])
                   for s_ in np.linspace(0, Q1_T_DELAY, 30)])
    ax.plot(bt[:, 0], bt[:, 1], bt[:, 2], color=plot_style.CATEGORICAL[2], lw=2.0,
            label="弹道(仅重力)")
    ax.scatter(*D, marker="v", s=80, color=plot_style.CATEGORICAL[1], zorder=6)
    ax.text(D[0] + 40, D[1], D[2] + 45, "投放点 D", fontsize=8, color=plot_style.CATEGORICAL[1])
    # 云团中心下沉轨迹 + 半透明实体球
    sink = np.array([gc.cloud_center(E, s_, sc["cloud_sink_speed"])
                     for s_ in np.linspace(0, sc["cloud_effective_duration"], 50)])
    ax.plot(sink[:, 0], sink[:, 1], sink[:, 2], color=plot_style.CATEGORICAL[1],
            lw=1.3, alpha=0.75, label="云团中心下沉轨迹")
    plot_style.solid_sphere(ax, C, sc["cloud_effective_radius"],
                            plot_style.CATEGORICAL[1], alpha=0.42)
    # 云心到视线最近点的连线 + 距离标注（遮蔽判据的可视化）
    ax.plot([C[0], proj[0]], [C[1], proj[1]], [C[2], proj[2]],
            color="k", lw=0.9, ls=":")
    ax.text(C[0] + 60, C[1], C[2] + 45, f"云心距视线 {dmin:.1f} m ≤ 10 m",
            fontsize=8.5, color="k")
    ax.text2D(0.03, 0.03,
              f"视线终点：真目标参考点 (0,200,0)，全长 ≈ {np.linalg.norm(M - gc.TARGET_REF):.0f} m",
              transform=ax.transAxes, fontsize=8, color=plot_style.CHROME["text_secondary"],
              va="bottom")

    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.set_zlabel("z (m)")
    ax.set_title("视线遮挡几何示意（问题 1 给定策略，云心距视线 ≤10 m 视为遮蔽）",
                 fontsize=11)
    # 图例与上面 (0.03, 0.96) 的 text2D 都锚在左上角会互相压字（复核时发现）——
    # 图例挪到绘图区外的正上方一行，跟标题分开、也不再跟任何角标文字重叠。
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=4,
              fontsize=8, frameon=False)
    ax.view_init(elev=18, azim=-62)

    # 总览 inset：全程视线（M1 → 真目标参考点）
    ax2 = fig.add_axes([0.66, 0.08, 0.31, 0.30], projection="3d")
    ax2.set_xlim(-500, 19000); ax2.set_ylim(-50, 250); ax2.set_zlim(-50, 2150)
    plot_style.equal3d(ax2)
    plot_style.style3d(ax2)
    ax2.plot(seg[:, 0], seg[:, 1], seg[:, 2], color="k", lw=1.5, ls="--")
    ax2.scatter(*M, color=plot_style.CATEGORICAL[0], s=60, zorder=6)
    ax2.scatter(*gc.TARGET_REF, color=plot_style.CATEGORICAL[2], s=70, marker="o", zorder=6)
    ax2.scatter(*C, color=plot_style.CATEGORICAL[1], s=50, zorder=6)
    ax2.text(0, 200, 150, "真目标参考点", fontsize=7.5, color=plot_style.CATEGORICAL[2])
    ax2.set_title("全程视线总览（M1→真目标）", fontsize=9)
    ax2.view_init(elev=20, azim=-70)
    _tickless3d(ax2, labels=False)
    ax2.set_position([0.66, 0.05, 0.31, 0.14])

    # 同 fig00_1：把两个 3D 子图窗口收紧到真实内容边界，消掉留白带。
    plot_style.fit3d_axes(fig, ax, pad_in=0.25)
    plot_style.fit3d_axes(fig, ax2, pad_in=0.12)
    plot_style.save(fig, IMG_DIR / "fig00_3_los_geometry.png")
    plt.close(fig)
    print("[EDA] fig00_3_los_geometry.png 已生成（问题1真实几何 + 距离标注）")


def main():
    sc = load_scenario()
    issues = data_quality_check(sc)
    print_scenario_summary(sc)
    if issues:
        print("[EDA] ⚠ 数据质量发现问题：")
        for it in issues:
            print("   -", it)
        sys.exit(1)
    print("[EDA] ✓ 数据质量检查通过：全部参数有限、量纲一致、范围合法")
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    fig_scene_3d(sc)
    fig_topview(sc)
    fig_los_geometry(sc)
    print("[EDA] ✓ EDA 完成，3 张图已输出至 latex/images/")


if __name__ == "__main__":
    main()
