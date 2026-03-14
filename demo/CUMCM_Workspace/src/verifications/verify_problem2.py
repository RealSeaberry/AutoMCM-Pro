"""
verify_problem2.py — 验证问题3 & 问题4（直接调用求解函数）
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),'../models'))
from problem2_multi import (compute_coverage, grenade_traj, missile_arrival,
                             union_coverage, DRONES, MISSILES, V_MIN, V_MAX,
                             T_EFF, INTERVAL_MIN, G,
                             solve_problem3, solve_problem4)

PASS,FAIL="✓ PASS","✗ FAIL"
results=[]
def check(name,cond,detail=""):
    s=PASS if cond else FAIL
    results.append((name,s,detail))
    print(f"  {s}  {name}"+(f": {detail}" if detail else ""))

print("  [重新求解问题3+4以获取精确参数...]")
res3=solve_problem3()
res4=solve_problem4()

# ── 验证1：问题3 ────────────────────────────────────────────────
print("\n=== 验证1：问题3 物理约束 ===")
angle3,speed3=res3['angle'],res3['speed']
d0=DRONES['FY1']
t_arr_m1=missile_arrival(MISSILES['M1'])

check("速度在范围[70,140]",V_MIN<=speed3<=V_MAX,f"{speed3:.2f}m/s")
check("总遮蔽>问题2单弹(4.7s)",res3['total_coverage']>4.7,f"{res3['total_coverage']:.4f}s")

# 验证每枚弹的物理参数
all_ivs3=[]
t_releases3=[]
for i,g in enumerate(res3['grenades'],1):
    dp,td=g['det_pos'],g['t_det']
    check(f"弹{i}起爆点z>0",dp[2]>0,f"z={dp[2]:.2f}m")
    check(f"弹{i}起爆点z<drone_altitude",dp[2]<d0[2]+1,f"z={dp[2]:.2f}<{d0[2]}")
    check(f"弹{i}t_det<t_arr",td<t_arr_m1,f"{td:.3f}<{t_arr_m1:.2f}")
    _,ivs=compute_coverage(dp,td,'M1',dt=0.0005)
    all_ivs3.append(ivs)

# 验证间隔约束（从params重建）
params3=res3['params']
t1,dt12,dt23=params3[2],params3[4],params3[6]
t2=t1+dt12; t3=t2+dt23
check("弹1→2间隔≥1s",dt12>=INTERVAL_MIN-0.05,f"间隔={dt12:.3f}s")
check("弹2→3间隔≥1s",dt23>=INTERVAL_MIN-0.05,f"间隔={dt23:.3f}s")

total3_verify,merged3=union_coverage(all_ivs3)
check("总遮蔽时长（验证重算≈原值）",
      abs(total3_verify-res3['total_coverage'])<0.1,
      f"{total3_verify:.4f}≈{res3['total_coverage']:.4f}")
check("有效遮蔽区间存在",len(merged3)>0,f"{len(merged3)}个区间")
for a,b in merged3:
    check(f"区间[{a:.2f},{b:.2f}]≤t_arr",b<=t_arr_m1+0.01,f"{b:.3f}≤{t_arr_m1:.2f}")

# ── 验证2：问题4 ────────────────────────────────────────────────
print("\n=== 验证2：问题4 物理约束 ===")
check("总遮蔽>问题3(3弹)",res4['total_coverage']>res3['total_coverage'],
      f"{res4['total_coverage']:.4f}>{res3['total_coverage']:.4f}")
check("总遮蔽>5s",res4['total_coverage']>5.0,f"{res4['total_coverage']:.4f}s")

for d in res4['drones']:
    dn,ang,spd,dp,td=d['drone'],d['angle'],d['speed'],d['det_pos'],d['t_det']
    check(f"{dn}速度在范围",V_MIN<=spd<=V_MAX,f"{spd:.2f}m/s")
    check(f"{dn}起爆点z>0",dp[2]>0,f"z={dp[2]:.2f}m")
    check(f"{dn}起爆点z<原高度",dp[2]<DRONES[dn][2]+1,f"z={dp[2]:.2f}")
    check(f"{dn}t_det<t_arr",td<t_arr_m1,f"{td:.3f}<{t_arr_m1:.2f}")

# 独立重算总遮蔽
all_ivs4=[d['intervals'] for d in res4['drones']]
total4_verify,merged4=union_coverage(all_ivs4)
check("总遮蔽（验证重算≈原值）",abs(total4_verify-res4['total_coverage'])<0.1,
      f"{total4_verify:.4f}≈{res4['total_coverage']:.4f}")
for a,b in merged4:
    check(f"Q4区间[{a:.2f},{b:.2f}]≤t_arr",b<=t_arr_m1+0.01,f"{b:.3f}≤{t_arr_m1:.2f}")

# ── 验证3：单调性 ─────────────────────────────────────────────
print("\n=== 验证3：遮蔽时长单调性 ===")
cov_q2=4.7085
check("Q3≥Q2(单弹)",res3['total_coverage']>=cov_q2-0.01,
      f"{res3['total_coverage']:.4f}≥{cov_q2:.4f}")
check("Q4≥Q3",res4['total_coverage']>=res3['total_coverage']-0.01,
      f"{res4['total_coverage']:.4f}≥{res3['total_coverage']:.4f}")

# ── 验证4：Excel ──────────────────────────────────────────────
print("\n=== 验证4：Excel输出 ===")
OUT=os.path.join(os.path.dirname(__file__),'../../output')
import openpyxl
for fname in ['result1.xlsx','result2.xlsx']:
    fpath=os.path.join(OUT,fname)
    exists=os.path.exists(fpath)
    check(f"{fname}已生成",exists)
    if exists:
        wb=openpyxl.load_workbook(fpath)
        ws=wb.active
        filled=sum(1 for row in ws.iter_rows(min_row=2,max_row=5)
                   if any(c.value is not None for c in row))
        check(f"{fname}数据行≥2",filled>=2,f"{filled}行")

# ── REPORT ────────────────────────────────────────────────────
print("\n"+"="*55)
print("  VERIFICATION REPORT — model_2 (问题3+4)")
print("="*55)
passed=sum(1 for _,s,_ in results if s==PASS)
total=len(results)
for name,status,detail in results:
    print(f"  {status}  {name}")
print(f"\n  总计: {passed}/{total} PASS")
print("="*55)
if passed<total:
    print("  ✗ 有验证项失败")
    sys.exit(1)
else:
    print("  ✓ 全部通过")
