# -*- coding: utf-8 -*-
"""
problem2_credit.py — 问题2：附件2（302 家无信贷记录企业）信贷风险量化 + 1 亿元信贷策略
2020 CUMCM C 题《中小微企业的信贷决策》

输入:
  - CUMCM_Workspace/data/features_a2.csv  (302 家企业发票特征)
  - CUMCM_Workspace/data/scorer_p1.pkl    (问题1 校准的评分器: LR+scaler+特征清单+利率表)
输出:
  - CUMCM_Workspace/data/strategy_p2.csv  (302 家企业信贷策略明细)
  - CUMCM_Workspace/data/psi_report.csv   (特征分布稳定性 PSI)
  - CUMCM_Workspace/latex/images/fig20_*.png

方法:
  1. 迁移打分: 用问题1 的 LR 模型 + scaler 对附件2 特征打分 → PD
  2. 分布偏移检查: 关键特征 PSI (Population Stability Index)
  3. 风险分层: 以附件1 各评级 PD 均值的中点为阈值, 映射伪评级(A/B/C/D)用于附件3 流失率曲线
  4. 信贷策略: 同问题1 的期望收益最大化分配, 总额 = 1 亿元 (10000 万元)
"""
import sys
import os
import pickle
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
plot_style.apply()

from scipy.interpolate import interp1d  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
IMG = os.path.join(BASE, "latex", "images")
os.makedirs(IMG, exist_ok=True)

TOTAL_WAN = 10000.0  # 1 亿元 = 10000 万元
LOG_FEAT_KEYS = ("sum_amt", "net_amt", "avg_inv", "max_inv", "sum_tax",
                 "n_inv", "n_void", "n_counterpart", "inv_per_active_month", "n_active_month")


def transform_features(df, feats):
    X = df[feats].copy()
    for c in feats:
        if any(k in c for k in LOG_FEAT_KEYS):
            X[c] = np.log1p(X[c].clip(lower=0))
    return X


def compute_psi(ref, cur, bins=10):
    """单特征 PSI: 参考分布 vs 当前分布的分箱偏移指数。"""
    lo, hi = np.percentile(ref, [1, 99])
    edges = np.linspace(lo, hi, bins + 1)
    edges[0], edges[-1] = -np.inf, np.inf
    r = np.histogram(ref, bins=edges)[0] / len(ref)
    c = np.histogram(cur, bins=edges)[0] / len(cur)
    r = np.clip(r, 1e-6, None)
    c = np.clip(c, 1e-6, None)
    return float(np.sum((c - r) * np.log(c / r)))


def pseudo_rating(pd_vals, boundaries):
    """按附件1 评级 PD 均值中点映射伪评级。"""
    tiers = []
    for p in pd_vals:
        if p < boundaries[0]:
            tiers.append("A")
        elif p < boundaries[1]:
            tiers.append("B")
        elif p < boundaries[2]:
            tiers.append("C")
        else:
            tiers.append("D")
    return np.array(tiers)


def optimal_rate_and_profit(pd_val, tier, churn_fns, rate_grid):
    if tier == "D":
        return None, 0.0
    fn = churn_fns[tier]
    best_r, best_p = None, 0.0
    for r in rate_grid:
        rev = r * (1 - pd_val) - pd_val
        if rev <= 0:
            continue
        p = (1 - fn(r)) * rev
        if p > best_p:
            best_p, best_r = p, r
    return best_r, best_p


def main():
    print("=" * 66)
    print("problem2_credit — 附件2 迁移打分 + 1 亿元信贷策略（302 家）")
    print("=" * 66)

    f2 = pd.read_csv(os.path.join(DATA, "features_a2.csv"))
    with open(os.path.join(DATA, "scorer_p1.pkl"), "rb") as fh:
        scorer = pickle.load(fh)
    model, scaler, feats = scorer["model"], scorer["scaler"], scorer["feats"]

    # ---------- 1. 迁移打分 ----------
    print("\n[1] 用问题1 评分器迁移打分...")
    X2 = transform_features(f2, feats)
    X2s = scaler.transform(X2)
    pd2 = model.predict_proba(X2s)[:, 1]
    f2 = f2.assign(PD=pd2)
    print(f"[P2] 302 家 PD: mean={pd2.mean():.4f}, min={pd2.min():.4f}, max={pd2.max():.4f}")

    # ---------- 2. PSI 分布偏移 ----------
    print("\n[2] 特征分布稳定性 PSI（附件1 vs 附件2）...")
    f1 = pd.read_csv(os.path.join(DATA, "features_a1.csv"))
    psi_rows = []
    for c in ["out_sum_amt", "in_sum_amt", "out_n_counterpart", "out_n_inv",
              "out_void_share", "out_cv_month", "out_in_ratio"]:
        psi = compute_psi(np.log1p(f1[c].clip(lower=0)), np.log1p(f2[c].clip(lower=0)))
        psi_rows.append((c, psi))
    psi_df = pd.DataFrame(psi_rows, columns=["feature", "PSI"])
    psi_df.to_csv(os.path.join(DATA, "psi_report.csv"), index=False, encoding="utf-8-sig")
    print(psi_df.to_string(index=False))
    print("[P2] PSI<0.1 稳定 / 0.1~0.25 轻度偏移 / >0.25 显著偏移")

    # ---------- 3. 风险分层（伪评级） ----------
    print("\n[3] 按附件1 评级 PD 均值中点映射伪评级...")
    # 从 strategy_p1.csv 取各评级的 PD 均值, 以相邻均值中点为分层阈值
    s1 = pd.read_csv(os.path.join(DATA, "strategy_p1.csv"))
    means = s1.groupby("信誉评级")["PD"].mean()
    boundaries = [(means["A"] + means["B"]) / 2, (means["B"] + means["C"]) / 2,
                  (means["C"] + means["D"]) / 2]
    print(f"[P2] 分层阈值(PD): A|B={boundaries[0]:.4f}, B|C={boundaries[1]:.4f}, C|D={boundaries[2]:.4f}")
    tiers = pseudo_rating(pd2, boundaries)
    f2 = f2.assign(tier=tiers)
    print(f2["tier"].value_counts().to_dict())

    # ---------- 4. 信贷策略（1 亿元） ----------
    print("\n[4] 期望收益最大化分配（总额 1 亿元）...")
    churn = pd.DataFrame(scorer["churn"])
    churn_fns = {r: interp1d(churn["rate"].values, churn[r].values, kind="linear",
                             bounds_error=False, fill_value=(churn[r].values[0], churn[r].values[-1]))
                 for r in ["A", "B", "C"]}
    rate_grid = scorer["rate_grid"]
    rating_cap = scorer["rating_cap"]
    turnover_ratio = scorer["turnover_ratio"]

    out = f2[["企业代号", "企业名称", "PD", "tier"]].copy()
    out["rate_opt"] = np.nan
    out["profit_unit"] = 0.0
    for i, row in out.iterrows():
        r, p = optimal_rate_and_profit(row["PD"], row["tier"], churn_fns, rate_grid)
        out.loc[i, "rate_opt"] = r if r is not None else np.nan
        out.loc[i, "profit_unit"] = p
    cap = np.minimum(out["tier"].map(rating_cap).values, turnover_ratio * f2["out_sum_amt_pos"].values / 1e4)
    out["cap_wan"] = np.clip(cap, 0, None)
    out["amount_wan"] = 0.0
    order_idx = np.argsort(-out["profit_unit"].values, kind="stable")
    remaining = TOTAL_WAN
    for i in order_idx:
        if out.loc[i, "profit_unit"] <= 0 or out.loc[i, "cap_wan"] <= 0:
            continue
        take = min(out.loc[i, "cap_wan"], remaining)
        out.loc[i, "amount_wan"] = take
        remaining -= take
        if remaining <= 1e-6:
            break
    out["expected_profit"] = out["amount_wan"] * out["profit_unit"]
    out = out.sort_values(["tier", "企业代号"]).reset_index(drop=True)
    out.to_csv(os.path.join(DATA, "strategy_p2.csv"), index=False, encoding="utf-8-sig")

    n_lend = (out["amount_wan"] > 0).sum()
    allocated = TOTAL_WAN - remaining
    print(f"[P2] 放贷 {n_lend} 家 / 302, 实际分配 {allocated:.0f} 万元, 期望收益 {out['expected_profit'].sum():.0f} 万元")
    print("[P2] 按层级汇总:")
    print(out[out["amount_wan"] > 0].groupby("tier").agg(
        家数=("企业代号", "count"), 额度=("amount_wan", "sum"),
        平均利率=("rate_opt", "mean"), 平均PD=("PD", "mean")).round(3).to_string())

    # ---------- TOPSIS 交叉验证轨 ----------
    print("\n[5] 熵权-TOPSIS 交叉验证（无标签轨）...")
    sys.path.insert(0, os.path.join(BASE, "src", "models"))
    from problem1_credit import topsis_score
    score2, _ = topsis_score(f2.drop(columns=["PD", "tier"]))
    rho_t, _ = spearmanr(score2, -pd2)
    print(f"[P2] TOPSIS 得分 与 (−PD) Spearman ρ = {rho_t:.4f}")

    # ---------- 图（§18：排序/评价类 → 直方图带分层线、堆叠条、散点） ----------
    print("\n[6] 生成模型结果图...")
    # fig20-1 PD 分布直方图（按伪评级着色 + 分层阈值线）
    fig, ax = plt.subplots(figsize=(9, 4.8))
    tier_order = ["A", "B", "C", "D"]
    for i, t in enumerate(tier_order):
        v = pd2[tiers == t]
        ax.hist(v, bins=30, range=(0, 1), alpha=0.55, color=plot_style.CATEGORICAL[i],
                label=f"伪评级 {t}（{len(v)} 家）")
    for b in boundaries:
        ax.axvline(b, color=plot_style.CATEGORICAL[3], ls="--", lw=1)
    ax.set_xlabel("迁移预测违约概率 PD")
    ax.set_ylabel("企业数")
    ax.set_title("问题2：附件2 302 家企业 PD 分布与风险分层")
    ax.legend(frameon=False, fontsize=8)
    plot_style.save(fig, os.path.join(IMG, "fig20_01_pd_histogram.png"))

    # fig20-2 PSI 条形图（按 PSI 排序）
    fig, ax = plt.subplots()
    p2 = psi_df.sort_values("PSI")
    colors = [plot_style.STATUS["good"] if v < 0.1 else (plot_style.CATEGORICAL[1] if v < 0.25 else plot_style.STATUS["critical"])
              for v in p2["PSI"]]
    ax.barh(p2["feature"], p2["PSI"], color=colors)
    ax.axvline(0.1, color=plot_style.STATUS["good"], ls="--", lw=1, label="PSI=0.1 稳定阈值")
    ax.axvline(0.25, color=plot_style.STATUS["critical"], ls="--", lw=1, label="PSI=0.25 显著偏移阈值")
    ax.set_xlabel("PSI")
    ax.set_title("问题2：附件1→附件2 关键特征分布稳定性（PSI）")
    ax.legend(frameon=False, fontsize=8)
    plot_style.save(fig, os.path.join(IMG, "fig20_02_psi.png"))

    # fig20-3 1 亿元分配结构：改成按企业排序的水平条形图（原先的单柱堆叠图在
    # 实际放贷只集中在 1 个层级时会退化成一整块纯色矩形，看不出任何结构——
    # 复核时发现这张图渲染出来就是这样，§18 讲的"按排序维度重排的条形图"
    # 惯例这里应该落到"每家企业一根条"而不是"每个层级一根条"，层级数太少
    # （本轮只有 A 层放贷）时后者天然没有信息量）。
    s2 = out[out["amount_wan"] > 0].sort_values("amount_wan", ascending=True)
    fig, ax = plt.subplots(figsize=(8, 3.2 + 0.32 * len(s2)))
    tier_color = {t: plot_style.CATEGORICAL[i] for i, t in enumerate(tier_order)}
    colors = [tier_color.get(t, plot_style.CATEGORICAL[0]) for t in s2["tier"]]
    ax.barh(s2["企业代号"], s2["amount_wan"], color=colors, height=0.6)
    for y, (amt, pd_) in enumerate(zip(s2["amount_wan"], s2["PD"])):
        ax.text(amt + s2["amount_wan"].max() * 0.015, y, f"{amt:.0f} 万元 · PD={pd_:.3f}",
                va="center", fontsize=7.5, color=plot_style.CHROME["text_secondary"])
    handles = [plt.Rectangle((0, 0), 1, 1, color=tier_color[t]) for t in tier_order
               if (s2["tier"] == t).any()]
    tier_labels = [f"伪评级 {t}（{(s2['tier'] == t).sum()} 家）" for t in tier_order
                   if (s2["tier"] == t).any()]
    ax.legend(handles, tier_labels, loc="lower right", fontsize=8, frameon=False)
    ax.set_xlabel("分配额度（万元）")
    ax.set_xlim(0, s2["amount_wan"].max() * 1.28)
    ax.set_title(f"问题2：1 亿元总额的信贷分配（共放贷 {n_lend} 家，按额度排序）")
    plot_style.save(fig, os.path.join(IMG, "fig20_03_allocation_by_tier.png"))

    # fig20-4 TOPSIS 得分 vs LR-PD 散点（两轨对照）
    fig, ax = plt.subplots(figsize=(7, 5))
    sc = ax.scatter(score2, pd2, s=18, c=pd2, cmap=plot_style.sequential_cmap(), alpha=0.8)
    ax.set_xlabel("熵权-TOPSIS 信用得分（越高越可信）")
    ax.set_ylabel("逻辑回归预测 PD")
    ax.set_title(f"问题2：无监督评分轨 vs 监督模型轨（ρ={rho_t:.3f}）")
    fig.colorbar(sc, ax=ax, shrink=0.75, label="PD")
    plot_style.save(fig, os.path.join(IMG, "fig20_04_topsis_vs_pd.png"))

    print("\n[P2] 完成。输出: strategy_p2.csv / psi_report.csv / fig20_01~04")
    return 0


if __name__ == "__main__":
    sys.exit(main())
