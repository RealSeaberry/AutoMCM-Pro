# -*- coding: utf-8 -*-
"""
problem1_credit.py — 问题1：附件1（123 家）信贷风险量化 + 年度信贷总额固定时的信贷策略
2020 CUMCM C 题《中小微企业的信贷决策》

输入: CUMCM_Workspace/data/features_a1.csv、rate_churn_curve.csv
输出:
  - CUMCM_Workspace/data/scorer_p1.pkl        (供问题2/3 复用的评分器与利率表)
  - CUMCM_Workspace/data/strategy_p1.csv      (信贷策略明细表)
  - CUMCM_Workspace/latex/images/fig10_*.png  (模型结果图)

方法:
  A. 风险量化主模型: 逻辑回归(仅发票特征, L2, 5 折 CV 调 C) → P(违约)
     - 对比: 随机森林 AUC; 交叉验证: PD 随信誉评级 A<B<C<D 单调
  B. 无标签客观评分轨: 熵权法 + TOPSIS 信用得分 (与 LR-PD 对照)
  C. 信贷策略: 利率 r∈[4%,15%] 上最大化 (1−churn(r;评级))·(r·(1−PD)−PD)，
     额度 cap_i = min(评级上限, 25%×年销项额)，按单位期望收益降序贪婪分配
     (线性背包最优解), 总额参数化输出覆盖曲线。
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

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.model_selection import cross_val_score, StratifiedKFold, GridSearchCV  # noqa: E402
from sklearn.metrics import roc_auc_score, roc_curve, accuracy_score  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA = os.path.join(BASE, "data")
IMG = os.path.join(BASE, "latex", "images")
os.makedirs(IMG, exist_ok=True)

RANDOM_STATE = 42
RATE_MIN, RATE_MAX = 0.04, 0.15
RATING_CAP_WAN = {"A": 1000.0, "B": 500.0, "C": 300.0, "D": 0.0}   # 万元
TURNOVER_RATIO = 0.25                                              # 额度 ≤ 25% 年销项额

# 特征变换规则: 金额/数量类特征取 log1p, 占比/比率类保持原值
LOG_FEAT_KEYS = ("sum_amt", "net_amt", "avg_inv", "max_inv", "sum_tax",
                 "n_inv", "n_void", "n_counterpart", "inv_per_active_month", "n_active_month")
RAW_FEAT_KEYS = ("void_share", "neg_share", "hhi", "cv_month", "growth", "tax_ratio", "out_in_ratio")


def load_features():
    f1 = pd.read_csv(os.path.join(DATA, "features_a1.csv"))
    churn = pd.read_csv(os.path.join(DATA, "rate_churn_curve.csv"))
    return f1, churn


def build_feature_matrix(df):
    """选出建模特征并做 log1p 变换, 返回 (X, 特征名列表, 变换标记)。"""
    log_cols = [c for c in df.columns if any(k in c for k in LOG_FEAT_KEYS)]
    raw_cols = [c for c in df.columns if any(k in c for k in RAW_FEAT_KEYS) and c not in log_cols]
    feats = log_cols + raw_cols
    X = df[feats].copy()
    for c in log_cols:
        X[c] = np.log1p(X[c].clip(lower=0))
    return X, feats


def fit_pd_model(f1):
    """逻辑回归(主) + 随机森林(对比), 5 折 CV 评估 AUC。"""
    X, feats = build_feature_matrix(f1)
    y = f1["label_default"].values
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    lr = LogisticRegression(max_iter=3000, random_state=RANDOM_STATE)
    grid = GridSearchCV(lr, {"C": [0.05, 0.1, 0.3, 1.0, 3.0]}, cv=StratifiedKFold(5, shuffle=True, random_state=RANDOM_STATE),
                        scoring="roc_auc", n_jobs=-1)
    grid.fit(Xs, y)
    best_lr = grid.best_estimator_
    cv_auc_lr = cross_val_score(best_lr, Xs, y, cv=StratifiedKFold(5, shuffle=True, random_state=RANDOM_STATE), scoring="roc_auc")

    rf = RandomForestClassifier(n_estimators=400, max_depth=4, min_samples_leaf=3,
                                random_state=RANDOM_STATE, class_weight="balanced")
    cv_auc_rf = cross_val_score(rf, Xs, y, cv=StratifiedKFold(5, shuffle=True, random_state=RANDOM_STATE), scoring="roc_auc")

    best_lr.fit(Xs, y)
    pd_vals = best_lr.predict_proba(Xs)[:, 1]
    rf.fit(Xs, y)
    pd_rf = rf.predict_proba(Xs)[:, 1]

    print(f"[P1] 逻辑回归最优 C = {grid.best_params_['C']:.2f}")
    print(f"[P1] LR 5折CV AUC = {cv_auc_lr.mean():.4f} ± {cv_auc_lr.std():.4f}")
    print(f"[P1] RF 5折CV AUC = {cv_auc_rf.mean():.4f} ± {cv_auc_rf.std():.4f}")
    return {"model": best_lr, "scaler": scaler, "feats": feats, "y": y,
            "pd": pd_vals, "pd_rf": pd_rf, "cv_auc_lr": cv_auc_lr, "cv_auc_rf": cv_auc_rf}


def topsis_score(f1):
    """熵权法 + TOPSIS 信用得分（不依赖标签, 用于交叉验证排序）。"""
    X, feats = build_feature_matrix(f1)
    benefit = [c for c in feats if any(k in c for k in ("sum_amt", "n_counterpart", "n_active_month",
                                                        "inv_per_active_month", "out_in_ratio", "net_amt"))]
    cost = [c for c in feats if any(k in c for k in ("void_share", "neg_share", "cv_month", "hhi"))]
    mat = X[feats].values.copy()
    # 归一化 (向量归一)
    norm = np.sqrt((mat ** 2).sum(axis=0, keepdims=True))
    norm[norm == 0] = 1
    mat = mat / norm
    # 熵权
    p = mat / mat.sum(axis=0, keepdims=True)
    p = np.clip(p, 1e-12, None)
    e = - (p * np.log(p)).sum(axis=0) / np.log(len(mat))
    d = 1 - e
    w = d / d.sum()
    # 加权归一化矩阵
    v = mat * w
    ideal_best = np.array([v[:, feats.index(c)].max() if c in benefit else v[:, feats.index(c)].min() for c in feats])
    ideal_worst = np.array([v[:, feats.index(c)].min() if c in benefit else v[:, feats.index(c)].max() for c in feats])
    d_best = np.sqrt(((v - ideal_best) ** 2).sum(axis=1))
    d_worst = np.sqrt(((v - ideal_worst) ** 2).sum(axis=1))
    score = d_worst / (d_best + d_worst + 1e-12)
    return score, w


def churn_interpolators(churn):
    """附件3: 每评级的 利率→流失率 插值函数。"""
    fns = {}
    for r in ["A", "B", "C"]:
        x = churn["rate"].values
        y = churn[r].values
        fns[r] = interp1d(x, y, kind="linear", bounds_error=False, fill_value=(y[0], y[-1]))
    return fns


def optimal_rate_and_profit(pd_val, rating, churn_fns, rate_grid):
    """在利率网格上最大化 (1-churn)·(r·(1-PD)-PD), 返回 (最优利率, 单位期望收益)。"""
    if rating == "D":
        return None, 0.0
    fn = churn_fns[rating]
    best_r, best_p = None, 0.0
    for r in rate_grid:
        rev = r * (1 - pd_val) - pd_val          # 单位金额毛期望
        if rev <= 0:
            continue
        p = (1 - fn(r)) * rev                     # 流失率折扣后的期望收益
        if p > best_p:
            best_p, best_r = p, r
    return best_r, best_p


def build_strategy(f1, pd_vals, churn_fns, rate_grid, total_wan):
    """总额固定时的最优分配（线性背包 → 按单位期望收益降序贪心）。"""
    out = pd.DataFrame({
        "企业代号": f1["企业代号"], "信誉评级": f1["信誉评级"], "PD": pd_vals,
    })
    out["rate_opt"] = np.nan
    out["profit_unit"] = 0.0
    for i, row in out.iterrows():
        r, p = optimal_rate_and_profit(row["PD"], row["信誉评级"], churn_fns, rate_grid)
        out.loc[i, "rate_opt"] = r if r is not None else np.nan
        out.loc[i, "profit_unit"] = p
    # 额度上限: min(评级上限, 25% × 年销项额(万元))
    turnover_wan = f1["out_sum_amt_pos"] / 1e4
    cap = np.minimum(out["信誉评级"].map(RATING_CAP_WAN).values, TURNOVER_RATIO * turnover_wan.values)
    cap = np.clip(cap, 0, None)
    out["cap_wan"] = cap
    out["amount_wan"] = 0.0
    out = out.sort_values("profit_unit", ascending=False).reset_index(drop=True)
    remaining = total_wan
    for i, row in out.iterrows():
        if row["profit_unit"] <= 0 or row["cap_wan"] <= 0:
            continue
        take = min(row["cap_wan"], remaining)
        out.loc[i, "amount_wan"] = take
        remaining -= take
        if remaining <= 1e-6:
            break
    out["expected_profit"] = out["amount_wan"] * out["profit_unit"]
    out = out.sort_values(["信誉评级", "企业代号"]).reset_index(drop=True)
    return out, total_wan - remaining


def main():
    print("=" * 66)
    print("problem1_credit — 信贷风险量化 + 总额固定信贷策略（附件1 123家）")
    print("=" * 66)
    f1, churn = load_features()
    churn_fns = churn_interpolators(churn)
    rate_grid = np.unique(churn["rate"].values)

    # ---------- A. PD 模型 ----------
    print("\n[A] 训练违约概率模型（逻辑回归主模型 + 随机森林对比）...")
    art = fit_pd_model(f1)
    pd_vals = art["pd"]

    # 评级单调性交叉验证
    mono = f1[["信誉评级", "label_default"]].copy()
    mono["PD"] = pd_vals
    order = ["A", "B", "C", "D"]
    grp = mono.groupby("信誉评级")["PD"].mean().reindex(order)
    print("[P1] 预测 PD 均值按评级: " + "  ".join(f"{k}={v:.4f}" for k, v in grp.items()))
    is_monotone = all(grp.iloc[i] <= grp.iloc[i + 1] for i in range(len(grp) - 1))
    print(f"[P1] PD-评级单调性(应 A≤B≤C≤D): {is_monotone}")

    # 与评级(专家先验)的一致性: PD 与评级等级秩相关
    from scipy.stats import spearmanr
    rank_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    rho, _ = spearmanr(pd_vals, mono["信誉评级"].map(rank_map))
    print(f"[P1] PD 与评级等级 Spearman ρ = {rho:.4f}")

    # ---------- B. TOPSIS 交叉验证轨 ----------
    print("\n[B] 熵权-TOPSIS 客观信用得分（无标签轨）...")
    topsis, w = topsis_score(f1)
    from scipy.stats import spearmanr as spr
    rho2, _ = spr(topsis, -pd_vals)
    print(f"[P1] TOPSIS 信用得分 与 (−PD) 的 Spearman ρ = {rho2:.4f}（越高越可信）")
    art["topsis"] = topsis

    # ---------- C. 信贷策略（总额参数化） ----------
    print("\n[C] 信贷策略（期望收益最大化分配）...")
    total_wan = 10000.0  # 演示总额: 1 亿元 = 10000 万元
    strat, allocated = build_strategy(f1, pd_vals, churn_fns, rate_grid, total_wan)
    strat.to_csv(os.path.join(DATA, "strategy_p1.csv"), index=False, encoding="utf-8-sig")
    n_lend = (strat["amount_wan"] > 0).sum()
    print(f"[P1] 总额 {total_wan:.0f} 万元时: 放贷 {n_lend} 家, 实际分配 {allocated:.0f} 万元, "
          f"期望收益合计 {strat['expected_profit'].sum():.0f} 万元")
    print(strat[strat["amount_wan"] > 0][["企业代号", "信誉评级", "PD", "rate_opt", "cap_wan", "amount_wan"]].head(12).to_string(index=False))

    # 覆盖曲线
    totals = np.array([2000, 5000, 10000, 15000, 20000, 30000, 50000.0])
    cov = []
    for t in totals:
        s, al = build_strategy(f1, pd_vals, churn_fns, rate_grid, t)
        cov.append((t, al, (s["amount_wan"] > 0).sum(), s["expected_profit"].sum()))
    cov_df = pd.DataFrame(cov, columns=["total", "allocated", "n_lend", "profit"])
    print("[P1] 总额-覆盖曲线:\n", cov_df.round(0).to_string(index=False))

    # ---------- 保存评分器（供问题2/3） ----------
    with open(os.path.join(DATA, "scorer_p1.pkl"), "wb") as fh:
        pickle.dump({"model": art["model"], "scaler": art["scaler"], "feats": art["feats"],
                     "rate_grid": rate_grid, "churn": churn.to_dict("records"),
                     "rating_cap": RATING_CAP_WAN, "turnover_ratio": TURNOVER_RATIO}, fh)
    print("\n[P1] 评分器已保存: data/scorer_p1.pkl")

    # ---------- 图（§18：评价/排序类 → ROC、按风险排序热力图、排序堆叠条、利率曲线） ----------
    print("\n[D] 生成模型结果图...")
    y = art["y"]
    # fig10-1 ROC 曲线
    fpr, tpr, _ = roc_curve(y, pd_vals)
    auc = roc_auc_score(y, pd_vals)
    fig, ax = plt.subplots()
    ax.plot(fpr, tpr, color=plot_style.CATEGORICAL[0], lw=2, label=f"逻辑回归 (AUC={auc:.3f})")
    fpr2, tpr2, _ = roc_curve(y, art["pd_rf"])
    ax.plot(fpr2, tpr2, color=plot_style.CATEGORICAL[1], lw=1.6, ls="--",
            label=f"随机森林 (AUC={roc_auc_score(y, art['pd_rf']):.3f})")
    ax.plot([0, 1], [0, 1], color=plot_style.CATEGORICAL[2], lw=1, ls=":")
    ax.set_xlabel("假正率 (FPR)")
    ax.set_ylabel("真正率 (TPR)")
    ax.set_title("问题1：违约预测模型 ROC 曲线（5 折 CV 调参）")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig10_01_roc_curve.png"))

    # fig10-2 预测 PD 按评级分布（排序维度 = 评级等级）
    fig, ax = plt.subplots(figsize=(7, 4.5))
    data = [pd_vals[mono["信誉评级"].values == r] for r in order]
    bp = ax.boxplot(data, labels=order, patch_artist=True, widths=0.5)
    for patch, i in zip(bp["boxes"], range(4)):
        patch.set_facecolor(plot_style.CATEGORICAL[i])
        patch.set_alpha(0.75)
    ax.set_xlabel("信誉评级（按等级排序）")
    ax.set_ylabel("模型预测违约概率 PD")
    ax.set_title("问题1：模型预测 PD 与信誉评级的分层一致性")
    plot_style.save(fig, os.path.join(IMG, "fig10_02_pd_by_rating.png"))

    # fig10-3 风险画像热力图: 企业按 PD 升序(最安全在上), 列为标准化后的代表性特征
    #
    # 这张图是 12 个特征(行) × 123 家企业(列)，行列比例接近 1:10。第一版用接近
    # 正方形的画布硬配 aspect="auto"，把 12 行拉伸到跟 123 列一样高，格子变成
    # 很扁的横条；改成按行列真实比例定宽横幅画布后，格子又变成"竖着的长方形"
    # ——用户第二次反馈仍不够标准。根源是 123 这个列数对一张印刷宽度的图来说
    # 太多了：无论怎么调画布尺寸/宽高比，只要真的画 123 条独立窄列，格子要么
    # 太扁要么太窄，没有能让 12×123 变成正方形格子的合理画布尺寸（宽度会超过
    # 版心）。信用风险热力图的惯例做法（含 BIS/Dickson2011 这类文献里的画法）
    # 是分箱/分层展示，不是给每个个体各画一条独立窄列——按预测风险把 123 家
    # 企业分成 10 个风险十分位、每箱内取特征均值，画成 12×10 的热力图，
    # aspect="equal" 直接给出真正的正方形格子，读图时也更容易看出"风险从低到
    # 高，各特征怎么系统性变化"的趋势（分箱做了平滑，比 123 条独立窄列的噪声
    # 更清楚），信息含量不降反升。
    X, feats = build_feature_matrix(f1)
    repr_feats = [c for c in feats if any(k in c for k in ("sum_amt", "n_counterpart", "n_active_month",
                                                           "void_share", "neg_share", "cv_month", "out_in_ratio",
                                                           "growth", "hhi", "inv_per_active_month"))][:12]
    Xs = StandardScaler().fit_transform(X[repr_feats])
    order_idx = np.argsort(pd_vals)  # 按风险升序
    Xs_sorted = Xs[order_idx]
    n_bins = 10
    edges = np.linspace(0, len(order_idx), n_bins + 1).astype(int)
    binned = np.array([Xs_sorted[edges[b]:edges[b + 1]].mean(axis=0) for b in range(n_bins)])
    bin_labels = [f"#{edges[b] + 1}\n~{edges[b + 1]}" for b in range(n_bins)]
    fig, ax = plt.subplots(figsize=(9, 8.5))
    im = ax.imshow(binned.T, cmap=plot_style.diverging_cmap(), aspect="equal", vmin=-1.5, vmax=1.5)
    ax.set_yticks(range(len(repr_feats)))
    ax.set_yticklabels(repr_feats, fontsize=9)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bin_labels, fontsize=7.5)
    ax.set_xlabel("企业风险十分位（按模型预测风险从低到高分箱，箱内取均值）")
    ax.set_title("问题1：123 家企业风险画像热力图（按 PD 十分位分箱重排）")
    fig.colorbar(im, ax=ax, shrink=0.7, label="标准化特征值（箱内均值）")
    plot_style.save(fig, os.path.join(IMG, "fig10_03_risk_heatmap.png"))

    # fig10-4 最优利率-违约率曲线（按评级）
    fig, ax = plt.subplots()
    pds = np.linspace(0.005, 0.5, 60)
    for i, r in enumerate(["A", "B", "C"]):
        rates = [optimal_rate_and_profit(p, r, churn_fns, rate_grid)[0] for p in pds]
        ax.plot(pds, rates, color=plot_style.CATEGORICAL[i], lw=1.8, label=f"评级 {r}")
    ax.set_xlabel("违约概率 PD")
    ax.set_ylabel("最优贷款年利率")
    ax.set_title("问题1：最优利率随违约概率变化（受附件3流失率约束）")
    ax.legend(frameon=False)
    plot_style.save(fig, os.path.join(IMG, "fig10_04_optimal_rate.png"))

    # fig10-5 总额 1 亿时的额度分配：改成按企业排序的水平条形图（原先"评级为
    # 排序维度"的单柱堆叠图，只有一个 x 位置时视觉上就是一整块填满画布的色块，
    # 看不出个体差异——复核时发现这是跟 fig20_03 完全一样的问题，两处一起改，
    # 落到 §18"按排序维度重排的条形图"惯例上应该是"每家企业一根条"）。
    s1 = strat[strat["amount_wan"] > 0].sort_values("amount_wan", ascending=True)
    fig, ax = plt.subplots(figsize=(8, 3.2 + 0.32 * len(s1)))
    rating_color = {r: plot_style.CATEGORICAL[i] for i, r in enumerate(order)}
    colors = [rating_color.get(r, plot_style.CATEGORICAL[0]) for r in s1["信誉评级"]]
    ax.barh(s1["企业代号"], s1["amount_wan"], color=colors, height=0.6)
    for y, (amt, pd_) in enumerate(zip(s1["amount_wan"], s1["PD"])):
        ax.text(amt + s1["amount_wan"].max() * 0.015, y, f"{amt:.0f} 万元 · PD={pd_:.3f}",
                va="center", fontsize=7.5, color=plot_style.CHROME["text_secondary"])
    handles = [plt.Rectangle((0, 0), 1, 1, color=rating_color[r]) for r in order
               if (s1["信誉评级"] == r).any()]
    rating_labels = [f"评级 {r}（{(s1['信誉评级'] == r).sum()} 家）" for r in order
                     if (s1["信誉评级"] == r).any()]
    ax.legend(handles, rating_labels, loc="lower right", fontsize=8, frameon=False)
    ax.set_xlabel("分配额度（万元）")
    ax.set_xlim(0, s1["amount_wan"].max() * 1.28)
    ax.set_title(f"问题1：总额 1 亿元时的信贷分配（共放贷 {n_lend} 家，按额度排序）")
    plot_style.save(fig, os.path.join(IMG, "fig10_05_allocation_by_rating.png"))

    print("\n[P1] 完成。输出: strategy_p1.csv / scorer_p1.pkl / fig10_01~05")
    return 0


if __name__ == "__main__":
    sys.exit(main())
