#!/usr/bin/env python3
"""
verify_problem2_schedule.py — model_2 强制验证脚本（问题 3：单机 3 弹时序调度）

检查项：
  [V-OPT-1] 可行性：θ∈[0,360]、v∈[70,140]、t_i∈[0,30]、相邻间隔 ≥1 s、d_i∈[0.5,15]；
  [V-OPT-2] 独立方法交叉验证：粗网格枚举最优并集时长 ≤ 主结果 + 0.5 s；
  [V-OPT-3] 扰动测试：±0.1% 扰动（保持排序）不产生更优并集时长（+0.02 s 容差）；
  [V-ODE-1] 弹道一致性：每弹起爆点与解析公式误差 <1e-6；
  [V-ODE-2] 云团下沉：每弹云团 1 s 位移 z 方向 −3 m；
  [V-ODE-3] 导弹运动学：M1 每秒位移 300 m/s 且指向假目标；
  [V-CONS-1] 单调性：3 弹并集 ≥ model_1 单弹最优 4.611 s − 0.1 s；
  [V-CONS-2] 并集逻辑：multi_bomb_union_masking 与手工合并区间一致（<0.02 s）；
  [V-XLSX]  result1.xlsx 已按模板填写 3 行且数值有限。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "models"))  # src/models
sys.path.insert(0, str(ROOT.parent / "scripts"))

import geometry_core as gc  # noqa: E402
import problem2_schedule as p2  # noqa: E402

SC = gc.load_scenario()
RES = json.loads((ROOT / "state" / "model2_results.json").read_text(encoding="utf-8"))
THETA, V = RES["theta"], RES["v"]
BOMBS = RES["bombs"]                     # 3 枚弹（theta/v/t_drop/t_delay/dur/ivs）
TOTAL = RES["total_dur"]
Q2_OPT = json.loads((ROOT / "state" / "model1_results.json").read_text(encoding="utf-8"))["q2"]


def check_feasibility() -> bool:
    ok = True
    if not (0.0 <= THETA <= 360.0):
        print("  ✗ θ 超界"); ok = False
    if not (70.0 - 1e-9 <= V <= 140.0 + 1e-9):
        print("  ✗ v 超界"); ok = False
    ts = [b["t_drop"] for b in BOMBS]
    ds = [b["t_delay"] for b in BOMBS]
    for t in ts:
        if not (0.0 <= t <= 30.0):
            print(f"  ✗ t_drop={t} 超界"); ok = False
    for d in ds:
        if not (0.5 - 1e-9 <= d <= 15.0 + 1e-9):
            print(f"  ✗ t_delay={d} 超界"); ok = False
    if ts[1] - ts[0] < 1.0 - 1e-9 or ts[2] - ts[1] < 1.0 - 1e-9:
        print(f"  ✗ 投放间隔不足 1 s: {ts}"); ok = False
    return ok


def check_cross_solver() -> bool:
    """粗网格枚举（独立方法）：θ 步长 30°、v 步长 20、t1∈{0..5}、间隔 1/2 s、d∈{2.5,3.5,4.5}。"""
    best = 0.0
    for theta in np.arange(0.0, 360.0, 30.0):
        for v in np.arange(70.0, 141.0, 20.0):
            for t1 in np.arange(0.0, 6.0, 1.0):
                for gap in (1.0, 2.0):
                    ts = [t1, t1 + gap, t1 + 2 * gap]
                    for d1 in (2.5, 3.5, 4.5):
                        for d2 in (2.5, 3.5, 4.5):
                            for d3 in (2.5, 3.5, 4.5):
                                dur = gc.multi_bomb_union_masking(
                                    SC, "M1",
                                    [("FY1", theta, v, ts[0], d1),
                                     ("FY1", theta, v, ts[1], d2),
                                     ("FY1", theta, v, ts[2], d3)])
                                if dur > best:
                                    best = dur
    print(f"  [V-OPT-2] 粗网格枚举 {best:.4f} s vs 主结果 {TOTAL:.4f} s")
    return best <= TOTAL + 0.5


def check_perturbation() -> bool:
    rng = np.random.default_rng(1)
    for _ in range(200):
        pert = 1.0 + rng.uniform(-0.001, 0.001, size=3)
        ts = [b["t_drop"] * pert[i] for i, b in enumerate(BOMBS)]
        ds = [b["t_delay"] * pert[i] for i, b in enumerate(BOMBS)]
        # 保持排序与间隔
        ts = sorted(ts)
        if ts[1] - ts[0] < 1.0 or ts[2] - ts[1] < 1.0:
            continue
        dur = gc.multi_bomb_union_masking(
            SC, "M1", [("FY1", THETA, V, ts[i], ds[i]) for i in range(3)])
        if dur > TOTAL + 0.02:
            print(f"  ✗ 扰动产生更优并集 {dur:.4f} > {TOTAL:.4f}")
            return False
    return True


def check_ballistics() -> bool:
    f0 = SC["uavs"]["FY1"]
    for i, b in enumerate(BOMBS):
        D = gc.uav_position(f0, THETA, V, b["t_drop"])
        E = gc.bomb_position(D, THETA, V, b["t_delay"], SC["g"])
        E_exp = D + V * b["t_delay"] * np.array(
            [np.cos(np.deg2rad(THETA)), np.sin(np.deg2rad(THETA)), 0.0])
        E_exp[2] -= 0.5 * SC["g"] * b["t_delay"] ** 2
        if float(np.linalg.norm(E - E_exp)) > 1e-6:
            print(f"  ✗ 弹{i+1} 弹道不一致"); return False
    print("  [V-ODE-1] 3 弹起爆点弹道解析一致（误差 <1e-6）")
    return True


def check_cloud_sink() -> bool:
    f0 = SC["uavs"]["FY1"]
    for i, b in enumerate(BOMBS):
        D = gc.uav_position(f0, THETA, V, b["t_drop"])
        E = gc.bomb_position(D, THETA, V, b["t_delay"], SC["g"])
        C1 = gc.cloud_center(E, 1.0, SC["cloud_sink_speed"])
        C2 = gc.cloud_center(E, 2.0, SC["cloud_sink_speed"])
        if abs((C2 - C1)[2] + 3.0) > 1e-9:
            print(f"  ✗ 弹{i+1} 下沉速度错误"); return False
    print("  [V-ODE-2] 3 弹云团均以 3 m/s 匀速下沉")
    return True


def check_missile_kinematics() -> bool:
    m0 = np.array(SC["missiles"]["M1"], dtype=float)
    decoy = np.array(SC["decoy"], dtype=float)
    M0 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 0.0)
    M1 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 1.0)
    speed = float(np.linalg.norm(M1 - M0))
    u = (M1 - M0) / speed
    u_exp = (decoy - m0) / np.linalg.norm(decoy - m0)
    ok = abs(speed - 300.0) < 1e-6 and float(np.linalg.norm(u - u_exp)) < 1e-9
    print(f"  [V-ODE-3] M1 速度 {speed:.6f} m/s，方向误差 {np.linalg.norm(u - u_exp):.2e}")
    return ok


def check_monotonicity() -> bool:
    ok = TOTAL >= Q2_OPT["dur"] - 0.1
    print(f"  [V-CONS-1] Q3 并集 {TOTAL:.3f} s ≥ Q2 单弹 {Q2_OPT['dur']:.3f} s − 0.1 s"
          f" → {'通过' if ok else '失败'}")
    return ok


def check_union_logic() -> bool:
    manual = gc.union_measure([tuple(iv) for b in BOMBS for iv in b["ivs"]])
    via_api = gc.multi_bomb_union_masking(
        SC, "M1", [("FY1", THETA, V, b["t_drop"], b["t_delay"]) for b in BOMBS])
    ok = abs(manual - via_api) < 0.02
    print(f"  [V-CONS-2] 手工并集 {manual:.4f} s vs API 并集 {via_api:.4f} s")
    return ok


def check_xlsx() -> bool:
    import openpyxl
    wb = openpyxl.load_workbook(ROOT / "data" / "result1.xlsx")
    ws = wb["Sheet1"]
    ok = True
    for r in range(2, 5):
        row = [ws.cell(r, c).value for c in range(1, 11)]
        if any(v is None for v in row):
            print(f"  ✗ result1.xlsx 第 {r} 行有空值: {row}")
            ok = False
            continue
        theta, v = row[0], row[1]
        if not (0.0 <= theta <= 360.0 and 70.0 <= v <= 140.0):
            print(f"  ✗ 第 {r} 行 θ/v 超界"); ok = False
        for val in row:
            if isinstance(val, (int, float)) and not np.isfinite(val):
                print(f"  ✗ 第 {r} 行含非有限值"); ok = False
    print(f"  [V-XLSX] result1.xlsx 3 行均已填写且数值有限 → {'通过' if ok else '失败'}")
    return ok


def main():
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print("Stage  : model_2_verify")
    checks = [
        ("V-OPT-1", check_feasibility(), "最优解可行域与 ≥1s 间隔约束"),
        ("V-OPT-2", check_cross_solver(), "粗网格枚举交叉验证"),
        ("V-OPT-3", check_perturbation(), "±0.1% 扰动不产生更优解"),
        ("V-ODE-1", check_ballistics(), "弹道解析一致"),
        ("V-ODE-2", check_cloud_sink(), "云团 3 m/s 下沉"),
        ("V-ODE-3", check_missile_kinematics(), "导弹 300 m/s 指向假目标"),
        ("V-CONS-1", check_monotonicity(), "3 弹不劣于单弹最优"),
        ("V-CONS-2", check_union_logic(), "并集测度逻辑一致"),
        ("V-XLSX", check_xlsx(), "result1.xlsx 已填写"),
    ]
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
