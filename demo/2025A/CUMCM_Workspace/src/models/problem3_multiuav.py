#!/usr/bin/env python3
"""
problem3_multiuav.py — model_3（覆盖问题 4 + 问题 5）

问题 4：FY1、FY2、FY3 三架无人机各投放 1 枚烟幕干扰弹，实施对 M1 的干扰，
        设计投放策略使 3 弹对 M1 的并集遮蔽时长最长（12 维优化）。
问题 5：FY1~FY5 五架无人机，每架至多 3 枚弹，实施对 M1、M2、M3 三枚导弹的干扰，
        使"对真目标的总有效遮蔽时长"= Σ_{k} 并集遮蔽时长(导弹 k) 最长。

求解方法（沿用 problem1_geometry 的成熟套路：物理启发多起点 + 坐标轮换精化）：
  - 问题 4：每架无人机独立做"单弹对 M1"的多起点优化 → 组合成若干联合起点 →
            按"轮流精化每机 4 变量"的坐标轮换做 2~3 轮联合精化（先 ±5% 后 ±1% span）。
  - 问题 5：阶段 1 对每个 (无人机 j, 导弹 k) 组合求最优单弹解；
            阶段 2 按单弹时长/边际增益贪心分配（同机至多 3 弹、同机投放间隔 ≥1 s）；
            阶段 3 对选中的每枚弹做局部精化（保持同机间隔约束）后整体确认。
  注：禁止直接用 scipy differential_evolution 从随机初始种群跑（可行域极窄，易陷零值平原）。

结果输出：
  - result2.xlsx / result3.xlsx（模板填写 + 复制到 output/）
  - state/model3_results.json（供验证脚本读取）
  - latex/images/fig03_q4_masking_window.png、fig03_q5_assignment.png

共享几何模型 geometry_core 已 approved，直接 import，禁止修改/重新实现。
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]                # CUMCM_Workspace
sys.path.insert(0, str(Path(__file__).resolve().parent))  # src/models (geometry_core)
sys.path.insert(0, str(ROOT.parent / "scripts"))          # plot_style
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import geometry_core as gc  # noqa: E402

SC = gc.load_scenario()
IMG_DIR = ROOT / "latex" / "images"
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "output"

VAR_NAMES = ["theta", "v", "t_drop", "t_delay"]
# 变量边界：θ 0~360°；v 70~140 m/s；投放时刻 0~40 s；起爆延迟 0.5~15 s
BOUNDS = [(0.0, 360.0), (70.0, 140.0), (0.0, 40.0), (0.5, 15.0)]
# 引导权重：在"零遮蔽平原"上用 LOS 接近度 (R-d_min) 引导搜索（沿用 model_1）
GUIDE_WEIGHT = 0.5

Q4_UAVS = ["FY1", "FY2", "FY3"]
Q5_UAVS = ["FY1", "FY2", "FY3", "FY4", "FY5"]
MISSILES = ["M1", "M2", "M3"]


# ---------------------------------------------------------------------------
# 目标函数
# ---------------------------------------------------------------------------
def _obj_single(x, m_name, f_name, sc=None):
    """单弹目标：遮蔽时长取负 + LOS 接近度引导项（对导弹 m_name、无人机 f_name）。"""
    sc = sc or SC
    theta, v, t_drop, t_delay = x
    dur, _, d_min = gc.single_bomb_masking_detail(sc, m_name, f_name, theta, v, t_drop, t_delay)
    guide = max(0.0, sc["cloud_effective_radius"] - d_min)
    return -(dur + GUIDE_WEIGHT * guide)


def _obj_single_fixed_dv(x, m_name, f_name, theta, v, sc=None):
    """固定 (θ, v) 下对 (t_drop, t_delay) 的目标（同机 θ/v 一旦确定不再调整）。"""
    sc = sc or SC
    t_drop, t_delay = x
    dur, _, d_min = gc.single_bomb_masking_detail(sc, m_name, f_name, theta, v, t_drop, t_delay)
    guide = max(0.0, sc["cloud_effective_radius"] - d_min)
    return -(dur + GUIDE_WEIGHT * guide)


def q4_union_dur(plan, sc=None):
    """问题 4 目标：3 弹（每机 1 弹）对 M1 的并集遮蔽时长。

    plan: {f_name: (theta, v, t_drop, t_delay), ...}
    """
    sc = sc or SC
    bombs = [(f, th, v, td, tl) for f, (th, v, td, tl) in plan.items()]
    return gc.multi_bomb_union_masking(sc, "M1", bombs)


def _q4_obj(plan, sc=None):
    return -q4_union_dur(plan, sc)


def total_objective(plan, sc=None):
    """问题 5 目标：Σ_k 并集遮蔽时长(导弹 k)，plan 为 dict 列表（b["m"] 为导弹编号）。"""
    sc = sc or SC
    tot = 0.0
    for m in MISSILES:
        bombs = [(b["f"], b["theta"], b["v"], b["t_drop"], b["t_delay"])
                 for b in plan if b["m"] == m]
        if bombs:
            tot += gc.multi_bomb_union_masking(sc, m, bombs)
    return tot


def per_missile_durs(plan, sc=None):
    sc = sc or SC
    durs = {}
    for m in MISSILES:
        bombs = [(b["f"], b["theta"], b["v"], b["t_drop"], b["t_delay"])
                 for b in plan if b["m"] == m]
        durs[m] = gc.multi_bomb_union_masking(sc, m, bombs) if bombs else 0.0
    return durs


# ---------------------------------------------------------------------------
# 物理启发多起点（推广 problem1_geometry._physics_seeds 到任意 (无人机, 导弹)）
# ---------------------------------------------------------------------------
def _physics_seeds_for(sc, f_name, m_name, cfg=None):
    """把云团放在"未来某时刻 t_m 导弹 M(t_m)→P_T 视线"上，精确反解 (θ, v, t_drop, t_delay)。

    精确推导（避免早期近似把 t_det 误当作 t_delay 的偏移错误）：
      视线高度 z_target ≤ 该机高度 → Q 为视线上该高度的点（云团目标位置）；
      云团水平位置 E_xy = f0_xy + v·t_det·(cosθ,sinθ) = Q_xy → t_det = |Q_xy - f0_xy| / v；
      云团在 t_m 时刻须到达 Q：E_z = Q_z + 3·(t_m - t_det)（下沉补偿，精确）；
      自由落体：E_z = z_uav - ½g·t_delay² → t_delay = sqrt(2·(z_uav - E_z)/g)；
      t_drop = t_det - t_delay ≥ 0。
    这样生成的起点其 d_min ≈ 0（云团在 t_m 恰在视线上），引导项能把精化带向真实遮蔽解。
    """
    cfg = cfg or {}
    f0 = np.array(sc["uavs"][f_name], dtype=float)
    g = sc["g"]
    m0 = np.array(sc["missiles"][m_name], dtype=float)
    decoy = np.array(sc["decoy"], dtype=float)
    dist = float(np.linalg.norm(decoy - m0))
    u = (decoy - m0) / dist
    t_arrive = dist / sc["missile_speed"]
    z_uav = f0[2]
    if abs(u[2]) > 1e-9:
        t_cross = (z_uav - m0[2]) / (sc["missile_speed"] * u[2])
    else:
        t_cross = 0.0
    t_start = max(2.0, t_cross - cfg.get("t_before", 12.0))
    t_end = min(t_arrive - 2.0, t_cross + cfg.get("t_after", 20.0))
    z_fracs = cfg.get("z_fracs", [0.40, 0.55, 0.70, 0.80, 0.88, 0.94, 0.98])
    v_grid = np.arange(70.0, 141.0 + 1e-9, cfg.get("v_step", 10.0))
    t_step = cfg.get("t_step", 1.0)
    max_delay = cfg.get("max_delay", 12.0)
    seeds = []
    for t_m in np.arange(t_start, t_end + 1e-9, t_step):
        M = gc.missile_trajectory(m0, sc["missile_speed"], decoy, t_m)
        v_los = gc.TARGET_REF - M
        if abs(v_los[2]) < 1e-9:
            continue
        for zf in z_fracs:
            z_target = zf * z_uav
            lam = (z_target - M[2]) / v_los[2]
            if not (0.0 <= lam <= 1.0):
                continue
            Q = M + lam * v_los
            H = Q[:2] - f0[:2]
            dist_h = float(np.linalg.norm(H))
            if dist_h < 1e-6:
                continue
            theta = float(np.degrees(np.arctan2(H[1], H[0])) % 360.0)
            for v in v_grid:
                t_det = dist_h / v
                if not (t_det - 1e-9 <= t_m <= t_det + sc["cloud_effective_duration"] + 1e-9):
                    continue  # 云团在 t_m 时必须已起爆且仍在有效期内
                E_z = Q[2] + sc["cloud_sink_speed"] * (t_m - t_det)  # 精确下沉补偿
                if E_z < 0.0 or E_z > z_uav:
                    continue
                t_delay = float(np.sqrt(2.0 * (z_uav - E_z) / g))
                if not (0.5 <= t_delay <= max_delay):
                    continue
                t_drop = t_det - t_delay
                if 0.0 <= t_drop <= 30.0:
                    seeds.append((theta, float(v), t_drop, t_delay))
    # Q1 基线（仅 FY1/M1 有意义，但保留无害）
    seeds.append((180.0, 120.0, 1.5, 3.6))
    # 去重
    uniq, seen = [], set()
    for s in seeds:
        key = tuple(round(x, 1) for x in s)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


def _grid_seeds():
    """兜底粗网格起点（保证可行域各区域都有覆盖，含零值平原的引导）。"""
    seeds = []
    for th in np.arange(0.0, 360.0, 30.0):
        for v in np.arange(80.0, 141.0, 20.0):
            for td in np.arange(0.0, 41.0, 10.0):
                for tl in np.arange(1.0, 13.0, 3.0):
                    seeds.append((float(th), float(v), float(td), float(tl)))
    return seeds


# ---------------------------------------------------------------------------
# 坐标轮换精化（单弹）
# ---------------------------------------------------------------------------
def _coord_refine_single(sc, m_name, f_name, x0, n_passes=2, n_scan=21, half_frac=0.05):
    x = np.array(x0, dtype=float)
    for _ in range(n_passes):
        for k in range(len(BOUNDS)):
            lo, hi = BOUNDS[k]
            span = hi - lo
            half = max(span * half_frac, 1e-3)
            cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), n_scan)
            best_x, best_f = x.copy(), _obj_single(x, m_name, f_name, sc)
            for c in cand:
                xc = x.copy()
                xc[k] = c
                f = _obj_single(xc, m_name, f_name, sc)
                if f < best_f - 1e-12:
                    best_f, best_x = f, xc
            x = best_x
    theta, v, t_drop, t_delay = x
    dur, _ = gc.single_bomb_masking(sc, m_name, f_name, theta, v, t_drop, t_delay)
    return x, dur


def single_bomb_solutions(sc, m_name, f_name, cfg=None, n_keep=3):
    """单弹优化器：物理启发多起点 + 粗/细两级坐标轮换，返回 top-n_keep 解列表。"""
    cfg = cfg or {}
    seeds = _physics_seeds_for(sc, f_name, m_name, cfg) + _grid_seeds()
    scored = sorted(((_obj_single(s, m_name, f_name, sc), s) for s in seeds),
                    key=lambda t: t[0])
    top = scored[: cfg.get("n_top", 12)]
    refined = []
    for _, s in top:
        x, dur = _coord_refine_single(sc, m_name, f_name, s, n_passes=2, n_scan=21, half_frac=0.05)
        refined.append((dur, x))
    refined.sort(key=lambda t: -t[0])
    sols = []
    for dur, x in refined[: max(n_keep, 4)]:
        x2, dur2 = _coord_refine_single(sc, m_name, f_name, x, n_passes=3, n_scan=41, half_frac=0.01)
        theta, v, t_drop, t_delay = x2
        _, ivs = gc.single_bomb_masking(sc, m_name, f_name, theta, v, t_drop, t_delay)
        sols.append(dict(f_name=f_name, m_name=m_name, theta=float(theta), v=float(v),
                         t_drop=float(t_drop), t_delay=float(t_delay), dur=float(dur2),
                         ivs=[list(iv) for iv in ivs]))
    sols.sort(key=lambda s: -s["dur"])
    return sols


# ---------------------------------------------------------------------------
# 问题 4：三机各 1 弹对 M1（联合优化）
# ---------------------------------------------------------------------------
def _joint_refine(plan, sc, n_rounds=2, n_scan=25, half_frac=0.05):
    """坐标轮换联合精化：轮流对每架无人机的 4 个变量精化（其余两机固定）。"""
    for _ in range(n_rounds):
        for f in list(plan.keys()):
            x = np.array(plan[f], dtype=float)
            for k in range(len(BOUNDS)):
                lo, hi = BOUNDS[k]
                span = hi - lo
                half = max(span * half_frac, 1e-3)
                cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), n_scan)
                trial = {ff: (vv if ff != f else x) for ff, vv in plan.items()}
                best_x, best_f = x.copy(), _q4_obj(trial, sc)
                for c in cand:
                    xc = x.copy()
                    xc[k] = c
                    trial = {ff: (vv if ff != f else xc) for ff, vv in plan.items()}
                    fv = _q4_obj(trial, sc)
                    if fv < best_f - 1e-12:
                        best_f, best_x = fv, xc
                x = best_x
            plan[f] = x
    return plan


def _stagger(plan, shifts):
    """对 plan 各机 t_drop 施加平移（用于构造不同联合起点），clip 到可行域。"""
    out = {}
    for f, (th, v, td, tl) in plan.items():
        td2 = float(np.clip(td + shifts.get(f, 0.0), BOUNDS[2][0], BOUNDS[2][1]))
        out[f] = (th, v, td2, tl)
    return out


def solve_problem4(cfg=None):
    """问题 4 求解：每机单弹优化 → 多联合起点 → 联合精化 → 取最优。"""
    cfg = cfg or {}
    print("=" * 70)
    print("问题 4：FY1/FY2/FY3 各投 1 弹对 M1 的联合投放策略优化")
    print("=" * 70)
    per_uav = {}
    for f in Q4_UAVS:
        per_uav[f] = single_bomb_solutions(SC, "M1", f, cfg, n_keep=3)
        print(f"[model_3/Q4] {f} 单弹最优时长 top3: "
              f"{[round(s['dur'], 3) for s in per_uav[f]]} s")

    def pick(choice):
        return {f: np.array([per_uav[f][choice[i]][k] for k in VAR_NAMES])
                for i, f in enumerate(Q4_UAVS)}

    rng = np.random.default_rng(2025)
    anchor = pick([0, 0, 0])
    starts = [anchor]
    starts.append(_stagger(anchor, {"FY1": 0.0, "FY2": 4.0, "FY3": 8.0}))
    starts.append(_stagger(anchor, {"FY1": 8.0, "FY2": 4.0, "FY3": 0.0}))
    starts.append(pick([1, 1, 1]))
    starts.append(pick([2, 2, 2]))
    jit = {f: tuple(v * (1.0 + rng.uniform(-0.03, 0.03)) for v in anchor[f]) for f in Q4_UAVS}
    starts.append({f: np.array([float(np.clip(jit[f][k], BOUNDS[k][0], BOUNDS[k][1]))
                                for k in range(4)]) for f in Q4_UAVS})
    starts.append(pick([1, 0, 2]))
    if cfg.get("joint_n_starts"):
        starts = starts[: cfg["joint_n_starts"]]
    print(f"[model_3/Q4] 联合起点数: {len(starts)}")

    refined = []
    n_coarse_passes = cfg.get("joint_coarse_passes", 2)
    n_coarse_scans = cfg.get("joint_coarse_scans", 25)
    for si, s in enumerate(starts):
        plan = {f: np.array(s[f], dtype=float) for f in Q4_UAVS}
        plan = _joint_refine(plan, SC, n_rounds=n_coarse_passes, n_scan=n_coarse_scans,
                             half_frac=0.05)
        dur = q4_union_dur(plan)
        refined.append((dur, plan))
        print(f"[model_3/Q4] 起点{si} 粗精化后并集时长 = {dur:.4f} s")
    refined.sort(key=lambda t: -t[0])
    if cfg.get("joint_fine", True):
        n_fine = cfg.get("joint_n_fine", 3)
        fine = []
        for dur, plan in refined[:n_fine]:
            plan2 = {f: np.array(plan[f], dtype=float) for f in Q4_UAVS}
            plan2 = _joint_refine(plan2, SC, n_rounds=3, n_scan=41, half_frac=0.01)
            fine.append((q4_union_dur(plan2), plan2))
        fine.sort(key=lambda t: -t[0])
        refined = fine

    best_dur, best_plan = refined[0]
    bombs_out = []
    for f in Q4_UAVS:
        th, v, td, tl = best_plan[f]
        D, E = gc.bomb_detonation_point(SC, SC["uavs"][f], th, v, td, tl)
        dur_i, ivs_i = gc.single_bomb_masking(SC, "M1", f, th, v, td, tl)
        bombs_out.append(dict(f_name=f, theta=float(th), v=float(v), t_drop=float(td),
                              t_delay=float(tl), D=[float(x) for x in D],
                              E=[float(x) for x in E], dur=float(dur_i),
                              ivs=[list(iv) for iv in ivs_i]))
        print(f"[model_3/Q4] {f}: θ={th:.3f}° v={v:.3f} m/s t_drop={td:.3f} s "
              f"t_delay={tl:.3f} s 单弹时长={dur_i:.3f} s 区间={[(round(a,2),round(b,2)) for a,b in ivs_i]}")
    all_ivs = []
    for b in bombs_out:
        all_ivs += b["ivs"]
    print(f"[model_3/Q4] 总并集遮蔽时长 = {best_dur:.4f} s")
    print(f"[model_3/Q4] 并集区间 = {[(round(a,2), round(b,2)) for a,b in _merge_intervals(sorted(all_ivs))]}")
    return dict(total_dur=best_dur, bombs=bombs_out)


def _merge_intervals(ivs):
    if not ivs:
        return []
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


# ---------------------------------------------------------------------------
# 问题 5：5 机 × 至多 3 弹 × 3 导弹（分阶段：单弹优化 → 贪心分配 → 局部精化）
# ---------------------------------------------------------------------------
def _snap_tdrop(td0, avoid=()):
    """把 t_drop 移到最近的可投放时刻（与同机已有弹的投放间隔 ≥ 1 s）。"""
    lo, hi = BOUNDS[2]
    cand = np.linspace(lo, hi, 161)
    best, bestd = None, 1e18
    for c in cand:
        if any(abs(c - d) < 1.0 - 1e-9 for d in avoid):
            continue
        d = abs(c - td0)
        if d < bestd:
            bestd, best = d, c
    if best is None:  # 理论上不可能（40 s 窗口 ≥ 3 弹），兜底 clip
        return float(np.clip(td0, lo, hi))
    return float(best)


def _locked_seeds(sc, m_name, f_name, theta, v, avoid_drops=()):
    """固定 (θ,v) 下 (t_drop, t_delay) 的物理启发起点。

    云团水平位置必须落在"从 f0_xy 出发、方向 θ、速率 v"的射线上（t_det = 投影距离/v），
    云团在 t_m 时刻位于视线 Q 上：E_z = Q_z + 3(t_m - t_det)，t_delay 由自由落体反解。
    """
    f0 = np.array(sc["uavs"][f_name], dtype=float)
    g = sc["g"]
    m0 = np.array(sc["missiles"][m_name], dtype=float)
    decoy = np.array(sc["decoy"], dtype=float)
    dist = float(np.linalg.norm(decoy - m0))
    u = (decoy - m0) / dist
    t_arrive = dist / sc["missile_speed"]
    z_uav = f0[2]
    t_cross = (z_uav - m0[2]) / (sc["missile_speed"] * u[2]) if abs(u[2]) > 1e-9 else 0.0
    t_start = max(2.0, t_cross - 12.0)
    t_end = min(t_arrive - 2.0, t_cross + 20.0)
    z_fracs = [0.45, 0.60, 0.75, 0.85, 0.92, 0.97, 0.99]
    th = np.deg2rad(theta)
    dir_h = np.array([np.cos(th), np.sin(th), 0.0])
    seeds = []
    for t_m in np.arange(t_start, t_end + 1e-9, 1.0):
        M = gc.missile_trajectory(m0, sc["missile_speed"], decoy, t_m)
        v_los = gc.TARGET_REF - M
        if abs(v_los[2]) < 1e-9:
            continue
        for zf in z_fracs:
            z_target = zf * z_uav
            lam = (z_target - M[2]) / v_los[2]
            if not (0.0 <= lam <= 1.0):
                continue
            Q = M + lam * v_los
            w = Q[:2] - f0[:2]
            proj = float(np.dot(w, dir_h[:2]))
            if proj < 0.0:
                continue
            perp = float(np.linalg.norm(w - proj * dir_h[:2]))
            # 注意：种子只是初始猜测，云团实际只需在视线"线段"10 m 带内即可遮蔽，
            # 视线点与射线的垂距可以大于 10 m（3D 几何下最近点不在云团高度处）。
            # 取 25 m 作为松弛阈值，避免把可行解（如 FY5→M2 同方向加弹）过滤掉，
            # 精化阶段会收敛到真正的遮蔽解。
            if perp > 25.0 + 1e-9:
                continue  # 云团必须落在固定射线附近（松弛到 25 m）
            t_det = proj / v
            if not (t_det - 1e-9 <= t_m <= t_det + sc["cloud_effective_duration"] + 1e-9):
                continue
            E_z = Q[2] + sc["cloud_sink_speed"] * (t_m - t_det)
            if E_z < 0.0 or E_z > z_uav:
                continue
            t_delay = float(np.sqrt(2.0 * (z_uav - E_z) / g))
            if not (0.5 <= t_delay <= 15.0):
                continue
            t_drop = t_det - t_delay
            if not (0.0 <= t_drop <= 40.0):
                continue
            if any(abs(t_drop - d) < 1.0 - 1e-9 for d in avoid_drops):
                continue
            seeds.append((t_drop, t_delay))
    return seeds


def _optimize_drop_delay_locked(sc, m_name, f_name, theta, v, avoid_drops=()):
    """固定 (θ,v) 下的 (t_drop, t_delay) 优化：物理起点多起点 + 2D 坐标轮换。

    返回去重后的 (时长, t_drop, t_delay) 列表（按 t_drop 聚类，最多 3 个不同时间窗）。
    找不到可行遮蔽解时返回 []。
    """
    seeds = _locked_seeds(sc, m_name, f_name, theta, v, avoid_drops)
    if not seeds:
        return []
    scored = sorted(((_obj_single_fixed_dv(s, m_name, f_name, theta, v), s)
                     for s in seeds), key=lambda t: t[0])
    results = []
    for _, s in scored[:8]:
        x = np.array([_snap_tdrop(s[0], avoid_drops), s[1]], dtype=float)
        for _ in range(2):
            for k in (0, 1):
                lo, hi = BOUNDS[2 + k]
                span = hi - lo
                half = span * 0.02
                cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), 31)
                best_x, best_f = x.copy(), _obj_single_fixed_dv(x, m_name, f_name, theta, v)
                for c in cand:
                    if k == 0 and any(abs(c - d) < 1.0 - 1e-9 for d in avoid_drops):
                        continue
                    xc = x.copy()
                    xc[k] = c
                    fv = _obj_single_fixed_dv(xc, m_name, f_name, theta, v)
                    if fv < best_f - 1e-12:
                        best_f, best_x = fv, xc
                x = best_x
        dur, _ = gc.single_bomb_masking(sc, m_name, f_name, theta, v, x[0], x[1])
        results.append((dur, float(x[0]), float(x[1])))
    results.sort(key=lambda t: -t[0])
    uniq = []
    for r in results:
        if r[0] <= 0.0:
            continue
        if any(abs(r[1] - u[1]) < 3.0 for u in uniq):
            continue
        uniq.append(r)
    return uniq[:3]


def _best_profile_for_uav(f_name, theta, v, base, locked3_cache, max_bombs=3):
    """给定方向 (θ,v)，为无人机 f 构造最优 1~max_bombs 弹配置（弹可对不同导弹）。

    对每个导弹取锁定方向优化得到的候选弹（最多 3 个不同时间窗），按边际增益贪心加入，
    保持同机投放间隔 ≥1 s。locked3_cache: (f, m, dir_key) -> [(dur, t_drop, t_delay)]。
    """
    cands = []
    dir_key = (round(theta, 2), round(v, 2))
    for m in MISSILES:
        ckey = (f_name, m, dir_key)
        if ckey not in locked3_cache:
            locked3_cache[ckey] = _optimize_drop_delay_locked(SC, m, f_name, theta, v,
                                                              avoid_drops=())
        for dur, td, tl in locked3_cache[ckey]:
            cands.append((dur, m, td, tl))
    cands.sort(key=lambda t: -t[0])
    chosen = []
    drops = []
    tot_cur = total_objective(base)
    for dur, m, td, tl in cands:
        if len(chosen) >= max_bombs:
            break
        if any(abs(td - d) < 1.0 - 1e-9 for d in drops):
            continue
        cand = dict(f=f_name, m=m, theta=theta, v=v, t_drop=td, t_delay=tl)
        cand_total = total_objective(base + chosen + [cand])
        if cand_total - tot_cur > 0.01:
            chosen.append(cand)
            drops.append(td)
            tot_cur = cand_total
    return chosen


def stage25_profile_optimize(plan, stage1, cfg=None):
    """阶段 2.7：按无人机轮换方向重配（坐标上升）。

    每架无人机在其"3 个单弹最优方向 + 网格方向 + 当前方向"中选取使总时长最大的
    至多 3 弹配置；锁定方向优化结果按 (f, m, 方向) 缓存（与其余弹无关，跨轮复用）。
    """
    cfg = cfg or {}
    grid_dirs = [(0.0, 120.0), (90.0, 120.0), (180.0, 120.0), (270.0, 120.0)]
    locked3_cache = {}
    n_rounds = cfg.get("profile_rounds", 2)
    for _r in range(n_rounds):
        changed = False
        for f in Q5_UAVS:
            f_idx = [i for i, b in enumerate(plan) if b["f"] == f]
            base = [b for i, b in enumerate(plan) if b["f"] != f]
            cur_total = total_objective(plan)
            dirs = [(stage1[(f, m)][0]["theta"], stage1[(f, m)][0]["v"]) for m in MISSILES]
            dirs += grid_dirs
            if f_idx:
                dirs.append((plan[f_idx[0]]["theta"], plan[f_idx[0]]["v"]))
            seen = set()
            best_prof, best_tot = None, cur_total
            for th, v in dirs:
                key = (round(th / 5.0), round(v / 5.0))
                if key in seen:
                    continue
                seen.add(key)
                prof = _best_profile_for_uav(f, th, v, base, locked3_cache, max_bombs=3)
                if not prof:
                    continue
                tot = total_objective(base + prof)
                if tot > best_tot + 1e-9:
                    best_tot, best_prof = tot, prof
            if best_prof is not None:
                plan = base + best_prof
                changed = True
                print(f"[model_3/Q5-阶段2.7] 重配 {f} → θ={best_prof[0]['theta']:.1f}° "
                      f"v={best_prof[0]['v']:.1f} m/s，弹={[b['m'] for b in best_prof]}，"
                      f"总时长 {cur_total:.3f} → {best_tot:.3f} s")
        if not changed:
            break
    return plan


def solve_problem5(cfg=None):
    """问题 5 分阶段求解。"""
    cfg = cfg or {}
    print("=" * 70)
    print("问题 5：5 机 × 至多 3 弹 × 3 导弹的分阶段投放策略优化")
    print("=" * 70)
    # ---- 阶段 1：每个 (机, 弹) 组合的单弹优化 ----
    stage1 = {}
    for f in Q5_UAVS:
        for m in MISSILES:
            sols = single_bomb_solutions(SC, m, f, cfg, n_keep=3)
            stage1[(f, m)] = sols
            print(f"[model_3/Q5-阶段1] ({f},{m}) 单弹最优时长 top3: "
                  f"{[round(s['dur'], 3) for s in sols]} s")
    # ---- 阶段 2：贪心分配 ----
    plan = []
    used_slots = {f: 0 for f in Q5_UAVS}
    uav_dir = {}      # f -> (theta, v) 已确定
    uav_drops = {f: [] for f in Q5_UAVS}
    total = 0.0
    locked_cache = {}   # (f, m, drops_key) -> [(dur, t_drop, t_delay), ...]
    dirty = {f: True for f in Q5_UAVS}  # 该机投放集变化后需重算锁定方向解
    for it in range(15):
        best_gain, best_cand = 0.0, None
        for f in Q5_UAVS:
            if used_slots[f] >= 3:
                continue
            for m in MISSILES:
                s0 = stage1[(f, m)][0]
                if f in uav_dir:
                    th, v = uav_dir[f]
                    drops_key = tuple(sorted(round(d, 3) for d in uav_drops[f]))
                    ckey = (f, m, drops_key)
                    if dirty[f] or ckey not in locked_cache:
                        locked_cache[ckey] = _optimize_drop_delay_locked(
                            SC, m, f, th, v, uav_drops[f])
                    for dur, td, tl in locked_cache[ckey]:
                        cand = dict(f=f, m=m, theta=th, v=v, t_drop=td, t_delay=tl)
                        gain = total_objective(plan + [cand]) - total
                        if gain > best_gain:
                            best_gain, best_cand = gain, cand
                else:
                    cand = dict(f=f, m=m, theta=s0["theta"], v=s0["v"],
                                t_drop=s0["t_drop"], t_delay=s0["t_delay"])
                    gain = total_objective(plan + [cand]) - total
                    if gain > best_gain:
                        best_gain, best_cand = gain, cand
        dirty = {ff: False for ff in Q5_UAVS}
        if best_cand is None or best_gain <= 0.01:
            break
        plan.append(best_cand)
        total += best_gain
        f = best_cand["f"]
        used_slots[f] += 1
        if f not in uav_dir:
            uav_dir[f] = (best_cand["theta"], best_cand["v"])
        uav_drops[f].append(best_cand["t_drop"])
        dirty[f] = True
        print(f"[model_3/Q5-阶段2] 第{it+1}枚: {best_cand['f']}→{best_cand['m']} "
              f"边际增益={best_gain:.3f} s, 当前总时长={total:.3f} s")
    # ---- 阶段 2.5：冗余弹移除扫描 ----
    changed = True
    while changed and plan:
        changed = False
        for i in range(len(plan)):
            tot_without = total_objective(plan[:i] + plan[i + 1:])
            if tot_without >= total - 1e-9:
                removed = plan.pop(i)
                total = tot_without
                print(f"[model_3/Q5-阶段2.5] 移除冗余弹 {removed['f']}→{removed['m']} "
                      f"(t_drop={removed['t_drop']:.2f})，总时长不变 {total:.3f} s")
                changed = True
                break
    # ---- 阶段 2.7：按机方向重配（profile 轮换，探索不同航向的服务导弹组合）----
    plan = stage25_profile_optimize(plan, stage1, cfg)
    total = total_objective(plan)
    # ---- 阶段 3：局部精化（保持同机间隔约束）----
    plan = refine_plan(plan)
    total = total_objective(plan)
    per_m = per_missile_durs(plan)
    print("[model_3/Q5-阶段3] 局部精化完成：")
    for m in MISSILES:
        print(f"  {m} 并集遮蔽时长 = {per_m[m]:.3f} s")
    print(f"[model_3/Q5] 总遮蔽时长（Σ 三导弹并集）= {total:.4f} s")
    bombs_out = []
    for b in plan:
        D, E = gc.bomb_detonation_point(SC, SC["uavs"][b["f"]], b["theta"], b["v"],
                                        b["t_drop"], b["t_delay"])
        dur_i, ivs_i = gc.single_bomb_masking(SC, b["m"], b["f"], b["theta"], b["v"],
                                              b["t_drop"], b["t_delay"])
        bombs_out.append(dict(f_name=b["f"], m_name=b["m"], theta=float(b["theta"]),
                              v=float(b["v"]), t_drop=float(b["t_drop"]),
                              t_delay=float(b["t_delay"]), D=[float(x) for x in D],
                              E=[float(x) for x in E], dur=float(dur_i),
                              ivs=[list(iv) for iv in ivs_i]))
        print(f"[model_3/Q5] {b['f']} 弹号{_bomb_no(bombs_out)} → {b['m']}: "
              f"θ={b['theta']:.2f}° v={b['v']:.2f} m/s t_drop={b['t_drop']:.2f} s "
              f"t_delay={b['t_delay']:.2f} s 单弹时长={dur_i:.3f} s")
    return dict(total_dur=total, per_missile=per_m, bombs=bombs_out)


def _bomb_no(bombs_out):
    """返回刚 append 的弹在所属无人机内的弹序号（1~3）。"""
    f = bombs_out[-1]["f_name"]
    return sum(1 for b in bombs_out if b["f_name"] == f)


def refine_plan(plan, n_rounds=2):
    """阶段 3 精化：A) 每机 (θ,v) 联合精化；B) 每弹 (t_drop,t_delay) 精化（保间隔）。"""
    uavs_in = sorted(set(b["f"] for b in plan))
    for _r in range(n_rounds):
        # A: 每机 θ/v（该机所有弹共享）
        for f in uavs_in:
            idxs = [i for i, b in enumerate(plan) if b["f"] == f]
            x = np.array([plan[idxs[0]]["theta"], plan[idxs[0]]["v"]])
            for _pass in range(2):
                for k in range(2):
                    lo, hi = BOUNDS[k]
                    span = hi - lo
                    half = span * (0.01 if _pass else 0.05)
                    cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), 31)
                    best_x, best_f = x.copy(), _plan_obj_uav(x, f, plan)
                    for c in cand:
                        xc = x.copy()
                        xc[k] = c
                        fv = _plan_obj_uav(xc, f, plan)
                        if fv < best_f - 1e-12:
                            best_f, best_x = fv, xc
                    x = best_x
            for i in idxs:
                plan[i]["theta"], plan[i]["v"] = float(x[0]), float(x[1])
        # B: 每弹 t_drop/t_delay
        for i, b in enumerate(plan):
            avoid = [plan[j]["t_drop"] for j in range(len(plan))
                     if j != i and plan[j]["f"] == b["f"]]
            x = np.array([_snap_tdrop(b["t_drop"], avoid), b["t_delay"]])
            for _pass in range(2):
                for k in (0, 1):
                    lo, hi = BOUNDS[2 + k]
                    span = hi - lo
                    half = span * (0.01 if _pass else 0.05)
                    cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), 31)
                    best_x, best_f = x.copy(), _plan_obj_bomb(x, i, plan)
                    for c in cand:
                        if k == 0 and any(abs(c - d) < 1.0 - 1e-9 for d in avoid):
                            continue
                        xc = x.copy()
                        xc[k] = c
                        fv = _plan_obj_bomb(xc, i, plan)
                        if fv < best_f - 1e-12:
                            best_f, best_x = fv, xc
                    x = best_x
            plan[i]["t_drop"], plan[i]["t_delay"] = float(x[0]), float(x[1])
    return plan


def _plan_obj_uav(x, f, plan):
    """把 f 机全部弹的 (θ,v) 设为 x 后的总目标（负总时长）。"""
    trial = []
    for b in plan:
        bb = dict(b)
        if b["f"] == f:
            bb["theta"], bb["v"] = float(x[0]), float(x[1])
        trial.append(bb)
    return -total_objective(trial)


def _plan_obj_bomb(x, i, plan):
    """把第 i 枚弹的 (t_drop,t_delay) 设为 x 后的总目标（负总时长）。"""
    trial = [dict(b) for b in plan]
    trial[i]["t_drop"], trial[i]["t_delay"] = float(x[0]), float(x[1])
    return -total_objective(trial)


# ---------------------------------------------------------------------------
# Excel 结果输出
# ---------------------------------------------------------------------------
def write_result2(result4, src="result2.xlsx"):
    import openpyxl
    p = DATA_DIR / src
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    for row_i, b in zip(range(2, 5), result4["bombs"]):
        ws.cell(row=row_i, column=2).value = round(b["theta"], 6)
        ws.cell(row=row_i, column=3).value = round(b["v"], 6)
        for k in range(3):
            ws.cell(row=row_i, column=4 + k).value = round(b["D"][k], 6)
            ws.cell(row=row_i, column=7 + k).value = round(b["E"][k], 6)
        ws.cell(row=row_i, column=10).value = round(b["dur"], 6)
    wb.save(p)
    out = OUT_DIR / src
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, out)
    print(f"[model_3] {src} 已填写（数据目录 + output 目录）")


def write_result3(result5, src="result3.xlsx"):
    import openpyxl
    p = DATA_DIR / src
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    # 每行: (无人机, 弹号) → 行号 = 2 + (uav_idx*3 + bomb_no - 1)
    bombs = sorted(result5["bombs"], key=lambda b: (Q5_UAVS.index(b["f_name"]),
                                                    _bomb_no_index(result5, b)))
    for b in bombs:
        uav_idx = Q5_UAVS.index(b["f_name"])
        bomb_no = sum(1 for x in result5["bombs"]
                      if x["f_name"] == b["f_name"] and x["t_drop"] <= b["t_drop"] + 1e-9)
        row_i = 2 + uav_idx * 3 + bomb_no - 1
        ws.cell(row=row_i, column=2).value = round(b["theta"], 6)
        ws.cell(row=row_i, column=3).value = round(b["v"], 6)
        for k in range(3):
            ws.cell(row=row_i, column=5 + k).value = round(b["D"][k], 6)
            ws.cell(row=row_i, column=8 + k).value = round(b["E"][k], 6)
        ws.cell(row=row_i, column=11).value = round(b["dur"], 6)
        ws.cell(row=row_i, column=12).value = b["m_name"]
    wb.save(p)
    out = OUT_DIR / src
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, out)
    print(f"[model_3] {src} 已填写（数据目录 + output 目录）")


def _bomb_no_index(result5, b):
    same = [x for x in result5["bombs"] if x["f_name"] == b["f_name"]]
    same.sort(key=lambda x: x["t_drop"])
    return same.index(b) + 1


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------
def fig_q4_masking(result4, out_name="fig03_q4_masking_window.png"):
    """问题 4：三机单弹对 M1 的遮蔽窗口（+ 并集行，条形末端标时长）。"""
    plot_style.apply()
    bombs = result4["bombs"]
    union = _merge_intervals([iv for b in bombs for iv in b["ivs"]])
    max_end = max((c for b in bombs for _, c in b["ivs"]), default=30.0)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for i, b in enumerate(bombs):
        lab = f"{b['f_name']} (θ={b['theta']:.0f}°, v={b['v']:.0f})"
        for a, c in b["ivs"]:
            ax.barh(lab, c - a, left=a, height=0.5,
                    color=plot_style.CATEGORICAL[i], alpha=0.85)
        tot = sum(c - a for a, c in b["ivs"])
        last_c = max(b["ivs"], key=lambda t: t[1])[1]
        ax.text(last_c + 0.3, lab, f"{tot:.2f} s", va="center", fontsize=8.5,
                color=plot_style.CATEGORICAL[i])
    union_dur = sum(c - a for a, c in union)
    for a, c in union:
        ax.barh("并集（总遮蔽）", c - a, left=a, height=0.5,
                color=plot_style.CHROME["text_secondary"], alpha=0.55)
    ax.text(max_end + 0.3, "并集（总遮蔽）", f"{union_dur:.2f} s", va="center",
            fontsize=8.5, color=plot_style.CHROME["text_secondary"])
    ax.set_xlabel("时间 t (s)")
    ax.set_title(f"问题 4：三机单弹对 M1 的有效遮蔽窗口（总并集 {result4['total_dur']:.2f} s）")
    ax.set_xlim(0, max_end + 1.8)
    ax.grid(True, axis="x", alpha=0.3)
    plot_style.save(fig, IMG_DIR / out_name)
    plt.close(fig)
    print(f"[model_3] {out_name} 已生成")


def fig_q5_assignment(result5, out_name="fig03_q5_assignment.png"):
    """问题 5：弹-导弹分配与遮蔽窗口（三面板共享时间轴 + 统一图例 + 时长标注）。"""
    plot_style.apply()
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.0), sharex=True)
    uav_color = {f: plot_style.CATEGORICAL[i % 8] for i, f in enumerate(Q5_UAVS)}
    max_end = max((c for b in result5["bombs"] for _, c in b["ivs"]), default=45.0)
    for ax, m in zip(axes, MISSILES):
        bm = [b for b in result5["bombs"] if b["m_name"] == m]
        for b in bm:
            for a, c in b["ivs"]:
                ax.barh(f"{b['f_name']} #{_bomb_no_of(result5, b)}", c - a, left=a,
                        height=0.5, color=uav_color[b["f_name"]], alpha=0.85)
            tot = sum(c - a for a, c in b["ivs"])
            last_c = max(b["ivs"], key=lambda t: t[1])[1]
            ax.text(last_c + 0.3, f"{b['f_name']} #{_bomb_no_of(result5, b)}",
                    f"{tot:.2f} s", va="center", fontsize=7.5,
                    color=plot_style.CHROME["text_secondary"])
        ax.set_title(f"{m}（并集 {result5['per_missile'][m]:.2f} s）")
        ax.set_xlabel("时间 t (s)")
        ax.grid(True, axis="x", alpha=0.3)
        ax.set_xlim(0, max_end + 1.6)
    handles = [plt.Line2D([0], [0], marker="o", ls="", color=uav_color[f], markersize=7,
                          label=f) for f in Q5_UAVS]
    fig.suptitle(f"问题 5：弹-导弹分配与遮蔽窗口（总时长 Σ 并集 = {result5['total_dur']:.2f} s）")
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.02),
               ncol=len(Q5_UAVS), fontsize=8.5, frameon=False)
    fig.subplots_adjust(top=0.86, bottom=0.14, wspace=0.28)
    plot_style.save(fig, IMG_DIR / out_name)
    plt.close(fig)
    print(f"[model_3] {out_name} 已生成")


def _bomb_no_of(result5, b):
    same = [x for x in result5["bombs"] if x["f_name"] == b["f_name"]]
    same.sort(key=lambda x: x["t_drop"])
    return same.index(b) + 1


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    res4 = solve_problem4()
    write_result2(res4)
    res5 = solve_problem5()
    write_result3(res5)
    fig_q4_masking(res4)
    fig_q5_assignment(res5)
    cache = {
        "problem4": {"total_dur": float(res4["total_dur"]),
                     "bombs": [{k: (v if k != "ivs" else [list(iv) for iv in v])
                                for k, v in b.items()} for b in res4["bombs"]]},
        "problem5": {"total_dur": float(res5["total_dur"]),
                     "per_missile": {k: float(v) for k, v in res5["per_missile"].items()},
                     "bombs": [{k: (v if k != "ivs" else [list(iv) for iv in v])
                                for k, v in b.items()} for b in res5["bombs"]]},
    }
    out = ROOT / "state" / "model3_results.json"
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[model_3] 结果缓存 → {out}")
    return res4, res5


if __name__ == "__main__":
    main()
