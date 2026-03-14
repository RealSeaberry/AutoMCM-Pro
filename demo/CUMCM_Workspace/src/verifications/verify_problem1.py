"""
verify_problem1.py — 验证问题1 & 问题2结果
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../models'))
from problem1_direct import (compute_coverage, grenade_traj, missile_pos,
                              missile_arrival, DRONES, MISSILES, TRUE_TARGET,
                              G, V_SINK, R_EFF, T_EFF)

PASS, FAIL = "✓ PASS", "✗ FAIL"
results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"  {status}  {name}" + (f": {detail}" if detail else ""))

# ── 1. 问题1参数核验（手工推导 vs 代码）─────────────────
print("\n=== 验证1：问题1物理参数 ===")
fy1 = DRONES['FY1']  # (17800, 0, 1800)
rp, dp, td = grenade_traj(fy1, 180.0, 120.0, 1.5, 3.6)
check("投放点x精确", abs(rp[0] - 17620.0) < 0.1, f"rp.x={rp[0]:.3f}")
check("投放点z精确", abs(rp[2] - 1800.0) < 0.1, f"rp.z={rp[2]:.3f}")
# 起爆点 z = 1800 - 0.5*9.8*3.6^2 = 1800 - 63.504 = 1736.496
det_z_expect = 1800 - 0.5*G*3.6**2
check("起爆点z精确", abs(dp[2] - det_z_expect) < 0.1, f"dp.z={dp[2]:.3f}, expect={det_z_expect:.3f}")
# 起爆点x = 17620 - 120*3.6 = 17620 - 432 = 17188
check("起爆点x精确", abs(dp[0] - 17188.0) < 0.1, f"dp.x={dp[0]:.3f}")
check("起爆时刻", abs(td - 5.1) < 0.01, f"t_det={td:.4f}")

# ── 2. 问题1遮蔽时长区间合理性 ─────────────────────────
print("\n=== 验证2：问题1遮蔽时长 ===")
cov1, ivs1 = compute_coverage(dp, td, 'M1', dt=0.0005)
check("遮蔽时长>0", cov1 > 0, f"{cov1:.4f}s")
check("仅1个遮蔽区间", len(ivs1) == 1, f"{len(ivs1)}个")
check("区间起始>t_det", ivs1[0][0] > td, f"{ivs1[0][0]:.4f}>{td:.2f}")
check("区间结束<t_det+20", ivs1[0][1] < td+T_EFF+0.01, f"{ivs1[0][1]:.4f}<{td+T_EFF:.2f}")
check("遮蔽时长范围[1.3,1.6]", 1.3 < cov1 < 1.6, f"{cov1:.4f}s")

# ── 3. 边界条件：起爆时刻±0.001s云团状态 ────────────────
print("\n=== 验证3：遮蔽边界一致性 ===")
a, b = ivs1[0]
# 区间中点应完全遮蔽
mid_t = (a + b) / 2
m_mid = missile_pos(MISSILES['M1'], mid_t)
c_mid = dp.copy(); c_mid[2] -= V_SINK*(mid_t - td)
d_vec = TRUE_TARGET - m_mid
s = np.dot(c_mid - m_mid, d_vec) / np.dot(d_vec, d_vec)
foot = m_mid + s * d_vec
dist_mid = np.linalg.norm(c_mid - foot)
check("中点距离<R_EFF", dist_mid < R_EFF, f"dist={dist_mid:.3f}m")
check("中点s∈[0,1]", 0 <= s <= 1, f"s={s:.6f}")

# ── 4. 问题2结果合理性验证 ──────────────────────────────
print("\n=== 验证4：问题2结果合理性 ===")
# 最优参数
angle2, v2, trel2, tdet2 = 177.61, 72.39, 0.2900, 2.6192
rp2, dp2, td2 = grenade_traj(DRONES['FY1'], angle2, v2, trel2, tdet2)
cov2, ivs2 = compute_coverage(dp2, td2, 'M1', dt=0.0005)
check("问题2遮蔽>问题1", cov2 > cov1, f"{cov2:.4f}>{cov1:.4f}")
check("问题2遮蔽>3s", cov2 > 3.0, f"{cov2:.4f}s")
check("速度在范围内", 70 <= v2 <= 140, f"{v2:.2f}m/s")
check("起爆点z>0", dp2[2] > 0, f"{dp2[2]:.3f}m")
check("起爆点z<1800", dp2[2] < 1800, f"{dp2[2]:.3f}m")
check("t_release≥0", trel2 >= 0, f"{trel2:.4f}s")
check("tau_det≥0.1", tdet2 >= 0.1, f"{tdet2:.4f}s")

# ── 5. 物理约束：云团在有效时窗内 ─────────────────────
print("\n=== 验证5：云团有效时窗约束 ===")
if ivs2:
    check("区间起始≥t_det", ivs2[0][0] >= td2 - 0.01, f"{ivs2[0][0]:.4f}≥{td2:.4f}")
    check("区间结束≤t_det+20", ivs2[-1][1] <= td2 + T_EFF + 0.01,
          f"{ivs2[-1][1]:.4f}≤{td2+T_EFF:.4f}")
    check("区间在导弹到达前", ivs2[-1][1] <= missile_arrival(MISSILES['M1'])+0.01,
          f"{ivs2[-1][1]:.4f}≤{missile_arrival(MISSILES['M1']):.2f}")
else:
    check("有有效区间", False, "无遮蔽区间")

# ── REPORT ──────────────────────────────────────────────
print("\n" + "="*55)
print("  VERIFICATION REPORT — model_1 (问题1+2)")
print("="*55)
passed = sum(1 for _,s,_ in results if s==PASS)
total  = len(results)
for name, status, detail in results:
    print(f"  {status}  {name}")
print(f"\n  总计: {passed}/{total} PASS")
print("="*55)
if passed < total:
    print("  ✗ 有验证项失败，需回到 model_build 修复")
    sys.exit(1)
else:
    print("  ✓ 全部通过")
