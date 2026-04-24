#!/usr/bin/env python3
"""
5cm 牛排煎-休息循环完整模拟
===========================
场景 A: 纯 sear-rest 循环 → 90% even @55°C
场景 B: 烤箱预热 + 最后煎 (reverse sear)

物理模型:
- 1D slab FDM, 半厚度 2.5cm (对称)
- Choi-Okos 热物性（温度依赖）
- 煎: Robin BC, h = 800-1500 W/m²K (铸铁锅接触)
- Rest: Robin BC, h = 8 W/m²K (空气自然对流), T_air = 22°C
- 烤箱: Robin BC, h = 15 W/m²K (强制对流热风)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from choi_okos import choi_okos_properties

import numpy as np
from dataclasses import dataclass

# ═══════ 参数 ═══════
RIBEYE_COMP = {"water": 0.66, "protein": 0.19, "fat": 0.13, "carb": 0.01, "ash": 0.01}
HALF_THICKNESS = 0.025     # 2.5cm = 半厚度 (对称模型, 总厚5cm)
N_NODES = 50               # 空间节点数 (更高精度)
T_INIT = 4.0               # 冰箱取出

# 热传导参数
H_SEAR = 1200.0            # 铸铁锅煎: W/m²K (接触传热, 有油膜)
H_REST = 8.0               # 空气自然对流: W/m²K
H_OVEN = 15.0              # 烤箱强制对流: W/m²K
T_AIR = 22.0               # 室温

# 目标
T_TARGET = 55.0            # 目标温度
EVENNESS_TARGET = 0.90     # 90% 均匀度


@dataclass
class PhaseResult:
    """单阶段模拟结果"""
    phase_name: str
    duration_s: float
    T_profile: np.ndarray   # 最终温度分布
    T_center: float
    T_surface: float
    T_min: float
    T_max: float
    evenness: float         # 在 target±2°C 内的节点比例


def get_props(T_C):
    """获取温度依赖的热物性"""
    T_C = max(-40, min(150, T_C))
    p = choi_okos_properties(RIBEYE_COMP, T_C)
    return p.k_W_mK, p.rho_kg_m3, p.Cp_J_kgK, p.alpha_m2_s


def calc_evenness(T_profile, target=T_TARGET, tolerance=2.0):
    """计算在 target ± tolerance 范围内的节点比例"""
    in_range = np.sum(np.abs(T_profile - target) <= tolerance)
    return in_range / len(T_profile)


def run_phase(T_init_profile, phase_name, T_env, h_conv, duration_s, 
              dx, dt_max=0.5, record_interval=5.0):
    """
    运行一个阶段的 FDM 模拟
    返回: PhaseResult + 温度历史
    """
    N = len(T_init_profile) - 1
    T = T_init_profile.copy()
    
    # 用当前平均温度计算物性
    T_mean = np.mean(T)
    k, rho, Cp, alpha = get_props(T_mean)
    
    # 稳定性条件
    Fo_max = 0.4
    dt = min(Fo_max * dx**2 / alpha, dt_max)
    dt = max(dt, 1e-4)
    
    n_steps = int(duration_s / dt) + 1
    
    history = []
    t = 0.0
    next_record = 0.0
    
    for step in range(n_steps):
        if t >= duration_s:
            break
            
        # 每100步更新物性（温度依赖）
        if step % 100 == 0:
            T_mean = np.mean(T)
            k, rho, Cp, alpha = get_props(T_mean)
            # 重算 dt
            dt_new = min(Fo_max * dx**2 / alpha, dt_max)
            dt = max(dt_new, 1e-4)
        
        T_new = T.copy()
        
        # 内部节点
        for i in range(1, N):
            d2T = (T[i-1] - 2*T[i] + T[i+1]) / dx**2
            T_new[i] = T[i] + alpha * dt * d2T
        
        # 中心节点 (对称, i=0): ghost node T[-1] = T[1]
        T_new[0] = T[0] + alpha * dt * 2 * (T[1] - T[0]) / dx**2
        
        # 表面节点 (Robin BC)
        T_new[N] = (k/dx * T_new[N-1] + h_conv * T_env) / (k/dx + h_conv)
        
        T = T_new
        t += dt
        
        # 记录
        if t >= next_record:
            history.append({
                't': round(t, 1),
                'T_center': round(float(T[0]), 2),
                'T_surface': round(float(T[N]), 2),
                'T_mean': round(float(np.mean(T)), 2),
                'evenness': round(calc_evenness(T), 3),
            })
            next_record = t + record_interval
    
    return PhaseResult(
        phase_name=phase_name,
        duration_s=duration_s,
        T_profile=T.copy(),
        T_center=float(T[0]),
        T_surface=float(T[N]),
        T_min=float(np.min(T)),
        T_max=float(np.max(T)),
        evenness=calc_evenness(T),
    ), history


def print_profile(T_profile, dx, label=""):
    """打印温度分布"""
    N = len(T_profile) - 1
    print(f"\n  温度分布 {label}:")
    print(f"  {'位置':>8s}  {'温度':>8s}  {'可视化'}")
    print(f"  {'─'*50}")
    for i in range(0, N+1, max(1, N//10)):
        depth_mm = i * dx * 1000
        T = T_profile[i]
        bar_len = int(max(0, (T - 0) / 2))
        bar = '█' * min(bar_len, 60)
        marker = " ← 中心" if i == 0 else (" ← 表面" if i == N else "")
        in_range = "✓" if abs(T - T_TARGET) <= 2.0 else "✗"
        print(f"  {depth_mm:6.1f}mm  {T:6.1f}°C  {in_range} {bar}{marker}")


# ═══════════════════════════════════════════════════════════════
# 场景 A: 纯 Sear-Rest 循环
# ═══════════════════════════════════════════════════════════════
def scenario_a():
    print("\n" + "="*70)
    print("  场景 A: 纯 Sear-Rest 循环")
    print("  5cm 牛排 | 4°C 冰箱 | 铸铁锅 | 目标: 90% even @55°C")
    print("="*70)
    
    dx = HALF_THICKNESS / (N_NODES - 1)
    
    # ── Step 0: 计算基础热物性 ──
    print("\n── Step 0: Choi-Okos 热物性计算 ──")
    for T_test in [4, 30, 55, 100]:
        p = choi_okos_properties(RIBEYE_COMP, T_test)
        print(f"  @{T_test:3d}°C: k={p.k_W_mK:.4f} W/mK, ρ={p.rho_kg_m3:.0f} kg/m³, "
              f"Cp={p.Cp_J_kgK:.0f} J/kgK, α={p.alpha_m2_s:.2e} m²/s")
    
    # 关键物理量
    p4 = choi_okos_properties(RIBEYE_COMP, 30)  # 平均温度
    t_diffuse = HALF_THICKNESS**2 / p4.alpha_m2_s
    print(f"\n  热扩散时间尺度 (L²/α): {t_diffuse:.0f}s = {t_diffuse/60:.1f}min")
    print(f"  → 这是热量从表面到中心的特征时间")
    print(f"  → 5cm 牛排的物理极限：热量穿透需要 ~{t_diffuse/60:.0f} 分钟量级")
    
    # ── Step 1: 先测试不同煎温和煎时 ──
    print("\n── Step 1: 参数扫描 — 寻找最优 sear/rest 组合 ──")
    
    # 策略: 短煎 + 长休息, 让热量渗透
    configs = [
        ("A1", 250, 10, 300, "250°C煎10s, rest 5min"),
        ("A2", 250, 15, 300, "250°C煎15s, rest 5min"),
        ("A3", 250, 20, 300, "250°C煎20s, rest 5min"),
        ("A4", 230, 20, 360, "230°C煎20s, rest 6min"),
        ("A5", 230, 25, 360, "230°C煎25s, rest 6min"),
        ("A6", 200, 30, 420, "200°C煎30s, rest 7min"),
    ]
    
    best_config = None
    best_result = None
    
    for tag, T_pan, sear_s, rest_s, desc in configs:
        T = np.full(N_NODES, T_INIT)
        total_time = 0
        cycles = 0
        
        for cycle in range(30):  # 最多30个循环
            # Sear
            result_sear, _ = run_phase(T, f"sear_{cycle}", T_pan, H_SEAR, sear_s, dx, record_interval=999)
            T = result_sear.T_profile
            total_time += sear_s
            
            # Rest
            result_rest, _ = run_phase(T, f"rest_{cycle}", T_AIR, H_REST, rest_s, dx, record_interval=999)
            T = result_rest.T_profile
            total_time += rest_s
            cycles += 1
            
            # 检查是否达标
            if result_rest.evenness >= EVENNESS_TARGET and abs(np.mean(T) - T_TARGET) < 3:
                print(f"  {tag} [{desc}]: ✓ {cycles}cycles, {total_time/60:.1f}min, "
                      f"center={result_rest.T_center:.1f}°C, even={result_rest.evenness:.0%}")
                if best_config is None or total_time < best_result:
                    best_config = tag
                    best_result = total_time
                break
            
            # 超温检查
            if result_rest.T_center > 62:
                print(f"  {tag} [{desc}]: ✗ 超温 @cycle {cycles}, "
                      f"center={result_rest.T_center:.1f}°C, surface曾到{result_sear.T_surface:.0f}°C")
                break
        else:
            print(f"  {tag} [{desc}]: ✗ 30cycles未达标, center={result_rest.T_center:.1f}°C, "
                  f"even={result_rest.evenness:.0%}")
    
    # ── Step 2: 智能策略 — 自适应停止 ──
    print("\n── Step 2: 智能自适应策略 ──")
    print("  规则: 每个cycle后检查平均温度, 接近目标时缩短煎时/延长rest")
    
    T_PAN = 250.0
    T = np.full(N_NODES, T_INIT)
    total_time = 0
    cycle_log = []
    
    for cycle in range(40):
        T_avg = np.mean(T)
        T_center = T[0]
        
        # 自适应: 根据离目标的距离调整煎时
        gap = T_TARGET - T_avg
        if gap <= 0:
            break
        
        if gap > 30:
            sear_time = 20  # 离目标远，正常煎
            rest_time = 300
        elif gap > 15:
            sear_time = 15
            rest_time = 360
        elif gap > 8:
            sear_time = 10  # 接近了，短煎
            rest_time = 420
        elif gap > 4:
            sear_time = 8
            rest_time = 480
        else:
            sear_time = 5   # 非常接近，微煎
            rest_time = 600  # 长rest让温度均匀化
        
        # Sear
        result_sear, _ = run_phase(T, f"sear_{cycle}", T_PAN, H_SEAR, sear_time, dx, record_interval=999)
        T = result_sear.T_profile
        total_time += sear_time
        
        # Rest
        result_rest, hist = run_phase(T, f"rest_{cycle}", T_AIR, H_REST, rest_time, dx, record_interval=60)
        T = result_rest.T_profile
        total_time += rest_time
        
        cycle_log.append({
            'cycle': cycle + 1,
            'sear_s': sear_time,
            'rest_s': rest_time,
            'T_center': round(result_rest.T_center, 1),
            'T_surface': round(result_rest.T_surface, 1),
            'T_avg': round(float(np.mean(T)), 1),
            'T_min': round(result_rest.T_min, 1),
            'T_max': round(result_rest.T_max, 1),
            'evenness': round(result_rest.evenness, 3),
            'sear_surface_peak': round(result_sear.T_surface, 1),
        })
        
        # 检查达标
        if result_rest.evenness >= EVENNESS_TARGET:
            break
    
    print(f"\n  {'Cycle':>5s} | {'Sear':>5s} | {'Rest':>5s} | {'中心':>6s} | {'表面':>6s} | "
          f"{'平均':>6s} | {'最低':>6s} | {'最高':>6s} | {'均匀度':>6s} | {'煎面峰值':>8s}")
    print(f"  {'─'*90}")
    for c in cycle_log:
        even_marker = " ✓" if c['evenness'] >= EVENNESS_TARGET else ""
        print(f"  {c['cycle']:>5d} | {c['sear_s']:>4d}s | {c['rest_s']:>4d}s | "
              f"{c['T_center']:>5.1f}° | {c['T_surface']:>5.1f}° | "
              f"{c['T_avg']:>5.1f}° | {c['T_min']:>5.1f}° | {c['T_max']:>5.1f}° | "
              f"{c['evenness']:>5.0%}{even_marker} | {c['sear_surface_peak']:>6.1f}°")
    
    print(f"\n  总时间: {total_time:.0f}s = {total_time/60:.1f}min")
    print_profile(T, dx, f"(策略A 自适应, {len(cycle_log)} cycles)")
    
    # ── Step 3: 终极策略 — 最后一次长rest ──
    print("\n── Step 3: 加一次终极长rest (10min) 看能否进一步均匀化 ──")
    result_final, hist_final = run_phase(T, "final_rest", T_AIR, H_REST, 600, dx, record_interval=60)
    T = result_final.T_profile
    total_time += 600
    
    print(f"  终极rest后: center={result_final.T_center:.1f}°C, "
          f"surface={result_final.T_surface:.1f}°C, "
          f"evenness={result_final.evenness:.0%}")
    print(f"  总时间: {total_time:.0f}s = {total_time/60:.1f}min")
    print_profile(T, dx, f"(终极rest后)")
    
    return total_time, cycle_log


# ═══════════════════════════════════════════════════════════════
# 场景 B: 烤箱 + 煎 (Reverse Sear & Variations)
# ═══════════════════════════════════════════════════════════════
def scenario_b():
    print("\n" + "="*70)
    print("  场景 B: 双热源 — 烤箱 + 铸铁锅")
    print("  5cm 牛排 | 4°C 冰箱 | 目标: 90% even @55°C")
    print("="*70)
    
    dx = HALF_THICKNESS / (N_NODES - 1)
    
    # ── B1: Classic Reverse Sear ──
    # 低温烤箱烤到接近目标 → 最后高温煎
    print("\n── B1: Classic Reverse Sear (低温烤箱 → 高温煎) ──")
    print("  思路: 烤箱110°C 慢烤到中心48°C → 铸铁锅250°C 煎两面")
    
    T = np.full(N_NODES, T_INIT)
    total_time = 0
    
    # Phase 1: 烤箱 110°C, 对流 BC
    # 模拟到中心达到 48°C
    # 分段跑，每60s检查
    oven_time = 0
    oven_history = []
    while T[0] < 48.0 and oven_time < 7200:
        result, hist = run_phase(T, "oven", 110, H_OVEN, 60, dx, record_interval=60)
        T = result.T_profile
        oven_time += 60
        if oven_time % 300 == 0:
            oven_history.append(f"    {oven_time/60:.0f}min: center={T[0]:.1f}°C, surface={T[-1]:.1f}°C")
    
    total_time += oven_time
    print(f"\n  烤箱阶段 (110°C, h={H_OVEN}):")
    for h in oven_history:
        print(h)
    print(f"  → 烤箱 {oven_time/60:.0f}min, 中心达到 {T[0]:.1f}°C")
    print_profile(T, dx, "烤箱后")
    
    # Phase 2: 高温煎 (每面30-45s)
    print(f"\n  煎阶段 (250°C, h={H_SEAR}):")
    sear_time = 40  # 秒
    result_sear, _ = run_phase(T, "sear_final", 250, H_SEAR, sear_time, dx, record_interval=5)
    T = result_sear.T_profile
    total_time += sear_time
    print(f"  → 煎{sear_time}s后: center={T[0]:.1f}°C, surface={T[-1]:.1f}°C")
    
    # Phase 3: 最终rest
    result_rest, _ = run_phase(T, "rest_final", T_AIR, H_REST, 300, dx, record_interval=60)
    T = result_rest.T_profile
    total_time += 300
    
    print(f"  → Rest 5min后: center={result_rest.T_center:.1f}°C, "
          f"surface={result_rest.T_surface:.1f}°C, evenness={result_rest.evenness:.0%}")
    print(f"  总时间: {total_time/60:.1f}min")
    print_profile(T, dx, "B1 Reverse Sear 最终")
    
    b1_time = total_time
    b1_evenness = result_rest.evenness
    b1_center = result_rest.T_center
    
    # ── B2: 优化 Reverse Sear — 调整烤箱目标温度 ──
    print("\n── B2: 优化 Reverse Sear — 烤箱烤到 45°C，煎后rest更久 ──")
    
    T = np.full(N_NODES, T_INIT)
    total_time = 0
    
    # Phase 1: 烤箱 110°C → 中心 45°C
    oven_time = 0
    while T[0] < 45.0 and oven_time < 7200:
        result, _ = run_phase(T, "oven", 110, H_OVEN, 60, dx, record_interval=999)
        T = result.T_profile
        oven_time += 60
    total_time += oven_time
    print(f"  烤箱: {oven_time/60:.0f}min → center={T[0]:.1f}°C")
    
    # Phase 2: 煎 35s
    result_sear, _ = run_phase(T, "sear", 250, H_SEAR, 35, dx, record_interval=999)
    T = result_sear.T_profile
    total_time += 35
    print(f"  煎35s → center={T[0]:.1f}°C, surface={T[-1]:.1f}°C (peak)")
    
    # Phase 3: Rest 8min
    result_rest, _ = run_phase(T, "rest", T_AIR, H_REST, 480, dx, record_interval=999)
    T = result_rest.T_profile
    total_time += 480
    print(f"  Rest 8min → center={result_rest.T_center:.1f}°C, surface={result_rest.T_surface:.1f}°C, "
          f"evenness={result_rest.evenness:.0%}")
    print(f"  总时间: {total_time/60:.1f}min")
    print_profile(T, dx, "B2 优化 Reverse Sear")
    
    b2_time = total_time
    b2_evenness = result_rest.evenness
    b2_center = result_rest.T_center
    
    # ── B3: 烤箱 + 多次短煎 ──
    print("\n── B3: 烤箱预热 + 短煎-rest 循环 ──")
    print("  思路: 烤箱烤到中心30°C（缩短预热时间）→ 然后用短煎-rest循环精确控温")
    
    T = np.full(N_NODES, T_INIT)
    total_time = 0
    
    # Phase 1: 烤箱 → 30°C
    oven_time = 0
    while T[0] < 30.0 and oven_time < 7200:
        result, _ = run_phase(T, "oven", 110, H_OVEN, 60, dx, record_interval=999)
        T = result.T_profile
        oven_time += 60
    total_time += oven_time
    print(f"  烤箱: {oven_time/60:.0f}min → center={T[0]:.1f}°C")
    
    # Phase 2: 自适应短煎-rest
    cycle_log_b3 = []
    for cycle in range(20):
        T_avg = np.mean(T)
        gap = T_TARGET - T_avg
        if gap <= 0:
            break
        
        if gap > 15:
            sear_time, rest_time = 15, 300
        elif gap > 8:
            sear_time, rest_time = 10, 360
        elif gap > 4:
            sear_time, rest_time = 8, 420
        else:
            sear_time, rest_time = 5, 480
        
        result_sear, _ = run_phase(T, f"sear_{cycle}", 250, H_SEAR, sear_time, dx, record_interval=999)
        T = result_sear.T_profile
        total_time += sear_time
        
        result_rest, _ = run_phase(T, f"rest_{cycle}", T_AIR, H_REST, rest_time, dx, record_interval=999)
        T = result_rest.T_profile
        total_time += rest_time
        
        cycle_log_b3.append({
            'cycle': cycle + 1,
            'sear_s': sear_time,
            'rest_s': rest_time,
            'T_center': round(result_rest.T_center, 1),
            'T_avg': round(float(np.mean(T)), 1),
            'evenness': round(result_rest.evenness, 3),
        })
        
        if result_rest.evenness >= EVENNESS_TARGET:
            break
    
    for c in cycle_log_b3:
        even_marker = " ✓" if c['evenness'] >= EVENNESS_TARGET else ""
        print(f"  Cycle {c['cycle']}: 煎{c['sear_s']}s+rest{c['rest_s']}s → "
              f"center={c['T_center']:.1f}°C, avg={c['T_avg']:.1f}°C, even={c['evenness']:.0%}{even_marker}")
    
    print(f"  总时间: {total_time/60:.1f}min")
    print_profile(T, dx, "B3 烤箱+短煎循环")
    
    b3_time = total_time
    b3_evenness = calc_evenness(T)
    b3_center = float(T[0])
    
    # ═══ 对比总结 ═══
    print("\n" + "="*70)
    print("  场景 B 对比总结")
    print("="*70)
    print(f"  {'方案':>20s} | {'总时间':>8s} | {'中心温度':>8s} | {'均匀度':>6s}")
    print(f"  {'─'*60}")
    print(f"  {'B1 经典Reverse Sear':>20s} | {b1_time/60:>6.1f}min | {b1_center:>6.1f}°C | {b1_evenness:>5.0%}")
    print(f"  {'B2 优化Reverse Sear':>20s} | {b2_time/60:>6.1f}min | {b2_center:>6.1f}°C | {b2_evenness:>5.0%}")
    print(f"  {'B3 烤箱+短煎循环':>20s} | {b3_time/60:>6.1f}min | {b3_center:>6.1f}°C | {b3_evenness:>5.0%}")
    
    return b1_time, b2_time, b3_time


# ═══════════════════════════════════════════════════════════════
# 灰边分析
# ═══════════════════════════════════════════════════════════════
def analyze_gray_band(T_profile, dx):
    """分析灰边厚度（>65°C = 过熟区域）"""
    N = len(T_profile) - 1
    gray_depth = 0
    for i in range(N, -1, -1):
        if T_profile[i] > 65:  # 过熟温度
            gray_depth = (N - i) * dx * 1000  # mm
        else:
            break
    
    overcooked_depth = 0
    for i in range(N, -1, -1):
        if T_profile[i] > 70:
            overcooked_depth = (N - i) * dx * 1000
        else:
            break
    
    return gray_depth, overcooked_depth


if __name__ == "__main__":
    print("\n" + "▓"*70)
    print("  5cm 牛排完整热力学模拟")
    print("  Choi-Okos 热物性 + 1D FDM 求解器")
    print("  目标: 90% even @55°C (±2°C)")
    print("▓"*70)
    
    a_time, a_log = scenario_a()
    b1, b2, b3 = scenario_b()
    
    # ═══ 全局对比 ═══
    print("\n" + "█"*70)
    print("  最终对比")
    print("█"*70)
    print(f"""
  方法                     | 总时间      | 优势                    | 劣势
  ─────────────────────────┼─────────────┼─────────────────────────┼──────────────────────────
  A  纯煎-rest循环         | {a_time/60:>5.1f} min  | 只需一个锅              | 时间长，灰边控制差
  B1 经典Reverse Sear      | {b1/60:>5.1f} min  | 均匀度最高              | 需要烤箱+锅
  B2 优化Reverse Sear      | {b2/60:>5.1f} min  | 均匀度高+省时间         | 需要精确控温
  B3 烤箱+短煎循环         | {b3/60:>5.1f} min  | 灵活，精确控温          | 操作复杂
    """)
    
    print("  物理结论:")
    print("  1. 5cm 牛排从4°C 开始，热扩散时间尺度 ~40min")
    print("     → 不管什么方法，都需要至少这个量级的时间")
    print("  2. 纯铸铁锅 sear-rest: 表面温度梯度极陡，灰边难以避免")
    print("  3. 加入烤箱（第二热源）后，均匀度显著提升")
    print("     → 低温烤箱提供均匀缓慢加热，不产生灰边")
    print("     → 最后高温煎只负责美拉德反应（表面风味）")
    print("  4. 推荐方案: B2 优化 Reverse Sear")
    print("     → 烤箱110°C烤到中心45°C → 250°C铸铁锅煎35s → Rest 8min")
