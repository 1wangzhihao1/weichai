



# 文件路径: scenarios/order_picking/export_sim_data.py

import sys
import os
import json
import simpy
import numpy as np
from collections import defaultdict
from sb3_contrib import MaskablePPO

# 🌟 寻路雷达
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from scenarios.order_picking.config import Config
from scenarios.order_picking.data_paths import MODEL_DIR, resolve_model_path
from core_engine.rules.dispatch_rules import DispatchRules
from scenarios.order_picking.rl_environment import PickingEnv
from core_engine.models.resource_model import SimpyStation

class TraceLogger:
    """剧本场记员：刻录 JSON 供前端 3D 大屏渲染"""
    def __init__(self):
        # 🌟 核心升级：精确计算每个站台到“统一大门”的平均距离，彻底抛弃等间距！
        precise_distances = []
        for i in range(Config.NUM_STATIONS):
            far_dist = Config.STATION_EXIT_FAR_DISTANCES[i]
            # 统一大门距离 = 远端距离 - (差值 / 2)
            avg_dist = far_dist - (Config.EXIT_PORT_DELTA / 2.0)
            precise_distances.append(round(avg_dist, 3))

        self.config_data = {
            "num_stations": int(Config.NUM_STATIONS),
            "buffer_capacity": int(getattr(Config, 'MAX_ORDERS_PER_STATION', 2)), 
            "belt_speed": float(Config.BELT_SPEED),
            "station_positions": precise_distances, # 传给前端的精准物理坐标系！
            "branch_in_length": float(Config.BRANCH_IN_LENGTH),
            "branch_out_length": float(Config.BRANCH_OUT_LENGTH)
        }
        self.events = []
        self.power_status = [] 

    def set_power_status(self, active_status_array):
        for i, status in enumerate(active_status_array):
            self.power_status.append({
                "station_id": int(i),
                "status": "POWER_ON" if float(status) > 0.0 else "POWER_OFF"
            })

    def log_event(self, time: float, entity_id: str, event_type: str, station_id: int, details: dict = None):
        event = {
            "time": round(float(time), 2),
            "entity_id": str(entity_id),
            "event_type": str(event_type),
            "station_id": int(station_id)
        }
        if details:
            event["details"] = details
        self.events.append(event)

    def export_to_json(self, filename="weichai_ai_animation_script.json"):
        self.events.sort(key=lambda x: x["time"])
        output = {
            "scene_config": self.config_data,
            "station_power_status": self.power_status, 
            "total_events": len(self.events),
            "timeline": self.events
        }
        output_dir = os.path.join(project_root, "output/playbooks")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, filename)
        
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"🎬 [1/2] 3D 动画剧本已导出至: {out_path}")

def deliver_box_with_trace(sim_env, station, box_id, order_id, delay, t_main, t_branch, p_time, entity_type, logger):
    if delay > 0:
        yield sim_env.timeout(delay)
    logger.log_event(sim_env.now, box_id, "spawn", station.station_id, {"type": str(entity_type)})
    yield sim_env.timeout(t_main)
    logger.log_event(sim_env.now, box_id, "reach_branch", station.station_id)
    yield sim_env.timeout(t_branch)
    try:
        yield sim_env.process(station.process_box(box_id, order_id, p_time, 0.0, entity_type))
    except TypeError:
        yield sim_env.process(station.process_box(box_id, p_time, 0.0, entity_type))

def auto_search_optimal_stations(model, daily_orders):
    print("\n🔍 智能排产大模型开始内存预演，探底极限降本方案...")
    test_env = PickingEnv(dataset_type='test')
    test_env.unwrapped.real_world_orders = daily_orders
    test_env.unwrapped.total_orders = len(daily_orders)
    test_env.unwrapped.episode_length = len(daily_orders)
    
    best_limit = Config.NUM_STATIONS
    for limit in range(8, Config.NUM_STATIONS + 1):
        obs, _ = test_env.reset(seed=999)
        done = False
        while not done:
            mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
            try:
                env_internal_mask = test_env.unwrapped.action_masks()
            except AttributeError:
                env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            combined_masks = np.logical_and(mask, env_internal_mask)
            if not np.any(combined_masks):
                combined_masks = mask
            action, _ = model.predict(obs, action_masks=combined_masks, deterministic=True)
            obs, _, done, _, _ = test_env.step(int(action))
            
        makespan = np.max(test_env.unwrapped.station_available_time)
        if makespan <= Config.DEADLINE_SECONDS:
            best_limit = limit
            print(f"✅ 找到全局最优解！满足交期的最小开机数为：{best_limit} 台！\n")
            break
    return best_limit

def export_animation_data():
    print("="*80)
    print("🎥 启动 [3D 动画剧本导出工具] (精确物理距离重构版)...")
    print("="*80)

    ai_env = PickingEnv(dataset_type='test')
    test_orders = ai_env.unwrapped.real_world_orders

    orders_by_date = defaultdict(list)
    for order in test_orders:
        date_str = order['start_time'].date().isoformat()
        orders_by_date[date_str].append(order)

    busiest_date = max(orders_by_date, key=lambda k: len(orders_by_date[k]))
    daily_orders = orders_by_date[busiest_date]
    actual_test_orders = len(daily_orders)

    print(f"\n📅 成功锁定大屏展示数据：测试集中最繁忙的一天 【{busiest_date}】")
    print(f"📦 剧本总订单量: {actual_test_orders} 单")
    
    ai_env.unwrapped.real_world_orders = daily_orders
    ai_env.unwrapped.total_orders = actual_test_orders
    ai_env.unwrapped.episode_length = actual_test_orders
    ai_env.reset(seed=999) 
    
    model_dir = str(MODEL_DIR)
    configured_model = resolve_model_path()
    zip_files = [str(configured_model)] if configured_model and configured_model.exists() else []
    if not zip_files:
        print("⏳ 致命错误：找不到模型！")
        return
        
    latest_model_path = zip_files[0]
    print(f"🧠 [自动装载] 成功锁定最新最强大脑: {os.path.basename(latest_model_path)}")

    try:
        model = MaskablePPO.load(latest_model_path)
    except Exception as e:
        print(f"⏳ 致命错误：模型加载失败！{e}")
        return

    optimal_stations = auto_search_optimal_stations(model, daily_orders)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

    sim_env = simpy.Environment()
    logger = TraceLogger()
    
    physical_stations = [SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2), logger) for i in range(Config.NUM_STATIONS)]

    done = False
    order_manifest = []

    while not done:
        try:
            env_internal_mask = ai_env.unwrapped.action_masks()
        except AttributeError:
            env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
        combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
        if not np.any(combined_masks):
            combined_masks = energy_saving_mask

        obs = ai_env.unwrapped._get_obs()
        action = int(DispatchRules.rule_ai_policy(model, obs=obs, valid_masks=combined_masks))
        current_order = ai_env.unwrapped.real_world_orders[ai_env.unwrapped.current_step]
        target_station = physical_stations[action]

        order_info = {
            "order_id": current_order['order_id'], "target_station": int(action),
            "total_process_time": float(current_order['total_p_time']), "total_boxes": len(current_order['boxes']), "parts": []
        }

        # 🌟 获取该站台精确的平均距离和支线长度
        d_main = Config.STATION_EXIT_FAR_DISTANCES[action] - (Config.EXIT_PORT_DELTA / 2.0)
        t_main = d_main / Config.BELT_SPEED
        t_branch = Config.BRANCH_IN_LENGTH / Config.BELT_SPEED

        local_cursor = ai_env.unwrapped.global_time
        temp_active = [{"finish_time": b["finish_time"], "order_id": b["order_id"]} for b in ai_env.unwrapped.station_active_boxes[action]]
        temp_avail = ai_env.unwrapped.station_available_time[action]
        
        for box in current_order['boxes']:
            order_info["parts"].append({
                "entity_id": f"{current_order['order_id']}-P{box['sku']}", "part_type": box['sku'],
                "quantity": 1, "process_time": float(box['p_time'])
            })

            while True:
                active = [b for b in temp_active if b['finish_time'] > local_cursor]
                active_ids = set(b['order_id'] for b in active)
                is_new = current_order['order_id'] not in active_ids
                if len(active) < Config.MAX_BOXES_PER_STATION and not (is_new and len(active_ids) >= getattr(Config, 'MAX_ORDERS_PER_STATION', 2)):
                    break 
                if active:
                    local_cursor = max(local_cursor, min(b['finish_time'] for b in active))
                else:
                    local_cursor += 1.0

            local_cursor += Config.DISPATCH_INTERVAL
            delay_before_launch = max(0, local_cursor - sim_env.now)
            
            sim_env.process(deliver_box_with_trace(sim_env, target_station, f"{current_order['order_id']}-P{box['sku']}", current_order['order_id'], delay_before_launch, t_main, t_branch, box['p_time'], box['sku'], logger))
            
            arr_time = local_cursor + (t_main + t_branch)
            start_p = max(temp_avail, arr_time)
            finish_p = start_p + box['p_time']
            temp_avail = finish_p
            temp_active.append({"finish_time": finish_p, "order_id": current_order['order_id']})
            
        order_manifest.append(order_info)
        obs, _, done, _, _ = ai_env.step(action)

    if hasattr(ai_env.unwrapped, 'station_active_status'):
        active_status = ai_env.unwrapped.station_active_status
    else:
        active_status = np.array([1.0] * optimal_stations + [0.0] * (Config.NUM_STATIONS - optimal_stations))
        
    logger.set_power_status(active_status)
    saved_machines_idx = [i for i, status in enumerate(active_status) if status == 0.0]
    final_makespan = np.max(ai_env.unwrapped.station_available_time)

    sim_env.run()
    logger.export_to_json("weichai_ai_animation_script.json")
    
    output_dir = os.path.join(project_root, "output/playbooks")
    manifest_path = os.path.join(output_dir, "weichai_order_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(order_manifest, f, ensure_ascii=False, indent=2)
    print("\n" + "="*80)
    print("🏆 【剧本导出完毕】已彻底解除等间距约束，启用不规则真实距离建模！")
    print("="*80)

if __name__ == "__main__":
    export_animation_data()
