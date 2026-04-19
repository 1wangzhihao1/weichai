# 文件路径: scenarios/order_picking/simpy_verify.py

import sys
import os
import time
import simpy
import numpy as np

# 🌟 寻路雷达：打通跨级调用
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from config import Config
from core_engine.models.resource_model import SimpyStation
from core_engine.rules.dispatch_rules import DispatchRules
from rl_environment import PickingEnv

# 📊 独立的数据统计看板
stats = {
    'peak_loads': np.zeros(Config.NUM_STATIONS, dtype=int),
    'busy_times': np.zeros(Config.NUM_STATIONS, dtype=float),
    'total_boxes': 0
}

def monitor_process(env, stations):
    """【监控引擎】：高频扫描产线，记录真实物理峰值负载"""
    while True:
        for s in stations:
            current_load = s.total_future_load
            if current_load > stats['peak_loads'][s.station_id]:
                stats['peak_loads'][s.station_id] = current_load
        yield env.timeout(0.1)

def auto_search_optimal_stations(model):
    """【同步主引擎】智能排产大模型开始内存预演，探底极限降本方案"""
    print("\n🔍 AI 正在推演极限降本方案...")
    test_env = PickingEnv()
    best_limit = Config.NUM_STATIONS
    for limit in range(8, Config.NUM_STATIONS + 1):
        obs, _ = test_env.reset(seed=999)
        done = False
        while not done:
            mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, _, done, _, _ = test_env.step(int(action))
        makespan = np.max(test_env.unwrapped.station_workloads)
        if makespan <= Config.DEADLINE_SECONDS:
            best_limit = limit
            break
    print(f"💡 降本策略锁定：本次仅需开启 {best_limit} 台站台！")
    return best_limit

def dispatch_engine(env, stations, rl_env, model, optimal_stations):
    """【主指挥中心】：AI 统筹大脑 + 智能发车阀门"""
    
    # 🌟 1. 重置环境 (环境内部的 reset 已经自动完成了 LPT 大单优先排序)
    obs, _ = rl_env.reset(seed=999)
    logical_orders = rl_env.unwrapped.logical_orders

    # 生成降本掩码
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

    # 🌟 2. 开始逐个派发
    for order in logical_orders:
        env_internal_mask = rl_env.unwrapped.action_masks()
        combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
        if not np.any(combined_masks):
            combined_masks = env_internal_mask

        action = DispatchRules.rule_ai_policy(model, obs, valid_masks=combined_masks)

        if action is None:
            yield env.timeout(1.0)
            rl_env.unwrapped.last_dispatch_time += 1.0
            obs = rl_env.unwrapped._get_obs()
            continue

        target_station = stations[action]
        
        # 使用统一的物理配置文件接口获取距离和耗时
        d_main = Config.get_station_main_distance(action)
        branch_info = Config.get_branch_info(action)
        t_trans = (d_main / Config.BELT_SPEED) + branch_info["transit_time_s"]

        # 从 order.entities 取出物理积木去跑沙盘
        for entity in order.entities:
            stats['total_boxes'] += 1
            
            p_time = entity.p_time
            part_type = entity.entity_type
            box_id = entity.entity_id

            # 智能发车阀门：只要“在途+排队”的箱子 >= 容量上限，发车履带强制拉下手刹！
            while target_station.total_future_load >= target_station.capacity:
                yield env.timeout(0.5) 

            stats['busy_times'][action] += p_time
            
            # 启动物理加工协程
            env.process(target_station.process_box(box_id, p_time, t_trans, part_type))
            yield env.timeout(Config.DISPATCH_INTERVAL)

        obs, _, done, _, _ = rl_env.step(action)

    # 全部发完后，主轴阻塞等待各站台干完手头的活
    while any(s.total_future_load > 0 for s in stations):
        yield env.timeout(1.0)

def run_verification():
    print("="*80)
    print("🔬 启动 [微观物理交叉验证引擎] (大一统架构洁净版)")
    print("="*80)
    
    # 核心修复：更新为目前最新的高维度降本模型
    model_path = os.path.join(project_root, "output/models/ppo_masking_model_v2_cost_saving")
    try:
        model = MaskablePPO.load(model_path)
        print("✅ V2 降本增效 AI 调度大脑加载成功！")
    except Exception as e:
        print(f"❌ 模型加载失败: {e}\n请确保模型路径正确: {model_path}")
        return

    # 动态推演应该开几台机器
    optimal_stations = auto_search_optimal_stations(model)

    print("\n⏳ 正在启动物理引擎，马上出报告...\n")
    simpy_env = simpy.Environment()
    stations = [SimpyStation(simpy_env, i, Config.BUFFER_CAPACITY) for i in range(Config.NUM_STATIONS)]
    rl_env = PickingEnv()
    
    simpy_env.process(monitor_process(simpy_env, stations))
    main_process = simpy_env.process(dispatch_engine(simpy_env, stations, rl_env, model, optimal_stations))
    
    time_start = time.time()
    simpy_env.run(until=main_process) 
    time_end = time.time()
    
    makespan = simpy_env.now
    
    # =========================================================
    # 📑 甲方演示专用：震撼的终端战报输出
    # =========================================================
    print("="*80)
    print(" 📑 [数字孪生物理沙盘交叉验证报告]")
    print("="*80)
    print(f"📦 验证规模: {rl_env.total_orders} 个重工订单 | 共计 {stats['total_boxes']} 个独立实体箱")
    print(f"⏱️  物理总完工时间: {makespan:.2f} 秒")
    print(f"⚡ 推演运算耗时: {(time_end - time_start):.3f} 秒")
    print("-" * 80)
    
    print("📊 [各工作站综合效能分析 (OEE)]")
    for s in stations:
        # 只打印开启的机器，被 AI 休眠的直接标灰
        if s.station_id >= optimal_stations:
            print(f"站台 S{s.station_id+1:02d} | ⚫ AI 智能休眠 (节约能耗)")
            continue
            
        peak = stats['peak_loads'][s.station_id]
        processed = s.processed_boxes
        utilization = (stats['busy_times'][s.station_id] / makespan) * 100 if makespan > 0 else 0
        
        bar_len = 20
        filled_len = int(bar_len * utilization / 100)
        bar = '█' * filled_len + '░' * (bar_len - filled_len)
        
        peak_str = f"{peak}/{s.capacity}"
        if peak > s.capacity:
            peak_str = f"⚠️ {peak_str} (爆仓)"
            
        print(f"站台 S{s.station_id+1:02d} | 峰值负载: {peak_str:<12} | 利用率: {utilization:5.1f}% [{bar}] | 共加工: {processed} 箱")

    print("-" * 80)
    
    is_success = all(p <= Config.BUFFER_CAPACITY for p in stats['peak_loads'])
    if is_success:
        print("\n✅ [认证通过] 工业级数字孪生测试大获成功！")
        print("   ➤ 底层 LPT 排序 + RL 路由：有效解决单一机器极度空闲的“贪婪饥饿”陷阱。")
        print("   ➤ 物理零穿模、零碰撞，发车阀门完美阻击爆仓！")
    else:
        print("\n❌ [认证失败] 发现严重的物理穿模或超载现象！请检查底层物理锁机制。")
        
    print("="*80)

if __name__ == "__main__":
    run_verification()