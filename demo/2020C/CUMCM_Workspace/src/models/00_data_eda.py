# -*- coding: utf-8 -*-
"""
00_data_eda.py — 数据预处理 + EDA + 向量化特征工程
2020 CUMCM C 题《中小微企业的信贷决策》

- 输入：附件1/2 的 企业信息 + 进项/销项发票信息；附件3 利率-流失率
- 输出：
  * CUMCM_Workspace/data/features_a1.csv  (123 家企业特征 + 评级/违约标签)
  * CUMCM_Workspace/data/features_a2.csv  (302 家企业特征，无标签)
  * CUMCM_Workspace/data/rate_churn_curve.csv (附件3 清洗后)
  * CUMCM_Workspace/latex/images/fig00_*.png (EDA 图)
- 性能：全部 groupby+agg 向量化，禁止逐行循环
"""
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
import plot_style  # noqa: E402
import matplotlib.pyplot as plt
plot_style.apply()

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
IMG = os.path.join(BASE, "latex", "images")
os.makedirs(IMG, exist_ok=True)

F_A1 = os.path.join(DATA, "附件1：123家有信贷记录企业的相关数据.xlsx")
F_A2 = os.path.join(DATA, "附件2：302家无信贷记录企业的相关数据.xlsx")
F_A3 = os.path.join(DATA, "附件3：银行贷款年利率与客户流失率关系的统计数据.xlsx")

INVOICE_COLS = ["企业代号", "发票号码", "开票日期", "对方代号", "金额", "税额", "价税合计", "发票状态"]
INVOICE_USE = [0, 1, 2, 3, 4, 5, 6, 7]


def load_invoices(path, sheets):
    frames = []
    for sh in sheets:
        df = pd.read_excel(path, sheet_name=sh, usecols=INVOICE_USE)
        df.columns = INVOICE_COLS
        df["发票状态"] = df["发票状态"].astype(str)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def enterprise_features(inv_df, label=""):
    """按企业聚合发票统计量（全部向量化）。"""
    df = inv_df.copy()
    df["金额"] = pd.to_numeric(df["金额"], errors="coerce")
    df["税额"] = pd.to_numeric(df["税额"], errors="coerce")
    df["开票日期"] = pd.to_datetime(df["开票日期"], errors="coerce")
    df["ym"] = df["开票日期"].dt.to_period("M").astype(str)
    df["is_void"] = df["发票状态"].str.contains("作废").astype(int)
    df["is_neg"] = (df["金额"] < 0).astype(int)
    df["amt"] = df["金额"].abs()
    df["sign"] = np.sign(df["金额"]).replace(0, 1)

    g = df.groupby("企业代号")
    feats = pd.DataFrame(index=g.size().index)
    feats["n_inv"] = g.size()
    feats["n_void"] = g["is_void"].sum()
    feats["void_share"] = feats["n_void"] / feats["n_inv"]
    feats["neg_share"] = g["is_neg"].mean()
    feats["sum_amt"] = g["amt"].sum()                       # 绝对金额合计
    feats["net_amt"] = g["金额"].sum()                      # 正负净额
    feats["sum_amt_pos"] = df.loc[df["sign"] > 0].groupby("企业代号")["amt"].sum()
    feats["sum_tax"] = g["税额"].sum()
    feats["avg_inv"] = g["amt"].mean()
    feats["max_inv"] = g["amt"].max()
    feats["n_counterpart"] = g["对方代号"].nunique()        # 对手方个数
    # 对手方集中度 HHI
    share = df.groupby(["企业代号", "对方代号"])["amt"].sum()
    share = share / share.groupby("企业代号").transform("sum")
    hhi = (share ** 2).groupby("企业代号").sum()
    feats["hhi"] = hhi
    # 月度活跃度与趋势（仅用有效正金额）
    valid = df[df["is_void"] == 0]
    msum = valid.groupby(["企业代号", "ym"])["amt"].sum()
    mcount = valid.groupby(["企业代号", "ym"]).size()
    msum = msum.unstack(fill_value=0.0)
    feats["n_active_month"] = (msum > 0).sum(axis=1)
    # 月度金额变异系数（稳定性）
    mstd = msum.std(axis=1)
    mmean = msum.mean(axis=1)
    feats["cv_month"] = (mstd / mmean.replace(0, np.nan)).fillna(0.0)
    # 月度增长趋势：后半期 vs 前半期
    cols = list(msum.columns)
    half = max(1, len(cols) // 2)
    first = msum[cols[:half]].sum(axis=1)
    last = msum[cols[half:]].sum(axis=1)
    feats["growth"] = ((last - first) / first.replace(0, np.nan)).fillna(0.0)
    # 税率代理（税额/价税合计）
    gross = g["价税合计"].sum()
    feats["tax_ratio"] = (feats["sum_tax"] / gross.replace(0, np.nan)).fillna(0.0)
    # 平均每月活跃月度的发票数（强度）
    feats["inv_per_active_month"] = feats["n_inv"] / feats["n_active_month"].replace(0, np.nan)
    feats["inv_per_active_month"] = feats["inv_per_active_month"].fillna(0.0)

    feats = feats.fillna(0.0)
    feats = feats.replace([np.inf, -np.inf], 0.0)
    feats = feats.reset_index().rename(columns={"index": "企业代号"})
    return feats


def main():
    print("=" * 60)
    print("00_data_eda — 数据预处理与特征工程")
    print("=" * 60)

    # ---------- 附件1 ----------
    print("\n[1/6] 读取附件1发票数据（进项 210,947 行 / 销项 162,485 行）...")
    a1_in = load_invoices(F_A1, ["进项发票信息"])
    a1_out = load_invoices(F_A1, ["销项发票信息"])
    fe_in = enterprise_features(a1_in)
    fe_out = enterprise_features(a1_out)
    fe_in = fe_in.add_prefix("in_").rename(columns={"in_企业代号": "企业代号"})
    fe_out = fe_out.add_prefix("out_").rename(columns={"out_企业代号": "企业代号"})
    info1 = pd.read_excel(F_A1, sheet_name="企业信息")
    feat1 = info1[["企业代号", "信誉评级", "是否违约"]].merge(fe_in, on="企业代号", how="left")
    feat1 = feat1.merge(fe_out, on="企业代号", how="left")
    # 进销联动特征
    feat1["out_in_ratio"] = feat1["out_sum_amt"] / feat1["in_sum_amt"].replace(0, np.nan)
    feat1["out_in_ratio"] = feat1["out_in_ratio"].fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feat1 = feat1.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    feat1["label_default"] = (feat1["是否违约"] == "是").astype(int)
    print("  附件1 特征矩阵:", feat1.shape)
    print("  违约率:", feat1["label_default"].mean().round(4), "| 评级分布:",
          feat1["信誉评级"].value_counts().to_dict())

    # ---------- 附件2 ----------
    print("[2/6] 读取附件2发票数据（进项 395,175 行 / 销项 330,836 行）...")
    a2_in = load_invoices(F_A2, ["进项发票信息"])
    a2_out = load_invoices(F_A2, ["销项发票信息"])
    fe_in2 = enterprise_features(a2_in).add_prefix("in_").rename(columns={"in_企业代号": "企业代号"})
    fe_out2 = enterprise_features(a2_out).add_prefix("out_").rename(columns={"out_企业代号": "企业代号"})
    info2 = pd.read_excel(F_A2, sheet_name="企业信息")
    feat2 = info2[["企业代号", "企业名称"]].merge(fe_in2, on="企业代号", how="left")
    feat2 = feat2.merge(fe_out2, on="企业代号", how="left")
    feat2["out_in_ratio"] = feat2["out_sum_amt"] / feat2["in_sum_amt"].replace(0, np.nan)
    feat2["out_in_ratio"] = feat2["out_in_ratio"].fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feat2 = feat2.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    print("  附件2 特征矩阵:", feat2.shape)

    # ---------- 附件3 ----------
    print("[3/6] 清洗附件3 利率-流失率数据...")
    a3 = pd.read_excel(F_A3, sheet_name="Sheet1", header=None, skiprows=1)
    a3.columns = ["rate", "A", "B", "C"]
    a3 = a3.dropna(subset=["rate"]).reset_index(drop=True)
    for c in ["A", "B", "C"]:
        a3[c] = pd.to_numeric(a3[c], errors="coerce")
    a3.to_csv(os.path.join(DATA, "rate_churn_curve.csv"), index=False, encoding="utf-8-sig")
    print("  附件3 清洗后:", a3.shape, "利率范围:", a3["rate"].min(), "→", a3["rate"].max())

    # ---------- 保存特征 ----------
    feat1.to_csv(os.path.join(DATA, "features_a1.csv"), index=False, encoding="utf-8-sig")
    feat2.to_csv(os.path.join(DATA, "features_a2.csv"), index=False, encoding="utf-8-sig")
    print("[4/6] 特征已保存: features_a1.csv / features_a2.csv")

    # ---------- EDA 图（§18：评价/排序类问题 → 热力图 + 按排序重排条形图，无 3D） ----------
    print("[5/6] 生成 EDA 图...")

    # fig00-1 各评级违约率（按评级等级排序的条形图）
    rate_order = ["A", "B", "C", "D"]
    g1 = feat1.groupby("信誉评级")["label_default"].agg(["mean", "size"])
    g1 = g1.reindex([r for r in rate_order if r in g1.index])
    fig, ax = plt.subplots()
    colors = [plot_style.CATEGORICAL[0]] * len(g1)
    bars = ax.bar(g1.index, g1["mean"], color=colors, width=0.6)
    for b, (idx, row) in zip(bars, g1.iterrows()):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01,
                f"{row['mean']:.1%}\n(n={int(row['size'])})", ha="center", va="bottom", fontsize=9)
    ax.set_xlabel("信誉评级（按等级排序）")
    ax.set_ylabel("违约率")
    ax.set_ylim(0, max(g1["mean"].max() * 1.35, 0.2))
    ax.set_title("附件1：各信誉评级企业的违约率")
    plot_style.save(fig, os.path.join(IMG, "fig00_01_default_rate_by_rating.png"))

    # fig00-2 特征相关性热力图：相关系数有正有负，属于"正负偏差"场景，改用
    # plot_style 的发散色板（原来误用了单一渐变的 sequential_cmap，复核时发现
    # 负相关和正相关在纯蓝色单向渐变下几乎分不清深浅方向）。
    num_cols = [c for c in feat1.columns if feat1[c].dtype in ("float64", "int64")
                and c not in ("label_default",)]
    corr = feat1[num_cols].corr()
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(corr.values, cmap=plot_style.diverging_cmap(), vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=6.5)
    ax.set_yticklabels(corr.columns, fontsize=6.5)
    fig.colorbar(im, ax=ax, shrink=0.8, label="相关系数")
    ax.set_title("特征相关性热力图（附件1，含进销项聚合特征）")
    plot_style.save(fig, os.path.join(IMG, "fig00_02_feature_corr_heatmap.png"))

    # fig00-3 附件3 利率-流失率曲线族（多评级叠画）
    fig, ax = plt.subplots()
    for i, r in enumerate(["A", "B", "C"]):
        ax.plot(a3["rate"], a3[r], marker="o", ms=3, lw=1.6,
                color=plot_style.CATEGORICAL[i], label=f"信誉评级 {r}")
    ax.set_xlabel("贷款年利率")
    ax.set_ylabel("客户流失率")
    ax.set_title("附件3：贷款年利率与客户流失率关系（2019 年统计）")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig00_03_churn_rate_curves.png"))

    # fig00-4 月度发票金额总量趋势（进/销项，全样本）
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for df_, sh, c, lab in [(a1_in, "in", 0, "附件1 进项"), (a1_out, "out", 1, "附件1 销项"),
                            (a2_in, "in", 2, "附件2 进项"), (a2_out, "out", 3, "附件2 销项")]:
        d = df_[df_["发票状态"] != "作废发票"].copy()
        d["ym"] = pd.to_datetime(d["开票日期"]).dt.to_period("M").astype(str)
        s = d.groupby("ym")["金额"].sum()
        ax.plot(range(len(s)), s.values, color=plot_style.CATEGORICAL[c], lw=1.2,
                label=lab)
    ax.set_xticks(range(0, 41, 4))
    ax.set_xticklabels(sorted(a1_in.assign(ym=pd.to_datetime(a1_in["开票日期"]).dt.to_period("M").astype(str))["ym"].unique())[::4], rotation=45, fontsize=7)
    ax.set_xlabel("年月")
    ax.set_ylabel("发票金额合计（元）")
    ax.set_title("进/销项发票月度金额总量趋势（2016-10 → 2020-02）")
    ax.legend(frameon=False, fontsize=8)
    plot_style.save(fig, os.path.join(IMG, "fig00_04_monthly_trend.png"))

    # fig00-5 关键特征分布（对数直方图小倍数）
    keys = ["in_sum_amt", "out_sum_amt", "out_in_ratio", "in_void_share"]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
    for ax, k in zip(axes, keys):
        for df_, c, lab in [(feat1, 0, "附件1(有标签)"), (feat2, 1, "附件2(无标签)")]:
            v = np.log1p(df_[k].clip(lower=0)).values if k != "out_in_ratio" else df_[k].clip(0, 10).values
            ax.hist(v, bins=40, alpha=0.55, color=plot_style.CATEGORICAL[c], label=lab)
        ax.set_title(k, fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0].legend(frameon=False, fontsize=7)
    fig.suptitle("附件1 vs 附件2 关键特征分布对比（分布偏移是迁移建模的前提检查）", fontsize=10)
    plot_style.save(fig, os.path.join(IMG, "fig00_05_feature_distributions.png"))

    # ---------- 数据质量报告 ----------
    print("[6/6] 数据质量报告：")
    qa = pd.DataFrame({
        "表": ["A1企业信息", "A1进项发票", "A1销项发票", "A2企业信息", "A2进项发票", "A2销项发票", "A3利率流失率"],
        "行数": [len(info1), len(a1_in), len(a1_out), len(info2), len(a2_in), len(a2_out), len(a3)],
        "企业数": [info1["企业代号"].nunique(), a1_in["企业代号"].nunique(), a1_out["企业代号"].nunique(),
                  info2["企业代号"].nunique(), a2_in["企业代号"].nunique(), a2_out["企业代号"].nunique(), np.nan],
        "金额缺失": [np.nan, a1_in["金额"].isna().sum(), a1_out["金额"].isna().sum(), np.nan,
                   a2_in["金额"].isna().sum(), a2_out["金额"].isna().sum(), np.nan],
    })
    print(qa.to_string(index=False))
    print("\n✓ 特征工程完成：附件1 特征", feat1.shape[1], "列 / 附件2 特征", feat2.shape[1], "列")


if __name__ == "__main__":
    main()
