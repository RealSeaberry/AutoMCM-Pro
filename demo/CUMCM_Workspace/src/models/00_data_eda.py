"""
00_data_eda.py — 数据探索与参数整理
2025 CUMCM A题：烟幕干扰弹投放策略

本脚本：
1. 定义所有问题常量
2. 验证 Excel 模板结构
3. 分析导弹轨迹与无人机的几何关系
4. 生成辅助可视化图
"""

import numpy as np
import openpyxl
import os
import sys

# ──────────────────────────────────────────────
# 1. 问题常量
# ──────────────────────────────────────────────
G = 9.8           # 重力加速度 (m/s²)
V_SINK = 3.0      # 云团下沉速度 (m/s)
R_EFF = 10.0      # 有效烟幕半径 (m)
T_EFF = 20.0      # 有效遮蔽持续时间 (s)
V_MISSILE = 300.0 # 导弹速度 (m/s)
V_DRONE_MIN = 70.0
V_DRONE_MAX = 140.0
DRONE_INTERVAL_MIN = 1.0  # 同无人机两弹最小间隔 (s)

# 假目标（原点），真目标
FAKE_TARGET = np.array([0.0, 0.0, 0.0])
TRUE_TARGET_CENTER = np.array([0.0, 200.0, 5.0])   # 圆柱中心
TRUE_TARGET_RADIUS = 7.0
TRUE_TARGET_HEIGHT = 10.0

# 导弹初始位置 (t=0)
MISSILES = {
    'M1': np.array([20000.0,    0.0, 2000.0]),
    'M2': np.array([19000.0,  600.0, 2100.0]),
    'M3': np.array([18000.0, -600.0, 1900.0]),
}

# 无人机初始位置 (t=0)
DRONES = {
    'FY1': np.array([17800.0,    0.0, 1800.0]),
    'FY2': np.array([12000.0, 1400.0, 1400.0]),
    'FY3': np.array([  6000.0, -3000.0,  700.0]),
    'FY4': np.array([11000.0, 2000.0, 1800.0]),
    'FY5': np.array([13000.0, -2000.0, 1300.0]),
}

# ──────────────────────────────────────────────
# 2. 核心物理函数
# ──────────────────────────────────────────────

def missile_position(m0, t):
    """导弹位置：从 m0 匀速飞向假目标"""
    dist = np.linalg.norm(m0)
    direction = -m0 / dist
    return m0 + V_MISSILE * t * direction

def missile_arrival_time(m0):
    """导弹到达假目标时刻"""
    return np.linalg.norm(m0) / V_MISSILE

def drone_direction_vector(angle_deg):
    """水平飞行方向向量（从x轴正向逆时针计量，角度制）"""
    angle_rad = np.radians(angle_deg)
    return np.array([np.cos(angle_rad), np.sin(angle_rad), 0.0])

def drone_position(d0, angle_deg, speed, t):
    """无人机位置（等高度匀速直线）"""
    dir_vec = drone_direction_vector(angle_deg)
    return d0 + speed * t * dir_vec

def grenade_position(release_pos, drone_velocity, tau):
    """
    干扰弹位置
    release_pos: 投放点 (3D)
    drone_velocity: 投放时无人机速度向量 (3D)
    tau: 投放后经过的时间 (s)
    """
    x = release_pos[0] + drone_velocity[0] * tau
    y = release_pos[1] + drone_velocity[1] * tau
    z = release_pos[2] - 0.5 * G * tau**2
    return np.array([x, y, z])

def cloud_center(det_pos, t_det, t):
    """
    云团中心（起爆后下沉）
    det_pos: 起爆点 (3D)
    t_det: 起爆时刻
    t: 当前时刻 (t >= t_det)
    """
    dt = t - t_det
    return np.array([det_pos[0], det_pos[1], det_pos[2] - V_SINK * dt])

def shielding_check(missile_pos, cloud_pos, target=TRUE_TARGET_CENTER, radius=R_EFF):
    """
    检验云团是否遮挡导弹到真目标的视线
    返回 (is_shielded, distance, s_param)
    """
    d = target - missile_pos   # 导弹→真目标方向向量
    v = cloud_pos - missile_pos
    d_sq = np.dot(d, d)
    if d_sq < 1e-12:
        return False, 999.0, 0.0
    s = np.dot(v, d) / d_sq
    # s 必须在 [0,1]（云团在线段范围内）
    if s < 0 or s > 1:
        return False, 999.0, s
    foot = missile_pos + s * d
    dist = np.linalg.norm(cloud_pos - foot)
    return dist <= radius, dist, s

def compute_coverage_time(
    det_pos, t_det,
    missile_name='M1',
    dt=0.001
):
    """
    计算单枚干扰弹对指定导弹的有效遮蔽时长

    返回：total_coverage_seconds, coverage_intervals
    """
    m0 = MISSILES[missile_name]
    t_arr = missile_arrival_time(m0)

    t_start = t_det
    t_end = min(t_det + T_EFF, t_arr)  # 导弹到达假目标后不再需要遮蔽

    if t_end <= t_start:
        return 0.0, []

    intervals = []
    in_coverage = False
    t_in = None

    t = t_start
    while t <= t_end:
        m_pos = missile_position(m0, t)
        c_pos = cloud_center(det_pos, t_det, t)
        shielded, dist, s = shielding_check(m_pos, c_pos)

        if shielded and not in_coverage:
            in_coverage = True
            t_in = t
        elif not shielded and in_coverage:
            in_coverage = False
            intervals.append((t_in, t))

        t += dt

    if in_coverage:
        intervals.append((t_in, t_end))

    total = sum(end - start for start, end in intervals)
    return total, intervals

# ──────────────────────────────────────────────
# 3. 验证 Excel 模板
# ──────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), '../../data')
RESULT_TEMPLATES = {
    'result1.xlsx': {
        'expected_cols': 10,
        'description': '问题3：FY1 × 3弹'
    },
    'result2.xlsx': {
        'expected_cols': 10,
        'description': '问题4：FY1+FY2+FY3 各1弹'
    },
    'result3.xlsx': {
        'expected_cols': 12,
        'description': '问题5：5架无人机 × ≤3弹 × 3导弹'
    },
}

def verify_excel_templates():
    print("=== Excel 模板验证 ===")
    all_ok = True
    for fname, info in RESULT_TEMPLATES.items():
        fpath = os.path.join(DATA_DIR, fname)
        try:
            wb = openpyxl.load_workbook(fpath)
            ws = wb.active
            header = [c.value for c in ws[1]]
            n_cols = len([h for h in header if h is not None])
            status = "✓" if n_cols == info['expected_cols'] else "✗"
            if status == "✗":
                all_ok = False
            print(f"  {status} {fname} ({info['description']})：{n_cols} 列")
            print(f"      列名：{header}")
        except Exception as e:
            print(f"  ✗ {fname}：读取失败 — {e}")
            all_ok = False
    return all_ok

# ──────────────────────────────────────────────
# 4. 几何分析：导弹轨迹与无人机相对位置
# ──────────────────────────────────────────────

def analyze_geometry():
    print("\n=== 导弹几何分析 ===")
    for name, m0 in MISSILES.items():
        dist = np.linalg.norm(m0)
        t_arr = dist / V_MISSILE
        direction = -m0 / dist
        print(f"  {name}: 初始位置={m0}, 距假目标={dist:.1f}m, 到达时间={t_arr:.2f}s")
        print(f"       飞行方向单位向量=({direction[0]:.5f}, {direction[1]:.5f}, {direction[2]:.5f})")

    print("\n=== 无人机初始位置 ===")
    for name, d0 in DRONES.items():
        print(f"  {name}: {d0}")

    print("\n=== FY1→假目标方向（水平投影）===")
    fy1 = DRONES['FY1']
    hor = np.array([-fy1[0], -fy1[1]])  # 水平向量
    angle = np.degrees(np.arctan2(hor[1], hor[0])) % 360
    print(f"  FY1 朝假目标水平方向角度（逆时针）= {angle:.2f}°（即 180°，沿 -x 方向）")


# ──────────────────────────────────────────────
# 5. 问题1 验算
# ──────────────────────────────────────────────

def problem1_calculation():
    print("\n=== 问题1 直接计算 ===")
    fy1_init = DRONES['FY1']

    # FY1 以 120 m/s 朝假目标方向（-x 方向）飞行
    v_drone = 120.0
    direction_angle = 180.0  # -x 方向（从x轴正向逆时针180°）
    dir_vec = drone_direction_vector(direction_angle)
    drone_vel_3d = np.array([dir_vec[0] * v_drone, dir_vec[1] * v_drone, 0.0])

    # 受领任务后 1.5s 投放
    t_release = 1.5
    release_pos = drone_position(fy1_init, direction_angle, v_drone, t_release)
    print(f"  投放时刻：t = {t_release}s")
    print(f"  投放点：{release_pos}")

    # 间隔 3.6s 后起爆
    tau_det = 3.6
    det_pos = grenade_position(release_pos, drone_vel_3d, tau_det)
    t_det = t_release + tau_det
    print(f"  起爆时刻：t = {t_det}s")
    print(f"  起爆点：({det_pos[0]:.3f}, {det_pos[1]:.3f}, {det_pos[2]:.3f})")

    # 计算遮蔽时长
    coverage, intervals = compute_coverage_time(det_pos, t_det, 'M1', dt=0.001)
    print(f"\n  有效遮蔽时长：{coverage:.4f} s")
    if intervals:
        for i, (a, b) in enumerate(intervals):
            print(f"    遮蔽区间 {i+1}：[{a:.4f}, {b:.4f}] s，时长={b-a:.4f}s")
    else:
        print("  无有效遮蔽（云团未遮挡导弹到真目标视线）")

    # 验证：M1 在云团附近的最近时刻
    m0 = MISSILES['M1']
    t_arr = missile_arrival_time(m0)
    print(f"\n  M1 到假目标时间：{t_arr:.2f}s")
    min_dist = 1e9
    t_min = -1
    for t_test in np.arange(t_det, min(t_det + T_EFF, t_arr), 0.01):
        m_pos = missile_position(m0, t_test)
        c_pos = cloud_center(det_pos, t_det, t_test)
        dist = np.linalg.norm(m_pos - c_pos)
        if dist < min_dist:
            min_dist = dist
            t_min = t_test
    print(f"  M1 到云团中心最近距离：{min_dist:.3f}m，发生在 t={t_min:.3f}s")

    return coverage, det_pos, t_det


# ──────────────────────────────────────────────
# 6. 生成几何可视化
# ──────────────────────────────────────────────

def plot_geometry():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D

        fig = plt.figure(figsize=(14, 6))

        # 图1：俯视图
        ax1 = fig.add_subplot(121)
        ax1.set_title('俯视图 (XY平面)', fontsize=12)

        # 导弹轨迹
        colors = {'M1': 'red', 'M2': 'orange', 'M3': 'brown'}
        for name, m0 in MISSILES.items():
            t_arr = missile_arrival_time(m0)
            ts = np.linspace(0, t_arr, 200)
            positions = np.array([missile_position(m0, t) for t in ts])
            ax1.plot(positions[:,0], positions[:,1], color=colors[name],
                     label=f'{name}', linewidth=2)
            ax1.plot(m0[0], m0[1], 'v', color=colors[name], markersize=8)

        # 无人机位置
        for name, d0 in DRONES.items():
            ax1.plot(d0[0], d0[1], '^', color='blue', markersize=8)
            ax1.annotate(name, (d0[0], d0[1]), fontsize=8, color='blue')

        # 假目标和真目标
        ax1.plot(0, 0, 'k*', markersize=15, label='假目标')
        ax1.plot(0, 200, 'g*', markersize=15, label='真目标')
        circle = plt.Circle((0, 200), 7, color='green', fill=False, linestyle='--')
        ax1.add_patch(circle)

        ax1.set_xlabel('X (m)')
        ax1.set_ylabel('Y (m)')
        ax1.legend(loc='upper right', fontsize=8)
        ax1.set_aspect('equal')
        ax1.grid(True, alpha=0.3)

        # 图2：侧视图 (XZ平面)
        ax2 = fig.add_subplot(122)
        ax2.set_title('侧视图 (XZ平面)', fontsize=12)

        for name, m0 in MISSILES.items():
            t_arr = missile_arrival_time(m0)
            ts = np.linspace(0, t_arr, 200)
            positions = np.array([missile_position(m0, t) for t in ts])
            ax2.plot(positions[:,0], positions[:,2], color=colors[name],
                     label=f'{name}', linewidth=2)
            ax2.plot(m0[0], m0[2], 'v', color=colors[name], markersize=8)

        for name, d0 in DRONES.items():
            ax2.plot(d0[0], d0[2], '^', color='blue', markersize=8)
            ax2.annotate(name, (d0[0], d0[2]), fontsize=8, color='blue')

        ax2.plot(0, 0, 'k*', markersize=15, label='假目标')
        # 问题1起爆点
        ax2.plot(17188, 1736.5, 'mo', markersize=10, label='Q1起爆点')

        ax2.set_xlabel('X (m)')
        ax2.set_ylabel('Z (m)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        out_path = os.path.join(os.path.dirname(__file__), '../../latex/images/fig00_geometry.png')
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"\n  [图像] 保存至 {out_path}")

    except ImportError as e:
        print(f"\n  [图像] matplotlib 不可用：{e}")


# ──────────────────────────────────────────────
# 主程序
# ──────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  AutoMCM-Pro | 2025 CUMCM A题 | 数据探索分析")
    print("=" * 60)

    ok = verify_excel_templates()
    analyze_geometry()
    coverage, det_pos, t_det = problem1_calculation()
    plot_geometry()

    print("\n" + "=" * 60)
    print("  DATA EDA REPORT")
    print("=" * 60)
    print(f"  Excel 模板验证：{'✓ ALL PASS' if ok else '✗ 有问题，请检查'}")
    print(f"  问题1 有效遮蔽时长：{coverage:.4f} s")
    print(f"  导弹数量：{len(MISSILES)}，无人机数量：{len(DRONES)}")
    print(f"  M1到假目标用时：{missile_arrival_time(MISSILES['M1']):.2f}s")
    print(f"  M2到假目标用时：{missile_arrival_time(MISSILES['M2']):.2f}s")
    print(f"  M3到假目标用时：{missile_arrival_time(MISSILES['M3']):.2f}s")
    print("=" * 60)
    print("  ✓ 数据预处理完成")
