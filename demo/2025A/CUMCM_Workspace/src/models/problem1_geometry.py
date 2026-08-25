#!/usr/bin/env python3
"""
problem1_geometry.py — model_1（覆盖问题 1 + 问题 2）

问题 1：FY1 以 120 m/s 朝假目标方向飞行，受领任务 1.5 s 后投放 1 枚弹，间隔 3.6 s
        起爆 —— 给定策略的正演计算（几何运动学模型直接给出有效遮蔽时长）。
问题 2：确定 FY1 的飞行方向 θ、飞行速度 v、投放时刻 t_drop、起爆延迟 t_delay，
        使有效遮蔽时长最大 —— 连续优化（差分进化全局搜索 + 坐标轮换局部精化）。

核心函数：solve_problem2()（附录节选对象）——见几何模型 geometry_core.masking_intervals。
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
from scipy.optimize import differential_evolution, minimize

ROOT = Path(__file__).resolve().parents[2]           # CUMCM_Workspace
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 本目录（geometry_core）
sys.path.insert(0, str(ROOT.parent / "scripts"))
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import geometry_core as gc  # noqa: E402

SC = gc.load_scenario()
IMG_DIR = ROOT / "latex" / "images"

# 问题 1 的给定策略
Q1_THETA, Q1_V, Q1_T_DROP, Q1_T_DELAY = 180.0, 120.0, 1.5, 3.6

# 问题 2 优化边界：θ 0~360°；v 70~140 m/s；投放时刻 0~40 s；起爆延迟 0.5~15 s
# （题目未对起爆延迟设上限，放宽边界让优化器自由选择云团高度）
BOUNDS_Q2 = [(0.0, 360.0), (70.0, 140.0), (0.0, 40.0), (0.5, 15.0)]
# 引导权重：遮蔽时长单位秒；引导项 max(0, R-d_min) 最大为 R=10，权重 0.5 → 引导上限 5，
# 一旦找到能产生遮蔽的解（时长>0），真实时长占主导，引导项只在"零遮蔽平原"上起作用
GUIDE_WEIGHT = 0.5


def solve_problem1():
    """问题 1：给定策略的正演计算。"""
    dur, ivs = gc.single_bomb_masking(SC, "M1", "FY1", Q1_THETA, Q1_V, Q1_T_DROP, Q1_T_DELAY)
    f0 = SC["uavs"]["FY1"]
    D = gc.uav_position(f0, Q1_THETA, Q1_V, Q1_T_DROP)
    E = gc.bomb_position(D, Q1_THETA, Q1_V, Q1_T_DELAY, SC["g"])
    print("=" * 66)
    print("问题 1：给定策略的有效遮蔽时长（正演计算）")
    print("=" * 66)
    print(f"FY1 航向角 θ        : {Q1_THETA:.1f}°（朝假目标方向，即 -x）")
    print(f"FY1 速度            : {Q1_V:.1f} m/s")
    print(f"投放时刻            : {Q1_T_DROP:.2f} s（受领任务后）")
    print(f"起爆延迟            : {Q1_T_DELAY:.2f} s")
    print(f"投放点 D            : ({D[0]:.1f}, {D[1]:.1f}, {D[2]:.1f}) m")
    print(f"起爆点 E            : ({E[0]:.1f}, {E[1]:.1f}, {E[2]:.1f}) m")
    print(f"起爆时刻            : {Q1_T_DROP + Q1_T_DELAY:.2f} s")
    print(f"遮蔽时间区间        : {[(round(a, 2), round(b, 2)) for a, b in ivs]}")
    print(f"有效遮蔽时长        : {dur:.3f} s")
    return dur, ivs, D, E


def _objective_q2(x):
    """问题 2 目标：遮蔽时长取负（求最大），叠加 LOS 接近度引导项。"""
    theta, v, t_drop, t_delay = x
    dur, _, d_min = gc.single_bomb_masking_detail(SC, "M1", "FY1", theta, v, t_drop, t_delay)
    guide = max(0.0, SC["cloud_effective_radius"] - d_min)
    return -(dur + GUIDE_WEIGHT * guide)


def _physics_seeds():
    """物理启发的多起点：把云团直接放在"未来某时刻的视线"上，反解 (θ,v,t_drop,t_delay)。

    视线参数化：Q(t_m, z) = M(t_m) 与 P_T 连线上高度 z 的点。让起爆点 E ≈ Q，
    则 E_xy 决定水平位移 → 由 (v, t_drop+t_delay) 与方向 θ 反解；E_z 决定 t_delay。
    """
    sc = SC
    f0 = np.array(sc["uavs"]["FY1"], dtype=float)
    g = sc["g"]
    seeds = []
    for t_m in np.arange(5.0, 31.0, 1.0):
        M = gc.missile_trajectory(sc["missiles"]["M1"], sc["missile_speed"], sc["decoy"], t_m)
        v_los = gc.TARGET_REF - M
        for z_target in [1300.0, 1400.0, 1500.0, 1600.0, 1650.0, 1700.0, 1720.0, 1750.0, 1780.0]:
            if abs(v_los[2]) < 1e-9:
                continue
            lam = (z_target - M[2]) / v_los[2]
            if not (0.0 <= lam <= 1.0):
                continue
            Q = M + lam * v_los
            # 下沉修正（近似 t_det ≈ t_m）：E_z ≈ Q_z + 3·(t_m - t_det)
            E = Q.copy()
            dz = f0[2] - E[2]
            if dz < 0.0:
                continue
            t_delay = float(np.sqrt(2.0 * dz / g))
            E[2] = Q[2] + 3.0 * max(0.0, t_m - t_delay)  # 下沉补偿（粗略）
            dz = f0[2] - E[2]
            if dz < 0.0:
                continue
            t_delay = float(np.sqrt(2.0 * dz / g))
            if not (0.5 <= t_delay <= 10.0):
                continue
            H = E[:2] - f0[:2]
            dist_h = float(np.linalg.norm(H))
            if dist_h < 1e-6:
                continue
            theta = float(np.degrees(np.arctan2(H[1], H[0])) % 360.0)
            for v in np.arange(70.0, 141.0, 10.0):
                t_drop = dist_h / v - t_delay
                if 0.0 <= t_drop <= 30.0:
                    seeds.append((theta, float(v), t_drop, t_delay))
    # Q1 基线（已知产生遮蔽）
    seeds.append((180.0, 120.0, 1.5, 3.6))
    # 去重
    uniq, seen = [], set()
    for s in seeds:
        key = tuple(round(x, 1) for x in s)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


def _coordinate_refine(x0, bounds, n_passes=3, n_scan=41, half_frac=0.02):
    """坐标轮换爬山精化：逐变量在邻域内网格扫描，多轮收敛到局部最优。"""
    x = np.array(x0, dtype=float)
    for _ in range(n_passes):
        for k in range(len(bounds)):
            lo, hi = bounds[k]
            span = hi - lo
            half = max(span * half_frac, 1e-3)
            cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), n_scan)
            best_x, best_f = x.copy(), _objective_q2(x)
            for c in cand:
                xc = x.copy()
                xc[k] = c
                f = _objective_q2(xc)
                if f < best_f - 1e-12:
                    best_f, best_x = f, xc
            x = best_x
    dur, _, d_min = gc.single_bomb_masking_detail(SC, "M1", "FY1", *x)
    return x, dur


def solve_problem2():
    """问题 2：单机单弹投放策略优化（物理启发多起点 + 两级坐标轮换精化）。"""
    print("=" * 66)
    print("问题 2：单机单弹投放策略优化（物理启发多起点 + 坐标轮换精化）")
    print("=" * 66)
    seeds = _physics_seeds()
    print(f"[model_1] 生成物理启发起点 {len(seeds)} 个")
    # 第 0 步：全部起点单次评分，保留 top 30
    scored = sorted(((_objective_q2(s), s) for s in seeds), key=lambda t: t[0])
    top = scored[:30]
    print(f"[model_1] 起点评分 top3 目标值: {[-s[0] for s in top[:3]]}")
    # 第一阶段粗精化（±5% span），选出最好的 8 个
    refined = []
    for _, s in top:
        x, dur = _coordinate_refine(s, BOUNDS_Q2, n_passes=2, n_scan=25, half_frac=0.05)
        refined.append((dur, x))
    refined.sort(key=lambda t: -t[0])
    print(f"[model_1] 粗精化后 top3 时长: "
          f"{[round(r[0], 3) for r in refined[:3]]} s")
    # 第二阶段细精化（±1% span）取最优
    best_dur, best_x = -1.0, None
    for dur, x in refined[:8]:
        x2, dur2 = _coordinate_refine(x, BOUNDS_Q2, n_passes=3, n_scan=41, half_frac=0.01)
        if dur2 > best_dur:
            best_dur, best_x = dur2, x2
    theta, v, t_drop, t_delay = best_x
    f0 = SC["uavs"]["FY1"]
    D = gc.uav_position(f0, theta, v, t_drop)
    E = gc.bomb_position(D, theta, v, t_delay, SC["g"])
    _, ivs = gc.single_bomb_masking(SC, "M1", "FY1", theta, v, t_drop, t_delay)
    print(f"最优航向角 θ        : {theta:.3f}°")
    print(f"最优速度 v          : {v:.3f} m/s")
    print(f"最优投放时刻        : {t_drop:.3f} s")
    print(f"最优起爆延迟        : {t_delay:.3f} s")
    print(f"投放点 D            : ({D[0]:.1f}, {D[1]:.1f}, {D[2]:.1f}) m")
    print(f"起爆点 E            : ({E[0]:.1f}, {E[1]:.1f}, {E[2]:.1f}) m")
    print(f"遮蔽时间区间        : {[(round(a, 2), round(b, 2)) for a, b in ivs]}")
    print(f"最大有效遮蔽时长    : {best_dur:.3f} s")
    return dict(theta=theta, v=v, t_drop=t_drop, t_delay=t_delay, D=D, E=E, dur=best_dur, ivs=ivs)


def fig_masking_window(ivs_q1, ivs_q2, out_name="fig01_masking_window.png"):
    """Q1/Q2 遮蔽时间窗口对比图。

    §18 惯例（见 memory/thought_process.md）：时间窗口图保留水平条形 + 时间轴，
    去掉多余留白（x 轴裁到实际区间范围）、条形末端直接标时长数值。
    """
    plot_style.apply()
    rows = [("问题1给定策略", ivs_q1, plot_style.CATEGORICAL[0]),
            ("问题2优化策略", ivs_q2, plot_style.CATEGORICAL[1])]
    max_end = max((b for _, ivs, _ in rows for _, b in ivs), default=10.0)
    fig, ax = plt.subplots(figsize=(8.5, 3.1))
    for label, ivs, color in rows:
        if not ivs:
            continue
        for a, b in ivs:
            ax.barh(label, b - a, left=a, height=0.5, color=color, alpha=0.85)
        total = sum(b - a for a, b in ivs)
        last_b = max(ivs, key=lambda t: t[1])[1]
        ax.text(last_b + 0.2, label, f"{total:.2f} s", va="center", fontsize=9,
                color=color)
    ax.set_xlabel("时间 t (s)")
    ax.set_title("有效遮蔽时间窗口对比")
    ax.set_xlim(0, max_end + 1.8)
    ax.grid(True, axis="x", alpha=0.3)
    plot_style.save(fig, IMG_DIR / out_name)
    plt.close(fig)
    print(f"[model_1] {out_name} 已生成")


def fig_q2_trajectory(opt, out_name="fig01_q2_trajectory.png"):
    """问题 2 优化解的三维轨迹图（交战区放大 + 全走廊总览双子图）。

    §18 惯例调研（见 memory/thought_process.md）：混尺度轨迹图（20 km 导弹全程
    vs 几十米内的投放/起爆点）单视角必然把关键点挤成一团，常规画法是"放大 +
    总览"双子图：左图放大交战区（D/E/云团/视线/遮蔽段全部可读），右图保留
    20 km 走廊上下文；云团下沉轨迹按"是否落在遮蔽时间区间内"分段上色。
    """
    plot_style.apply()
    fig = plt.figure(figsize=(13.5, 6.2))
    axa = fig.add_axes([0.02, 0.06, 0.46, 0.62], projection="3d")   # 交战区放大
    axb = fig.add_axes([0.53, 0.06, 0.44, 0.62], projection="3d")   # 全走廊总览

    t_det = opt["t_drop"] + opt["t_delay"]
    ivs = opt["ivs"]
    D = np.asarray(opt["D"], dtype=float)
    E = np.asarray(opt["E"], dtype=float)
    ts = np.linspace(0, 30, 120)
    mt = np.array([gc.missile_trajectory(SC["missiles"]["M1"], SC["missile_speed"],
                                         SC["decoy"], t) for t in ts])
    ct_ts = np.linspace(0, SC["cloud_effective_duration"], 80)
    ct = np.array([gc.cloud_center(E, s, SC["cloud_sink_speed"]) for s in ct_ts])
    abs_t = t_det + ct_ts
    in_mask = np.array([any(a <= tt <= b for a, b in ivs) for tt in abs_t])
    m_in_mask = np.array([any(a <= t <= b for a, b in ivs) for t in ts])
    bt = np.array([gc.bomb_position(D, opt["theta"], opt["v"], s, SC["g"])
                   for s in np.linspace(0, opt["t_delay"], 40)])
    # 遮蔽窗口内取一个代表时刻（云团球体画在这里）
    t_mid = 0.5 * (ivs[0][0] + ivs[0][1]) if ivs else t_det
    Cmid = gc.cloud_center(E, t_mid - t_det, SC["cloud_sink_speed"])
    Mm = gc.missile_trajectory(SC["missiles"]["M1"], SC["missile_speed"], SC["decoy"], t_mid)

    # ── 左：交战区放大 ──
    axa.set_xlim(16700, 18600); axa.set_ylim(-120, 420); axa.set_zlim(1580, 1980)
    plot_style.equal3d(axa)
    plot_style.style3d(axa)
    axa.plot(mt[~m_in_mask, 0], mt[~m_in_mask, 1], mt[~m_in_mask, 2],
             color=plot_style.CATEGORICAL[0], lw=1.5, alpha=0.85)
    if m_in_mask.any():
        axa.plot(mt[m_in_mask, 0], mt[m_in_mask, 1], mt[m_in_mask, 2],
                 color=plot_style.STATUS["good"], lw=3.0)
    axa.plot(bt[:, 0], bt[:, 1], bt[:, 2], color=plot_style.CATEGORICAL[2], lw=2.2)
    axa.plot(ct[~in_mask, 0], ct[~in_mask, 1], ct[~in_mask, 2],
             color=plot_style.CHROME["text_muted"], lw=1.3, alpha=0.6)
    if in_mask.any():
        axa.plot(ct[in_mask, 0], ct[in_mask, 1], ct[in_mask, 2],
                 color=plot_style.STATUS["good"], lw=3.2)
    plot_style.solid_sphere(axa, Cmid, SC["cloud_effective_radius"],
                            plot_style.CATEGORICAL[1], alpha=0.35)
    seg = np.stack([Mm, gc.TARGET_REF])
    axa.plot(seg[:, 0], seg[:, 1], seg[:, 2], color="k", lw=1.2, ls="--", alpha=0.85)
    # D/E 标签：3D 数据空间里的偏移量在某些视角下投影到屏幕仍会压字（复核时
    # 实测发现"投放/起爆"两行文字在 elev=18/azim=-58 视角下几乎重叠），改成
    # 屏幕空间固定角标（text2D，不随 3D 投影变化，绝对不会跟场景内容压字），
    # 3D marker 只保留点位不再直接挂文字。
    axa.scatter(*D, marker="v", s=120, color=plot_style.CATEGORICAL[1], zorder=6)
    axa.scatter(*E, marker="o", s=120, color=plot_style.CATEGORICAL[2], zorder=6)
    if ivs:
        a0, b0 = ivs[0]
        axa.text2D(0.03, 0.97, f"遮蔽窗口 [{a0:.2f}, {b0:.2f}] s，共 {opt['dur']:.2f} s",
                   transform=axa.transAxes, fontsize=8.5, color=plot_style.STATUS["good"],
                   va="top")
    axa.text2D(0.03, 0.90, f"▽ 投放 t={opt['t_drop']:.2f}s", transform=axa.transAxes,
               fontsize=8.5, color=plot_style.CATEGORICAL[1], va="top")
    axa.text2D(0.03, 0.84, f"● 起爆 t={t_det:.2f}s", transform=axa.transAxes,
               fontsize=8.5, color=plot_style.CATEGORICAL[2], va="top")
    axa.set_xlabel("x (m)"); axa.set_ylabel("y (m)"); axa.set_zlabel("z (m)")
    axa.set_title("交战区放大：投放/起爆点、云团与视线", fontsize=10.5)
    axa.view_init(elev=18, azim=-58)
    axa.set_position([0.005, 0.06, 0.50, 0.62])

    # ── 右：全走廊总览（保留 20 km 上下文）──
    axb.set_xlim(10000, 20500); axb.set_ylim(-300, 500); axb.set_zlim(900, 2100)
    plot_style.equal3d(axb, box=(1.0, 0.42, 0.42))
    plot_style.style3d(axb)
    axb.plot(mt[:, 0], mt[:, 1], mt[:, 2], color=plot_style.CATEGORICAL[0], lw=1.6,
             label="M1 飞行轨迹")
    if m_in_mask.any():
        axb.plot(mt[m_in_mask, 0], mt[m_in_mask, 1], mt[m_in_mask, 2],
                 color=plot_style.STATUS["good"], lw=3.0)
    ts_uav = np.linspace(0, opt["t_drop"], 40)
    ut = np.array([gc.uav_position(SC["uavs"]["FY1"], opt["theta"], opt["v"], t)
                   for t in ts_uav])
    axb.plot(ut[:, 0], ut[:, 1], ut[:, 2], color=plot_style.CATEGORICAL[1], lw=1.6,
             ls="--", label="FY1 飞行轨迹")
    axb.plot(bt[:, 0], bt[:, 1], bt[:, 2], color=plot_style.CATEGORICAL[2], lw=2.2,
             label="弹道(仅重力)")
    axb.plot(ct[~in_mask, 0], ct[~in_mask, 1], ct[~in_mask, 2],
             color=plot_style.CHROME["text_muted"], lw=1.4, alpha=0.6,
             label="云团中心轨迹（未遮蔽）")
    if in_mask.any():
        axb.plot(ct[in_mask, 0], ct[in_mask, 1], ct[in_mask, 2],
                 color=plot_style.STATUS["good"], lw=3.2,
                 label=f"遮蔽中（{opt['dur']:.2f}s）")
    axb.scatter(*D, marker="v", s=80, color=plot_style.CATEGORICAL[1], label="投放点 D",
                zorder=6)
    axb.scatter(*E, marker="o", s=80, color=plot_style.CATEGORICAL[2], label="起爆点 E",
                zorder=6)
    # 放在 axb 顶部而不是底部：底部离图下方的整图图例太近，fit3d_axes 收紧
    # 窗口后两者实测会紧贴甚至压字。
    axb.text2D(0.03, 0.95, "视线终点：真目标参考点 (0,200,0)",
               transform=axb.transAxes, fontsize=8, color=plot_style.CHROME["text_secondary"],
               va="top")
    axb.set_xlabel("x (m)"); axb.set_ylabel("y (m)"); axb.set_zlabel("z (m)")
    axb.set_title("全走廊总览（导弹 0~30 s 飞行）", fontsize=10.5)
    axb.view_init(elev=16, azim=-75)
    axb.set_position([0.53, 0.06, 0.43, 0.60])

    handles, labels = axb.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.005),
               ncol=4, fontsize=8.3, frameon=False)
    # set_box_aspect 后两个子图的实际渲染内容比 set_position 指定的矩形窄得多，
    # 中间/两侧留下大片死白——用 fit3d_axes 按渲染后的真实边界收紧窗口。
    plot_style.fit3d_axes(fig, axa, pad_in=0.22)
    plot_style.fit3d_axes(fig, axb, pad_in=0.22)
    plot_style.save(fig, IMG_DIR / out_name)
    plt.close(fig)
    print(f"[model_1] {out_name} 已生成（交战区放大+全走廊总览）")


def main():
    dur1, ivs1, D1, E1 = solve_problem1()
    opt = solve_problem2()
    print(f"\n[model_1] 提升幅度：问题1 {dur1:.3f} s → 问题2 {opt['dur']:.3f} s "
          f"(+{opt['dur'] - dur1:.3f} s)")
    fig_masking_window(ivs1, opt["ivs"])
    fig_q2_trajectory(opt)
    # 结果缓存（供验证脚本使用，避免重复优化）
    cache = {
        "q1": {"dur": dur1, "ivs": ivs1, "theta": Q1_THETA, "v": Q1_V,
               "t_drop": Q1_T_DROP, "t_delay": Q1_T_DELAY,
               "D": [float(x) for x in D1], "E": [float(x) for x in E1]},
        "q2": {"theta": float(opt["theta"]), "v": float(opt["v"]),
               "t_drop": float(opt["t_drop"]), "t_delay": float(opt["t_delay"]),
               "D": [float(x) for x in opt["D"]], "E": [float(x) for x in opt["E"]],
               "dur": float(opt["dur"]), "ivs": opt["ivs"]},
    }
    out = ROOT / "state" / "model1_results.json"
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[model_1] 结果缓存 → {out}")
    return opt


if __name__ == "__main__":
    main()
