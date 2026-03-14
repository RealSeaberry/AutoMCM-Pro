"""
verify_problem3.py — 验证问题5
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),'../models'))
from problem3_full import (compute_coverage, union_length, grenade_traj,
                            missile_arrival, DRONES, MISSILES, DRONE_NAMES,
                            MISSILE_NAMES, V_MIN, V_MAX, T_EFF, INTERVAL_MIN,
                            solve_problem5, save_result3)

PASS,FAIL="✓ PASS","✗ FAIL"
results=[]
def check(name,cond,detail=""):
    s=PASS if cond else FAIL
    results.append((name,s,detail))
    print(f"  {s}  {name}"+(f": {detail}" if detail else ""))

print("  [重新求解问题5...]")
total5,assign5,detail5=solve_problem5()
save_result3(assign5,detail5)

print("\n=== 验证1：分配方案完整性 ===")
missiles_covered=set(assign5.values())
check("三枚导弹均有分配",missiles_covered==set(MISSILE_NAMES),str(missiles_covered))
check("所有无人机均被分配",len(assign5)==5,f"{len(assign5)}架")

print("\n=== 验证2：每架无人机物理约束 ===")
for dn in DRONE_NAMES:
    mn=assign5.get(dn)
    grenades=detail5.get(mn,{}).get('grenades',[])
    g_list=[g for g in grenades if g['drone']==dn]
    for i,g in enumerate(g_list[:3],1):
        spd,dp,td=g['speed'],g['det_pos'],g['t_det']
        t_arr=missile_arrival(MISSILES[mn])
        check(f"{dn}弹{i}速度[70,140]",V_MIN<=spd<=V_MAX,f"{spd:.2f}m/s")
        check(f"{dn}弹{i}起爆z>0",dp[2]>0,f"z={dp[2]:.2f}")
        check(f"{dn}弹{i}t_det<t_arr",td<t_arr,f"{td:.3f}<{t_arr:.2f}")
        check(f"{dn}弹{i}t_det≥0",td>=0,f"{td:.3f}")

print("\n=== 验证3：各导弹遮蔽时长>0 ===")
for mn in MISSILE_NAMES:
    c=detail5[mn]['coverage']
    check(f"{mn}遮蔽>0",c>0,f"{c:.4f}s")

print("\n=== 验证4：总遮蔽合理（>15s） ===")
check("总遮蔽>15s",total5>15.,f"{total5:.4f}s")
check("M1遮蔽最长（主要威胁）",
      detail5['M1']['coverage']>=detail5['M2']['coverage'],
      f"M1={detail5['M1']['coverage']:.4f}>M2={detail5['M2']['coverage']:.4f}")

print("\n=== 验证5：遮蔽时间窗在导弹到达前 ===")
for mn in MISSILE_NAMES:
    t_arr=missile_arrival(MISSILES[mn])
    for a,b in detail5[mn].get('merged',[]):
        check(f"{mn}区间[{a:.2f},{b:.2f}]≤t_arr",b<=t_arr+0.01,f"{b:.3f}≤{t_arr:.2f}")

print("\n=== 验证6：result3.xlsx输出 ===")
OUT=os.path.join(os.path.dirname(__file__),'../../output')
import openpyxl
fpath=os.path.join(OUT,'result3.xlsx')
check("result3.xlsx已生成",os.path.exists(fpath))
if os.path.exists(fpath):
    wb=openpyxl.load_workbook(fpath)
    ws=wb.active
    filled=sum(1 for row in ws.iter_rows(min_row=2,max_row=20)
               if any(c.value is not None for c in row))
    check("result3数据行≥5",filled>=5,f"{filled}行")

print("\n"+"="*55)
print("  VERIFICATION REPORT — model_3 (问题5)")
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
