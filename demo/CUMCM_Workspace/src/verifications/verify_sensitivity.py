"""verify_sensitivity.py — 数值稳定性检查"""
import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),'../models'))
from problem1_direct import compute_coverage, grenade_traj, DRONES

PASS,FAIL="✓ PASS","✗ FAIL"
results=[]
def check(name,cond,detail=""):
    s=PASS if cond else FAIL; results.append((name,s,detail))
    print(f"  {s}  {name}"+(f": {detail}" if detail else ""))

# 基准
rp,dp,td=grenade_traj(DRONES['FY1'],180.,120.,1.5,3.6)
c_base,_=compute_coverage(dp,td,'M1',dt=0.001)
print(f"  基准遮蔽时长: {c_base:.4f}s")

# dt 收敛性
print("\n=== 时间步长收敛性 ===")
for dt in [0.01,0.005,0.002,0.001,0.0005]:
    c,_=compute_coverage(dp,td,'M1',dt=dt)
    diff=abs(c-c_base)
    check(f"dt={dt:.4f}: |误差|<0.05s",diff<0.05,f"c={c:.4f},err={diff:.4f}")

# 参数扰动稳定性（±1%扰动不改变遮蔽方向）
print("\n=== 参数±1%扰动稳定性（问题2最优解）===")
BASE={'angle':177.61,'speed':72.39,'t_rel':0.29,'tau_det':2.619}
def gt(p): return grenade_traj(DRONES['FY1'],p['angle'],p['speed'],p['t_rel'],p['tau_det'])
rp2,dp2,td2=gt(BASE)
c0,_=compute_coverage(dp2,td2,'M1',dt=0.002)
print(f"  基准: {c0:.4f}s")
for key,eps in [('angle',1.78),('speed',0.72),('t_rel',0.003),('tau_det',0.026)]:
    pp={**BASE,key:BASE[key]+eps}
    _,dp_p,td_p=gt(pp)
    cp,_=compute_coverage(dp_p,td_p,'M1',dt=0.002)
    pm={**BASE,key:BASE[key]-eps}
    _,dp_m,td_m=gt(pm)
    cm,_=compute_coverage(dp_m,td_m,'M1',dt=0.002)
    check(f"{key}±1%: 遮蔽均>0",cp>0 and cm>0,f"+:{cp:.4f},-:{cm:.4f}")

print("\n"+"="*50)
print("  VERIFICATION REPORT — sensitivity")
print("="*50)
passed=sum(1 for _,s,_ in results if s==PASS)
for n,s,d in results: print(f"  {s}  {n}")
print(f"\n  总计: {passed}/{len(results)} PASS")
print("="*50)
if passed<len(results): sys.exit(1)
else: print("  ✓ 全部通过")
