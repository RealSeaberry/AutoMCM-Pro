#!/usr/bin/env python3
"""
geometry_core.py — 共享几何运动学模型（2025 CUMCM A：烟幕干扰弹投放策略）

这是 3 个 model 槽位共用的"同一套无人机轨迹几何模型"：
  1. 导弹：沿直线飞向假目标（原点），速度 300 m/s，位置 M(t) = M0 - v_m·t·û，û 指向假目标；
  2. 无人机：等高度匀速直线飞行，位置 F(t) = F0 + v·t·(cosθ, sinθ, 0)（θ 为航向角，
     以 +x 轴为正向逆时针为正，0~360°）；
  3. 烟幕干扰弹：投放点 D=F(t_drop)，脱离后仅受重力（初速 = 无人机水平速度），
     弹道 B(t) = D + v·(t-t_drop)·(cosθ, sinθ, 0) - ½g(t-t_drop)²·ẑ；
  4. 云团：起爆点 E=B(t_drop+t_delay)，瞬时形成球状云团并以 3 m/s 匀速下沉，
     C(t) = E - 3·(t-t_det)·ẑ，起爆后 20 s 内有效；
  5. 遮蔽判据：云团中心 C(t) 到"导弹 M(t)→真目标参考点 P_T=(0,200,0)"视线线段的
     距离 ≤ 10 m（点-线段距离，多弹取时间并集测度）。

所有 model_N 脚本均 import 本模块；附录代码节选的核心函数即 masking_intervals()
（本文件的核心求解逻辑）。
"""
import json
from pathlib import Path

import numpy as np

SCENARIO_PATH = Path(__file__).resolve().parents[2] / "data" / "scenario.json"
# 真目标参考点：题目给出"真目标下底面圆心为 (0,200,0)"，遮蔽判据以该点为视线终点
TARGET_REF = np.array([0.0, 200.0, 0.0], dtype=float)


def load_scenario() -> dict:
    with open(SCENARIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def missile_trajectory(m0, v_m, decoy, t):
    """导弹 t 时刻位置：从 M0 以 v_m 直线飞向假目标 decoy。"""
    m0 = np.asarray(m0, dtype=float)
    decoy = np.asarray(decoy, dtype=float)
    u = (decoy - m0) / np.linalg.norm(decoy - m0)
    return m0 + v_m * t * u


def uav_position(f0, theta_deg, v, t):
    """无人机 t 时刻位置：等高度匀速直线飞行（z 不变）。"""
    th = np.deg2rad(theta_deg)
    f0 = np.asarray(f0, dtype=float)
    return f0 + v * t * np.array([np.cos(th), np.sin(th), 0.0])


def bomb_position(D, theta_deg, v_h, t_after, g):
    """弹道位置：投放点 D，初速为无人机水平速度 v_h·(cosθ,sinθ,0)，仅受重力。"""
    th = np.deg2rad(theta_deg)
    D = np.asarray(D, dtype=float)
    p = D + v_h * t_after * np.array([np.cos(th), np.sin(th), 0.0])
    p[2] -= 0.5 * g * t_after ** 2
    return p


def cloud_center(E, t_after_detonation, sink_speed):
    """云团中心：起爆点 E，以 sink_speed 匀速下沉。"""
    E = np.asarray(E, dtype=float)
    return E + np.array([0.0, 0.0, -sink_speed * t_after_detonation])


def point_segment_distance(P, A, B):
    """点 P 到线段 AB 的最小距离（3D）。"""
    P = np.asarray(P, dtype=float)
    A = np.asarray(A, dtype=float)
    B = np.asarray(B, dtype=float)
    AB = B - A
    denom = float(np.dot(AB, AB))
    if denom <= 1e-12:
        return float(np.linalg.norm(P - A))
    s = float(np.clip(np.dot(P - A, AB) / denom, 0.0, 1.0))
    return float(np.linalg.norm(P - (A + s * AB)))


def bomb_detonation_point(sc, f0, theta_deg, v, t_drop, t_delay):
    """投放点与起爆点（几何链路一步到位，向量化函数共用）。"""
    th = np.deg2rad(theta_deg)
    dir_h = np.array([np.cos(th), np.sin(th), 0.0])
    D = np.asarray(f0, dtype=float) + v * t_drop * dir_h
    E = D + v * t_delay * dir_h
    E[2] -= 0.5 * sc["g"] * t_delay ** 2
    return D, E


def _dist_to_los_vec(sc, m_name, f0, theta_deg, v, t_drop, t_delay, ts):
    """向量化：ts 数组各时刻"云团中心到视线线段"的距离数组。

    单次调用完成 1000+ 时刻的遮蔽几何计算（供优化器高频调用，不能有 Python 循环）。
    """
    th = np.deg2rad(theta_deg)
    dir_h = np.array([np.cos(th), np.sin(th), 0.0])
    D = np.asarray(f0, dtype=float) + v * t_drop * dir_h
    t_det = t_drop + t_delay
    E = D + v * t_delay * dir_h
    E[2] -= 0.5 * sc["g"] * t_delay ** 2
    ts = np.asarray(ts, dtype=float)
    sink = sc["cloud_sink_speed"]
    C = E[None, :] + np.array([0.0, 0.0, -sink])[None, :] * (ts - t_det)[:, None]
    m0 = np.asarray(sc["missiles"][m_name], dtype=float)
    decoy = np.asarray(sc["decoy"], dtype=float)
    u = (decoy - m0) / np.linalg.norm(decoy - m0)
    M = m0[None, :] + sc["missile_speed"] * ts[:, None] * u[None, :]
    B = TARGET_REF[None, :] + np.zeros_like(M)
    AB = B - M
    denom = np.einsum("ij,ij->i", AB, AB)
    denom[denom < 1e-12] = 1.0
    s = np.clip(np.einsum("ij,ij->i", C - M, AB) / denom, 0.0, 1.0)
    proj = M + s[:, None] * AB
    return np.linalg.norm(C - proj, axis=1)


def masking_intervals(sc, m_name, f0, theta_deg, v, t_drop, t_delay, dt=0.02):
    """单弹对单导弹的有效遮蔽时间区间列表（起爆后 20 s 窗口内，二分精化边界）。

    这是本文件的核心求解函数：向量化采样 + 符号变化检测 + 二分精化，返回
    [(t_start, t_end), ...]（可能多个不连续子区间），供上层做并集测度。
    """
    t_det = t_drop + t_delay
    t_end = t_det + sc["cloud_effective_duration"]
    ts = np.arange(t_det, t_end + 1e-9, dt)
    dist = _dist_to_los_vec(sc, m_name, f0, theta_deg, v, t_drop, t_delay, ts)
    active = dist <= sc["cloud_effective_radius"]
    intervals = []
    n = len(ts)
    i = 0
    while i < n:
        if active[i]:
            j = i
            while j + 1 < n and active[j + 1]:
                j += 1
            t0, t1 = float(ts[i]), float(ts[j])
            if i > 0:
                b = _bisect_boundary(sc, m_name, f0, theta_deg, v, t_drop, t_delay,
                                     float(ts[i - 1]), float(ts[i]))
                if b is not None:
                    t0 = b
            if j + 1 < n:
                b = _bisect_boundary(sc, m_name, f0, theta_deg, v, t_drop, t_delay,
                                     float(ts[j]), float(ts[j + 1]))
                if b is not None:
                    t1 = b
            intervals.append((t0, t1))
            i = j + 1
        else:
            i += 1
    return intervals


def _bisect_boundary(sc, m_name, f0, theta_deg, v, t_drop, t_delay, t_lo, t_hi):
    """在 [t_lo, t_hi] 内用二分法求遮蔽指示函数 g(t)=dist-R 的过零点（要求两端异号）。"""
    R = sc["cloud_effective_radius"]
    D, E = bomb_detonation_point(sc, f0, theta_deg, v, t_drop, t_delay)
    t_det = t_drop + t_delay

    def fval(t):
        C = cloud_center(E, t - t_det, sc["cloud_sink_speed"])
        M = missile_trajectory(sc["missiles"][m_name], sc["missile_speed"], sc["decoy"], t)
        return point_segment_distance(C, M, TARGET_REF) - R

    f_lo, f_hi = fval(t_lo), fval(t_hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(50):
        tm = 0.5 * (t_lo + t_hi)
        fm = fval(tm)
        if fm == 0.0:
            return tm
        if f_lo * fm < 0:
            t_hi, f_hi = tm, fm
        else:
            t_lo, f_lo = tm, fm
    return 0.5 * (t_lo + t_hi)


def union_measure(intervals):
    """区间并集测度（合并重叠区间后求和）。"""
    if not intervals:
        return 0.0
    ivs = sorted(intervals)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return float(sum(b - a for a, b in merged))


def single_bomb_masking(sc, m_name, f_name, theta_deg, v, t_drop, t_delay, dt=0.02):
    """单枚烟幕干扰弹的有效遮蔽时长（浮点秒）+ 区间列表。"""
    f0 = sc["uavs"][f_name]
    ivs = masking_intervals(sc, m_name, f0, theta_deg, v, t_drop, t_delay, dt)
    return union_measure(ivs), ivs


def single_bomb_masking_detail(sc, m_name, f_name, theta_deg, v, t_drop, t_delay, dt=0.02):
    """单弹细节：返回 (时长, 区间列表, 窗口内云团到视线线段的最小距离 d_min)。

    d_min 作为优化代理量（平滑引导项）：即使遮蔽时长为 0，d_min 也能刻画
    "云团离视线有多近"，让优化器在平坦的零值区也能朝正确方向爬。
    """
    f0 = sc["uavs"][f_name]
    ivs = masking_intervals(sc, m_name, f0, theta_deg, v, t_drop, t_delay, dt)
    dur = union_measure(ivs)
    t_det = t_drop + t_delay
    ts = np.arange(t_det, t_det + sc["cloud_effective_duration"] + 1e-9, 0.05)
    dist = _dist_to_los_vec(sc, m_name, f0, theta_deg, v, t_drop, t_delay, ts)
    d_min = float(np.min(dist)) if dist.size else 1e6
    return dur, ivs, d_min


def multi_bomb_union_masking(sc, m_name, bombs, dt=0.02):
    """多枚弹（bombs=[(f_name, θ, v, t_drop, t_delay), ...]）对同一导弹的并集遮蔽时长。"""
    all_ivs = []
    for f_name, theta_deg, v, t_drop, t_delay in bombs:
        f0 = sc["uavs"][f_name]
        all_ivs += masking_intervals(sc, m_name, f0, theta_deg, v, t_drop, t_delay, dt)
    return union_measure(all_ivs)


if __name__ == "__main__":
    import time
    sc = load_scenario()
    # 快速自检：Q1 给定策略（FY1 朝假目标 θ=180°，120 m/s，t_drop=1.5，t_delay=3.6）
    t0 = time.time()
    dur, ivs = single_bomb_masking(sc, "M1", "FY1", 180.0, 120.0, 1.5, 3.6)
    print(f"[geometry_core] Q1 给定策略有效遮蔽时长 = {dur:.4f} s")
    print(f"[geometry_core] 区间: {[(round(a,3), round(b,3)) for a,b in ivs]}")
    print(f"[geometry_core] 单次评估耗时 {1e3*(time.time()-t0):.2f} ms")
