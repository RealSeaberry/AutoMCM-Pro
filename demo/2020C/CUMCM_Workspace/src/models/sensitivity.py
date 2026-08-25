# -*- coding: utf-8 -*-
"""
sensitivity.py — 灵敏度分析（参数扰动 + tornado 图）
2020 CUMCM C 题《中小微企业的信贷决策》

对问题2/3 策略模型的关键假设做单参数扰动, 度量对
  (a) 总期望收益 (b) 放贷家数 (c) 分配结构 的影响。
参数:
  1. turnover_ratio  额度上限比例       0.15 / 0.25(base) / 0.35
  2. churn_scale     流失率缩放         0.5× / 1.0× / 1.5×
  3. tier_shift      伪评级分层阈值偏移  −20% / 0 / +20%
  4. recovery        违约回收率(损失缓解) 0 / 0.2 / 0.4
  5. shock_scale     冲击系数缩放(问题3) 0.5× / 1.0× / 1.5×
  6. total_wan       信贷总额           8000 / 10000(base) / 12000 万元
输出:
  - CUMCM_Workspace/data/sensitivity_report.csv
  - CUMCM_Workspace/latex/images/fig40_*.png (tornado 图)
"""
import sys
import os
import pickle
import warnings
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
plot_style.apply()

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
IMG = os.path.join(BASE, "latex", "images")
os.makedirs(IMG, exist_ok=True)

BASE_TOTAL = 10000.0


def load_base():
    f2 = pd.read_csv(os.path.join(DATA, "features_a2.csv"))
    strat = pd.read_csv(os.path.join(DATA, "strategy_p2.csv"))
    with open(os.path.join(DATA, "scorer_p1.pkl"), "rb") as fh:
        scorer = pickle.load(fh)
    return f2, strat, scorer


def churn_fns_from(scorer, scale=1.0):
    churn = pd.DataFrame(scorer["churn"])
    fns = {}
    for r in ["A", "B", "C"]:
        y = np.clip(churn[r].values * scale, 0, 1)
        fns[r] = interp1d(churn["rate"].values, y, kind="linear",
                          bounds_error=False, fill_value=(y[0], y[-1]))
    return fns


def optimal_rate_and_profit(pd_val, tier, churn_fns, rate_grid, recovery=0.0):
    if tier == "D":
        return None, 0.0
    fn = churn_fns[tier]
    best_r, best_p = None, 0.0
    for r in rate_grid:
        rev = r * (1 - pd_val) - pd_val * (1 - recovery)
        if rev <= 0:
            continue
        p = (1 - fn(r)) * rev
        if p > best_p:
            best_p, best_r = p, r
    return best_r, best_p


def run_strategy(f2, strat, scorer, total_wan=BASE_TOTAL, turnover_ratio=None,
                 churn_scale=1.0, tier_shift=0.0, recovery=0.0):
    """带参数化假设的问题2 策略计算。返回 (n_lend, allocated, profit, 结构表)。"""
    turnover_ratio = scorer["turnover_ratio"] if turnover_ratio is None else turnover_ratio
    rate_grid = scorer["rate_grid"]
    cf = churn_fns_from(scorer, churn_scale)
    rating_cap = scorer["rating_cap"]

    # 分层阈值: 从 strategy_p2 的层级 PD 均值反推, 再按 tier_shift 平移
    means = strat.groupby("tier")["PD"].mean()
    b = [(means["A"] + means["B"]) / 2, (means["B"] + means["C"]) / 2, (means["C"] + means["D"]) / 2]
    b = [x * (1 + tier_shift) for x in b]

    pd_vals = strat["PD"].values
    tiers = []
    for p in pd_vals:
        if p < b[0]:
            tiers.append("A")
        elif p < b[1]:
            tiers.append("B")
        elif p < b[2]:
            tiers.append("C")
        else:
            tiers.append("D")
    tiers = np.array(tiers)

    out = pd.DataFrame({"企业代号": strat["企业代号"], "PD": pd_vals, "tier": tiers})
    amt = out[["企业代号"]].merge(f2[["企业代号", "out_sum_amt_pos"]], on="企业代号")["out_sum_amt_pos"].values
    out["rate_opt"] = np.nan
    out["profit_unit"] = 0.0
    for i, row in out.iterrows():
        r, p = optimal_rate_and_profit(row["PD"], row["tier"], cf, rate_grid, recovery)
        out.loc[i, "rate_opt"] = r if r is not None else np.nan
        out.loc[i, "profit_unit"] = p
    cap = np.minimum(out["tier"].map(rating_cap).values, turnover_ratio * amt / 1e4)
    out["cap_wan"] = np.clip(cap, 0, None)
    out["amount_wan"] = 0.0
    order_idx = np.argsort(-out["profit_unit"].values, kind="stable")
    remaining = total_wan
    for i in order_idx:
        if out.loc[i, "profit_unit"] <= 0 or out.loc[i, "cap_wan"] <= 0:
            continue
        take = min(out.loc[i, "cap_wan"], remaining)
        out.loc[i, "amount_wan"] = take
        remaining -= take
        if remaining <= 1e-6:
            break
    out["expected_profit"] = out["amount_wan"] * out["profit_unit"]
    n_lend = int((out["amount_wan"] > 0).sum())
    allocated = total_wan - remaining
    profit = out["expected_profit"].sum()
    struct = out[out["amount_wan"] > 0].groupby("tier")["amount_wan"].sum().to_dict()
    return n_lend, allocated, profit, struct


def run_shock_scenario(f2, strat, scorer, shock_scale=1.0, total_wan=BASE_TOTAL):
    """问题3 冲击情景（参数: 冲击系数缩放）。"""
    p3 = pd.read_csv(os.path.join(DATA, "strategy_p3.csv"))
    f2i = f2.merge(p3[["企业代号", "impact"]], on="企业代号", how="left")
    f2i["impact"] = f2i["impact"].fillna(0.0) * shock_scale
    f2s = f2i.copy()
    f2s["out_sum_amt_pos"] = f2s["out_sum_amt_pos"] * (1 - 0.5 * f2s["impact"])
    pd_shock = np.clip(strat["PD"].values * (1 + f2i["impact"].values), 0, 0.95)
    strat_s = strat[["企业代号", "tier"]].assign(PD=pd_shock)
    return run_strategy(f2s, strat_s, scorer, total_wan=total_wan)


def main():
    print("=" * 66)
    print("sensitivity — 参数灵敏度分析（tornado 图）")
    print("=" * 66)
    f2, strat, scorer = load_base()

    base = run_strategy(f2, strat, scorer)
    print(f"[BASE] 放贷 {base[0]} 家, 分配 {base[1]:.0f} 万元, 期望收益 {base[2]:.0f} 万元")

    rows = []
    variants = {
        "turnover_ratio": [("低 0.15", dict(turnover_ratio=0.15)), ("高 0.35", dict(turnover_ratio=0.35))],
        "churn_scale": [("低 0.5×", dict(churn_scale=0.5)), ("高 1.5×", dict(churn_scale=1.5))],
        "tier_shift": [("低 −20%", dict(tier_shift=-0.2)), ("高 +20%", dict(tier_shift=0.2))],
        "recovery": [("低 0", dict(recovery=0.0)), ("高 0.4", dict(recovery=0.4))],
        "total_wan": [("低 8000", dict(total_wan=8000.0)), ("高 12000", dict(total_wan=12000.0))],
    }
    for pname, vlist in variants.items():
        for vlabel, kw in vlist:
            n, al, prof, struct = run_strategy(f2, strat, scorer, **kw)
            rows.append({"param": pname, "variant": vlabel, "n_lend": n,
                         "allocated": al, "profit": prof,
                         "d_profit": prof - base[2], "d_n_lend": n - base[0]})
    # 问题3 冲击系数缩放
    base3 = run_shock_scenario(f2, strat, scorer, shock_scale=1.0)
    for s, lab in [(0.5, "低 0.5×"), (1.5, "高 1.5×")]:
        n, al, prof, struct = run_shock_scenario(f2, strat, scorer, shock_scale=s)
        rows.append({"param": "shock_scale", "variant": lab, "n_lend": n,
                     "allocated": al, "profit": prof,
                     "d_profit": prof - base3[2], "d_n_lend": n - base3[0]})

    rep = pd.DataFrame(rows)
    rep.to_csv(os.path.join(DATA, "sensitivity_report.csv"), index=False, encoding="utf-8-sig")
    print("\n[sens] 灵敏度报告:")
    print(rep.to_string(index=False))

    # ---------- tornado 图（§18 灵敏度惯例: 按影响幅度排序的水平条形） ----------
    # 期望收益 tornado
    fig, ax = plt.subplots(figsize=(9, 5.5))
    prof_wide = rep.pivot(index="param", columns="variant", values="d_profit")
    order = rep.groupby("param")["d_profit"].apply(lambda s: s.abs().max()).sort_values().index
    y = 0
    labels = []
    for p in order:
        lows = prof_wide.loc[p].dropna()
        lo, hi = lows.min(), lows.max()
        ax.barh(y, max(0, hi), left=0, color=plot_style.CATEGORICAL[0], height=0.55)
        ax.barh(y, -max(0, -lo), left=0, color=plot_style.CATEGORICAL[1], height=0.55)
        ax.text(hi + 3, y, f"+{hi:.0f}", va="center", fontsize=8)
        ax.text(lo - 3, y, f"{lo:.0f}", va="center", ha="right", fontsize=8)
        labels.append(p)
        y += 1
    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("期望收益变化（万元，相对基准）")
    ax.set_title("灵敏度：关键参数对总期望收益的影响（tornado 图）")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=plot_style.CATEGORICAL[0], label="参数上调"),
                       Patch(color=plot_style.CATEGORICAL[1], label="参数下调")],
              frameon=False, loc="lower right")
    plot_style.save(fig, os.path.join(IMG, "fig40_01_profit_tornado.png"))

    # 放贷家数 tornado
    fig, ax = plt.subplots(figsize=(9, 5.5))
    nl_wide = rep.pivot(index="param", columns="variant", values="d_n_lend")
    order = rep.groupby("param")["d_n_lend"].apply(lambda s: s.abs().max()).sort_values().index
    y = 0
    for p in order:
        lows = nl_wide.loc[p].dropna()
        lo, hi = lows.min(), lows.max()
        ax.barh(y, max(0, hi), left=0, color=plot_style.CATEGORICAL[0], height=0.55)
        ax.barh(y, -max(0, -lo), left=0, color=plot_style.CATEGORICAL[1], height=0.55)
        ax.text(hi + 0.4, y, f"+{hi:.0f}", va="center", fontsize=8)
        ax.text(lo - 0.4, y, f"{lo:.0f}", va="center", ha="right", fontsize=8)
        y += 1
    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.set_xlabel("放贷家数变化（相对基准）")
    ax.set_title("灵敏度：关键参数对放贷家数的影响（tornado 图）")
    ax.legend(handles=[Patch(color=plot_style.CATEGORICAL[0], label="参数上调"),
                       Patch(color=plot_style.CATEGORICAL[1], label="参数下调")],
              frameon=False, loc="lower right")
    plot_style.save(fig, os.path.join(IMG, "fig40_02_nlend_tornado.png"))

    # 期望收益随总额变化的曲线（补充视图）
    totals = np.arange(4000, 18001, 2000)
    profs, nlends = [], []
    for t in totals:
        n, al, prof, struct = run_strategy(f2, strat, scorer, total_wan=t)
        profs.append(prof)
        nlends.append(n)
    fig, ax = plt.subplots()
    ax.plot(totals / 1e4, profs, marker="o", ms=4, color=plot_style.CATEGORICAL[0], label="总期望收益")
    ax.set_xlabel("年度信贷总额（亿元）")
    ax.set_ylabel("总期望收益（万元）")
    ax.set_title("灵敏度：总期望收益随信贷总额的变化")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig40_03_profit_vs_total.png"))

    print("\n[sens] 完成。输出: sensitivity_report.csv / fig40_01~03")
    return 0


if __name__ == "__main__":
    sys.exit(main())
