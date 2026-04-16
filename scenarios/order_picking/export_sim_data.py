# 文件路径: scenarios/order_picking/export_sim_data.py

import sys
import os
import json
import simpy
import numpy as np
from sb3_contrib import MaskablePPO

# 🌟 寻路雷达
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from config import Config
from core_engine.rules.dispatch_rules import DispatchRules
from rl_environment import PickingEnv
from core_engine.models.resource_model import SimpyStation

class TraceLogger:
    """剧本场记员：刻录 JSON"""
    def __init__(self):
        self.config_data = {
            "num_stations": int(Config.NUM_STATIONS),
            "buffer_capacity": int(Config.BUFFER_CAPACITY),
            "belt_speed": float(Config.BELT_SPEED),
            "station_distance": float(Config.STATION_DISTANCE),
            "main_line_offset": float(Config.MAIN_LINE_OFFSET)
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

def deliver_box_with_trace(sim_env, station, box_id, delay, t_main, t_branch, p_time, entity_type, logger):
    if delay > 0:
        yield sim_env.timeout(delay)
    logger.log_event(sim_env.now, box_id, "spawn", station.station_id, {"type": int(entity_type)})
    yield sim_env.timeout(t_main)
    logger.log_event(sim_env.now, box_id, "reach_branch", station.station_id)
    yield sim_env.timeout(t_branch)
    yield sim_env.process(station.process_box(box_id, p_time, 0.0, entity_type))

def delayed_breakdown(sim_env, station, trigger_time, repair_time=600):
    """确保机床在指定的上帝时间精准宕机，彻底解决时空错位问题"""
    if trigger_time > 0:
        yield sim_env.timeout(trigger_time)
    if hasattr(station, 'trigger_breakdown'):
        station.trigger_breakdown(repair_time=repair_time)

def auto_search_optimal_stations(model):
    print("\n🔍 智能排产大模型开始内存预演，探底极限降本方案...")
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
            print(f"✅ 找到全局最优解！满足交期的最小开机数为：{best_limit} 台！\n")
            break
    return best_limit

# ==============================================================================
# 🌟 终极修复：拆分 vip_time 和 breakdown_time，彻底消灭“平行宇宙”和“蝴蝶效应”
# ==============================================================================
def export_animation_data(trigger_vip=False, vip_time=0.0, broken_stations=None, breakdown_time=0.0):
    print("="*80)
    print("🎥 启动 [3D 动画剧本导出工具] (数字孪生抗扰动双线融合版)...")
    print("="*80)

    ai_env = PickingEnv()
    ai_env.reset(seed=999) 
    
    model_path = os.path.join(project_root, "output/models/ppo_masking_model_v2_cost_saving")
    try:
        model = MaskablePPO.load(model_path)
    except Exception as e:
        print(f"⏳ 致命错误：找不到 V2 AI 模型！请确保模型保存在 {model_path}.zip")
        return

    optimal_stations = auto_search_optimal_stations(model)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

    sim_env = simpy.Environment()
    logger = TraceLogger()
    
    physical_stations = [
        SimpyStation(sim_env, i, Config.BUFFER_CAPACITY, logger) 
        for i in range(Config.NUM_STATIONS)
    ]

    done = False
    order_manifest = []
    
    vip_injected = False 
    breakdown_triggered = False
    
    # 兜底物理掩码，兼容所有老版本环境
    dynamic_broken_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

    print("🧠 正在使用 AI 策略进行物理推演与多维事件融合刻录...")

    while not done:
        dispatch_time_cursor = ai_env.last_dispatch_time 

        # --- ⏳ 时空裂缝 1：精准锚定并重现过去的 VIP 插单 ---
        if trigger_vip and not vip_injected and dispatch_time_cursor >= vip_time:
            vip_file_path = os.path.join(project_root, "vip_urgent_order.json")
            if os.path.exists(vip_file_path):
                with open(vip_file_path, 'r', encoding='utf-8') as f:
                    vip_data_list = json.load(f) 
            else:
                raise FileNotFoundError(f"🚨 致命错误: 未找到 {vip_file_path}！")
            
            class DummyEntity:
                def __init__(self, e_id, e_type, p_time):
                    self.entity_id, self.entity_type, self.qty, self.p_time = e_id, e_type, 1, p_time
            class DummyOrder:
                def __init__(self, data):
                    raw_id = str(data.get("vip_order_id", "VIP-999"))
                    self.order_id = raw_id if "VIP" in raw_id.upper() else f"VIP-{raw_id}"
                    # 🛡️ 修复：给同型号的 VIP 零件加上序号 i，防止字典 Key 覆盖导致变成幽灵！
                    self.entities = [
                        DummyEntity(f"{self.order_id}-P{p['type']}-{i}", p["type"], p["p_time"]) 
                        for i, p in enumerate(data["parts"])
                    ]
                    self.total_process_time = sum(p["p_time"] for p in data["parts"])

            print(f"\n🔴 [调度中枢] 读取全局记忆，在时空坐标 {vip_time:.1f}s 处成功重现 VIP 插单！")
            
            for idx, vip_data in enumerate(vip_data_list):
                vip_order = DummyOrder(vip_data)
                # 兼容旧版本环境直接插入逻辑，防止环境未提供 hook
                insert_idx = ai_env.current_step + 1 + idx
                
                ai_env.logical_orders.insert(insert_idx, vip_order)
                if hasattr(ai_env, 'order_process_times'):
                    if isinstance(ai_env.order_process_times, list):
                        ai_env.order_process_times.insert(insert_idx, vip_order.total_process_time)
                    else:
                        ai_env.order_process_times = np.insert(ai_env.order_process_times, insert_idx, vip_order.total_process_time)
                
                if hasattr(ai_env, 'order_box_p_times'):
                    box_times = [p["p_time"] for p in vip_data["parts"]]
                    if isinstance(ai_env.order_box_p_times, list):
                        ai_env.order_box_p_times.insert(insert_idx, box_times)
                    else:
                        temp_list = list(ai_env.order_box_p_times)
                        temp_list.insert(insert_idx, box_times)
                        ai_env.order_box_p_times = temp_list
                        
            ai_env.total_orders += len(vip_data_list)
            vip_injected = True 

        # --- ⏳ 时空裂缝 2：精准处理最新的物理设备故障 ---
        if broken_stations and not breakdown_triggered and dispatch_time_cursor >= breakdown_time:
            print(f"\n💥 [调度中枢] 截获设备异常报警！受损机床: {broken_stations} | 触发时点: {breakdown_time:.1f}s")
            
            # 更新局部动作掩码黑名单
            for sid in broken_stations:
                dynamic_broken_mask[sid] = False
                
            # 兼容：如果使用的是新版环境模型，则调用新版 hook
            if hasattr(ai_env, 'trigger_breakdown'):
                ai_env.trigger_breakdown(broken_stations)
                
            # 🌟 埋设物理定时炸弹，保证时间坐标绝对对齐
            for sid in broken_stations:
                if 0 <= sid < Config.NUM_STATIONS:
                    sim_env.process(delayed_breakdown(sim_env, physical_stations[sid], breakdown_time, 600))
                    
            breakdown_triggered = True

        # ==========================================================
        # 🌟 三重掩码大一统：AI降本掩码 + 环境内置掩码 + 外部物理宕机掩码
        # ==========================================================
        try:
            env_internal_mask = ai_env.action_masks()
        except AttributeError:
            env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
        combined_masks = np.logical_and(energy_saving_mask, dynamic_broken_mask)
        combined_masks = np.logical_and(combined_masks, env_internal_mask)
        
        # 安全兜底：如果宕机把正常开着的机器全干废了，只能退而求其次允许它用其他机器
        if not np.any(combined_masks):
            combined_masks = env_internal_mask

        obs = ai_env._get_obs()
        action = DispatchRules.rule_ai_policy(model, obs=obs, valid_masks=combined_masks)
        current_order = ai_env.logical_orders[ai_env.current_step]
        target_station = physical_stations[action]

        order_info = {
            "order_id": current_order.order_id,
            "target_station": int(action),
            "total_process_time": float(current_order.total_process_time),
            "total_boxes": len(current_order.entities),
            "parts": []
        }

        d_main = Config.get_station_main_distance(action)
        t_main = d_main / Config.BELT_SPEED
        branch_info = Config.get_branch_info(action)
        t_branch = branch_info["transit_time_s"]
        t_trans = t_main + t_branch

        buffer_q = list(ai_env.station_buffers[action]) 
        current_workload = ai_env.station_workloads[action] 
        
        for entity in current_order.entities:
            order_info["parts"].append({
                "entity_id": entity.entity_id,
                "part_type": int(entity.entity_type),
                "quantity": int(entity.qty),
                "process_time": float(entity.p_time)
            })

            if len(buffer_q) >= Config.BUFFER_CAPACITY:
                free_time = buffer_q.pop(0)
                dispatch_time_cursor = max(dispatch_time_cursor + Config.DISPATCH_INTERVAL, free_time - t_trans)
            else:
                dispatch_time_cursor += Config.DISPATCH_INTERVAL
            
            delay_before_launch = max(0, dispatch_time_cursor - sim_env.now)
            
            sim_env.process(
                deliver_box_with_trace(
                    sim_env, target_station, entity.entity_id, delay_before_launch, 
                    t_main, t_branch, entity.p_time, entity.entity_type, logger
                )
            )
            
            arr_time = dispatch_time_cursor + t_trans
            start_p = max(arr_time, current_workload)
            finish_p = start_p + entity.p_time
            buffer_q.append(finish_p)
            current_workload = finish_p 
            
        order_manifest.append(order_info)
        obs, _, done, _, _ = ai_env.step(action)

    active_status = ai_env.station_active_status
    logger.set_power_status(active_status)
    saved_machines_idx = [i for i, status in enumerate(active_status) if status == 0.0]
    final_makespan = np.max(ai_env.station_workloads)

    sim_env.run()
    logger.export_to_json("weichai_ai_animation_script.json")
    
    output_dir = os.path.join(project_root, "output/playbooks")
    manifest_path = os.path.join(output_dir, "weichai_order_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(order_manifest, f, ensure_ascii=False, indent=2)
    print(f"📦 [2/2] 订单档案库已导出至: {manifest_path}")
    
    display_machines = [i + 1 for i in saved_machines_idx]
    
    print("\n" + "="*80)
    print("🏆 【AI 降本增效可视战报】")
    print(f"⏱️ 完工时间: {final_makespan:.1f} 秒 (死线 {Config.DEADLINE_SECONDS}s)")
    print(f"💡 自动为您省下 {len(saved_machines_idx)} 台机床！")
    print(f"🔌 JSON 剧本已写入【断电熄灯】指令的站台: {display_machines}")
    print("="*80)

if __name__ == "__main__":
    export_animation_data()