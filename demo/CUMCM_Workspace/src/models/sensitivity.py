"""
sensitivity.py — 敏感性分析
对问题1和问题2的关键参数进行单因素扰动分析
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from problem1_direct import compute_coverage, grenade_traj, DRONES

G=9.8; V_SINK=3.; R_EFF=10.; T_EFF=20.; V_MISSILE=300.

# 基准参数（问题1）
BASE_Q1={'angle':180.,'speed':120.,'t_rel':1.5,'tau_det':3.6}
det_base_q1=grenade_traj(DRONES['FY1'],180.,120.,1.5,3.6)

# 基准参数（问题2最优）
BASE_Q2={'angle':177.61,'speed':72.39,'t_rel':0.29,'tau_det':2.619}

def cov(angle,speed,t_rel,tau_det,mn='M1'):
    rp,dp,td=grenade_traj(DRONES['FY1'],angle,speed,t_rel,tau_det)
    if dp[2]<=0: return 0.
    c,_=compute_coverage(dp,td,mn,dt=0.002)
    return c

print("="*65)
print("  敏感性分析 — 问题1基准参数")
print("="*65)
base1=cov(**BASE_Q1)
print(f"  基准遮蔽时长: {base1:.4f}s\n")

params_q1=[
    ('飞行速度v(m/s)',   'speed',   np.arange(80,141,10)),
    ('投放延迟t_rel(s)', 't_rel',   np.arange(0,5.1,0.5)),
    ('引信延迟tau(s)',   'tau_det', np.arange(1,8.1,0.5)),
]
for label,key,vals in params_q1:
    print(f"  [{label}]")
    print(f"  {'值':>10}  {'遮蔽时长':>10}  {'变化%':>8}")
    for v in vals:
        p={**BASE_Q1,key:v}
        c=cov(**p)
        pct=(c-base1)/base1*100 if base1>0 else 0
        print(f"  {v:>10.2f}  {c:>10.4f}  {pct:>+8.1f}%")
    print()

print("="*65)
print("  敏感性分析 — 问题2最优参数")
print("="*65)
base2=cov(**BASE_Q2)
print(f"  基准遮蔽时长: {base2:.4f}s\n")

params_q2=[
    ('飞行方向θ(°)',    'angle',   np.arange(160,200,5)),
    ('飞行速度v(m/s)',  'speed',   np.arange(70,141,10)),
    ('引信延迟tau(s)',  'tau_det', np.arange(1,6.1,0.5)),
]
for label,key,vals in params_q2:
    print(f"  [{label}]")
    print(f"  {'值':>10}  {'遮蔽时长':>10}  {'变化%':>8}")
    for v in vals:
        p={**BASE_Q2,key:v}
        c=cov(**p)
        pct=(c-base2)/base2*100 if base2>0 else 0
        print(f"  {v:>10.2f}  {c:>10.4f}  {pct:>+8.1f}%")
    print()

# ── 生成图表 ──────────────────────────────────────────────────────────────
try:
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig,axes=plt.subplots(2,3,figsize=(15,8))
    fig.suptitle('Sensitivity Analysis: Coverage Time vs Parameters',fontsize=13)
    axes=axes.flatten()

    all_params=[
        ('Q1:Speed(m/s)',    'speed',   np.arange(70,141,5),  BASE_Q1, base1),
        ('Q1:t_rel(s)',      't_rel',   np.arange(0,6,0.25),   BASE_Q1, base1),
        ('Q1:tau_det(s)',    'tau_det', np.arange(0.5,9,0.5),  BASE_Q1, base1),
        ('Q2:Direction(deg)','angle',   np.arange(150,210,5),  BASE_Q2, base2),
        ('Q2:Speed(m/s)',    'speed',   np.arange(70,141,5),   BASE_Q2, base2),
        ('Q2:tau_det(s)',    'tau_det', np.arange(0.5,7,0.5),  BASE_Q2, base2),
    ]
    for ax,(title,key,vals,base_p,base_c) in zip(axes,all_params):
        cvs=[cov(**{**base_p,key:v}) for v in vals]
        ax.plot(vals,cvs,'b-o',markersize=4)
        ax.axhline(base_c,color='r',linestyle='--',label=f'base={base_c:.2f}s')
        ax.set_title(title,fontsize=10)
        ax.set_ylabel('Coverage (s)')
        ax.legend(fontsize=8); ax.grid(True,alpha=0.3)

    plt.tight_layout()
    out=os.path.join(os.path.dirname(__file__),'../../latex/images/fig_sensitivity.png')
    plt.savefig(out,dpi=150,bbox_inches='tight')
    plt.close()
    print(f"  [图像] 保存至 {out}")
except Exception as e:
    print(f"  [图像] 跳过: {e}")

print("\n  ✓ 敏感性分析完成")
