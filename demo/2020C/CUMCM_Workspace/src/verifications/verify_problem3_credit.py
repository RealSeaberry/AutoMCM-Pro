# -*- coding: utf-8 -*-
"""
verify_problem3_credit.py — 问题3 模型验证
验证项:
  1. 类别完整性: 302 家全部分配类别, 冲击系数 ∈ 文献设定集合
  2. 冲击传导正确性: PD_shock = clip(PD_base·(1+impact)), 独立重算一致(误差<1e-9)
  3. 冲击方向: 冲击后 PD 均值上升; 逐企业 PD_shock ≥ PD_base
  4. 预算约束: 冲击后总分配 ≈ 10000 万元, 不超支
  5. 额度约束: 各企业额度 ≤ 冲击后 cap, 非负
  6. 利率约束: 放贷企业最优利率 ∈ [4%,15%]
  7. 政策约束: 伪评级 D 不放贷
  8. 调整动作一致性: delta_wan 符号与 action 标签吻合
"""
import sys
import os
import pickle
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}: {detail}")


def optimal_rate(pd_val, tier, churn_fns, rate_grid):
    if tier == "D":
        return None
    fn = churn_fns[tier]
    best_r, best_p = None, 0.0
    for r in rate_grid:
        rev = r * (1 - pd_val) - pd_val
        if rev <= 0:
            continue
        p = (1 - fn(r)) * rev
        if p > best_p:
            best_p, best_r = p, r
    return best_r


def main():
    print("=" * 60)
    print("VERIFICATION — model_3_verify (problem3_credit)")
    print("=" * 60)
    f2 = pd.read_csv(os.path.join(DATA, "features_a2.csv"))
    res = pd.read_csv(os.path.join(DATA, "strategy_p3.csv"))
    with open(os.path.join(DATA, "scorer_p1.pkl"), "rb") as fh:
        scorer = pickle.load(fh)

    # --- 1. 类别完整性 ---
    check("类别: 302 家全覆盖", len(res) == 302, f"{len(res)} 行")
    check("类别: 标签均为已定义类别", res["cluster_label"].isin(
        ["大型批发-制造型", "大额低频-项目工程型", "购销失衡-贸易中介型",
         "高频小额-零售餐饮型", "低活跃-个体微型"]).all(),
        f"实际类别={sorted(res['cluster_label'].unique())}")
    check("冲击系数 ∈ {0.10,0.15,0.20,0.25,0.35}", res["impact"].isin([0.10, 0.15, 0.20, 0.25, 0.35]).all(),
          f"实际系数={sorted(res['impact'].unique())}")

    # --- 2. 冲击传导重算 ---
    pd_shock_re = np.clip(res["PD_base"].values * (1 + res["impact"].values), 0, 0.95)
    max_diff = np.abs(res["PD_shock"].values - pd_shock_re).max()
    check("冲击传导: 重算 PD_shock 一致", max_diff < 1e-9, f"max|Δ|={max_diff:.2e}")

    # --- 3. 冲击方向 ---
    check("冲击方向: 均值 PD 上升", res["PD_shock"].mean() > res["PD_base"].mean(),
          f"{res['PD_base'].mean():.4f} → {res['PD_shock'].mean():.4f}")
    # 逐企业: PD_shock ≥ PD_base, 但 PD_base>0.95 的企业受 0.95 截断保护可合法降低
    viol = res[(res["PD_shock"] < res["PD_base"] - 1e-12) & (res["PD_base"] < 0.95)]
    check("冲击方向: 逐企业 PD_shock ≥ PD_base（0.95 截断除外）", len(viol) == 0,
          f"违反家数={len(viol)}")

    # --- 4. 预算约束 ---
    total = res["amount_wan_shock"].sum()
    check("预算: 总分配 ≈ 10000 万元", abs(total - 10000.0) < 1e-6, f"{total:.2f} 万元")
    check("预算: 不超支", total <= 10000.0 + 1e-6, f"{total:.2f} ≤ 10000")

    # --- 5. 额度约束（冲击后 cap 含销项收缩; 按企业代号对齐） ---
    merged = f2[["企业代号", "out_sum_amt_pos"]].merge(
        res[["企业代号", "tier", "impact", "amount_wan_shock"]], on="企业代号")
    cap = np.minimum(merged["tier"].map(scorer["rating_cap"]).values,
                     scorer["turnover_ratio"] * merged["out_sum_amt_pos"].values / 1e4
                     * (1 - 0.5 * merged["impact"].values))
    check("额度 ≤ 冲击后 cap", (merged["amount_wan_shock"] <= np.clip(cap, 0, None) + 1e-6).all(),
          f"超限家数={(merged['amount_wan_shock'] > np.clip(cap, 0, None) + 1e-6).sum()}")
    check("额度非负", (res["amount_wan_shock"] >= 0).all(),
          f"负额度家数={(res['amount_wan_shock'] < 0).sum()}")

    # --- 6. 利率约束（重算最优利率） ---
    churn = pd.DataFrame(scorer["churn"])
    churn_fns = {r: interp1d(churn["rate"].values, churn[r].values, kind="linear",
                             bounds_error=False, fill_value=(churn[r].values[0], churn[r].values[-1]))
                 for r in ["A", "B", "C"]}
    rate_grid = scorer["rate_grid"]
    rates = []
    for _, row in res[res["amount_wan_shock"] > 0].iterrows():
        rates.append(optimal_rate(row["PD_shock"], row["tier"], churn_fns, rate_grid))
    rates = [r for r in rates if r is not None]
    check("利率 ∈ [4%,15%]", rates and all(0.04 <= r <= 0.15 for r in rates),
          f"min={min(rates):.4f}, max={max(rates):.4f} (n={len(rates)})")

    # --- 7. 政策约束 ---
    d_lent = res[(res["tier"] == "D") & (res["amount_wan_shock"] > 0)]
    check("伪评级 D 不放贷", len(d_lent) == 0, f"D 层级放贷家数={len(d_lent)}")

    # --- 8. 调整动作一致性 ---
    act_ok = True
    for _, row in res.iterrows():
        d = row["delta_wan"]
        a = row["action"]
        if a == "维持" and abs(d) > 1e-6 and row["amount_wan_base"] > 0:
            act_ok = False
        if a == "收缩" and d >= -1e-6:
            act_ok = False
        if a == "加码" and d <= 1e-6:
            act_ok = False
    check("调整动作与 delta 符号一致", act_ok,
          f"动作分布={res['action'].value_counts().to_dict()}")

    print("=" * 60)
    n_pass = sum(1 for _, ok, _ in results if ok)
    print("========== VERIFICATION REPORT ==========")
    print("Stage  : model_3_verify")
    print(f"Result : {'PASS' if n_pass == len(results) else 'FAIL'}")
    print("Checks :")
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
    print(f"  ({n_pass}/{len(results)} 项通过)")
    print("==========================================")
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
