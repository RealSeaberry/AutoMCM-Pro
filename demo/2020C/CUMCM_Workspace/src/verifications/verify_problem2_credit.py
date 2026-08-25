# -*- coding: utf-8 -*-
"""
verify_problem2_credit.py — 问题2 模型验证
验证项:
  1. 迁移打分: 302 家全部有 PD, 无 NaN, PD∈[0,1]
  2. 与问题1 评分器一致性: 用 scorer 重算 PD 与 strategy_p2.csv 一致(误差<1e-9)
  3. 分布偏移已量化: psi_report.csv 存在且覆盖关键特征
  4. 分层单调: 伪评级 A/B/C/D 的 PD 均值递增
  5. 预算约束: 总分配额度 ≈ 1 亿元(10000 万元), 不超支
  6. 利率约束: 放贷企业利率 ∈ [4%,15%]
  7. 额度约束: 各企业额度 ≤ cap, 非负
  8. 政策约束: 伪评级 D 不放贷
"""
import sys
import os
import pickle
import numpy as np
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
LOG_FEAT_KEYS = ("sum_amt", "net_amt", "avg_inv", "max_inv", "sum_tax",
                 "n_inv", "n_void", "n_counterpart", "inv_per_active_month", "n_active_month")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}: {detail}")


def main():
    print("=" * 60)
    print("VERIFICATION — model_2_verify (problem2_credit)")
    print("=" * 60)
    f2 = pd.read_csv(os.path.join(DATA, "features_a2.csv"))
    strat = pd.read_csv(os.path.join(DATA, "strategy_p2.csv"))
    with open(os.path.join(DATA, "scorer_p1.pkl"), "rb") as fh:
        scorer = pickle.load(fh)

    # --- 1. 打分完整性 ---
    check("迁移打分: 302 家全覆盖", len(strat) == 302, f"策略表 {len(strat)} 行")
    check("PD 无 NaN/inf", np.isfinite(strat["PD"]).all(), f"NaN={strat['PD'].isna().sum()}")
    check("PD 范围 [0,1]", strat["PD"].between(0, 1).all(),
          f"min={strat['PD'].min():.4f}, max={strat['PD'].max():.4f}")

    # --- 2. 与评分器一致性 ---
    X = f2[scorer["feats"]].copy()
    for c in scorer["feats"]:
        if any(k in c for k in LOG_FEAT_KEYS):
            X[c] = np.log1p(X[c].clip(lower=0))
    pd_re = scorer["model"].predict_proba(scorer["scaler"].transform(X))[:, 1]
    merged = f2[["企业代号"]].merge(strat[["企业代号", "PD"]], on="企业代号")
    max_diff = np.abs(merged["PD"].values - pd_re).max()
    check("一致性: 重算 PD 与保存值一致", max_diff < 1e-9, f"max|ΔPD|={max_diff:.2e}")

    # --- 3. PSI 报告 ---
    psi = pd.read_csv(os.path.join(DATA, "psi_report.csv"))
    check("PSI 报告存在且≥6 特征", len(psi) >= 6, f"{len(psi)} 个特征")
    check("PSI 数值合理", np.isfinite(psi["PSI"]).all() and (psi["PSI"] >= 0).all(),
          f"PSI 范围 [{psi['PSI'].min():.4f}, {psi['PSI'].max():.4f}]")

    # --- 4. 分层单调 ---
    grp = strat.groupby("tier")["PD"].mean()
    order = ["A", "B", "C", "D"]
    vals = [grp.get(t, np.nan) for t in order]
    check("分层单调: PD 均值 A<B<C<D", all(vals[i] < vals[i + 1] for i in range(3)),
          " ".join(f"{t}={v:.4f}" for t, v in zip(order, vals)))

    # --- 5. 预算约束 ---
    total = strat["amount_wan"].sum()
    check("预算: 总分配 ≈ 10000 万元", abs(total - 10000.0) < 1e-6, f"总分配={total:.2f} 万元")
    check("预算: 不超支", total <= 10000.0 + 1e-6, f"{total:.2f} ≤ 10000")

    # --- 6. 利率约束 ---
    r = strat["rate_opt"].dropna()
    check("利率 ∈ [4%,15%]", ((r >= 0.04) & (r <= 0.15)).all(),
          f"min={r.min():.4f}, max={r.max():.4f}")

    # --- 7. 额度约束 ---
    check("额度 ≤ cap", (strat["amount_wan"] <= strat["cap_wan"] + 1e-6).all(),
          f"超限家数={((strat['amount_wan'] > strat['cap_wan'] + 1e-6)).sum()}")
    check("额度非负", (strat["amount_wan"] >= 0).all(), f"负额度家数={(strat['amount_wan'] < 0).sum()}")

    # --- 8. 政策约束 ---
    d_lent = strat[(strat["tier"] == "D") & (strat["amount_wan"] > 0)]
    check("伪评级 D 不放贷", len(d_lent) == 0, f"D 层级放贷家数={len(d_lent)}")

    print("=" * 60)
    n_pass = sum(1 for _, ok, _ in results if ok)
    print("========== VERIFICATION REPORT ==========")
    print("Stage  : model_2_verify")
    print(f"Result : {'PASS' if n_pass == len(results) else 'FAIL'}")
    print("Checks :")
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
    print(f"  ({n_pass}/{len(results)} 项通过)")
    print("==========================================")
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
