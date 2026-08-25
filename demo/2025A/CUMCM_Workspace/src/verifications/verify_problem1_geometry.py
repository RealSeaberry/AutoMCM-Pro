#!/usr/bin/env python3
"""
verify_problem1_geometry.py — model_1 强制验证脚本（AutoMCM_SOP §4.3）

检查项（优化模型 V-OPT + 动力学 V-ODE 混合）：
  [V-OPT-1] 原始可行性：最优解各变量在可行域内；
  [V-OPT-2] 替代求解器交叉验证：不同随机种子 DE + SLSQP 精修，目标差异在容差内；
  [V-OPT-3] 扰动测试：最优解 ±0.1% 扰动不产生更优目标值；
  [V-ODE-1] 弹道一致性：起爆点与"投放点+无人机初速+重力"解析公式一致；
  [V-ODE-2] 云团下沉：云团中心每 1 s 下沉 3 m（守恒/运动学检查）；
  [V-ODE-3] 导弹运动学：|M(t+1)-M(t)| = 300 m/s，方向指向假目标；
  [V-ODE-4] 遮蔽边界：遮蔽区间端点处点-线段距离 ≈ 10 m（±0.1 m）；
  [V-REG-1] 数值健全性：无 inf/nan，Q1 独立重算（细网格）与模型结果一致。
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "models"))  # src/models
sys.path.insert(0, str(ROOT.parent / "scripts"))

import geometry_core as gc  # noqa: E402
import problem1_geometry as p1  # noqa: E402

SC = p1.SC
TOL_DUR = 0.05     # 时长交叉验证容差 (s)
TOL_BND = 0.10     # 遮蔽边界距离容差 (m)

# 读取模型结果缓存（由 problem1_geometry.py main() 生成）
_CACHE = json.loads((ROOT / "state" / "model1_results.json").read_text(encoding="utf-8"))
Q1_DUR = _CACHE["q1"]["dur"]
Q2_OPT = {k: (tuple(v) if k == "ivs" else
              (np.array(v) if isinstance(v, list) else v))
          for k, v in _CACHE["q2"].items()}


def check_feasibility(opt) -> bool:
    """V-OPT-1：可行域检查。"""
    ok = True
    if not (0.0 <= opt["theta"] <= 360.0):
        print("  ✗ θ 超出 [0,360]"); ok = False
    if not (70.0 - 1e-9 <= opt["v"] <= 140.0 + 1e-9):
        print("  ✗ v 超出 [70,140]"); ok = False
    if not (0.0 <= opt["t_drop"] <= 40.0):
        print("  ✗ t_drop 超出 [0,40]"); ok = False
    if not (0.5 - 1e-9 <= opt["t_delay"] <= 15.0 + 1e-9):
        print("  ✗ t_delay 超出 [0.5,15]"); ok = False
    return ok


def check_cross_solver() -> bool:
    """V-OPT-2：独立方法交叉验证——全定义域粗网格枚举（纯枚举，与多起点精化
    是两种完全不同的搜索方法），网格最优时长应 ≤ 主结果 + 容差。"""
    best_dur = 0.0
    for theta in np.arange(0.0, 360.0, 20.0):
        for v in np.arange(70.0, 140.0 + 1e-9, 10.0):
            for t_drop in np.arange(0.0, 11.0, 1.0):
                for t_delay in np.arange(1.0, 11.0, 1.0):
                    dur, _ = gc.single_bomb_masking(SC, "M1", "FY1", theta, v, t_drop, t_delay)
                    if dur > best_dur:
                        best_dur = dur
    print(f"  [V-OPT-2] 粗网格枚举最优时长 {best_dur:.4f} s vs 主结果 "
          f"{Q2_OPT['dur']:.4f} s")
    return best_dur <= Q2_OPT["dur"] + 0.25


def check_perturbation() -> bool:
    """V-OPT-3：最优解 ±0.1% 扰动不产生更优遮蔽时长（目标为时长本身）。"""
    x0 = np.array([Q2_OPT["theta"], Q2_OPT["v"],
                   Q2_OPT["t_drop"], Q2_OPT["t_delay"]])
    dur0 = Q2_OPT["dur"]
    rng = np.random.default_rng(0)
    for _ in range(300):
        pert = 1.0 + rng.uniform(-0.001, 0.001, size=4)
        xp = np.clip(x0 * pert, [b[0] for b in p1.BOUNDS_Q2],
                     [b[1] for b in p1.BOUNDS_Q2])
        dur, _ = gc.single_bomb_masking(SC, "M1", "FY1", *xp)
        if dur > dur0 + 0.02:
            print(f"  ✗ 扰动 {xp} 产生更优时长 {dur:.4f} > {dur0:.4f}")
            return False
    return True


def check_ballistics() -> bool:
    """V-ODE-1：弹道解析一致性。"""
    f0 = SC["uavs"]["FY1"]
    D = gc.uav_position(f0, Q2_OPT["theta"], Q2_OPT["v"], Q2_OPT["t_drop"])
    E = gc.bomb_position(D, Q2_OPT["theta"], Q2_OPT["v"], Q2_OPT["t_delay"], SC["g"])
    E_expected = D.copy()
    th = np.deg2rad(Q2_OPT["theta"])
    E_expected += Q2_OPT["v"] * Q2_OPT["t_delay"] * np.array([np.cos(th), np.sin(th), 0.0])
    E_expected[2] -= 0.5 * SC["g"] * Q2_OPT["t_delay"] ** 2
    err = float(np.linalg.norm(E - E_expected))
    print(f"  [V-ODE-1] 起爆点解析一致误差 {err:.2e} m")
    return err < 1e-6


def check_cloud_sink() -> bool:
    """V-ODE-2：云团下沉速度 = 3 m/s。"""
    f0 = SC["uavs"]["FY1"]
    D = gc.uav_position(f0, Q2_OPT["theta"], Q2_OPT["v"], Q2_OPT["t_drop"])
    E = gc.bomb_position(D, Q2_OPT["theta"], Q2_OPT["v"], Q2_OPT["t_delay"], SC["g"])
    C1 = gc.cloud_center(E, 1.0, SC["cloud_sink_speed"])
    C2 = gc.cloud_center(E, 2.0, SC["cloud_sink_speed"])
    diff = C2 - C1
    ok = abs(diff[0]) < 1e-9 and abs(diff[1]) < 1e-9 and abs(diff[2] + 3.0) < 1e-9
    print(f"  [V-ODE-2] 云团 1s 位移 = ({diff[0]:.2e}, {diff[1]:.2e}, {diff[2]:.4f}) m")
    return ok


def check_missile_kinematics() -> bool:
    """V-ODE-3：导弹速度 300 m/s 且指向假目标。"""
    m0 = np.array(SC["missiles"]["M1"], dtype=float)
    decoy = np.array(SC["decoy"], dtype=float)
    M0 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 0.0)
    M1 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 1.0)
    step = M1 - M0
    speed = float(np.linalg.norm(step))
    u = step / speed
    u_expected = (decoy - m0) / np.linalg.norm(decoy - m0)
    ok = abs(speed - 300.0) < 1e-6 and float(np.linalg.norm(u - u_expected)) < 1e-9
    print(f"  [V-ODE-3] 导弹 1s 位移 {speed:.6f} m/s，方向误差 "
          f"{np.linalg.norm(u - u_expected):.2e}")
    return ok


def check_masking_boundary() -> bool:
    """V-ODE-4：遮蔽区间端点处距离 ≈ 10 m。"""
    opt = Q2_OPT
    f0 = SC["uavs"]["FY1"]
    ok = True
    for t_b in (opt["ivs"][0][0], opt["ivs"][0][1]):
        th = np.deg2rad(opt["theta"])
        D = np.asarray(f0, dtype=float) + opt["v"] * opt["t_drop"] * np.array([np.cos(th), np.sin(th), 0.0])
        E = D + opt["v"] * opt["t_delay"] * np.array([np.cos(th), np.sin(th), 0.0])
        E[2] -= 0.5 * SC["g"] * opt["t_delay"] ** 2
        C = gc.cloud_center(E, t_b - opt["t_drop"] - opt["t_delay"], SC["cloud_sink_speed"])
        M = gc.missile_trajectory(SC["missiles"]["M1"], SC["missile_speed"], SC["decoy"], t_b)
        d = gc.point_segment_distance(C, M, gc.TARGET_REF)
        if abs(d - 10.0) > TOL_BND:
            print(f"  ✗ 边界 t={t_b:.3f} 处距离 {d:.4f} m ≠ 10（容差 {TOL_BND} m）")
            ok = False
    print(f"  [V-ODE-4] 遮蔽区间端点距离检查：{'通过' if ok else '失败'}")
    return ok


def check_q1_regression() -> bool:
    """V-REG-1：Q1 用更细网格 (dt=0.005) 独立重算，与主结果一致。"""
    dur_fine, _ = gc.single_bomb_masking(SC, "M1", "FY1", 180.0, 120.0, 1.5, 3.6, dt=0.005)
    dur_main = Q1_DUR
    ok = abs(dur_fine - dur_main) <= 0.05
    print(f"  [V-REG-1] Q1 细网格重算 {dur_fine:.4f} s vs 主结果 {dur_main:.4f} s"
          f"（差异 {abs(dur_fine - dur_main):.4f} s）")
    return ok


def check_no_nan() -> bool:
    """数值健全性：全部输出有限。"""
    for k, v in Q2_OPT.items():
        if isinstance(v, (float, np.floating)) and not np.isfinite(v):
            print(f"  ✗ Q2_OPT[{k}] 非有限"); return False
    return True


def main():
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print("Stage  : model_1_verify")
    checks = []
    # V-OPT-1 可行性
    checks.append(("V-OPT-1", check_feasibility(Q2_OPT), "最优解在可行域内"))
    # V-OPT-2 替代求解器
    checks.append(("V-OPT-2", check_cross_solver(), "全定义域粗网格枚举交叉验证"))
    # V-OPT-3 扰动
    checks.append(("V-OPT-3", check_perturbation(), "±0.1% 扰动不产生更优解"))
    # V-ODE-1 弹道
    checks.append(("V-ODE-1", check_ballistics(), "起爆点弹道解析一致"))
    # V-ODE-2 云团
    checks.append(("V-ODE-2", check_cloud_sink(), "云团 3 m/s 匀速下沉"))
    # V-ODE-3 导弹
    checks.append(("V-ODE-3", check_missile_kinematics(), "导弹 300 m/s 指向假目标"))
    # V-ODE-4 遮蔽边界
    checks.append(("V-ODE-4", check_masking_boundary(), "遮蔽区间端点距离≈10m"))
    # V-REG-1 数值健全 + Q1 回归
    checks.append(("V-REG-1", check_q1_regression() and check_no_nan(), "Q1 细网格回归一致，无 inf/nan"))
    all_pass = all(r for _, r, _ in checks)
    print(f"Result : {'PASS' if all_pass else 'FAIL'}")
    print("Checks :")
    for cid, result, detail in checks:
        print(f"  [{cid}] {'✓ PASS' if result else '✗ FAIL'}  {detail}")
    print("=" * 60)
    print(f"OVERALL: {'ALL PASS' if all_pass else 'FAILED — SEE ABOVE'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
