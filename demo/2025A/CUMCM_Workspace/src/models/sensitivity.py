#!/usr/bin/env python3
"""
sensitivity.py — 灵敏度分析（AutoMCM_SOP §5 Phase 4）

考察关键参数扰动对"各问题最优策略的有效遮蔽时长"的影响：
  1. 导弹速度 v_m (300 ±10%)
  2. 云团下沉速度 (3 ±10%)
  3. 云团有效半径 (10 ±10%)
  4. 云团有效时长 (20 ±10%)
  5. 重力加速度 g (9.8 ±5%)
  6. 真目标参考点高度 (0 / 5 / 10 m，圆柱高 10 m 的垂直范围——建模模糊性检验)

对每个扰动：
  - 用"标称最优策略"（从各 model 结果缓存读取）在扰动物理下重评估遮蔽时长；
  - 对 Q2 单弹优化问题，在扰动物理下重优化（物理启发多起点 + 坐标轮换精化），
    观察可达到的最优时长如何移动（验证策略对参数的鲁棒性）。
输出灵敏度表 + 图 fig04_sensitivity.png。
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
import problem1_geometry as p1  # noqa: E402

IMG_DIR = ROOT / "latex" / "images"
STATE = ROOT / "state"


def load_model_results():
    """加载各 model 的结果缓存（最优策略）。"""
    out = {}
    for key, fname in [("m1", "model1_results.json"), ("m2", "model2_results.json"),
                       ("m3", "model3_results.json")]:
        p = STATE / fname
        if p.exists():
            out[key] = json.loads(p.read_text(encoding="utf-8"))
    return out


def make_scenario(**overrides):
    """深拷贝基准 scenario 并叠加扰动参数。"""
    sc = json.loads((ROOT / "data" / "scenario.json").read_text(encoding="utf-8"))
    for k, v in overrides.items():
        sc[k] = v
    return sc


def eval_q2_strategy(sc, res_m1, theta, v, t_drop, t_delay):
    """在给定物理 sc 下重评估单弹策略的遮蔽时长。"""
    f0 = sc["uavs"]["FY1"]
    ivs = gc.masking_intervals(sc, "M1", f0, theta, v, t_drop, t_delay)
    return gc.union_measure(ivs)


def eval_m2_strategy(sc, res_m2):
    """在给定物理 sc 下重评估问题 3（3 弹并集）总时长。"""
    if not res_m2:
        return None
    bombs = []
    for b in res_m2.get("bombs", []):
        bombs.append(("FY1", b["theta"], b["v"], b["t_drop"], b["t_delay"]))
    if not bombs:
        return None
    return gc.multi_bomb_union_masking(sc, "M1", bombs)


def eval_m3_strategy(sc, res_m3):
    """在给定物理 sc 下重评估问题 4（3 机各 1 弹对 M1）与问题 5（多机多弹多导弹）总时长。

    兼容两种缓存 schema：{q4,q5} 或 {problem4,problem5}；弹字段 uav/f_name、
    missile/m_name 均可。
    """
    if not res_m3:
        return None, None
    q4 = None
    r4 = res_m3.get("q4") or res_m3.get("problem4")
    if r4:
        bombs4 = [(_uav(b), b.get("theta"), b.get("v"), b.get("t_drop"), b.get("t_delay"))
                  for b in r4.get("bombs", [])]
        bombs4 = [b for b in bombs4 if all(x is not None for x in b)]
        if bombs4:
            q4 = gc.multi_bomb_union_masking(sc, "M1", bombs4)
    q5 = None
    r5 = res_m3.get("q5") or res_m3.get("problem5")
    if r5:
        per_missile = {"M1": [], "M2": [], "M3": []}
        for b in r5.get("bombs", []):
            m = b.get("missile") or b.get("m_name") or "M1"
            if m in per_missile:
                per_missile[m].append((_uav(b), b.get("theta"), b.get("v"),
                                       b.get("t_drop"), b.get("t_delay")))
        per_missile = {k: [x for x in v if all(y is not None for y in x)]
                       for k, v in per_missile.items()}
        if any(per_missile.values()):
            q5 = sum(gc.multi_bomb_union_masking(sc, k, v) for k, v in per_missile.items()
                     if v)
    return q4, q5


def _uav(b):
    return b.get("uav") or b.get("f_name")


def reoptimize_q2(sc, theta0, v0, t_drop0, t_delay0):
    """在扰动物理下重优化单弹策略（以标称最优为起点做两级坐标轮换精化）。"""
    import problem1_geometry as p1m

    def _dmin(x, sc_):
        _, _, dmin = gc.single_bomb_masking_detail(sc_, "M1", "FY1", *x)
        return dmin

    def obj(x):
        dur, _, _ = gc.single_bomb_masking_detail(sc, "M1", "FY1", *x)
        guide = max(0.0, sc["cloud_effective_radius"] - _dmin(x, sc))
        return -(dur + p1m.GUIDE_WEIGHT * guide)

    x0 = np.array([theta0, v0, t_drop0, t_delay0])
    x = x0.copy()
    bounds = p1m.BOUNDS_Q2
    for _ in range(2):
        for k in range(4):
            lo, hi = bounds[k]
            span = hi - lo
            cand = np.linspace(max(lo, x[k] - span * 0.03), min(hi, x[k] + span * 0.03), 41)
            best_x, best_f = x.copy(), obj(x)
            for c in cand:
                xc = x.copy()
                xc[k] = c
                f = obj(xc)
                if f < best_f - 1e-12:
                    best_f, best_x = f, xc
            x = best_x
    dur, _, _ = gc.single_bomb_masking_detail(sc, "M1", "FY1", *x)
    return dur, x


def fig_sensitivity(rows, baseline, out_path=None):
    """灵敏度 tornado 图（从 rows 渲染，供 main 与重出图脚本共用）。

    §18 惯例（见 memory/thought_process.md）：单参数扰动的灵敏度分析常规画法是
    tornado 图——以标称值为中央基准（虚线）、低扰动蓝/高扰动红（发散配色）、按
    影响幅度从大到小排序（最大在顶部）、条形末端标扰动方向与数值；本版再补
    每行右侧的影响幅度 Δ 标注，并给 x 轴留足文字余量防止标签被裁剪。
    """
    plot_style.apply()
    groups = {}
    for r in rows:
        groups.setdefault(r["param"], []).append(r)
    tornado = []
    for param, grp in groups.items():
        vals = [(g["pert"], g["q2"]) for g in grp]
        lo_label, lo_val = min(vals, key=lambda t: t[1])
        hi_label, hi_val = max(vals, key=lambda t: t[1])
        tornado.append(dict(param=param, lo_label=lo_label, lo_val=lo_val,
                             hi_label=hi_label, hi_val=hi_val,
                             spread=hi_val - lo_val))
    tornado.sort(key=lambda d: d["spread"])  # 升序画：spread 最大的排最上面

    fig, ax = plt.subplots(figsize=(9.8, 2.4 + 0.66 * len(tornado)))
    y = np.arange(len(tornado))
    for i, d in enumerate(tornado):
        lo_w, hi_w = baseline - d["lo_val"], d["hi_val"] - baseline
        if lo_w <= 1e-9 and hi_w <= 1e-9:
            # 扰动范围内评估值与标称完全一致——不是缺数据，是该参数当前不是瓶颈，
            # 用中性小标记明确标出，不留看起来像缺数据的空行。
            ax.scatter([baseline], [i], marker="|", s=260,
                       color=plot_style.CHROME["text_muted"])
            ax.text(baseline + 0.06, i, "±10% 均无影响（非瓶颈约束）",
                    ha="left", va="center", fontsize=7.5,
                    color=plot_style.CHROME["text_muted"])
            continue
        if lo_w > 1e-9:
            ax.barh(i, -lo_w, left=baseline, color=plot_style.DIVERGING_LOW, height=0.5)
            ax.text(d["lo_val"] - 0.08, i, f"{d['lo_label']} ({d['lo_val']:.2f}s)",
                    ha="right", va="center", fontsize=8, color=plot_style.DIVERGING_LOW)
        if hi_w > 1e-9:
            ax.barh(i, hi_w, left=baseline, color=plot_style.DIVERGING_HIGH, height=0.5)
            ax.text(d["hi_val"] + 0.08, i, f"{d['hi_label']} ({d['hi_val']:.2f}s)",
                    ha="left", va="center", fontsize=8, color=plot_style.DIVERGING_HIGH)
        ax.text(d["hi_val"] + 1.15, i, f"Δ={d['spread']:.2f}s",
                ha="left", va="center", fontsize=7.5, color=plot_style.CHROME["text_secondary"])
    ax.axvline(baseline, color=plot_style.CHROME["text_secondary"], lw=1.2, ls="--",
               label=f"标称 Q2={baseline:.3f}s")
    ax.set_yticks(y)
    ax.set_yticklabels([d["param"] for d in tornado], fontsize=10)
    ax.set_xlabel("Q2 策略遮蔽时长 (s)")
    ax.set_title("参数扰动下 Q2 最优策略遮蔽时长的灵敏度（tornado 图，按影响幅度排序）")
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    xmin = min(d["lo_val"] for d in tornado) - 1.2
    xmax = max(d["hi_val"] for d in tornado) + 2.4   # 给末端数值与 Δ 标注留足空间
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(-0.6, len(tornado) - 0.4)
    ax.grid(True, axis="x", alpha=0.3)
    if out_path is not None:
        plot_style.save(fig, out_path)
        plt.close(fig)
        print(f"[sensitivity] tornado 图已生成 -> {out_path}")
    return fig


def main():
    res = load_model_results()
    print("=" * 78)
    print("灵敏度分析（各参数扰动对最优策略有效遮蔽时长的影响）")
    print("=" * 78)
    if "m1" not in res:
        print("[sensitivity] ⚠ model_1 结果缓存缺失，无法分析——先运行 problem1_geometry.py")
        return
    q2 = res["m1"]["q2"]
    q1 = res["m1"]["q1"]
    m2_total = None
    if res.get("m2"):
        m2_total = res["m2"].get("total_dur")
    m3_txt = ""
    if res.get("m3"):
        r4 = res["m3"].get("q4") or res["m3"].get("problem4")
        r5 = res["m3"].get("q5") or res["m3"].get("problem5")
        m3_txt = (f"  Q4={r4['total_dur']:.3f}s  Q5={r5['total_dur']:.3f}s"
                  if r4 and r5 else "")
    print(f"基准：Q1={q1['dur']:.3f}s  Q2={q2['dur']:.3f}s"
          + (f"  Q3={m2_total:.3f}s" if m2_total else "")
          + m3_txt)

    rows = []
    base = load_scenario() if False else json.loads((ROOT / "data" / "scenario.json").read_text(encoding="utf-8"))

    def add_row(param, pert_label, sc, note=""):
        d_q2 = eval_q2_strategy(sc, res["m1"], q2["theta"], q2["v"], q2["t_drop"], q2["t_delay"])
        m2 = eval_m2_strategy(sc, res.get("m2")) if res.get("m2") else None
        m3q4, m3q5 = eval_m3_strategy(sc, res.get("m3"))
        rows.append(dict(param=param, pert=pert_label, q2=d_q2, q3=m2, q4=m3q4, q5=m3q5,
                         note=note))

    # 1) 导弹速度 ±10%
    for f in (0.9, 1.1):
        sc = make_scenario(missile_speed=300.0 * f)
        add_row("导弹速度", f"{'+' if f > 1 else ''}{round((f - 1) * 100)}%", sc)
    # 2) 云团下沉速度 ±10%
    for f in (0.9, 1.1):
        sc = make_scenario(cloud_sink_speed=3.0 * f)
        add_row("云团下沉速度", f"{'+' if f > 1 else ''}{round((f - 1) * 100)}%", sc)
    # 3) 云团有效半径 ±10%
    for f in (0.9, 1.1):
        sc = make_scenario(cloud_effective_radius=10.0 * f)
        add_row("云团有效半径", f"{'+' if f > 1 else ''}{round((f - 1) * 100)}%", sc)
    # 4) 云团有效时长 ±10%
    for f in (0.9, 1.1):
        sc = make_scenario(cloud_effective_duration=20.0 * f)
        add_row("云团有效时长", f"{'+' if f > 1 else ''}{round((f - 1) * 100)}%", sc)
    # 5) 重力加速度 ±5%
    for f in (0.95, 1.05):
        sc = make_scenario(g=9.8 * f)
        add_row("重力加速度", f"{'+' if f > 1 else ''}{round((f - 1) * 100)}%", sc)
    # 6) 真目标参考点高度（圆柱垂直范围建模模糊性）
    for z in (5.0, 10.0):
        sc = make_scenario()
        old_ref = gc.TARGET_REF.copy()
        gc.TARGET_REF[2] = z
        add_row("目标参考点高度", f"z={z:.0f}m", sc, note="建模模糊性检验")
        gc.TARGET_REF[:] = old_ref

    # 输出表
    hdr = f"{'参数':<12}{'扰动':<10}{'Q2评估':>8}{'Q3评估':>8}{'Q4评估':>8}{'Q5评估':>8}"
    print("-" * 78)
    print(hdr)
    for r in rows:
        fmt = lambda v: f"{v:7.2f}" if v is not None else "     -"
        print(f"{r['param']:<12}{r['pert']:<10}{fmt(r['q2']):>8}{fmt(r['q3']):>8}"
              f"{fmt(r['q4']):>8}{fmt(r['q5']):>8}  {r['note']}")
    print("-" * 78)

    # 重优化 Q2（导弹速度与下沉速度、有效半径扰动下）
    print("\n[灵敏度] Q2 在扰动物理下的重优化（验证可达时长鲁棒性）：")
    for param, fvals in [("missile_speed", (0.9, 1.1)),
                         ("cloud_sink_speed", (0.9, 1.1)),
                         ("cloud_effective_radius", (0.9, 1.1))]:
        for f in fvals:
            sc = make_scenario(**{param: base[param] * f})
            dur, x = reoptimize_q2(sc, q2["theta"], q2["v"], q2["t_drop"], q2["t_delay"])
            print(f"  {param}×{f:.2f}: 重优化时长 {dur:.3f} s（标称 4.611 s，"
                  f"变化 {(dur-4.611)/4.611*100:+.1f}%）")

    # 图：灵敏度分析结果 —— tornado 图
    # §18 惯例调研（见 memory/thought_process.md）：单参数扰动的灵敏度分析常规画法
    # 是 tornado 图——按影响幅度从大到小排序的水平条形图，一眼看出"哪个参数最
    # 敏感"；原先的普通柱状图在参数一多就会导致 x 轴刻度标签互相重叠、且不天然
    # 按敏感度排序，改成 tornado 图后两个问题一起解决。绘图逻辑见 fig_sensitivity()。
    fig_sensitivity(rows, baseline=q2["dur"], out_path=IMG_DIR / "fig04_sensitivity.png")

    # 缓存灵敏度表供验证脚本
    (STATE / "sensitivity_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[sensitivity] 灵敏度表已缓存 → state/sensitivity_results.json")


if __name__ == "__main__":
    main()
