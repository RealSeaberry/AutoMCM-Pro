#!/usr/bin/env python3
"""
problem2_schedule.py — model_2（问题 3：单机 3 弹时序调度）

FY1 投放 3 枚烟幕干扰弹实施对 M1 的干扰：确定 FY1 的航向角 θ、速度 v 与
3 枚弹的投放时刻 t1<t2<t3（相邻间隔 ≥1 s）、起爆延迟 d1,d2,d3，
使 3 枚云团对 M1 的并集有效遮蔽时长最大（遮蔽可不连续，取时间并集测度）。

核心函数：solve_problem3()（附录节选对象）——物理启发多起点 + 两级坐标轮换精化，
复用 geometry_core.masking_intervals 的遮蔽判据。
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np

ROOT = Path(__file__).resolve().parents[2]               # CUMCM_Workspace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/models
sys.path.insert(0, str(ROOT.parent / "scripts"))
import plot_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import geometry_core as gc  # noqa: E402

SC = gc.load_scenario()
IMG_DIR = ROOT / "latex" / "images"

# 优化边界（FY1 共用航向/速度；3 弹投放时刻与起爆延迟）
B_THETA = (0.0, 360.0)
B_V = (70.0, 140.0)
B_T1 = (0.0, 30.0)      # 第一弹投放时刻
B_GAP = (0.0, 8.0)      # 相邻两弹额外间隔（实际间隔 = 1 + gap）
B_DELAY = (0.5, 15.0)   # 起爆延迟
# 排序参数化：t2 = t1 + 1 + g2，t3 = t2 + 1 + g3，自动满足 ≥1 s 间隔约束
LB = np.array([B_THETA[0], B_V[0], B_T1[0], B_GAP[0], B_GAP[0],
               B_DELAY[0], B_DELAY[0], B_DELAY[0]])
UB = np.array([B_THETA[1], B_V[1], B_T1[1], B_GAP[1], B_GAP[1],
               B_DELAY[1], B_DELAY[1], B_DELAY[1]])


def decode(x):
    """解码 8 维向量 → (theta, v, [t1,t2,t3], [d1,d2,d3])。"""
    theta, v, t1, g2, g3, d1, d2, d3 = x
    t2 = t1 + 1.0 + g2
    t3 = t2 + 1.0 + g3
    return theta, v, [t1, t2, t3], [d1, d2, d3]


def objective(x, sc=None):
    """3 弹并集遮蔽时长取负。"""
    sc = sc or SC
    theta, v, ts, ds = decode(x)
    f0 = sc["uavs"]["FY1"]
    all_ivs = []
    for t_drop, d in zip(ts, ds):
        all_ivs += gc.masking_intervals(sc, "M1", f0, theta, v, t_drop, d)
    return -gc.union_measure(all_ivs)


def _physics_seeds():
    """物理启发多起点：沿 FY1 飞行射线（θ 方向）等距放置 3 枚云团，
    每枚取"自然高度" z = x/10（导弹-目标视线在高度 z 处恰位于 x≈10z），
    由弹道反解起爆延迟 d 与投放时刻 t_drop，取 3 个间隔 ≥1 s 的组合。

    关键物理：视线在固定高度 z 处近似位于 x = 10·z 的竖直线上（导弹沿指向
    原点的直线飞行时 x(z) = M_x·z/M_z ≡ 10z），云团沿射线错开 y 位置即可
    依次覆盖视线在 y 方向的扫描窗口，形成时间链。
    """
    sc = SC
    f0 = np.array(sc["uavs"]["FY1"], dtype=float)
    g = sc["g"]
    seeds = []
    s_vals = [300.0, 450.0, 600.0, 750.0, 900.0, 1050.0, 1200.0, 1350.0]
    for theta in np.arange(174.0, 187.0, 1.0):
        th = np.deg2rad(theta)
        dir_ = np.array([np.cos(th), np.sin(th)])
        for v in np.arange(80.0, 141.0, 10.0):
            cand = []
            for s in s_vals:
                x = f0[0] + s * dir_[0]
                z = max(1200.0, min(1790.0, x / 10.0))
                d = float(np.sqrt(max(0.0, 2.0 * (f0[2] - z) / g)))
                if not (0.5 <= d <= 15.0):
                    continue
                t_drop = s / v - d
                if not (0.0 <= t_drop <= 30.0):
                    continue
                cand.append((t_drop, d, s))
            cand.sort()
            for i in range(len(cand)):
                for j in range(i + 1, len(cand)):
                    if cand[j][0] - cand[i][0] < 1.0:
                        continue
                    for k in range(j + 1, len(cand)):
                        if cand[k][0] - cand[j][0] < 1.0:
                            continue
                        seeds.append((theta, float(v),
                                      [cand[i][0], cand[j][0], cand[k][0]],
                                      [cand[i][1], cand[j][1], cand[k][1]]))
                        break
    # Q2 最优单弹策略作为 3 弹退化的起点（其余两弹向后顺延）
    m1 = json.loads((ROOT / "state" / "model1_results.json").read_text(encoding="utf-8"))
    q2 = m1["q2"]
    seeds.append((q2["theta"], q2["v"], [q2["t_drop"], q2["t_drop"] + 1.5, q2["t_drop"] + 3.0],
                  [q2["t_delay"], q2["t_delay"], q2["t_delay"]]))
    return seeds


def _to_vector(theta, v, ts, ds):
    """把 (theta,v,[t1,t2,t3],[d1,d2,d3]) 转成 8 维排序参数化向量。"""
    t1, t2, t3 = sorted(ts)
    g2 = max(0.0, t2 - t1 - 1.0)
    g3 = max(0.0, t3 - t2 - 1.0)
    return np.array([theta, v, t1, g2, g3, ds[0], ds[1], ds[2]])


def _coordinate_refine(x0, n_passes=3, n_scan=41, half_frac=0.02):
    """坐标轮换爬山精化：逐变量邻域网格扫描（排序参数化下间隔约束自动满足）。"""
    x = np.array(x0, dtype=float)
    for _ in range(n_passes):
        for k in range(8):
            lo, hi = LB[k], UB[k]
            span = hi - lo
            half = max(span * half_frac, 1e-3)
            cand = np.linspace(max(lo, x[k] - half), min(hi, x[k] + half), n_scan)
            best_x, best_f = x.copy(), objective(x)
            for c in cand:
                xc = x.copy()
                xc[k] = c
                f = objective(xc)
                if f < best_f - 1e-12:
                    best_f, best_x = f, xc
            x = best_x
    return x, -best_f


def solve_problem3():
    """问题 3：单机 3 弹时序调度优化。"""
    print("=" * 66)
    print("问题 3：单机 3 弹投放策略优化（物理启发多起点 + 坐标轮换精化）")
    print("=" * 66)
    seeds = _physics_seeds()
    print(f"[model_2] 生成物理启发起点 {len(seeds)} 个")
    # 起点评分（引导项：并集时长 + 接近度）
    scored = []
    for theta, v, ts, ds in seeds:
        x = _to_vector(theta, v, ts, ds)
        scored.append((objective(x), x))
    scored.sort(key=lambda t: t[0])
    top = scored[:24]
    # 粗精化
    refined = []
    for _, x in top:
        x2, dur = _coordinate_refine(x, n_passes=2, n_scan=21, half_frac=0.05)
        refined.append((dur, x2))
    refined.sort(key=lambda t: -t[0])
    print(f"[model_2] 粗精化后 top3 时长: {[round(r[0], 3) for r in refined[:3]]} s")
    # 细精化
    best_dur, best_x = -1.0, None
    for dur, x in refined[:8]:
        x2, dur2 = _coordinate_refine(x, n_passes=3, n_scan=41, half_frac=0.01)
        if dur2 > best_dur:
            best_dur, best_x = dur2, x2
    theta, v, ts, ds = decode(best_x)
    f0 = SC["uavs"]["FY1"]
    Ds, Es, ivs_list, durs = [], [], [], []
    all_ivs = []
    for t_drop, d in zip(ts, ds):
        D = gc.uav_position(f0, theta, v, t_drop)
        E = gc.bomb_position(D, theta, v, d, SC["g"])
        Ds.append(D)
        Es.append(E)
        ivs = gc.masking_intervals(SC, "M1", f0, theta, v, t_drop, d)
        ivs_list.append(ivs)
        all_ivs += ivs
        durs.append(gc.union_measure(ivs))
    print(f"最优航向角 θ        : {theta:.3f}°")
    print(f"最优速度 v          : {v:.3f} m/s")
    print(f"投放时刻 t1/t2/t3   : {[round(t, 3) for t in ts]} s")
    print(f"起爆延迟 d1/d2/d3   : {[round(x, 3) for x in ds]} s")
    for i in range(3):
        print(f"弹{i+1}: 投放点 ({Ds[i][0]:.1f},{Ds[i][1]:.1f},{Ds[i][2]:.1f})  "
              f"起爆点 ({Es[i][0]:.1f},{Es[i][1]:.1f},{Es[i][2]:.1f})  "
              f"自身时长 {durs[i]:.3f}s  区间 {[(round(a,2),round(b,2)) for a,b in ivs_list[i]]}")
    print(f"3 弹并集遮蔽时长     : {best_dur:.3f} s")
    return dict(theta=theta, v=v, ts=ts, ds=ds, Ds=Ds, Es=Es,
                ivs_list=ivs_list, durs=durs, total_dur=best_dur)


def _merge_intervals(ivs):
    """区间合并（并集）。"""
    out = []
    for a, b in sorted(ivs):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def fig_q3(ivs_list, out_name="fig02_q3_masking_window.png"):
    """3 弹遮蔽时间窗口图（每弹 + 并集行，条形末端标时长）。"""
    plot_style.apply()
    colors = plot_style.categorical(3)
    union = _merge_intervals([iv for ivs in ivs_list for iv in ivs])
    union_dur = sum(b - a for a, b in union)
    max_end = max((b for ivs in ivs_list for _, b in ivs), default=12.0)
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    ys = ["弹 1", "弹 2", "弹 3", "并集（总遮蔽）"]
    for i, ivs in enumerate(ivs_list):
        for a, b in ivs:
            ax.barh(ys[i], b - a, left=a, height=0.5, color=colors[i], alpha=0.85)
        if ivs:
            tot = sum(b - a for a, b in ivs)
            last_b = max(ivs, key=lambda t: t[1])[1]
            ax.text(last_b + 0.2, ys[i], f"{tot:.2f} s", va="center", fontsize=8.5,
                    color=colors[i])
    for a, b in union:
        ax.barh(ys[3], b - a, left=a, height=0.5,
                color=plot_style.CHROME["text_secondary"], alpha=0.55)
    ax.text(max_end + 0.2, ys[3], f"{union_dur:.2f} s", va="center", fontsize=8.5,
            color=plot_style.CHROME["text_secondary"])
    ax.set_xlabel("时间 t (s)")
    ax.set_title("问题 3：FY1 三枚烟幕干扰弹的有效遮蔽时间窗口")
    ax.set_xlim(0, max_end + 1.8)
    ax.grid(True, axis="x", alpha=0.3)
    plot_style.save(fig, IMG_DIR / out_name)
    plt.close(fig)
    print(f"[model_2] {out_name} 已生成")


def write_result1(opt):
    """把结果写入 result1.xlsx 模板（并复制到 output/）。"""
    import openpyxl
    theta, v, ts, ds = opt["theta"], opt["v"], opt["ts"], opt["ds"]
    wb = openpyxl.load_workbook(ROOT / "data" / "result1.xlsx")
    ws = wb["Sheet1"]
    for i in range(3):
        r = 2 + i
        ws.cell(r, 1, round(theta, 2))                       # 无人机运动方向
        ws.cell(r, 2, round(v, 2))                           # 无人机运动速度
        D, E = opt["Ds"][i], opt["Es"][i]
        for c, val in zip((4, 5, 6), D):                     # 投放点 x/y/z
            ws.cell(r, c, round(float(val), 2))
        for c, val in zip((7, 8, 9), E):                     # 起爆点 x/y/z
            ws.cell(r, c, round(float(val), 2))
        ws.cell(r, 10, round(opt["durs"][i], 2))             # 有效干扰时长
    wb.save(ROOT / "data" / "result1.xlsx")
    (ROOT / "output").mkdir(exist_ok=True)
    wb.save(ROOT / "output" / "result1.xlsx")
    print("[model_2] result1.xlsx 已填写（3 行）")


def main():
    opt = solve_problem3()
    fig_q3(opt["ivs_list"])
    write_result1(opt)
    cache = {
        "total_dur": opt["total_dur"],
        "theta": opt["theta"], "v": opt["v"],
        "bombs": [
            {"theta": opt["theta"], "v": opt["v"], "t_drop": opt["ts"][i],
             "t_delay": opt["ds"][i], "dur": opt["durs"][i],
             "ivs": [[round(a, 3), round(b, 3)] for a, b in opt["ivs_list"][i]]}
            for i in range(3)
        ],
    }
    out = ROOT / "state" / "model2_results.json"
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[model_2] 结果缓存 → {out}")
    return opt


if __name__ == "__main__":
    main()
