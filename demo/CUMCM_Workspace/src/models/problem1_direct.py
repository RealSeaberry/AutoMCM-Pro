"""
problem1_direct.py — 问题1 & 问题2
2025 CUMCM A题：烟幕干扰弹投放策略
"""

import numpy as np
from scipy.optimize import minimize

G = 9.8; V_SINK = 3.0; R_EFF = 10.0; T_EFF = 20.0; V_MISSILE = 300.0
V_DRONE_MIN = 70.0; V_DRONE_MAX = 140.0
TRUE_TARGET = np.array([0.0, 200.0, 5.0])
MISSILES = {
    'M1': np.array([20000.0,    0.0, 2000.0]),
    'M2': np.array([19000.0,  600.0, 2100.0]),
    'M3': np.array([18000.0, -600.0, 1900.0]),
}
DRONES = {
    'FY1': np.array([17800.0,    0.0, 1800.0]),
    'FY2': np.array([12000.0, 1400.0, 1400.0]),
    'FY3': np.array([ 6000.0,-3000.0,  700.0]),
    'FY4': np.array([11000.0, 2000.0, 1800.0]),
    'FY5': np.array([13000.0,-2000.0, 1300.0]),
}

def missile_pos(m0, t):
    return m0 * (1 - V_MISSILE * t / np.linalg.norm(m0))

def missile_arrival(m0):
    return np.linalg.norm(m0) / V_MISSILE

def compute_coverage(det_pos, t_det, missile_name='M1', dt=0.001):
    """Vectorised shielding check: cloud sphere on line missile→TT."""
    m0 = MISSILES[missile_name]
    t_arr = missile_arrival(m0)
    t0, t1 = t_det, min(t_det + T_EFF, t_arr)
    if t1 <= t0:
        return 0.0, []
    ts = np.arange(t0, t1 + dt, dt)
    fac = V_MISSILE * ts / np.linalg.norm(m0)
    M = m0[np.newaxis, :] * (1 - fac[:, np.newaxis])          # missile pos
    C = np.tile(det_pos, (len(ts), 1))
    C[:, 2] -= V_SINK * (ts - t_det)                           # cloud sinking

    d  = TRUE_TARGET - M                                        # (N,3)
    v  = C - M
    ds = np.sum(d**2, axis=1)
    s  = np.sum(v * d, axis=1) / np.maximum(ds, 1e-12)
    foot = M + s[:, np.newaxis] * d
    dist = np.linalg.norm(C - foot, axis=1)
    ok = (dist <= R_EFF) & (s >= 0) & (s <= 1)

    intervals, in_c, t_in = [], False, None
    for i, flag in enumerate(ok):
        if flag and not in_c:  in_c = True;  t_in = ts[i]
        elif not flag and in_c: in_c = False; intervals.append((t_in, ts[i]))
    if in_c: intervals.append((t_in, ts[-1]))
    return sum(b-a for a,b in intervals), intervals

def grenade_traj(drone_init, angle_deg, v_drone, t_release, tau_det):
    """Return (release_pos, det_pos, t_det)."""
    ar = np.radians(angle_deg)
    vel = np.array([v_drone*np.cos(ar), v_drone*np.sin(ar), 0.0])
    rp  = drone_init + vel * t_release
    dp  = np.array([rp[0] + vel[0]*tau_det,
                    rp[1] + vel[1]*tau_det,
                    rp[2] - 0.5*G*tau_det**2])
    return rp, dp, t_release + tau_det

# ── Problem 1 ──────────────────────────────────────────────────────────────
def solve_problem1():
    print("="*60)
    print("  问题1：固定参数直接计算")
    print("="*60)
    fy1 = DRONES['FY1']
    rp, dp, td = grenade_traj(fy1, 180.0, 120.0, 1.5, 3.6)
    print(f"  投放点: ({rp[0]:.3f}, {rp[1]:.3f}, {rp[2]:.3f})")
    print(f"  起爆点: ({dp[0]:.3f}, {dp[1]:.3f}, {dp[2]:.3f}), t_det={td:.2f}s")
    cov, ivs = compute_coverage(dp, td, 'M1', dt=0.0005)
    print(f"  有效遮蔽时长: {cov:.4f} s")
    for i,(a,b) in enumerate(ivs):
        print(f"    区间{i+1}: [{a:.4f}, {b:.4f}]s")
    return {'release_pos':rp,'det_pos':dp,'t_det':td,'coverage':cov,'intervals':ivs,
            'angle':180.0,'speed':120.0}

# ── Problem 2：Physics-informed grid + local refine ──────────────────────
def neg_cov(params, drone_name='FY1', missile_name='M1'):
    angle_deg, v_drone, t_release, tau_det = params
    if not (V_DRONE_MIN <= v_drone <= V_DRONE_MAX): return 0.0
    if t_release < 0 or tau_det < 0.1: return 0.0
    d0 = DRONES[drone_name]
    _, dp, td = grenade_traj(d0, angle_deg, v_drone, t_release, tau_det)
    if dp[2] <= 0: return 0.0
    c, _ = compute_coverage(dp, td, missile_name, dt=0.002)
    return -c

def physics_grid_search(drone_name='FY1', missile_name='M1'):
    """
    Grid over (t_pass, tau_offset, angle_deg).
    For each (t_pass, tau_offset): analytically compute det_pos,
    then solve for (angle, v_drone, t_release, tau_det).
    """
    d0 = DRONES[drone_name]
    m0 = MISSILES[missile_name]
    t_arr = missile_arrival(m0)
    best_cov, best_params = 0.0, None

    for t_pass in np.arange(5.0, t_arr - 1, 0.5):
        for tau_off in np.arange(0.5, min(20.0, t_pass), 0.5):
            # cloud center at t_pass must equal missile position
            m_at_pass = missile_pos(m0, t_pass)
            # det_pos: cloud sinks tau_off seconds to reach m_at_pass
            det_z = m_at_pass[2] + V_SINK * tau_off
            if det_z >= d0[2]:
                continue  # cloud would need to start above drone altitude → infeasible
            tau_det = np.sqrt(2.0 * (d0[2] - det_z) / G)
            t_det = t_pass - tau_off
            if t_det < 0:
                continue
            t_release = t_det - tau_det
            if t_release < 0:
                continue
            # horizontal displacement needed
            for delta_y in [-5.0, 0.0, 5.0, 10.0]:
                det_x = m_at_pass[0]
                det_y = m_at_pass[1] + delta_y
                # drone must fly from d0 to reach position such that:
                # release_pos + vel*tau_det = (det_x, det_y, _)
                # release_pos = d0 + vel*t_release
                # => d0 + vel*(t_release + tau_det) = det_pos_xy
                tx = (det_x - d0[0])
                ty = (det_y - d0[1])
                total_t = t_det  # = t_release + tau_det
                if total_t <= 0:
                    continue
                vx = tx / total_t
                vy = ty / total_t
                v_drone = np.sqrt(vx**2 + vy**2)
                if not (V_DRONE_MIN <= v_drone <= V_DRONE_MAX):
                    continue
                angle_deg = np.degrees(np.arctan2(vy, vx)) % 360
                det_pos = np.array([det_x, det_y, det_z])
                cov, _ = compute_coverage(det_pos, t_det, missile_name, dt=0.001)
                if cov > best_cov:
                    best_cov = cov
                    best_params = [angle_deg, v_drone, t_release, tau_det]

    return best_cov, best_params

def solve_problem2():
    print("\n"+"="*60)
    print("  问题2：优化 FY1+1弹 对 M1 的遮蔽时长")
    print("="*60)

    # Sanity check with problem-1 params
    test_val = -neg_cov([180.0, 120.0, 1.5, 3.6])
    print(f"  [校验] 问题1参数代入目标函数: coverage={test_val:.4f}s (应≈1.405s)")

    print("  [1/2] 物理驱动网格搜索...")
    best_cov, best_p = physics_grid_search('FY1', 'M1')
    print(f"  网格最优: {best_cov:.4f}s, 参数={[f'{x:.3f}' for x in best_p]}")

    # Multi-start local refinement from grid best + problem1 point
    seeds = [best_p, [180.0, 120.0, 1.5, 3.6]]
    final_best_cov, final_best_p = best_cov, best_p

    print("  [2/2] 局部精化...")
    for seed in seeds:
        res = minimize(neg_cov, seed, args=('FY1','M1'), method='Nelder-Mead',
                       options={'xatol':1e-5,'fatol':1e-5,'maxiter':10000})
        c = -res.fun
        if c > final_best_cov:
            final_best_cov, final_best_p = c, res.x.tolist()

    angle_deg, v_drone, t_release, tau_det = final_best_p
    rp, dp, td = grenade_traj(DRONES['FY1'], angle_deg%360, v_drone, t_release, tau_det)
    cov, ivs = compute_coverage(dp, td, 'M1', dt=0.0005)

    print(f"\n  ══ 问题2 最优结果 ══")
    print(f"  飞行方向: {angle_deg%360:.2f}°  速度: {v_drone:.2f} m/s")
    print(f"  投放延迟: {t_release:.4f}s  引信延迟: {tau_det:.4f}s")
    print(f"  投放点: ({rp[0]:.3f}, {rp[1]:.3f}, {rp[2]:.3f})")
    print(f"  起爆点: ({dp[0]:.3f}, {dp[1]:.3f}, {dp[2]:.3f})")
    print(f"  起爆时刻: {td:.4f}s")
    print(f"  有效遮蔽时长: {cov:.4f} s")
    for i,(a,b) in enumerate(ivs):
        print(f"    区间{i+1}: [{a:.4f}, {b:.4f}]s")
    return {'angle':angle_deg%360,'speed':v_drone,'t_release':t_release,
            'tau_det':tau_det,'release_pos':rp,'det_pos':dp,'t_det':td,
            'coverage':cov,'intervals':ivs}

if __name__ == '__main__':
    r1 = solve_problem1()
    r2 = solve_problem2()
    print("\n"+"="*60)
    print(f"  问题1 遮蔽时长: {r1['coverage']:.4f} s")
    print(f"  问题2 最优遮蔽时长: {r2['coverage']:.4f} s")
    print("="*60)
