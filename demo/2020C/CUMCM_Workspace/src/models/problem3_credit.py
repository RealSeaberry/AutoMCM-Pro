# -*- coding: utf-8 -*-
"""
problem3_credit.py — 问题3：突发因素（新冠疫情）对不同类别企业的影响 + 1 亿元信贷调整策略
2020 CUMCM C 题《中小微企业的信贷决策》

输入:
  - CUMCM_Workspace/data/features_a2.csv   (302 家发票特征)
  - CUMCM_Workspace/data/strategy_p2.csv   (问题2 基线策略: PD/层级/额度)
  - CUMCM_Workspace/data/scorer_p1.pkl
输出:
  - CUMCM_Workspace/data/strategy_p3.csv   (冲击情景下的调整策略 + 与基线对比)
  - CUMCM_Workspace/latex/images/fig30_*.png

方法:
  1. 类别画像: 发票行为特征 KMeans 聚类(标准化+log1p) → 302 家企业分为 5 类
     (企业名称已脱敏, 无行业字段; 类别由发票行为代理, 论文中明示该假设)
  2. 冲击系数: 依据类别行为画像对照文献(如 BIS 2021 分行业信用压力: 住宿餐饮最重、
     批发零售次之、制造中等)赋予 情景冲击系数 impact_k
  3. 冲击传导: PD_i' = clip(PD_i × (1 + impact_k), 0, 0.95);
     销项额冲击 → 额度上限收缩 (1 − 0.5·impact_k)
  4. 调整策略: 冲击情景下重新做期望收益最大化分配(1 亿元), 与基线对比:
     收缩/维持/新增 三类调整动作
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
from sklearn.cluster import KMeans  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.metrics import silhouette_score  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
IMG = os.path.join(BASE, "latex", "images")
os.makedirs(IMG, exist_ok=True)

TOTAL_WAN = 10000.0
K_CLUSTERS = 5
LOG_FEAT_KEYS = ("sum_amt", "net_amt", "avg_inv", "max_inv", "sum_tax",
                 "n_inv", "n_void", "n_counterpart", "inv_per_active_month", "n_active_month")

CLUSTER_FEATURES = ["out_sum_amt", "in_sum_amt", "out_n_inv", "out_avg_inv",
                    "out_n_counterpart", "out_n_active_month", "out_in_ratio",
                    "out_void_share", "in_void_share", "out_cv_month"]

# 冲击系数(情景假设, 依据行为画像映射到文献中的行业冲击量级):
#   高频小额(零售/餐饮/住宿类) 冲击最重; 大额低频(批发/大宗/项目类) 次之;
#   均衡购销(制造类) 中等; 低活跃(微小个体) 影响相对有限
IMPACT_BY_LABEL = {
    "高频小额-零售餐饮型": 0.35,
    "大额低频-项目工程型": 0.25,
    "大型批发-制造型": 0.15,
    "低活跃-个体微型": 0.10,
    "购销失衡-贸易中介型": 0.20,
}


def transform_cluster_features(df):
    X = df[CLUSTER_FEATURES].copy()
    for c in CLUSTER_FEATURES:
        if any(k in c for k in LOG_FEAT_KEYS):
            X[c] = np.log1p(X[c].clip(lower=0))
    X["out_in_ratio"] = X["out_in_ratio"].clip(0, 20)
    return X


def label_clusters(prof):
    """依据簇画像（变换后特征均值）给类别命名（确定性规则, 与诊断出的簇结构一致）。"""
    labels = []
    for _, r in prof.iterrows():
        avg_inv = np.expm1(r["out_avg_inv"])
        n_inv = np.expm1(r["out_n_inv"])
        oir = r["out_in_ratio"]
        void = r["out_void_share"]
        n_counterpart = np.expm1(r["out_n_counterpart"])
        if void > 0.5:
            labels.append("大额低频-项目工程型")          # 作废率极高 + 大额低频
        elif avg_inv < 2e4 and n_inv > 200:
            labels.append("高频小额-零售餐饮型")          # 高频小票
        elif n_inv > 1000 and n_counterpart > 100:
            labels.append("大型批发-制造型")              # 规模大、渠道多
        elif oir > 3.0:
            labels.append("购销失衡-贸易中介型")          # 销项远大于进项
        else:
            labels.append("低活跃-个体微型")
    return labels


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


def allocate(out, f2, churn_fns, rate_grid, rating_cap, turnover_ratio, total_wan):
    """期望收益最大化分配(线性背包贪心)。额度上限按企业代号对齐 f2 的销项额。"""
    out = out.copy()
    amt = out[["企业代号"]].merge(f2[["企业代号", "out_sum_amt_pos"]], on="企业代号")["out_sum_amt_pos"].values
    out["rate_opt"] = np.nan
    out["profit_unit"] = 0.0
    for i, row in out.iterrows():
        r, p = optimal_rate_and_profit(row["PD"], row["tier"], churn_fns, rate_grid)
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
    return out.sort_values(["tier", "企业代号"]).reset_index(drop=True), total_wan - remaining


def main():
    print("=" * 66)
    print("problem3_credit — 突发因素冲击建模 + 1 亿元信贷调整策略（302 家）")
    print("=" * 66)
    f2 = pd.read_csv(os.path.join(DATA, "features_a2.csv"))
    base = pd.read_csv(os.path.join(DATA, "strategy_p2.csv"))
    with open(os.path.join(DATA, "scorer_p1.pkl"), "rb") as fh:
        scorer = pickle.load(fh)

    # ---------- 1. 类别画像聚类 ----------
    print("\n[1] 发票行为画像聚类（KMeans, k=5）...")
    X = transform_cluster_features(f2)
    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=K_CLUSTERS, random_state=42, n_init=10).fit(Xs)
    sil = silhouette_score(Xs, km.labels_)
    print(f"[P3] Silhouette 系数 = {sil:.4f}")
    prof = X.assign(cluster=km.labels_).groupby("cluster")[CLUSTER_FEATURES].mean()
    label_names = label_clusters(prof)
    f2 = f2.assign(cluster=km.labels_, cluster_label=[label_names[c] for c in km.labels_])
    cnt = f2.groupby("cluster_label").size()
    print("[P3] 类别分布:\n", cnt.to_string())

    # ---------- 2. 冲击系数 ----------
    print("\n[2] 情景冲击系数（映射自文献行业冲击量级）...")
    f2["impact"] = f2["cluster_label"].map(IMPACT_BY_LABEL)
    print(f2.groupby("cluster_label")["impact"].first().to_string())

    # ---------- 3. 冲击传导与调整策略 ----------
    print("\n[3] 冲击传导: PD' = PD·(1+impact), 额度上限收缩...")
    shock = base[["企业代号", "tier", "PD", "amount_wan", "expected_profit"]].merge(
        f2[["企业代号", "cluster_label", "impact"]], on="企业代号")
    shock["PD_shock"] = np.clip(shock["PD"] * (1 + shock["impact"]), 0, 0.95)
    # 销项额冲击: 用原始 out_sum_amt_pos 收缩
    f2_shock = f2.copy()
    f2_shock["out_sum_amt_pos"] = f2_shock["out_sum_amt_pos"] * (1 - 0.5 * f2_shock["impact"])
    out_shock = shock[["企业代号", "tier", "PD_shock"]].rename(columns={"PD_shock": "PD"})
    churn = pd.DataFrame(scorer["churn"])
    churn_fns = {r: interp1d(churn["rate"].values, churn[r].values, kind="linear",
                             bounds_error=False, fill_value=(churn[r].values[0], churn[r].values[-1]))
                 for r in ["A", "B", "C"]}
    rate_grid = scorer["rate_grid"]
    rating_cap = scorer["rating_cap"]
    turnover_ratio = scorer["turnover_ratio"]

    out_shock, allocated = allocate(out_shock, f2_shock, churn_fns, rate_grid,
                                    rating_cap, turnover_ratio, TOTAL_WAN)
    res = base[["企业代号", "tier", "PD", "amount_wan"]].merge(
        out_shock[["企业代号", "PD", "amount_wan"]], on="企业代号", suffixes=("_base", "_shock"))
    res = res.merge(f2[["企业代号", "cluster_label", "impact"]], on="企业代号")
    res["delta_wan"] = res["amount_wan_shock"] - res["amount_wan_base"]
    res["action"] = np.where(res["amount_wan_base"] > 0, "维持",
                             np.where(res["amount_wan_shock"] > 0, "新增", "不贷"))
    res.loc[(res["amount_wan_base"] > 0) & (res["amount_wan_shock"] < res["amount_wan_base"] - 1e-6), "action"] = "收缩"
    res.loc[(res["amount_wan_base"] > 0) & (res["amount_wan_shock"] > res["amount_wan_base"] + 1e-6), "action"] = "加码"
    res.to_csv(os.path.join(DATA, "strategy_p3.csv"), index=False, encoding="utf-8-sig")

    n_lend = (res["amount_wan_shock"] > 0).sum()
    print(f"[P3] 冲击后放贷 {n_lend} 家, 实际分配 {allocated:.0f} 万元, "
          f"期望收益 {out_shock['expected_profit'].sum():.0f} 万元")
    print("[P3] 调整动作汇总:")
    print(res["action"].value_counts().to_string())
    print("[P3] 按类别: 基线 vs 冲击后额度")
    print(res.groupby("cluster_label")[["amount_wan_base", "amount_wan_shock"]].sum().round(0).to_string())

    # ---------- 图（§18：画像比较→雷达图; 排序/评价→排序条形; 对比→成组堆叠条） ----------
    print("\n[4] 生成模型结果图...")
    # fig30-1 类别画像雷达图（5 类 × 6 维, min-max 归一）
    radar_feats = ["out_sum_amt", "out_n_inv", "out_avg_inv", "out_in_ratio",
                   "out_n_counterpart", "out_n_active_month"]
    prof = f2.groupby("cluster_label")[radar_feats].mean()
    norm = (prof - prof.min()) / (prof.max() - prof.min() + 1e-12)
    angles = np.linspace(0, 2 * np.pi, len(radar_feats), endpoint=False).tolist()
    angles += angles[:1]
    fig, ax = plt.subplots(figsize=(7.5, 7.5), subplot_kw=dict(polar=True))
    for i, (lab, row) in enumerate(norm.iterrows()):
        vals = row.values.tolist() + [row.values[0]]
        ax.plot(angles, vals, color=plot_style.CATEGORICAL[i], lw=1.8, label=lab)
        ax.fill(angles, vals, color=plot_style.CATEGORICAL[i], alpha=0.12)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(radar_feats, fontsize=8)
    ax.set_title("问题3：五类企业发票行为画像（雷达图，min-max 归一化）", pad=24)
    ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.35, 1.12), fontsize=8)
    plot_style.save(fig, os.path.join(IMG, "fig30_01_cluster_radar.png"))

    # fig30-2 冲击系数条形（按系数排序）
    imp = f2.groupby("cluster_label")["impact"].first().sort_values()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.barh(imp.index, imp.values, color=plot_style.sequential_cmap()(np.linspace(0.4, 1, len(imp))))
    for i, v in enumerate(imp.values):
        ax.text(v + 0.005, i, f"{v:.0%}", va="center", fontsize=9)
    ax.set_xlabel("情景冲击系数（叠加到 PD 的乘子）")
    ax.set_title("问题3：各类别企业的新冠疫情冲击系数（情景假设）")
    plot_style.save(fig, os.path.join(IMG, "fig30_02_shock_multipliers.png"))

    # fig30-3 基线 vs 冲击后额度分配（按类别成组堆叠条, 类别按冲击系数排序）
    agg = res.groupby("cluster_label")[["amount_wan_base", "amount_wan_shock"]].sum()
    agg = agg.reindex(imp.index)  # 按冲击系数升序
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(agg))
    w = 0.36
    ax.bar(x - w / 2, agg["amount_wan_base"], w, color=plot_style.CATEGORICAL[0], label="基线（问题2）")
    ax.bar(x + w / 2, agg["amount_wan_shock"], w, color=plot_style.CATEGORICAL[1], label="冲击调整后（问题3）")
    ax.set_xticks(x)
    ax.set_xticklabels(agg.index, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("分配额度（万元）")
    ax.set_title("问题3：疫情冲击前后 1 亿元信贷分配对比（按类别）")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig30_03_allocation_shift.png"))

    # fig30-4 冲击前后 PD 分布变化（直方图叠画）
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.hist(res["PD_base"], bins=30, alpha=0.55, color=plot_style.CATEGORICAL[0], label="基线 PD")
    ax.hist(res["PD_shock"], bins=30, alpha=0.55, color=plot_style.CATEGORICAL[1], label="冲击后 PD'")
    ax.set_xlabel("违约概率")
    ax.set_ylabel("企业数")
    ax.set_title("问题3：疫情冲击前后 302 家企业 PD 分布变化")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig30_04_pd_shift.png"))

    print("\n[P3] 完成。输出: strategy_p3.csv / fig30_01~04")
    return 0


if __name__ == "__main__":
    sys.exit(main())
