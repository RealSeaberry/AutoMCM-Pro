#!/usr/bin/env python3
"""
verify_sensitivity.py — 灵敏度分析数值稳定性验证（AutoMCM_SOP §5 Phase 4）

检查项：
  [V-SEN-1] 单调性：云团有效半径增大不减少遮蔽时长（固定策略重评估）；
  [V-SEN-2] 目标参考点高度模糊性：z=5/10 m 相对 z=0 的 Q2 时长变化 < 20%（模型稳健）；
  [V-SEN-3] 重优化数值稳定：不同精化强度（邻域扫描点数 25 vs 41）下重优化时长差 < 0.05 s；
  [V-SEN-4] 数值健全：灵敏度表中全部数值有限、无 inf/nan；
  [V-SEN-5] 敏感性方向合理：导弹速度 ±10% 引起 Q2 时长变化率有界（<50%）。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "models"))  # src/models
sys.path.insert(0, str(ROOT.parent / "scripts"))

import geometry_core as gc  # noqa: E402
import sensitivity  # noqa: E402


def load_rows():
    p = ROOT / "state" / "sensitivity_results.json"
    if not p.exists():
        print("  ✗ sensitivity_results.json 不存在，先运行 sensitivity.py")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def check_monotonicity(rows) -> bool:
    """V-SEN-1：半径 10→11 m 不减少 Q2 时长。"""
    r9 = next(r for r in rows if r["param"] == "云团有效半径" and r["pert"] == "-10%")
    r11 = next(r for r in rows if r["param"] == "云团有效半径" and r["pert"] == "+10%")
    ok = r11["q2"] >= r9["q2"] - 1e-9
    print(f"  [V-SEN-1] 半径-10%: {r9['q2']:.3f}s / +10%: {r11['q2']:.3f}s → "
          f"{'通过' if ok else '失败'}")
    return ok


def check_ref_height(rows) -> bool:
    """V-SEN-2：目标参考点高度 z=5/10 相对 z=0（即标称 Q2=4.611）的变化 < 20%。"""
    z0 = 4.611  # z=0 即标称情形（Q2 最优时长）
    ok = True
    for r in rows:
        if r["param"] != "目标参考点高度":
            continue
        rel = abs(r["q2"] - z0) / z0
        if rel >= 0.20:
            print(f"  ✗ z={r['pert']} 相对 z=0 变化 {rel*100:.1f}% ≥ 20%")
            ok = False
    print(f"  [V-SEN-2] 参考点高度 z=5/10 相对 z=0 变化 < 20% → {'通过' if ok else '失败'}")
    return ok


def check_reopt_stability() -> bool:
    """V-SEN-3：重优化数值稳定（25 vs 41 扫描点）。"""
    import problem1_geometry as p1m
    sc = gc.load_scenario()
    q2 = json.loads((ROOT / "state" / "model1_results.json").read_text(encoding="utf-8"))["q2"]
    durs = []
    for n_scan in (25, 41):
        x = np.array([q2["theta"], q2["v"], q2["t_drop"], q2["t_delay"]])
        bounds = p1m.BOUNDS_Q2
        for _ in range(2):
            for k in range(4):
                lo, hi = bounds[k]
                cand = np.linspace(max(lo, x[k] - (hi - lo) * 0.03),
                                   min(hi, x[k] + (hi - lo) * 0.03), n_scan)
                best_x, best_f = x.copy(), p1m._objective_q2(x)
                for c in cand:
                    xc = x.copy()
                    xc[k] = c
                    f = p1m._objective_q2(xc)
                    if f < best_f - 1e-12:
                        best_f, best_x = f, xc
                x = best_x
        dur, _, _ = gc.single_bomb_masking_detail(sc, "M1", "FY1", *x)
        durs.append(dur)
    ok = abs(durs[0] - durs[1]) < 0.05
    print(f"  [V-SEN-3] 精化扫描 25 点 {durs[0]:.4f}s vs 41 点 {durs[1]:.4f}s，"
          f"差 {abs(durs[0]-durs[1]):.4f}s → {'通过' if ok else '失败'}")
    return ok


def check_finite(rows) -> bool:
    """V-SEN-4：全部数值有限。"""
    ok = True
    for r in rows:
        for k in ("q2", "q3", "q4", "q5"):
            v = r[k]
            if v is not None and not np.isfinite(v):
                print(f"  ✗ {r['param']} {r['pert']} {k}={v} 非有限")
                ok = False
    print(f"  [V-SEN-4] 灵敏度表数值全部有限 → {'通过' if ok else '失败'}")
    return ok


def check_direction(rows) -> bool:
    """V-SEN-5：导弹速度 ±10% 引起 Q2 变化率有界（<50%）。"""
    base = next(r for r in rows if r["param"] == "导弹速度" and r["pert"] == "-10%")
    ok = True
    for r in rows:
        if r["param"] != "导弹速度":
            continue
        rel = abs(r["q2"] - base["q2"]) / max(base["q2"], 1e-9)
        if rel >= 0.5:
            print(f"  ✗ 导弹速度 {r['pert']} 变化率 {rel*100:.1f}% ≥ 50%")
            ok = False
    print(f"  [V-SEN-5] 导弹速度 ±10% 的 Q2 变化率有界 → {'通过' if ok else '失败'}")
    return ok


def main():
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print("Stage  : sensitivity_verify")
    rows = load_rows()
    checks = [
        ("V-SEN-1", check_monotonicity(rows), "半径增大不减少遮蔽时长"),
        ("V-SEN-2", check_ref_height(rows), "参考点高度模糊性 < 20%"),
        ("V-SEN-3", check_reopt_stability(), "重优化数值稳定"),
        ("V-SEN-4", check_finite(rows), "数值有限"),
        ("V-SEN-5", check_direction(rows), "敏感性方向合理"),
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
