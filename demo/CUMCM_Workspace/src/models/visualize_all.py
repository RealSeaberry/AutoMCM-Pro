"""
visualize_all.py — 美化版可视化图表生成
2025 CUMCM A题：烟幕干扰弹投放策略
"""
import numpy as np
import sys, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.ticker as ticker
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap

# ── 全局字体与样式 ─────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    'font.family': ['Microsoft YaHei', 'SimHei', 'sans-serif'],
    'axes.unicode_minus': False,
    'font.size': 12,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'xtick.labelsize': 10.5,
    'ytick.labelsize': 10.5,
    'legend.fontsize': 10,
    'figure.facecolor': '#fafafa',
    'axes.facecolor': '#f8f8f8',
    'axes.grid': True,
    'grid.alpha': 0.35,
    'grid.linestyle': '--',
    'grid.linewidth': 0.7,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'lines.linewidth': 2.0,
})

# ── 配色方案 ────────────────────────────────────────────────────────────────
PALETTE = {
    'M1': '#e74c3c', 'M2': '#e67e22', 'M3': '#8e44ad',
    'FY1': '#2980b9', 'FY2': '#27ae60', 'FY3': '#f39c12',
    'FY4': '#16a085', 'FY5': '#8e44ad',
    'union': '#e67e22', 'bg': '#ecf0f1',
    'accent': '#2c3e50', 'highlight': '#f1c40f',
}

IMG_DIR = os.path.join(os.path.dirname(__file__), '../../latex/images')
os.makedirs(IMG_DIR, exist_ok=True)

# ── 物理常数 ────────────────────────────────────────────────────────────────
G = 9.8; V_SINK = 3.0; R_EFF = 10.0; T_EFF = 20.0; V_MISSILE = 300.0
TRUE_TARGET = np.array([0.0, 200.0, 5.0])
MISSILES = {
    'M1': np.array([20000., 0., 2000.]),
    'M2': np.array([19000., 600., 2100.]),
    'M3': np.array([18000., -600., 1900.]),
}
DRONES = {
    'FY1': np.array([17800., 0., 1800.]),
    'FY2': np.array([12000., 1400., 1400.]),
    'FY3': np.array([6000., -3000., 700.]),
    'FY4': np.array([11000., 2000., 1800.]),
    'FY5': np.array([13000., -2000., 1300.]),
}

def missile_pos(m0, t): return m0 * (1 - V_MISSILE * t / np.linalg.norm(m0))
def missile_arrival(m0): return np.linalg.norm(m0) / V_MISSILE

def compute_coverage(det_pos, t_det, missile_name='M1', dt=0.001):
    m0 = MISSILES[missile_name]; t_arr = missile_arrival(m0)
    t0, t1 = t_det, min(t_det + T_EFF, t_arr)
    if t1 <= t0: return 0.0, []
    ts = np.arange(t0, t1 + dt, dt)
    fac = V_MISSILE * ts / np.linalg.norm(m0)
    M = m0[np.newaxis, :] * (1 - fac[:, np.newaxis])
    C = np.tile(det_pos, (len(ts), 1)); C[:, 2] -= V_SINK * (ts - t_det)
    d = TRUE_TARGET - M; v = C - M
    ds = np.sum(d**2, axis=1)
    s = np.sum(v * d, axis=1) / np.maximum(ds, 1e-12)
    foot = M + s[:, np.newaxis] * d
    dist = np.linalg.norm(C - foot, axis=1)
    ok = (dist <= R_EFF) & (s >= 0) & (s <= 1)
    ivs, in_c, t_in = [], False, None
    for i, flag in enumerate(ok):
        if flag and not in_c: in_c = True; t_in = ts[i]
        elif not flag and in_c: in_c = False; ivs.append((t_in, ts[i]))
    if in_c: ivs.append((t_in, ts[-1]))
    return sum(b - a for a, b in ivs), ivs

def grenade_traj(d0, angle_deg, v_drone, t_release, tau_det):
    ar = np.radians(angle_deg)
    vel = np.array([v_drone * np.cos(ar), v_drone * np.sin(ar), 0.0])
    rp = d0 + vel * t_release
    dp = np.array([rp[0] + vel[0] * tau_det,
                   rp[1] + vel[1] * tau_det,
                   rp[2] - 0.5 * G * tau_det**2])
    return rp, dp, t_release + tau_det

# ── 已知最优结果 ───────────────────────────────────────────────────────────
Q5_detail = {
    'M1': dict(cov=12.771, merged=[(2.907, 7.617), (19.418, 23.370), (30.794, 34.903)],
               drones=['FY1','FY5','FY3'], drone_covs={'FY1':4.71,'FY5':3.95,'FY3':4.11}),
    'M2': dict(cov=4.054, merged=[(15.752, 19.806)],
               drones=['FY2'], drone_covs={'FY2':4.054}),
    'M3': dict(cov=3.425, merged=[(18.536, 21.961)],
               drones=['FY4'], drone_covs={'FY4':3.425}),
}
Q5_assign = {'FY1':'M1','FY2':'M2','FY3':'M1','FY4':'M3','FY5':'M1'}

def save_fig(name):
    path = os.path.join(IMG_DIR, name)
    plt.savefig(path, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"    ✓ {name}")

# ═══════════════════════════════════════════════════════════════════════════
# fig03_3d_scene.png — 三维战场全景（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [1/8] fig03_3d_scene.png ...")
fig = plt.figure(figsize=(14, 9), facecolor='white')
ax = fig.add_subplot(111, projection='3d')
ax.set_facecolor('#f0f4f8')

# 导弹轨迹（渐变透明度）
for mn, m0 in MISSILES.items():
    t_arr = missile_arrival(m0)
    ts = np.linspace(0, t_arr, 300)
    traj = np.array([missile_pos(m0, t) for t in ts])
    ax.plot(traj[:, 0]/1000, traj[:, 1]/1000, traj[:, 2]/1000,
            color=PALETTE[mn], lw=2.8, alpha=0.9, zorder=5,
            path_effects=[pe.SimpleLineShadow(offset=(1,-1), shadow_color='gray',
                                               alpha=0.2), pe.Normal()])
    ax.scatter(*m0/1000, color=PALETTE[mn], s=180, marker='^', zorder=10,
               edgecolors='white', linewidths=1.2)
    ax.text(m0[0]/1000+0.4, m0[1]/1000, m0[2]/1000+0.15, mn,
            fontsize=12, color=PALETTE[mn], fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor=PALETTE[mn]))

# 无人机位置及分配连线
fy_colors = [PALETTE[dn] for dn in DRONES]
for dn, d0 in DRONES.items():
    mn_t = Q5_assign[dn]
    m0_t = MISSILES[mn_t]
    c = PALETTE[dn]
    ax.scatter(*d0/1000, color=c, s=200, marker='D', zorder=10,
               edgecolors='white', linewidths=1.5)
    ax.text(d0[0]/1000-0.6, d0[1]/1000, d0[2]/1000+0.15, dn,
            fontsize=11, color=c, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.75, edgecolor=c))
    # 虚线连到目标导弹轨迹中点
    mid = missile_pos(m0_t, missile_arrival(m0_t)*0.4)
    ax.plot([d0[0]/1000, mid[0]/1000], [d0[1]/1000, mid[1]/1000],
            [d0[2]/1000, mid[2]/1000],
            color=PALETTE[mn_t], lw=1.2, ls='--', alpha=0.5, zorder=2)

# 真实目标
ax.scatter(*TRUE_TARGET/1000, color='#c0392b', s=400, marker='*',
           zorder=15, edgecolors='white', linewidths=1.5)
ax.text(TRUE_TARGET[0]/1000, TRUE_TARGET[1]/1000+0.4, TRUE_TARGET[2]/1000+0.2,
        '真实目标', fontsize=11, color='#c0392b', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8, edgecolor='#c0392b'))

# 假目标
ax.scatter(0, 0, 0, color='gray', s=200, marker='o', zorder=10,
           edgecolors='white', linewidths=1.2)
ax.text(0.3, 0, 0.1, '假目标', fontsize=10, color='gray')

# 坐标轴美化
ax.set_xlabel('X 坐标 (km)', labelpad=10, fontsize=11)
ax.set_ylabel('Y 坐标 (km)', labelpad=10, fontsize=11)
ax.set_zlabel('Z 高度 (km)', labelpad=10, fontsize=11)
ax.set_title('三维战场全景：导弹来袭轨迹与无人机部署（问题5分配方案）',
             fontsize=14, fontweight='bold', pad=20)

# 图例
legend_elems = [
    plt.Line2D([0],[0], color=PALETTE['M1'], lw=3, label='M1 来袭轨迹'),
    plt.Line2D([0],[0], color=PALETTE['M2'], lw=3, label='M2 来袭轨迹'),
    plt.Line2D([0],[0], color=PALETTE['M3'], lw=3, label='M3 来袭轨迹'),
    plt.Line2D([0],[0], marker='D', color='w', markerfacecolor=PALETTE['FY1'],
               markersize=10, label='FY1 → M1', markeredgecolor='gray'),
    plt.Line2D([0],[0], marker='D', color='w', markerfacecolor=PALETTE['FY2'],
               markersize=10, label='FY2 → M2', markeredgecolor='gray'),
    plt.Line2D([0],[0], marker='D', color='w', markerfacecolor=PALETTE['FY3'],
               markersize=10, label='FY3 → M1', markeredgecolor='gray'),
    plt.Line2D([0],[0], marker='D', color='w', markerfacecolor=PALETTE['FY4'],
               markersize=10, label='FY4 → M3', markeredgecolor='gray'),
    plt.Line2D([0],[0], marker='D', color='w', markerfacecolor=PALETTE['FY5'],
               markersize=10, label='FY5 → M1', markeredgecolor='gray'),
    plt.Line2D([0],[0], marker='*', color='w', markerfacecolor='#c0392b',
               markersize=15, label='真实目标', markeredgecolor='white'),
]
ax.legend(handles=legend_elems, loc='upper right', fontsize=9.5, ncol=2,
          bbox_to_anchor=(1.02, 1.0), framealpha=0.9)
ax.view_init(elev=20, azim=-50)
ax.grid(True, alpha=0.2)
plt.tight_layout()
save_fig('fig03_3d_scene.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig04_q1_shielding.png — 问题1遮蔽几何（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [2/8] fig04_q1_shielding.png ...")
rp1, dp1, td1 = grenade_traj(DRONES['FY1'], 180., 120., 1.5, 3.6)
_, ivs1 = compute_coverage(dp1, td1, 'M1', dt=0.001)
m0_M1 = MISSILES['M1']
t_arr_M1 = missile_arrival(m0_M1)

fig = plt.figure(figsize=(15, 6.5), facecolor='white')
gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.38)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])

# 左图：x-z侧视图
# 导弹轨迹
ts_m = np.linspace(0, t_arr_M1, 400)
mx = [missile_pos(m0_M1, t)[0]/1000 for t in ts_m]
mz = [missile_pos(m0_M1, t)[2]/1000 for t in ts_m]
ax1.plot(mx, mz, color=PALETTE['M1'], lw=2.5, label='M1导弹轨迹', zorder=5,
         path_effects=[pe.Stroke(linewidth=4, foreground='#fcc', alpha=0.5), pe.Normal()])
ax1.scatter(m0_M1[0]/1000, m0_M1[2]/1000, color=PALETTE['M1'], s=150, marker='^',
            zorder=10, label='M1初始位置', edgecolors='white', linewidths=1.5)
ax1.scatter(TRUE_TARGET[0]/1000, TRUE_TARGET[2]/1000, color='#c0392b', s=300,
            marker='*', zorder=15, label='真实目标', edgecolors='white')

# FY1无人机
fy1 = DRONES['FY1']
ax1.scatter(fy1[0]/1000, fy1[2]/1000, color=PALETTE['FY1'], s=200, marker='D',
            zorder=10, label='FY1', edgecolors='white', linewidths=1.5)
ax1.annotate('FY1', (fy1[0]/1000, fy1[2]/1000), xytext=(fy1[0]/1000+0.5, fy1[2]/1000+0.05),
             fontsize=10, color=PALETTE['FY1'], fontweight='bold')

# 干扰弹弹道
ts_g = np.linspace(0, td1, 80)
ar = np.radians(180.)
vel = np.array([120.*np.cos(ar), 0., 0.])
gx = [(fy1[0] + vel[0]*(1.5+t))/1000 for t in ts_g]
gz = [(fy1[2] - 0.5*G*t**2)/1000 for t in ts_g]
ax1.plot(gx, gz, color='#f39c12', lw=2.2, ls='-', label='干扰弹弹道', zorder=6,
         path_effects=[pe.Stroke(linewidth=4, foreground='#fde68a', alpha=0.6), pe.Normal()])
ax1.scatter(dp1[0]/1000, dp1[2]/1000, color='#f39c12', s=250, marker='o',
            zorder=12, label=f'起爆点', edgecolors='white', linewidths=1.5)
ax1.annotate(f'起爆点\n({dp1[0]/1000:.1f},{dp1[2]/1000:.3f})km',
             (dp1[0]/1000, dp1[2]/1000), xytext=(dp1[0]/1000-3, dp1[2]/1000-0.15),
             fontsize=8.5, color='#d35400',
             arrowprops=dict(arrowstyle='->', color='#d35400', lw=1.2), zorder=15)

# 云团（两个时刻）
circle1 = plt.Circle((dp1[0]/1000, dp1[2]/1000), R_EFF/1000,
                      color='#95a5a6', alpha=0.35, zorder=3, label='烟幕云团')
ax1.add_patch(circle1)
t_mid = (ivs1[0][0] + ivs1[0][1]) / 2 if ivs1 else td1 + 2
cloud_mid_z = dp1[2] - V_SINK * (t_mid - td1)
circle2 = plt.Circle((dp1[0]/1000, cloud_mid_z/1000), R_EFF/1000,
                      color='#7f8c8d', alpha=0.55, zorder=4)
ax1.add_patch(circle2)

# 遮蔽时刻视线
m_mid = missile_pos(m0_M1, t_mid)
ax1.plot([m_mid[0]/1000, TRUE_TARGET[0]/1000],
         [m_mid[2]/1000, TRUE_TARGET[2]/1000],
         color='#9b59b6', lw=1.8, ls=':', alpha=0.8,
         label=f't={t_mid:.1f}s视线（遮蔽中）', zorder=6)
ax1.scatter(m_mid[0]/1000, m_mid[2]/1000, color='#9b59b6', s=120, zorder=11, alpha=0.9,
            edgecolors='white')
ax1.annotate(f't={t_mid:.1f}s', (m_mid[0]/1000, m_mid[2]/1000),
             xytext=(m_mid[0]/1000+2, m_mid[2]/1000+0.1),
             fontsize=8.5, color='#9b59b6',
             arrowprops=dict(arrowstyle='->', color='#9b59b6', lw=1))

ax1.set_xlabel('X 坐标 (km)', fontsize=11)
ax1.set_ylabel('Z 坐标（高度）(km)', fontsize=11)
ax1.set_title('问题1：弹道与遮蔽几何（x-z侧视图）', fontsize=12, fontweight='bold', pad=10)
ax1.legend(loc='lower left', fontsize=8.5, framealpha=0.9, ncol=1)
ax1.set_xlim(-1, 21); ax1.set_ylim(-0.05, 2.3)
ax1.set_facecolor('#f8fbff')

# 右图：距离-时间曲线
ts_full = np.linspace(0, t_arr_M1, 2000)
dists = []
for t in ts_full:
    if t < td1:
        dists.append(np.nan)
        continue
    mt = missile_pos(m0_M1, t)
    cz = dp1[2] - V_SINK*(t - td1)
    cp = np.array([dp1[0], dp1[1], cz])
    dv = TRUE_TARGET - mt; vv = cp - mt
    ds2 = np.dot(dv, dv)
    s_ = np.dot(vv, dv)/max(ds2, 1e-12)
    foot_ = mt + s_*dv
    dists.append(np.linalg.norm(cp - foot_))

dists_arr = np.array([d if d is not None and not np.isnan(d) else np.nan for d in dists])
valid = ~np.isnan(dists_arr)

ax2.plot(ts_full[valid], dists_arr[valid], color=PALETTE['FY1'], lw=2.2,
         label='云团到视线段距离', zorder=5)
ax2.fill_between(ts_full[valid], dists_arr[valid], alpha=0.12, color=PALETTE['FY1'])
ax2.axhline(R_EFF, color=PALETTE['M1'], lw=2, ls='--',
            label=f'有效半径 {R_EFF}m（遮蔽阈值）', zorder=4)

# 遮蔽区间高亮
if ivs1:
    for i, (a, b) in enumerate(ivs1):
        ax2.axvspan(a, b, color=PALETTE['highlight'], alpha=0.5, zorder=3,
                    label=f'有效遮蔽 [{a:.2f},{b:.2f}]s' if i==0 else '')
        # 双箭头标注宽度
        ax2.annotate('', xy=(b, 3), xytext=(a, 3),
                     arrowprops=dict(arrowstyle='<->', color='#8B6914', lw=1.5))
        ax2.text((a+b)/2, 4.5, f'{b-a:.4f}s', ha='center', fontsize=10.5,
                 color='#8B6914', fontweight='bold',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#fef9e7', edgecolor='#f39c12'))

ax2.axvline(td1, color='gray', lw=1.5, ls=':', alpha=0.8,
            label=f'起爆时刻 {td1:.1f}s')
ax2.axvline(t_arr_M1, color='black', lw=1.5, ls='--', alpha=0.5,
            label=f'M1到达 {t_arr_M1:.0f}s')

ax2.set_xlabel('时间 (s)', fontsize=11)
ax2.set_ylabel('云团到瞄准线距离 (m)', fontsize=11)
ax2.set_title('问题1：视线遮蔽时序分析', fontsize=12, fontweight='bold', pad=10)
ax2.legend(fontsize=9, loc='upper right', framealpha=0.9)
ax2.set_ylim(-2, 70); ax2.set_xlim(0, min(30, t_arr_M1))
ax2.set_facecolor('#f8fbff')

plt.suptitle('问题1：固定参数下的弹道计算与遮蔽效果分析', fontsize=14,
             fontweight='bold', y=1.01, color='#2c3e50')
plt.tight_layout()
save_fig('fig04_q1_shielding.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig05_q2_landscape.png — 问题2参数景观（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [3/8] fig05_q2_landscape.png ...")
sys.path.insert(0, os.path.dirname(__file__))

d0_fy1 = DRONES['FY1']
opt_angle, opt_speed = 177.61, 72.39
opt_t_rel, opt_tau_det = 0.29, 2.619

angles = np.linspace(160, 200, 36)
speeds = np.linspace(60, 140, 36)
Z = np.zeros((len(speeds), len(angles)))
for i, spd in enumerate(speeds):
    for j, ang in enumerate(angles):
        rp, dp, td = grenade_traj(d0_fy1, ang, spd, opt_t_rel, opt_tau_det)
        Z[i, j] = compute_coverage(dp, td, 'M1', dt=0.008)[0] if dp[2] > 0 else 0.

# 方向角扫描
angles_scan = np.linspace(155, 205, 80)
cov_q1 = []
cov_q2 = []
for ang in angles_scan:
    rp, dp, td = grenade_traj(d0_fy1, ang, 120., 1.5, 3.6)
    cov_q1.append(compute_coverage(dp, td, 'M1', dt=0.008)[0] if dp[2]>0 else 0.)
    rp, dp, td = grenade_traj(d0_fy1, ang, opt_speed, opt_t_rel, opt_tau_det)
    cov_q2.append(compute_coverage(dp, td, 'M1', dt=0.008)[0] if dp[2]>0 else 0.)

fig = plt.figure(figsize=(15, 6.5), facecolor='white')
gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.38)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])

# 自定义渐变色
cmap = LinearSegmentedColormap.from_list('cov', ['#ecf0f1','#a8d8a8','#2ecc71','#27ae60','#1e8449'], N=256)
cf = ax1.contourf(angles, speeds, Z, levels=20, cmap=cmap, alpha=0.92)
cb = plt.colorbar(cf, ax=ax1, label='遮蔽时长 (s)', pad=0.02, shrink=0.9)
cb.ax.tick_params(labelsize=9)
# 等高线
cs = ax1.contour(angles, speeds, Z, levels=[1.,2.,3.,4.,4.5], colors='#2c3e50',
                 linewidths=0.8, alpha=0.5)
ax1.clabel(cs, fmt='%.1fs', fontsize=8, inline=True)

ax1.scatter(opt_angle, opt_speed, color='#2980b9', s=350, marker='*', zorder=10,
            label=f'最优点 ({opt_angle}°, {opt_speed}m/s)\n遮蔽={Z.max():.2f}s',
            edgecolors='white', linewidths=1.5)
ax1.scatter(180., 120., color='#e67e22', s=180, marker='D', zorder=10,
            label='问题1参数 (180°, 120m/s)', edgecolors='white', linewidths=1.2)
ax1.annotate(f'最优点\n({opt_angle}°,{opt_speed}m/s)', (opt_angle, opt_speed),
             xytext=(opt_angle+4, opt_speed+12),
             fontsize=9, color='#2980b9', fontweight='bold',
             arrowprops=dict(arrowstyle='->', color='#2980b9', lw=1.5),
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#eaf4fb', edgecolor='#2980b9'))

ax1.set_xlabel('飞行方向角 θ (°)', fontsize=11)
ax1.set_ylabel('飞行速度 v (m/s)', fontsize=11)
ax1.set_title('遮蔽时长 f(θ, v) 参数空间热力图\n（固定最优 t_rel 和 τ_det）',
              fontsize=11.5, fontweight='bold', pad=8)
ax1.legend(loc='upper right', fontsize=9, framealpha=0.92)
ax1.set_facecolor('#f8fbff')

# 右图：单因素扫描
ax2.plot(angles_scan, cov_q1, color='#2980b9', lw=2.2, marker='o', markersize=3.5,
         alpha=0.85, label='问题1参数组 (v=120m/s, τ=3.6s)')
ax2.fill_between(angles_scan, cov_q1, alpha=0.1, color='#2980b9')
ax2.plot(angles_scan, cov_q2, color='#e74c3c', lw=2.2, marker='s', markersize=3.5,
         alpha=0.85, label='问题2最优参数组 (v=72.4m/s, τ=2.6s)')
ax2.fill_between(angles_scan, cov_q2, alpha=0.1, color='#e74c3c')
ax2.axvline(180., color='#2980b9', lw=1.5, ls='--', alpha=0.7)
ax2.axvline(opt_angle, color='#e74c3c', lw=1.5, ls='--', alpha=0.7)
ax2.text(180.3, 0.3, 'θ=180°\n(问题1)', fontsize=8.5, color='#2980b9')
ax2.text(opt_angle+0.5, 0.3, f'θ={opt_angle}°\n(最优)', fontsize=8.5, color='#e74c3c')

# 标注峰值
idx_q2 = np.argmax(cov_q2)
ax2.scatter(angles_scan[idx_q2], max(cov_q2), color='#e74c3c', s=120, zorder=10,
            marker='*', edgecolors='white')
ax2.annotate(f'峰值 {max(cov_q2):.2f}s', (angles_scan[idx_q2], max(cov_q2)),
             xytext=(angles_scan[idx_q2]+5, max(cov_q2)-0.4),
             fontsize=9, color='#e74c3c',
             arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=1.2))

ax2.set_xlabel('飞行方向角 θ (°)', fontsize=11)
ax2.set_ylabel('遮蔽时长 (s)', fontsize=11)
ax2.set_title('方向角单因素扫描对比\n两组参数的响应曲线', fontsize=11.5, fontweight='bold', pad=8)
ax2.legend(fontsize=9.5, framealpha=0.9, loc='upper left')
ax2.set_ylim(-0.1, 5.5); ax2.set_facecolor('#f8fbff')

plt.suptitle('问题2：优化目标函数的参数空间分析', fontsize=14,
             fontweight='bold', y=1.01, color='#2c3e50')
plt.tight_layout()
save_fig('fig05_q2_landscape.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig06_q3_timeline.png — 问题3多弹时序（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [4/8] fig06_q3_timeline.png ...")
try:
    from problem2_multi import solve_problem3 as _sp3
    _r3 = _sp3()
    angle3, speed3 = _r3['angle'], _r3['speed']
    grenades3 = _r3['grenades']
    merged3 = _r3['merged_intervals']
    total3 = _r3['total_coverage']
except Exception as e:
    print(f"    (使用近似值: {e})")
    angle3, speed3, total3 = 179.15, 124.08, 5.9461
    grenades3 = [
        {'t_det':3.598,'coverage':3.677,'intervals':[(3.598,7.275)]},
        {'t_det':5.232,'coverage':2.531,'intervals':[(5.232,7.763)]},
        {'t_det':6.558,'coverage':0.000,'intervals':[]},
    ]
    merged3 = [(3.598, 9.544)]

fig = plt.figure(figsize=(14, 8), facecolor='white')
gs = gridspec.GridSpec(2, 1, figure=fig, hspace=0.45, height_ratios=[2.2, 1])
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])

gren_colors = ['#3498db', '#e74c3c', '#2ecc71']
gren_labels = ['第1枚干扰弹', '第2枚干扰弹', '第3枚干扰弹']

# 上图
for idx, g in enumerate(grenades3[:3]):
    ivs = g.get('intervals', [])
    t_d = g['t_det']
    c_g = g['coverage']
    y = 3 - idx
    color = gren_colors[idx]

    # 有效时窗背景
    t_end = min(t_d + T_EFF, t_arr_M1)
    ax1.barh(y, t_end - t_d, left=t_d, height=0.55,
             color=color, alpha=0.1, zorder=1)
    ax1.barh(y, t_end - t_d, left=t_d, height=0.55,
             color='none', edgecolor=color, linewidth=0.8, alpha=0.5, zorder=1)

    # 遮蔽区间
    for a, b in ivs:
        ax1.barh(y, b-a, left=a, height=0.52, color=color, alpha=0.88, zorder=3,
                 edgecolor='white', linewidth=0.5)
        if b-a > 0.1:
            ax1.text((a+b)/2, y, f'{b-a:.2f}s', ha='center', va='center',
                     fontsize=9.5, color='white', fontweight='bold', zorder=5)

    # 起爆标记
    ax1.axvline(t_d, color=color, lw=1.3, ls=':', alpha=0.65, zorder=2)
    ax1.text(t_d, y+0.33, f'起爆\n{t_d:.2f}s', ha='center', fontsize=7.5,
             color=color, fontweight='bold')

    # 右侧注释
    ax1.text(t_arr_M1*1.005, y, f'{gren_labels[idx]}\n单弹 {c_g:.3f}s',
             va='center', fontsize=9, color=color, fontweight='bold')

# 并集行
y_u = 0
for a, b in merged3:
    ax1.barh(y_u, b-a, left=a, height=0.52, color='#e67e22', alpha=0.9,
             zorder=3, edgecolor='white', linewidth=0.5)
    ax1.text((a+b)/2, y_u, f'{b-a:.2f}s', ha='center', va='center',
             fontsize=9.5, color='white', fontweight='bold', zorder=5)
ax1.text(t_arr_M1*1.005, y_u, f'并集总计\n{total3:.4f}s', va='center',
         fontsize=9.5, color='#e67e22', fontweight='bold')

ax1.axvline(t_arr_M1, color='#2c3e50', lw=2, ls='--', alpha=0.7, zorder=4)
ax1.text(t_arr_M1-1, 3.7, f'M1到达\n{t_arr_M1:.1f}s', ha='right',
         fontsize=9, color='#2c3e50', fontweight='bold')

ax1.set_yticks([0, 1, 2, 3])
ax1.set_yticklabels(['并集（总遮蔽）', '第1枚', '第2枚', '第3枚'], fontsize=11)
ax1.set_xlabel('时间 (s)', fontsize=11)
ax1.set_xlim(-0.5, t_arr_M1 + 5)
ax1.set_title(f'FY1 序贯投放3枚干扰弹（θ={angle3:.2f}°，v={speed3:.2f}m/s）\n'
              f'并集总遮蔽 = {total3:.4f}s，区间 {[(f"{a:.2f}",f"{b:.2f}") for a,b in merged3]}',
              fontsize=12, fontweight='bold', pad=8)
ax1.set_facecolor('#f8fbff')
ax1.spines['left'].set_visible(False)
ax1.tick_params(left=False)

# 下图：柱状图
single_covs = [g['coverage'] for g in grenades3[:3]]
bar_labels = ['第1枚', '第2枚', '第3枚']
bars = ax2.bar(bar_labels, single_covs, color=gren_colors, alpha=0.85,
               edgecolor='white', linewidth=1.2, width=0.55)
ax2.axhline(total3, color='#e67e22', lw=2, ls='--', label=f'并集总计 {total3:.4f}s',
            zorder=4)
for bar, val in zip(bars, single_covs):
    ax2.text(bar.get_x()+bar.get_width()/2, val+0.05, f'{val:.3f}s',
             ha='center', va='bottom', fontsize=11, fontweight='bold',
             color=bar.get_facecolor())
ax2.set_ylabel('单弹遮蔽时长 (s)', fontsize=11)
ax2.set_title('各枚干扰弹的单独遮蔽时长对比（并集＜各弹之和，因存在区间重叠）',
              fontsize=11, fontweight='bold', pad=5)
ax2.legend(fontsize=10.5, loc='upper right', framealpha=0.9)
ax2.set_ylim(0, max(single_covs)*1.35+0.3)
ax2.set_facecolor('#f8fbff')

plt.suptitle('问题3：单机多弹序贯投放策略时序分析', fontsize=14,
             fontweight='bold', y=1.01, color='#2c3e50')
save_fig('fig06_q3_timeline.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig07_q4_timeline.png — 问题4多机协同时序（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [5/8] fig07_q4_timeline.png ...")
try:
    from problem2_multi import solve_problem4 as _sp4
    _r4 = _sp4()
    drones4 = _r4['drones']
    merged4 = _r4['merged_intervals']
    total4 = _r4['total_coverage']
except Exception as e:
    print(f"    (使用近似值: {e})")
    drones4 = [
        {'drone':'FY1','t_det':3.721,'coverage':4.605,'intervals':[(3.721,8.326)]},
        {'drone':'FY2','t_det':0.928,'coverage':0.000,'intervals':[]},
        {'drone':'FY3','t_det':29.593,'coverage':4.236,'intervals':[(29.593,33.829)]},
    ]
    merged4 = [(3.721,8.326),(29.593,33.829)]
    total4 = 8.8405

fig = plt.figure(figsize=(14, 8), facecolor='white')
gs = gridspec.GridSpec(2, 1, figure=fig, hspace=0.45, height_ratios=[2.2, 1])
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])

drone_colors4 = [PALETTE['FY1'], PALETTE['FY2'], PALETTE['FY3']]

for idx, d in enumerate(drones4[:3]):
    ivs = d.get('intervals', [])
    t_d = d['t_det']
    c_d = d['coverage']
    dn = d['drone']
    y = 3 - idx
    color = drone_colors4[idx]

    t_end = min(t_d + T_EFF, t_arr_M1)
    ax1.barh(y, t_end-t_d, left=t_d, height=0.55, color=color, alpha=0.1, zorder=1)
    ax1.barh(y, t_end-t_d, left=t_d, height=0.55, color='none',
             edgecolor=color, linewidth=0.8, alpha=0.4, zorder=1)

    for a, b in ivs:
        ax1.barh(y, b-a, left=a, height=0.52, color=color, alpha=0.88, zorder=3,
                 edgecolor='white', linewidth=0.5)
        if b-a > 0.1:
            ax1.text((a+b)/2, y, f'{b-a:.2f}s', ha='center', va='center',
                     fontsize=9.5, color='white', fontweight='bold', zorder=5)

    ax1.axvline(t_d, color=color, lw=1.3, ls=':', alpha=0.65, zorder=2)
    note = '（无遮蔽贡献）' if c_d == 0 else f'遮蔽 {c_d:.3f}s'
    ax1.text(t_arr_M1*1.005, y, f'{dn}\n{note}',
             va='center', fontsize=9, color=color, fontweight='bold')

# 并集
y_u = 0
for a, b in merged4:
    ax1.barh(y_u, b-a, left=a, height=0.52, color='#c0392b', alpha=0.9, zorder=3,
             edgecolor='white', linewidth=0.5)
    ax1.text((a+b)/2, y_u, f'{b-a:.2f}s', ha='center', va='center',
             fontsize=9.5, color='white', fontweight='bold', zorder=5)
ax1.text(t_arr_M1*1.005, y_u, f'并集总计\n{total4:.4f}s', va='center',
         fontsize=9.5, color='#c0392b', fontweight='bold')

ax1.axvline(t_arr_M1, color='#2c3e50', lw=2, ls='--', alpha=0.7, zorder=4)
ax1.text(t_arr_M1-1, 3.7, f'M1到达\n{t_arr_M1:.1f}s', ha='right',
         fontsize=9, color='#2c3e50', fontweight='bold')

# 标注间隙
if len(merged4) >= 2:
    gap_start = merged4[0][1]
    gap_end = merged4[1][0]
    ax1.annotate('', xy=(gap_end, -0.3), xytext=(gap_start, -0.3),
                 arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
    ax1.text((gap_start+gap_end)/2, -0.55, f'遮蔽间隙\n{gap_end-gap_start:.1f}s',
             ha='center', fontsize=8.5, color='gray', style='italic')

ax1.set_yticks([0, 1, 2, 3])
ax1.set_yticklabels(['并集（总遮蔽）', 'FY1', 'FY2', 'FY3'], fontsize=11)
ax1.set_xlabel('时间 (s)', fontsize=11)
ax1.set_xlim(-1, t_arr_M1 + 5)
ax1.set_title(f'FY1+FY2+FY3 协同拦截 M1 时序\n并集总遮蔽 = {total4:.4f}s'
              f'（两段不连续：早期近端 + 晚期远端）',
              fontsize=12, fontweight='bold', pad=8)
ax1.set_facecolor('#f8fbff')
ax1.spines['left'].set_visible(False)
ax1.tick_params(left=False)
ax1.set_ylim(-0.8, 3.8)

# 下图
single_covs4 = [d['coverage'] for d in drones4[:3]]
bars4 = ax2.bar(['FY1', 'FY2', 'FY3'], single_covs4, color=drone_colors4,
                alpha=0.85, edgecolor='white', linewidth=1.2, width=0.45)
ax2.axhline(total4, color='#c0392b', lw=2, ls='--',
            label=f'并集总计 {total4:.4f}s（两段不重叠）', zorder=4)
for bar, val in zip(bars4, single_covs4):
    label = f'{val:.3f}s' if val > 0 else '0s（无贡献）'
    ax2.text(bar.get_x()+bar.get_width()/2, val+0.05, label,
             ha='center', va='bottom', fontsize=11, fontweight='bold',
             color=bar.get_facecolor())
ax2.annotate('FY2位置偏离M1\n轨迹平面，无法\n有效拦截',
             xy=(1, 0.1), xytext=(1.6, 2.5),
             fontsize=8.5, color=PALETTE['FY2'], style='italic',
             arrowprops=dict(arrowstyle='->', color=PALETTE['FY2'], lw=1.2),
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#eafaf1', edgecolor=PALETTE['FY2']))
ax2.set_ylabel('单机遮蔽时长 (s)', fontsize=11)
ax2.set_title('各无人机单独贡献对比', fontsize=11, fontweight='bold', pad=5)
ax2.legend(fontsize=10, loc='upper right', framealpha=0.9)
ax2.set_ylim(0, max(single_covs4)*1.5+0.5)
ax2.set_facecolor('#f8fbff')

plt.suptitle('问题4：多机协同时序互补分析（早期+晚期双段接力）',
             fontsize=14, fontweight='bold', y=1.01, color='#2c3e50')
save_fig('fig07_q4_timeline.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig08_q5_summary.png — 问题5分配方案汇总（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [6/8] fig08_q5_summary.png ...")
fig = plt.figure(figsize=(16, 7.5), facecolor='white')
gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.38)
ax_left = fig.add_subplot(gs[0])
ax_right = fig.add_subplot(gs[1])

# 左图：分配拓扑图
ax_left.set_xlim(0, 10); ax_left.set_ylim(-0.8, 10.5)
ax_left.axis('off')
ax_left.set_title('无人机—导弹分配拓扑图', fontsize=13, fontweight='bold', pad=10, color='#2c3e50')

# 无人机节点位置
dn_pos = {'FY1':(2,8.5),'FY2':(2,6.5),'FY3':(2,4.5),'FY4':(2,2.5),'FY5':(2,0.5)}
mn_pos = {'M1':(7.5,7.5),'M2':(7.5,4.5),'M3':(7.5,1.5)}
m_assign_color = {'M1':PALETTE['M1'],'M2':PALETTE['M2'],'M3':PALETTE['M3']}

# 连线（先画，在节点之下）
for dn,(dx,dy) in dn_pos.items():
    mn = Q5_assign[dn]
    mx,my = mn_pos[mn]
    color = m_assign_color[mn]
    ax_left.annotate('', xy=(mx-0.55,my), xytext=(dx+0.55,dy),
                     arrowprops=dict(arrowstyle='->', color=color, lw=2.0,
                                     connectionstyle='arc3,rad=0.12'),
                     zorder=2)

# 无人机节点
for dn,(dx,dy) in dn_pos.items():
    mn = Q5_assign[dn]
    c = PALETTE[dn]
    circle = plt.Circle((dx,dy), 0.58, color=c, zorder=5, alpha=0.92,
                         linewidth=2, edgecolor='white')
    ax_left.add_patch(circle)
    ax_left.text(dx, dy+0.05, dn, ha='center', va='center',
                 fontsize=12, color='white', fontweight='bold', zorder=10)
    ax_left.text(dx-1.5, dy, f'→{mn}', ha='center', va='center',
                 fontsize=10, color=m_assign_color[mn], fontweight='bold')

# 导弹节点
for mn,(mx,my) in mn_pos.items():
    c = m_assign_color[mn]
    cov = Q5_detail[mn]['cov']
    fancy = FancyBboxPatch((mx-1.0,my-0.55), 2.0, 1.1,
                           boxstyle='round,pad=0.08', facecolor=c,
                           edgecolor='white', linewidth=2, zorder=5, alpha=0.88)
    ax_left.add_patch(fancy)
    ax_left.text(mx, my+0.15, mn, ha='center', va='center',
                 fontsize=13, color='white', fontweight='bold', zorder=10)
    ax_left.text(mx, my-0.22, f'遮蔽 {cov:.2f}s', ha='center', va='center',
                 fontsize=9.5, color='white', zorder=10)

# 图例说明
ax_left.text(5.0,10.0,'→ 表示无人机被分配拦截对应导弹', ha='center', fontsize=9.5,
             color='#555', style='italic',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#f0f0f0', edgecolor='#ccc'))
ax_left.text(2.0,10.0,'无人机\n初始位置', ha='center', fontsize=9.5, color='#555', style='italic')
ax_left.text(7.5,10.0,'目标导弹\n（遮蔽时长）', ha='center', fontsize=9.5, color='#555', style='italic')

# 右图：三导弹遮蔽时序
t_arrivals = {mn: missile_arrival(MISSILES[mn]) for mn in ['M1','M2','M3']}
m_colors_r = [PALETTE['M1'], PALETTE['M2'], PALETTE['M3']]
y_positions = [3, 2, 1]

for idx, mn in enumerate(['M1','M2','M3']):
    y = y_positions[idx]
    color = m_colors_r[idx]
    detail = Q5_detail[mn]
    t_arr_mn = t_arrivals[mn]

    # 背景
    ax_right.barh(y, t_arr_mn, left=0, height=0.55, color=color, alpha=0.08, zorder=1)
    ax_right.barh(y, t_arr_mn, left=0, height=0.55, color='none',
                  edgecolor=color, linewidth=0.7, alpha=0.3, zorder=1)

    for a, b in detail['merged']:
        ax_right.barh(y, b-a, left=a, height=0.52, color=color, alpha=0.88, zorder=3,
                      edgecolor='white', linewidth=0.5)
        ax_right.text((a+b)/2, y, f'{b-a:.2f}s', ha='center', va='center',
                      fontsize=8.5, color='white', fontweight='bold', zorder=5)

    ax_right.axvline(t_arr_mn, color=color, lw=1.8, ls='--', alpha=0.6, zorder=2)
    ax_right.text(t_arr_mn+0.3, y+0.3, f'{mn}到达\n{t_arr_mn:.0f}s',
                  fontsize=8.5, color=color, fontweight='bold')

ax_right.set_yticks(y_positions)
ax_right.set_yticklabels(
    [f'{mn}\n（共{Q5_detail[mn]["cov"]:.2f}s）' for mn in ['M1','M2','M3']],
    fontsize=11)
ax_right.set_xlabel('时间 (s)', fontsize=11)
total_q5 = sum(Q5_detail[m]['cov'] for m in ['M1','M2','M3'])
ax_right.set_title(f'三导弹遮蔽时序甘特图\n总遮蔽时长合计 = {total_q5:.3f}s',
                   fontsize=12, fontweight='bold', pad=8)
ax_right.set_xlim(-1, max(t_arrivals.values())+5)
ax_right.set_facecolor('#f8fbff')
ax_right.spines['left'].set_visible(False)
ax_right.tick_params(left=False)
ax_right.set_ylim(0.3, 3.8)

# 汇总框
ax_right.text(0.02, 0.05,
              f'M1: {Q5_detail["M1"]["cov"]:.2f}s\nM2: {Q5_detail["M2"]["cov"]:.2f}s\n'
              f'M3: {Q5_detail["M3"]["cov"]:.2f}s\n───────\n总计: {total_q5:.2f}s',
              transform=ax_right.transAxes, ha='left', va='bottom',
              fontsize=10.5, fontweight='bold', color='#2c3e50',
              bbox=dict(boxstyle='round,pad=0.6', facecolor='#fffde7',
                        edgecolor='#f39c12', linewidth=1.5))

plt.suptitle('问题5：5机×3弹×3导弹全系统最优分配方案',
             fontsize=14, fontweight='bold', y=1.01, color='#2c3e50')
save_fig('fig08_q5_summary.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig09_comparison.png — 各问题遮蔽时长综合对比（美化版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [7/8] fig09_comparison.png ...")
fig = plt.figure(figsize=(15, 6.5), facecolor='white')
gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.42)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])

labels = ['Q1\n1弹固定', 'Q2\n1弹优化', 'Q3\n3弹序贯', 'Q4\n3机协同',
          'Q5:M1', 'Q5:M2', 'Q5:M3', 'Q5\n总计']
values = [1.4055, 4.7085, 5.9461, 8.8405, 12.771, 4.054, 3.425, 20.250]
bar_colors = ['#95a5a6','#3498db','#2ecc71','#e67e22',
              '#e74c3c','#e67e22','#8e44ad','#c0392b']

bars = ax1.bar(labels, values, color=bar_colors, alpha=0.87,
               edgecolor='white', linewidth=1.5, width=0.6)
for bar, val in zip(bars, values):
    ax1.text(bar.get_x()+bar.get_width()/2, val+0.2,
             f'{val:.2f}s', ha='center', va='bottom', fontsize=9,
             fontweight='bold', color=bar.get_facecolor())

# 分组标注
ax1.axvline(3.5, color='#bdc3c7', lw=1.5, ls='--', alpha=0.7)
ax1.axvline(7.45, color='#bdc3c7', lw=1.5, ls='--', alpha=0.7)
ax1.text(1.5, 22.5, '问题1-4\n（单目标M1）', ha='center', fontsize=9, color='#7f8c8d', style='italic')
ax1.text(6.0, 22.5, '问题5\n（三导弹系统）', ha='center', fontsize=9, color='#7f8c8d', style='italic')

ax1.set_ylabel('遮蔽时长 (s)', fontsize=11)
ax1.set_title('各问题遮蔽时长汇总对比', fontsize=13, fontweight='bold', pad=8)
ax1.set_ylim(0, 26); ax1.set_facecolor('#f8fbff')

# 右图：提升幅度
improvements = {
    '参数优化\n(Q1→Q2)': (4.7085/1.4055-1)*100,
    '增加弹数\n(Q2→Q3)': (5.9461/4.7085-1)*100,
    '多机协同\n(Q3→Q4)': (8.8405/5.9461-1)*100,
}
imp_labels = list(improvements.keys())
imp_vals = list(improvements.values())
imp_colors = ['#3498db','#2ecc71','#e67e22']

bars2 = ax2.bar(imp_labels, imp_vals, color=imp_colors, alpha=0.87,
                edgecolor='white', linewidth=1.5, width=0.45)
for bar, val in zip(bars2, imp_vals):
    ax2.text(bar.get_x()+bar.get_width()/2, val+0.5,
             f'+{val:.1f}%', ha='center', va='bottom', fontsize=12,
             fontweight='bold', color=bar.get_facecolor())

# 策略说明
strategies = ['飞行方向/速度/\n时机联合优化', '时间错开形成\n接力遮蔽', '地理互补\n空间分工']
for bar, strat, c in zip(bars2, strategies, imp_colors):
    ax2.text(bar.get_x()+bar.get_width()/2, 2, strat,
             ha='center', va='bottom', fontsize=8.5, color='white',
             fontweight='bold', zorder=5)

ax2.set_ylabel('遮蔽时长提升幅度 (%)', fontsize=11)
ax2.set_title('各优化步骤的遮蔽时长提升幅度', fontsize=13, fontweight='bold', pad=8)
ax2.set_ylim(0, 280); ax2.set_facecolor('#f8fbff')

plt.suptitle('策略递进优化效果综合分析', fontsize=14,
             fontweight='bold', y=1.01, color='#2c3e50')
save_fig('fig09_comparison.png')

# ═══════════════════════════════════════════════════════════════════════════
# fig_sensitivity.png — 敏感性分析（美化重生成版）
# ═══════════════════════════════════════════════════════════════════════════
print("  [8/8] fig_sensitivity.png ...")

def cov_q(angle, speed, t_rel, tau_det, mn='M1'):
    d0 = DRONES['FY1']
    rp, dp, td = grenade_traj(d0, angle, speed, t_rel, tau_det)
    if dp[2] <= 0: return 0.
    return compute_coverage(dp, td, mn, dt=0.005)[0]

BASE_Q1 = dict(angle=180., speed=120., t_rel=1.5, tau_det=3.6)
BASE_Q2 = dict(angle=177.61, speed=72.39, t_rel=0.29, tau_det=2.619)
base1 = cov_q(**BASE_Q1)
base2 = cov_q(**BASE_Q2)

params_scan = [
    ('Q1：飞行速度 v (m/s)',  'speed',   np.arange(70,141,4),   BASE_Q1, base1, '#3498db'),
    ('Q1：投放延迟 t_rel (s)', 't_rel',  np.arange(0,6,0.25),   BASE_Q1, base1, '#e74c3c'),
    ('Q1：引信延迟 τ_det (s)','tau_det', np.arange(0.5,9,0.3),  BASE_Q1, base1, '#2ecc71'),
    ('Q2：飞行方向 θ (°)',    'angle',   np.arange(155,205,2.5),BASE_Q2, base2, '#e67e22'),
    ('Q2：飞行速度 v (m/s)',  'speed',   np.arange(60,141,4),   BASE_Q2, base2, '#9b59b6'),
    ('Q2：引信延迟 τ_det (s)','tau_det', np.arange(0.5,7,0.25), BASE_Q2, base2, '#16a085'),
]

fig, axes = plt.subplots(2, 3, figsize=(16, 10), facecolor='white')
fig.suptitle('敏感性分析：关键参数对遮蔽时长的单因素影响',
             fontsize=15, fontweight='bold', y=1.01, color='#2c3e50')
axes = axes.flatten()

for ax, (title, key, vals, base_p, base_c, color) in zip(axes, params_scan):
    cvs = np.array([cov_q(**{**base_p, key:v}) for v in vals])
    ax.plot(vals, cvs, color=color, lw=2.2, marker='o', markersize=4, alpha=0.9, zorder=5)
    ax.fill_between(vals, cvs, alpha=0.15, color=color)
    ax.axhline(base_c, color='#c0392b', lw=1.8, ls='--', alpha=0.85,
               label=f'基准值 {base_c:.3f}s', zorder=4)

    # 最优点
    max_idx = np.argmax(cvs)
    ax.scatter(vals[max_idx], cvs[max_idx], color='#c0392b', s=130, zorder=10,
               marker='*', edgecolors='white', linewidths=1,
               label=f'最大 {cvs[max_idx]:.3f}s @{vals[max_idx]:.2f}')
    # 基准点
    base_val = base_p[key]
    base_cov_at_base = cov_q(**base_p)
    ax.axvline(base_val, color='#7f8c8d', lw=1.2, ls=':', alpha=0.7)
    ax.scatter(base_val, base_cov_at_base, color='#7f8c8d', s=80, zorder=8,
               marker='D', edgecolors='white')

    ax.set_title(title, fontsize=11.5, fontweight='bold', pad=5, color='#2c3e50')
    ax.set_ylabel('遮蔽时长 (s)', fontsize=10)
    ax.legend(fontsize=8.5, framealpha=0.9, loc='upper right')
    ax.set_ylim(-0.1, max(cvs)*1.28+0.2)
    ax.set_facecolor('#f8fbff')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.3, linestyle='--')

plt.tight_layout()
save_fig('fig_sensitivity.png')

# ─────────────────────────────────────────────────────────────────────────
print("\n" + "="*55)
print("  ✓ 全部图表生成完毕")
imgs = [f for f in os.listdir(IMG_DIR) if f.endswith('.png')]
for f in sorted(imgs):
    size_kb = os.path.getsize(os.path.join(IMG_DIR, f)) // 1024
    print(f"  {f:42s} {size_kb:5d} KB")
print("="*55)
