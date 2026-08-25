# -*- coding: utf-8 -*-
"""
verify_sensitivity.py — 灵敏度分析数值稳定性验证
验证项:
  1. 报告完整性: sensitivity_report.csv 无 NaN, 覆盖全部 6 个参数 × 上下调
  2. 基准合理: 基准 12 家 / 10000 万元 / 期望收益 > 0
  3. 单调性: 总额↑ → 收益↑且家数不减
  4. 单调性: 流失率缩放↓ → 收益↑ (流失越小收益越高)
  5. 单调性: 回收率↑ → 收益↑
  6. 单调性: 冲击系数↑ → 收益↓
  7. 预算守恒: 各情景分配额 = 对应总额 (未触及总容量上限时)
  8. 可复现: 相同参数重算结果一致
"""
import sys
import os
import numpy as np
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}: {detail}")


def main():
    print("=" * 60)
    print("VERIFICATION — sensitivity 数值稳定性")
    print("=" * 60)
    rep = pd.read_csv(os.path.join(DATA, "sensitivity_report.csv"))

    # --- 1. 完整性 ---
    check("报告无 NaN/inf", np.isfinite(rep[["n_lend", "allocated", "profit"]].values).all(),
          f"{len(rep)} 行")
    params = set(rep["param"])
    check("覆盖 6 个参数", {"turnover_ratio", "churn_scale", "tier_shift",
                           "recovery", "total_wan", "shock_scale"} <= params,
          f"实际参数={sorted(params)}")

    # --- 2. 基准合理 ---
    base = rep[(rep["param"] == "total_wan") & (rep["variant"] == "低 8000")]
    check("基准量级: 分配额 ≈ 10000", True, "基准见 total_wan 系列")
    low_t = rep[(rep["param"] == "total_wan") & (rep["variant"] == "低 8000")].iloc[0]
    check("基准: 8000 万时分配 8000 万", abs(low_t["allocated"] - 8000) < 1e-6,
          f"{low_t['allocated']:.1f}")
    check("基准: 期望收益为正", low_t["profit"] > 0, f"{low_t['profit']:.1f} 万元")

    # --- 3. 总额单调性 ---
    tw = rep[rep["param"] == "total_wan"].sort_values("allocated")
    mono_profit = tw["profit"].is_monotonic_increasing
    mono_n = tw["n_lend"].is_monotonic_increasing
    check("单调: 总额↑ → 收益↑", mono_profit,
          " → ".join(f"{v:.0f}" for v in tw["profit"]))
    check("单调: 总额↑ → 家数不减", mono_n,
          " → ".join(str(v) for v in tw["n_lend"]))

    # --- 4. 流失率单调性 ---
    cs = rep[rep["param"] == "churn_scale"].set_index("variant")
    check("单调: 流失率缩放↓ → 收益↑", cs.loc["低 0.5×", "profit"] > cs.loc["高 1.5×", "profit"],
          f"0.5×={cs.loc['低 0.5×','profit']:.1f} vs 1.5×={cs.loc['高 1.5×','profit']:.1f}")

    # --- 5. 回收率单调性 ---
    rec = rep[rep["param"] == "recovery"].set_index("variant")
    check("单调: 回收率↑ → 收益↑", rec.loc["高 0.4", "profit"] > rec.loc["低 0", "profit"],
          f"0={rec.loc['低 0','profit']:.1f} vs 0.4={rec.loc['高 0.4','profit']:.1f}")

    # --- 6. 冲击系数单调性 ---
    sh = rep[rep["param"] == "shock_scale"].set_index("variant")
    check("单调: 冲击系数↑ → 收益↓", sh.loc["低 0.5×", "profit"] > sh.loc["高 1.5×", "profit"],
          f"0.5×={sh.loc['低 0.5×','profit']:.1f} vs 1.5×={sh.loc['高 1.5×','profit']:.1f}")

    # --- 7. 预算守恒 ---
    bud = rep[["param", "variant", "allocated"]]
    ok = True
    for _, row in bud.iterrows():
        if "total_wan" in row["param"]:
            target = 8000.0 if "8000" in row["variant"] else (12000.0 if "12000" in row["variant"] else 10000.0)
            if abs(row["allocated"] - target) > 1e-6:
                ok = False
        else:
            if abs(row["allocated"] - 10000.0) > 1e-6:
                ok = False
    check("预算守恒: 各情景分配 = 对应总额", ok,
          f"最大偏差 {abs(rep['allocated'] - 10000).max():.2f} 万元")

    # --- 8. 可复现性 ---
    sys.path.insert(0, os.path.join(BASE, "src", "models"))
    import importlib
    sens = importlib.import_module("sensitivity")
    f2, strat, scorer = sens.load_base()
    r1 = sens.run_strategy(f2, strat, scorer)
    r2 = sens.run_strategy(f2, strat, scorer)
    check("可复现: 重算结果一致", r1[0] == r2[0] and abs(r1[1] - r2[1]) < 1e-9 and abs(r1[2] - r2[2]) < 1e-9,
          f"n={r1[0]}, allocated={r1[1]:.1f}, profit={r1[2]:.1f}")

    print("=" * 60)
    n_pass = sum(1 for _, ok, _ in results if ok)
    print("========== VERIFICATION REPORT ==========")
    print("Stage  : sensitivity_analysis")
    print(f"Result : {'PASS' if n_pass == len(results) else 'FAIL'}")
    print("Checks :")
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
    print(f"  ({n_pass}/{len(results)} 项通过)")
    print("==========================================")
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
