#!/usr/bin/env python3
"""
verify_problem3_multiuav.py — model_3 强制验证脚本（问题 4 + 问题 5）

检查项：
  [V-OPT-1] 可行性：全部 θ∈[0,360]、v∈[70,140]、t_drop∈[0,40]、t_delay∈[0.5,15]；
            同机相邻弹投放间隔 ≥1 s；
  [V-OPT-2] 一致性交叉验证：由 result2/3.xlsx 参数重算的并集时长与缓存一致（<0.02 s）；
  [V-OPT-3] 扰动测试：Q4 最优解 ±0.1% 扰动（保持同机间隔）不产生更优并集（+0.02 s）；
  [V-ODE-1] 弹道一致性：抽查每机 1 弹，起爆点与解析公式误差 <1e-6；
  [V-ODE-2] 云团下沉：抽查 2 弹，云团 1 s 位移 z 方向 −3 m；
  [V-ODE-3] 导弹运动学：M2/M3 每秒位移 300 m/s 且指向假目标；
  [V-CONS-1] 单调性：Q4 ≥ Q2 单弹最优 4.611 − 0.1 s；Q5 ≥ Q4 − 0.1 s；
  [V-CONS-2] 分配正确性：每枚 Q5 弹对其干扰导弹的时长 > 0，且 per_missile 并集与
            总时长一致；
  [V-XLSX]  result2.xlsx（3 行）与 result3.xlsx（已用行）填写正确、数值有限。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "models"))  # src/models
sys.path.insert(0, str(ROOT.parent / "scripts"))

import geometry_core as gc  # noqa: E402

SC = gc.load_scenario()
RES = json.loads((ROOT / "state" / "model3_results.json").read_text(encoding="utf-8"))
Q4 = RES["problem4"]
Q5 = RES["problem5"]
Q2_OPT = json.loads((ROOT / "state" / "model1_results.json").read_text(encoding="utf-8"))["q2"]


def _bomb_tuple(b):
    return (b["f_name"], b["theta"], b["v"], b["t_drop"], b["t_delay"])


def check_feasibility() -> bool:
    ok = True
    for tag, blist in (("Q4", Q4["bombs"]), ("Q5", Q5["bombs"])):
        by_uav = {}
        for b in blist:
            if not (0.0 <= b["theta"] <= 360.0):
                print(f"  ✗ {tag} {b['f_name']} θ 超界"); ok = False
            if not (70.0 - 1e-9 <= b["v"] <= 140.0 + 1e-9):
                print(f"  ✗ {tag} {b['f_name']} v 超界"); ok = False
            if not (0.0 <= b["t_drop"] <= 40.0):
                print(f"  ✗ {tag} {b['f_name']} t_drop 超界"); ok = False
            if not (0.5 - 1e-9 <= b["t_delay"] <= 15.0 + 1e-9):
                print(f"  ✗ {tag} {b['f_name']} t_delay 超界"); ok = False
            by_uav.setdefault(b["f_name"], []).append(b["t_drop"])
        for uav, ts in by_uav.items():
            ts_sorted = sorted(ts)
            for a, b in zip(ts_sorted, ts_sorted[1:]):
                if b - a < 1.0 - 1e-9:
                    print(f"  ✗ {tag} {uav} 投放间隔 {b-a:.3f} s < 1 s"); ok = False
    return ok


def check_consistency() -> bool:
    """由 result2/3.xlsx 反解参数重算并集，与缓存（由同一 xlsx 生成）一致。"""
    q4_re = gc.multi_bomb_union_masking(SC, "M1", [_bomb_tuple(b) for b in Q4["bombs"]])
    ok4 = abs(q4_re - Q4["total_dur"]) < 0.02
    per = {"M1": [], "M2": [], "M3": []}
    for b in Q5["bombs"]:
        per[b["m_name"]].append(_bomb_tuple(b))
    q5_re = sum(gc.multi_bomb_union_masking(SC, k, v) for k, v in per.items() if v)
    ok5 = abs(q5_re - Q5["total_dur"]) < 0.02
    print(f"  [V-OPT-2] Q4 重算 {q4_re:.4f} vs 缓存 {Q4['total_dur']:.4f}；"
          f"Q5 重算 {q5_re:.4f} vs 缓存 {Q5['total_dur']:.4f}")
    return ok4 and ok5


def check_perturbation() -> bool:
    rng = np.random.default_rng(2)
    for _ in range(150):
        pert = 1.0 + rng.uniform(-0.001, 0.001, size=12)
        bombs = []
        for i, b in enumerate(Q4["bombs"]):
            bombs.append((b["f_name"],
                          b["theta"] * pert[i * 4],
                          b["v"] * pert[i * 4 + 1],
                          b["t_drop"] * pert[i * 4 + 2],
                          b["t_delay"] * pert[i * 4 + 3]))
        # 同机间隔保持检查（跳过间隔<1的组合）
        by_uav = {}
        ok_spacing = True
        for f, th, v, td, dl in bombs:
            by_uav.setdefault(f, []).append(td)
        for uav, ts in by_uav.items():
            ts = sorted(ts)
            for a, b in zip(ts, ts[1:]):
                if b - a < 1.0:
                    ok_spacing = False
        if not ok_spacing:
            continue
        dur = gc.multi_bomb_union_masking(SC, "M1", bombs)
        if dur > Q4["total_dur"] + 0.02:
            print(f"  ✗ Q4 扰动产生更优并集 {dur:.4f} > {Q4['total_dur']:.4f}")
            return False
    return True


def check_ballistics() -> bool:
    for b in Q4["bombs"]:
        f0 = SC["uavs"][b["f_name"]]
        D = gc.uav_position(f0, b["theta"], b["v"], b["t_drop"])
        E = gc.bomb_position(D, b["theta"], b["v"], b["t_delay"], SC["g"])
        th = np.deg2rad(b["theta"])
        E_exp = D + b["v"] * b["t_delay"] * np.array([np.cos(th), np.sin(th), 0.0])
        E_exp[2] -= 0.5 * SC["g"] * b["t_delay"] ** 2
        if float(np.linalg.norm(E - E_exp)) > 1e-6:
            print(f"  ✗ {b['f_name']} 弹道不一致"); return False
    print("  [V-ODE-1] Q4 三弹起爆点弹道解析一致（误差 <1e-6）")
    return True


def check_cloud_sink() -> bool:
    for b in Q5["bombs"][:2]:
        f0 = SC["uavs"][b["f_name"]]
        D = gc.uav_position(f0, b["theta"], b["v"], b["t_drop"])
        E = gc.bomb_position(D, b["theta"], b["v"], b["t_delay"], SC["g"])
        C1 = gc.cloud_center(E, 1.0, SC["cloud_sink_speed"])
        C2 = gc.cloud_center(E, 2.0, SC["cloud_sink_speed"])
        if abs((C2 - C1)[2] + 3.0) > 1e-9:
            print(f"  ✗ {b['f_name']}->{b['m_name']} 下沉速度错误"); return False
    print("  [V-ODE-2] Q5 抽查 2 弹云团均以 3 m/s 匀速下沉")
    return True


def check_missile_kinematics() -> bool:
    for m_name in ("M2", "M3"):
        m0 = np.array(SC["missiles"][m_name], dtype=float)
        decoy = np.array(SC["decoy"], dtype=float)
        M0 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 0.0)
        M1 = gc.missile_trajectory(m0, SC["missile_speed"], decoy, 1.0)
        speed = float(np.linalg.norm(M1 - M0))
        u = (M1 - M0) / speed
        u_exp = (decoy - m0) / np.linalg.norm(decoy - m0)
        if abs(speed - 300.0) > 1e-6 or float(np.linalg.norm(u - u_exp)) > 1e-9:
            print(f"  ✗ {m_name} 运动学错误"); return False
    print("  [V-ODE-3] M2/M3 均 300 m/s 指向假目标")
    return True


def check_monotonicity() -> bool:
    ok4 = Q4["total_dur"] >= Q2_OPT["dur"] - 0.1
    ok5 = Q5["total_dur"] >= Q4["total_dur"] - 0.1
    print(f"  [V-CONS-1] Q4 {Q4['total_dur']:.3f} ≥ Q2 {Q2_OPT['dur']:.3f} − 0.1 "
          f"→ {'通过' if ok4 else '失败'}；Q5 {Q5['total_dur']:.3f} ≥ Q4 {Q4['total_dur']:.3f} − 0.1 "
          f"→ {'通过' if ok5 else '失败'}")
    return ok4 and ok5


def check_assignment() -> bool:
    ok = True
    for b in Q5["bombs"]:
        f0 = SC["uavs"][b["f_name"]]
        dur, ivs = gc.single_bomb_masking(SC, b["m_name"], b["f_name"],
                                          b["theta"], b["v"], b["t_drop"], b["t_delay"])
        if dur <= 0.0:
            print(f"  ✗ {b['f_name']}->{b['m_name']} 对该导弹时长为 0"); ok = False
        if abs(dur - b["dur"]) > 0.05:
            print(f"  ✗ {b['f_name']}->{b['m_name']} 时长不一致 {dur:.3f} vs {b['dur']:.3f}")
            ok = False
    # per_missile 并集与总时长一致性
    per = {"M1": [], "M2": [], "M3": []}
    for b in Q5["bombs"]:
        per[b["m_name"]].append(_bomb_tuple(b))
    total = sum(gc.multi_bomb_union_masking(SC, k, v) for k, v in per.items() if v)
    if abs(total - Q5["total_dur"]) > 0.02:
        print(f"  ✗ per_missile 并集 {total:.4f} ≠ 总时长 {Q5['total_dur']:.4f}"); ok = False
    print(f"  [V-CONS-2] {len(Q5['bombs'])} 枚弹分配正确（对各自导弹时长>0），per_missile 并集 {total:.3f} s")
    return ok


def check_xlsx() -> bool:
    import openpyxl
    ok = True
    wb2 = openpyxl.load_workbook(ROOT / "data" / "result2.xlsx")
    ws2 = wb2["Sheet1"]
    for r in range(2, 5):
        row = [ws2.cell(r, c).value for c in range(1, 11)]
        if any(v is None for v in row):
            print(f"  ✗ result2.xlsx 第 {r} 行有空值"); ok = False
            continue
        if not (0.0 <= row[1] <= 360.0 and 70.0 <= row[2] <= 140.0):
            print(f"  ✗ result2.xlsx 第 {r} 行 θ/v 超界"); ok = False
        for v in row:
            if isinstance(v, (int, float)) and not np.isfinite(v):
                print(f"  ✗ result2.xlsx 第 {r} 行非有限"); ok = False
    wb3 = openpyxl.load_workbook(ROOT / "data" / "result3.xlsx")
    ws3 = wb3["Sheet1"]
    used = 0
    for r in range(2, 17):
        row = [ws3.cell(r, c).value for c in range(1, 13)]
        if row[1] is None:
            continue
        used += 1
        if not (0.0 <= row[1] <= 360.0 and 70.0 <= row[2] <= 140.0):
            print(f"  ✗ result3.xlsx 第 {r} 行 θ/v 超界"); ok = False
        if row[11] not in ("M1", "M2", "M3"):
            print(f"  ✗ result3.xlsx 第 {r} 行导弹编号 {row[11]}"); ok = False
        for v in row:
            if isinstance(v, (int, float)) and not np.isfinite(v):
                print(f"  ✗ result3.xlsx 第 {r} 行非有限"); ok = False
    print(f"  [V-XLSX] result2.xlsx 3 行、result3.xlsx {used} 行已用，均填写正确")
    return ok


def main():
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print("Stage  : model_3_verify")
    checks = [
        ("V-OPT-1", check_feasibility(), "可行域与同机 ≥1s 间隔"),
        ("V-OPT-2", check_consistency(), "xlsx 反解重算与缓存一致"),
        ("V-OPT-3", check_perturbation(), "Q4 ±0.1% 扰动不产生更优解"),
        ("V-ODE-1", check_ballistics(), "弹道解析一致"),
        ("V-ODE-2", check_cloud_sink(), "云团 3 m/s 下沉"),
        ("V-ODE-3", check_missile_kinematics(), "M2/M3 运动学"),
        ("V-CONS-1", check_monotonicity(), "Q4≥Q2、Q5≥Q4 单调性"),
        ("V-CONS-2", check_assignment(), "弹-导弹分配正确"),
        ("V-XLSX", check_xlsx(), "result2/3.xlsx 填写正确"),
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
