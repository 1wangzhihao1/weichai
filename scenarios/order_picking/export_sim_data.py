# # 文件路径: scenarios/order_picking/export_sim_data.py

# import sys
# import os
# import json
# import simpy
# import numpy as np
# import copy # 👈 新增引入，用于深拷贝历史事件日志
# from sb3_contrib import MaskablePPO

# # 🌟 寻路雷达
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
# if project_root not in sys.path:
#     sys.path.append(project_root)

# from config import Config
# from core_engine.rules.dispatch_rules import DispatchRules
# from rl_environment import PickingEnv
# from core_engine.models.resource_model import SimpyStation

# class TraceLogger:
#     """剧本场记员：刻录 JSON"""
#     def __init__(self):
#         self.config_data = {
#             "num_stations": int(Config.NUM_STATIONS),
#             "buffer_capacity": int(Config.BUFFER_CAPACITY),
#             "belt_speed": float(Config.BELT_SPEED),
#             "station_distance": float(Config.STATION_DISTANCE),
#             "main_line_offset": float(Config.MAIN_LINE_OFFSET)
#         }
#         self.events = []
#         self.power_status = [] 

#     def set_power_status(self, active_status_array):
#         for i, status in enumerate(active_status_array):
#             self.power_status.append({
#                 "station_id": int(i),
#                 "status": "POWER_ON" if float(status) > 0.0 else "POWER_OFF"
#             })

#     def log_event(self, time: float, entity_id: str, event_type: str, station_id: int, details: dict = None):
#         event = {
#             "time": round(float(time), 2),
#             "entity_id": str(entity_id),
#             "event_type": str(event_type),
#             "station_id": int(station_id)
#         }
#         if details:
#             event["details"] = details
#         self.events.append(event)

#     def export_to_json(self, filename="weichai_ai_animation_script.json"):
#         self.events.sort(key=lambda x: x["time"])
#         output = {
#             "scene_config": self.config_data,
#             "station_power_status": self.power_status, 
#             "total_events": len(self.events),
#             "timeline": self.events
#         }
#         output_dir = os.path.join(project_root, "output/playbooks")
#         os.makedirs(output_dir, exist_ok=True)
#         out_path = os.path.join(output_dir, filename)
        
#         with open(out_path, 'w', encoding='utf-8') as f:
#             json.dump(output, f, ensure_ascii=False, indent=2)
#         print(f"🎬 [1/2] 3D 动画剧本已导出至: {out_path}")

# def deliver_box_with_trace(sim_env, station, box_id, delay, t_main, t_branch, p_time, entity_type, logger):
#     if delay > 0:
#         yield sim_env.timeout(delay)
#     logger.log_event(sim_env.now, box_id, "spawn", station.station_id, {"type": int(entity_type)})
#     yield sim_env.timeout(t_main)
#     logger.log_event(sim_env.now, box_id, "reach_branch", station.station_id)
#     yield sim_env.timeout(t_branch)
#     yield sim_env.process(station.process_box(box_id, p_time, 0.0, entity_type))

# def delayed_breakdown(sim_env, station, trigger_time, repair_time=600):
#     """确保机床在指定的上帝时间精准宕机，彻底解决时空错位问题"""
#     if trigger_time > 0:
#         yield sim_env.timeout(trigger_time)
#     if hasattr(station, 'trigger_breakdown'):
#         station.trigger_breakdown(repair_time=repair_time)

# def auto_search_optimal_stations(model):
#     print("\n🔍 智能排产大模型开始内存预演，探底极限降本方案...")
#     test_env = PickingEnv()
#     best_limit = Config.NUM_STATIONS
#     for limit in range(8, Config.NUM_STATIONS + 1):
#         obs, _ = test_env.reset(seed=999)
#         done = False
#         while not done:
#             mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
#             action, _ = model.predict(obs, action_masks=mask, deterministic=True)
#             obs, _, done, _, _ = test_env.step(int(action))
#         makespan = np.max(test_env.unwrapped.station_workloads)
#         if makespan <= Config.DEADLINE_SECONDS:
#             best_limit = limit
#             print(f"✅ 找到全局最优解！满足交期的最小开机数为：{best_limit} 台！\n")
#             break
#     return best_limit

# # ==============================================================================
# # 🌟 终极修复：接收 breakdown_events 数组，重现所有历史灾难，打通时间线叠加！
# # ==============================================================================
# def export_animation_data(trigger_vip=False, vip_time=0.0, breakdown_events=None):
#     print("="*80)
#     print("🎥 启动 [3D 动画剧本导出工具] (全息多维灾难重演版)...")
#     print("="*80)

#     ai_env = PickingEnv()
#     ai_env.reset(seed=999) 
    
#     model_path = os.path.join(project_root, "output/models/ppo_masking_model_v2_cost_saving")
#     try:
#         model = MaskablePPO.load(model_path)
#     except Exception as e:
#         print(f"⏳ 致命错误：找不到 V2 AI 模型！请确保模型保存在 {model_path}.zip")
#         return

#     optimal_stations = auto_search_optimal_stations(model)
#     energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

#     sim_env = simpy.Environment()
#     logger = TraceLogger()
    
#     physical_stations = [
#         SimpyStation(sim_env, i, Config.BUFFER_CAPACITY, logger) 
#         for i in range(Config.NUM_STATIONS)
#     ]

#     done = False
#     order_manifest = []
    
#     vip_injected = False 
#     dynamic_broken_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

#     # 🌟 核心：将网关传来的灾难日记深拷贝一份，用作“备忘录”，在推演中逐个勾销
#     pending_breakdowns = copy.deepcopy(breakdown_events) if breakdown_events else []

#     print("🧠 正在使用 AI 策略进行物理推演与多维事件融合刻录...")

#     while not done:
#         dispatch_time_cursor = ai_env.last_dispatch_time 

#         # --- ⏳ 时空裂缝 1：精准锚定并重现过去的 VIP 插单 ---
#         if trigger_vip and not vip_injected and dispatch_time_cursor >= vip_time:
#             vip_file_path = os.path.join(project_root, "vip_urgent_order.json")
#             if os.path.exists(vip_file_path):
#                 with open(vip_file_path, 'r', encoding='utf-8') as f:
#                     vip_data_list = json.load(f) 
#             else:
#                 raise FileNotFoundError(f"🚨 致命错误: 未找到 {vip_file_path}！")
            
#             class DummyEntity:
#                 def __init__(self, e_id, e_type, p_time):
#                     self.entity_id, self.entity_type, self.qty, self.p_time = e_id, e_type, 1, p_time
#             class DummyOrder:
#                 def __init__(self, data):
#                     raw_id = str(data.get("vip_order_id", "VIP-999"))
#                     self.order_id = raw_id if "VIP" in raw_id.upper() else f"VIP-{raw_id}"
#                     # 防止 ID 覆盖的唯一序号
#                     self.entities = [
#                         DummyEntity(f"{self.order_id}-P{p['type']}-{i}", p["type"], p["p_time"]) 
#                         for i, p in enumerate(data["parts"])
#                     ]
#                     self.total_process_time = sum(p["p_time"] for p in data["parts"])

#             print(f"\n🔴 [调度中枢] 读取全局记忆，在时空坐标 {vip_time:.1f}s 处成功重现 VIP 插单！")
            
#             for idx, vip_data in enumerate(vip_data_list):
#                 vip_order = DummyOrder(vip_data)
#                 insert_idx = ai_env.current_step + 1 + idx
                
#                 ai_env.logical_orders.insert(insert_idx, vip_order)
#                 if hasattr(ai_env, 'order_process_times'):
#                     if isinstance(ai_env.order_process_times, list):
#                         ai_env.order_process_times.insert(insert_idx, vip_order.total_process_time)
#                     else:
#                         ai_env.order_process_times = np.insert(ai_env.order_process_times, insert_idx, vip_order.total_process_time)
                
#                 if hasattr(ai_env, 'order_box_p_times'):
#                     box_times = [p["p_time"] for p in vip_data["parts"]]
#                     if isinstance(ai_env.order_box_p_times, list):
#                         ai_env.order_box_p_times.insert(insert_idx, box_times)
#                     else:
#                         temp_list = list(ai_env.order_box_p_times)
#                         temp_list.insert(insert_idx, box_times)
#                         ai_env.order_box_p_times = temp_list
                        
#             ai_env.total_orders += len(vip_data_list)
#             vip_injected = True 

#         # ==============================================================================
#         # --- ⏳ 时空裂缝 2：遍历历史灾难日记，到点了就引爆，引爆完就打钩！ ---
#         # ==============================================================================
#         for b_event in pending_breakdowns:
#             # 如果该事件还没触发，并且当前 AI 推演时间已经推进到了该事件发生的时间
#             if not b_event.get("triggered", False) and dispatch_time_cursor >= b_event["time"]:
#                 b_stations = b_event["stations"]
#                 print(f"\n💥 [调度中枢] 时空重现：受损机床: {b_stations} | 触发时点: {b_event['time']:.1f}s")
                
#                 # 1. 更新局部动作掩码黑名单 (永久生效，直到修好，目前假设彻底拉黑)
#                 for sid in b_stations: 
#                     dynamic_broken_mask[sid] = False
                    
#                 # 2. 通知 AI 大脑切断相关路由
#                 if hasattr(ai_env, 'trigger_breakdown'): 
#                     ai_env.trigger_breakdown(b_stations)
                    
#                 # 3. 在物理沙盘的对应上帝时间点，埋下定时炸弹
#                 for sid in b_stations:
#                     if 0 <= sid < Config.NUM_STATIONS: 
#                         sim_env.process(delayed_breakdown(sim_env, physical_stations[sid], b_event["time"], 600))
                        
#                 # 🌟 4. 将这个事件打钩，防止在后续的 while 循环中被重复引爆
#                 b_event["triggered"] = True

#         # ==========================================================
#         # 🌟 三重掩码大一统：AI降本掩码 + 内部动态掩码 + 多重物理宕机掩码
#         # ==========================================================
#         try:
#             env_internal_mask = ai_env.action_masks()
#         except AttributeError:
#             env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
#         combined_masks = np.logical_and(energy_saving_mask, dynamic_broken_mask)
#         combined_masks = np.logical_and(combined_masks, env_internal_mask)
        
#         # 安全兜底：如果宕机把正常开着的机器全干废了，只能退而求其次允许它调用一切没宕机的资源
#         if not np.any(combined_masks):
#             combined_masks = env_internal_mask

#         obs = ai_env._get_obs()
#         action = DispatchRules.rule_ai_policy(model, obs=obs, valid_masks=combined_masks)
#         current_order = ai_env.logical_orders[ai_env.current_step]
#         target_station = physical_stations[action]

#         order_info = {
#             "order_id": current_order.order_id,
#             "target_station": int(action),
#             "total_process_time": float(current_order.total_process_time),
#             "total_boxes": len(current_order.entities),
#             "parts": []
#         }

#         d_main = Config.get_station_main_distance(action)
#         t_main = d_main / Config.BELT_SPEED
#         branch_info = Config.get_branch_info(action)
#         t_branch = branch_info["transit_time_s"]
#         t_trans = t_main + t_branch

#         buffer_q = list(ai_env.station_buffers[action]) 
#         current_workload = ai_env.station_workloads[action] 
        
#         for entity in current_order.entities:
#             order_info["parts"].append({
#                 "entity_id": entity.entity_id,
#                 "part_type": int(entity.entity_type),
#                 "quantity": int(entity.qty),
#                 "process_time": float(entity.p_time)
#             })

#             if len(buffer_q) >= Config.BUFFER_CAPACITY:
#                 free_time = buffer_q.pop(0)
#                 dispatch_time_cursor = max(dispatch_time_cursor + Config.DISPATCH_INTERVAL, free_time - t_trans)
#             else:
#                 dispatch_time_cursor += Config.DISPATCH_INTERVAL
            
#             delay_before_launch = max(0, dispatch_time_cursor - sim_env.now)
            
#             sim_env.process(
#                 deliver_box_with_trace(
#                     sim_env, target_station, entity.entity_id, delay_before_launch, 
#                     t_main, t_branch, entity.p_time, entity.entity_type, logger
#                 )
#             )
            
#             arr_time = dispatch_time_cursor + t_trans
#             start_p = max(arr_time, current_workload)
#             finish_p = start_p + entity.p_time
#             buffer_q.append(finish_p)
#             current_workload = finish_p 
            
#         order_manifest.append(order_info)
#         obs, _, done, _, _ = ai_env.step(action)

#     active_status = ai_env.station_active_status
#     logger.set_power_status(active_status)
#     saved_machines_idx = [i for i, status in enumerate(active_status) if status == 0.0]
#     final_makespan = np.max(ai_env.station_workloads)

#     sim_env.run()
#     logger.export_to_json("weichai_ai_animation_script.json")
    
#     output_dir = os.path.join(project_root, "output/playbooks")
#     manifest_path = os.path.join(output_dir, "weichai_order_manifest.json")
#     with open(manifest_path, "w", encoding="utf-8") as f:
#         json.dump(order_manifest, f, ensure_ascii=False, indent=2)
#     print(f"📦 [2/2] 订单档案库已导出至: {manifest_path}")
    
#     display_machines = [i + 1 for i in saved_machines_idx]
    
#     print("\n" + "="*80)
#     print("🏆 【AI 降本增效可视战报】")
#     print(f"⏱️ 完工时间: {final_makespan:.1f} 秒 (死线 {Config.DEADLINE_SECONDS}s)")
#     print(f"💡 自动为您省下 {len(saved_machines_idx)} 台机床！")
#     print(f"🔌 JSON 剧本已写入【断电熄灯】指令的站台: {display_machines}")
#     print("="*80)

# if __name__ == "__main__":
#     export_animation_data()



# # 文件路径: scenarios/order_picking/export_sim_data.py

# import sys
# import os
# import json
# import simpy
# import numpy as np
# import copy 
# from sb3_contrib import MaskablePPO

# # 🌟 寻路雷达
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
# if project_root not in sys.path:
#     sys.path.append(project_root)

# from config import Config
# from core_engine.rules.dispatch_rules import DispatchRules
# from rl_environment import PickingEnv
# from core_engine.models.resource_model import SimpyStation

# class TraceLogger:
#     """剧本场记员：刻录 JSON 供前端 3D 大屏渲染"""
#     def __init__(self):
#         self.config_data = {
#             "num_stations": int(Config.NUM_STATIONS),
#             # 🌟 兼容前端读取：把最大订单数作为视觉容量传给大屏
#             "buffer_capacity": int(getattr(Config, 'MAX_ORDERS_PER_STATION', 2)), 
#             "belt_speed": float(Config.BELT_SPEED),
#             "station_distance": float(Config.STATION_DISTANCE),
#             "main_line_offset": float(Config.MAIN_LINE_OFFSET)
#         }
#         self.events = []
#         self.power_status = [] 

#     def set_power_status(self, active_status_array):
#         for i, status in enumerate(active_status_array):
#             self.power_status.append({
#                 "station_id": int(i),
#                 "status": "POWER_ON" if float(status) > 0.0 else "POWER_OFF"
#             })

#     def log_event(self, time: float, entity_id: str, event_type: str, station_id: int, details: dict = None):
#         event = {
#             "time": round(float(time), 2),
#             "entity_id": str(entity_id),
#             "event_type": str(event_type),
#             "station_id": int(station_id)
#         }
#         if details:
#             event["details"] = details
#         self.events.append(event)

#     def export_to_json(self, filename="weichai_ai_animation_script.json"):
#         self.events.sort(key=lambda x: x["time"])
#         output = {
#             "scene_config": self.config_data,
#             "station_power_status": self.power_status, 
#             "total_events": len(self.events),
#             "timeline": self.events
#         }
#         output_dir = os.path.join(project_root, "output/playbooks")
#         os.makedirs(output_dir, exist_ok=True)
#         out_path = os.path.join(output_dir, filename)
        
#         with open(out_path, 'w', encoding='utf-8') as f:
#             json.dump(output, f, ensure_ascii=False, indent=2)
#         print(f"🎬 [1/2] 3D 动画剧本已导出至: {out_path}")

# def deliver_box_with_trace(sim_env, station, box_id, order_id, delay, t_main, t_branch, p_time, entity_type, logger):
#     """独立的物理包裹投递进程（记录生命周期）"""
#     if delay > 0:
#         yield sim_env.timeout(delay)
#     logger.log_event(sim_env.now, box_id, "spawn", station.station_id, {"type": int(entity_type)})
    
#     yield sim_env.timeout(t_main)
#     logger.log_event(sim_env.now, box_id, "reach_branch", station.station_id)
    
#     yield sim_env.timeout(t_branch)
    
#     # 🌟 极致鲁棒性兼容：防止你还没更新 resource_model.py 导致缺少 order_id 参数报错
#     try:
#         yield sim_env.process(station.process_box(box_id, order_id, p_time, 0.0, entity_type))
#     except TypeError:
#         yield sim_env.process(station.process_box(box_id, p_time, 0.0, entity_type))

# def delayed_breakdown(sim_env, station, trigger_time, repair_time=600):
#     """确保机床在指定的上帝时间精准宕机，彻底解决时空错位问题"""
#     if trigger_time > 0:
#         yield sim_env.timeout(trigger_time)
#     if hasattr(station, 'trigger_breakdown'):
#         station.trigger_breakdown(repair_time=repair_time)

# def auto_search_optimal_stations(model):
#     print("\n🔍 智能排产大模型开始内存预演，探底极限降本方案...")
#     test_env = PickingEnv()
#     best_limit = Config.NUM_STATIONS
#     for limit in range(8, Config.NUM_STATIONS + 1):
#         obs, _ = test_env.reset(seed=999)
#         done = False
#         while not done:
#             # 结界 1：降本掩码
#             mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
#             # 结界 2：物理防爆仓掩码
#             try:
#                 env_internal_mask = test_env.unwrapped.action_masks()
#             except AttributeError:
#                 env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
#             combined_masks = np.logical_and(mask, env_internal_mask)
#             if not np.any(combined_masks):
#                 combined_masks = mask
                
#             action, _ = model.predict(obs, action_masks=combined_masks, deterministic=True)
#             obs, _, done, _, _ = test_env.step(int(action))
            
#         makespan = np.max(test_env.unwrapped.station_workloads)
#         if makespan <= Config.DEADLINE_SECONDS:
#             best_limit = limit
#             print(f"✅ 找到全局最优解！满足交期的最小开机数为：{best_limit} 台！\n")
#             break
#     return best_limit

# # ==============================================================================
# # 🌟 终极动画导出主轴
# # ==============================================================================
# def export_animation_data(trigger_vip=False, vip_time=0.0, breakdown_events=None):
#     print("="*80)
#     print("🎥 启动 [3D 动画剧本导出工具] (V4 连续发车物理隔离版)...")
#     print("="*80)

#     ai_env = PickingEnv()
#     ai_env.reset(seed=999) 
    
#     # 🌟 核心改动 1：模型读取指向 V4 极品丹药！(附带自动回退逻辑)
#     model_name = "ppo_masking_model_v4_order_level.zip"
#     model_path = os.path.join(project_root, "output/models", model_name)
#     if not os.path.exists(model_path):
#         fallback_path = os.path.join(project_root, "output/models/ppo_masking_model_v3_order_level.zip")
#         if os.path.exists(fallback_path):
#             model_path = fallback_path
#             print("💡 未找到 V4 模型，自动回退加载 V3 存档...")

#     try:
#         model = MaskablePPO.load(model_path)
#     except Exception as e:
#         print(f"⏳ 致命错误：找不到 AI 模型！请确保模型保存在 {model_path}")
#         return

#     optimal_stations = auto_search_optimal_stations(model)
#     energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

#     sim_env = simpy.Environment()
#     logger = TraceLogger()
    
#     physical_stations = [
#         SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2), logger) 
#         for i in range(Config.NUM_STATIONS)
#     ]

#     done = False
#     order_manifest = []
    
#     vip_injected = False 
#     dynamic_broken_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
#     pending_breakdowns = copy.deepcopy(breakdown_events) if breakdown_events else []

#     print("🧠 正在使用 AI 策略进行物理推演与多维事件融合刻录...")

#     while not done:
#         dispatch_time_cursor = ai_env.last_dispatch_time 

#         # --- ⏳ 时空裂缝 1：精准锚定并重现过去的 VIP 插单 ---
#         if trigger_vip and not vip_injected and dispatch_time_cursor >= vip_time:
#             vip_file_path = os.path.join(project_root, "vip_urgent_order.json")
#             if os.path.exists(vip_file_path):
#                 with open(vip_file_path, 'r', encoding='utf-8') as f:
#                     vip_data_list = json.load(f) 
#             else:
#                 raise FileNotFoundError(f"🚨 致命错误: 未找到 {vip_file_path}！")
            
#             class DummyEntity:
#                 def __init__(self, e_id, e_type, p_time):
#                     self.entity_id, self.entity_type, self.qty, self.p_time = e_id, e_type, 1, p_time
#             class DummyOrder:
#                 def __init__(self, data):
#                     raw_id = str(data.get("vip_order_id", "VIP-999"))
#                     self.order_id = raw_id if "VIP" in raw_id.upper() else f"VIP-{raw_id}"
#                     self.entities = [
#                         DummyEntity(f"{self.order_id}-P{p['type']}-{i}", p["type"], p["p_time"]) 
#                         for i, p in enumerate(data["parts"])
#                     ]
#                     self.total_process_time = sum(p["p_time"] for p in data["parts"])

#             print(f"\n🔴 [调度中枢] 读取全局记忆，在时空坐标 {vip_time:.1f}s 处成功重现 VIP 插单！")
            
#             for idx, vip_data in enumerate(vip_data_list):
#                 vip_order = DummyOrder(vip_data)
#                 insert_idx = ai_env.current_step + 1 + idx
                
#                 ai_env.logical_orders.insert(insert_idx, vip_order)
#                 if hasattr(ai_env, 'order_process_times'):
#                     if isinstance(ai_env.order_process_times, list):
#                         ai_env.order_process_times.insert(insert_idx, vip_order.total_process_time)
#                     else:
#                         ai_env.order_process_times = np.insert(ai_env.order_process_times, insert_idx, vip_order.total_process_time)
                
#                 if hasattr(ai_env, 'order_box_p_times'):
#                     box_times = [p["p_time"] for p in vip_data["parts"]]
#                     if isinstance(ai_env.order_box_p_times, list):
#                         ai_env.order_box_p_times.insert(insert_idx, box_times)
#                     else:
#                         temp_list = list(ai_env.order_box_p_times)
#                         temp_list.insert(insert_idx, box_times)
#                         ai_env.order_box_p_times = temp_list
                        
#             ai_env.total_orders += len(vip_data_list)
#             vip_injected = True 

#         # --- ⏳ 时空裂缝 2：重现宕机日记 ---
#         for b_event in pending_breakdowns:
#             if not b_event.get("triggered", False) and dispatch_time_cursor >= b_event["time"]:
#                 b_stations = b_event["stations"]
#                 print(f"\n💥 [调度中枢] 时空重现：受损机床: {b_stations} | 触发时点: {b_event['time']:.1f}s")
                
#                 for sid in b_stations: 
#                     dynamic_broken_mask[sid] = False
                    
#                 if hasattr(ai_env, 'trigger_breakdown'): 
#                     ai_env.trigger_breakdown(b_stations)
                    
#                 for sid in b_stations:
#                     if 0 <= sid < Config.NUM_STATIONS: 
#                         sim_env.process(delayed_breakdown(sim_env, physical_stations[sid], b_event["time"], 600))
                        
#                 b_event["triggered"] = True

#         # ==========================================================
#         # 🌟 三重掩码大一统：降本关机 + 突发宕机 + 物理防爆安检门
#         # ==========================================================
#         try:
#             env_internal_mask = ai_env.action_masks()
#         except AttributeError:
#             env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
#         combined_masks = np.logical_and(energy_saving_mask, dynamic_broken_mask)
#         combined_masks = np.logical_and(combined_masks, env_internal_mask)
        
#         # 安全兜底：如果没机器可选了，必须降级开放
#         if not np.any(combined_masks):
#             combined_masks = np.logical_and(energy_saving_mask, dynamic_broken_mask)
#             if not np.any(combined_masks):
#                 combined_masks = energy_saving_mask

#         obs = ai_env._get_obs()
#         action = DispatchRules.rule_ai_policy(model, obs=obs, valid_masks=combined_masks)
#         current_order = ai_env.logical_orders[ai_env.current_step]
#         target_station = physical_stations[action]

#         order_info = {
#             "order_id": current_order.order_id,
#             "target_station": int(action),
#             "total_process_time": float(current_order.total_process_time),
#             "total_boxes": len(current_order.entities),
#             "parts": []
#         }

#         d_main = Config.get_station_main_distance(action)
#         t_main = d_main / Config.BELT_SPEED
#         branch_info = Config.get_branch_info(action)
#         t_branch = branch_info["transit_time_s"]

#         # ==========================================================
#         # 🌟 核心改动 3：物理沙盘时钟对齐 AI 的订单级死等死锁
#         # ==========================================================
#         local_cursor = dispatch_time_cursor
        
#         # 精准模拟 AI 脑海中的等位逻辑：如果这台机器已经挂了 2 个订单，必须死等
#         if hasattr(ai_env, 'station_active_orders'):
#             active_orders = [t for t in ai_env.station_active_orders[action] if t > local_cursor]
#             max_orders = getattr(Config, 'MAX_ORDERS_PER_STATION', 2)
#             if len(active_orders) >= max_orders:
#                 # 传送带拉手刹，等待第一个订单完工腾出坑位
#                 local_cursor = max(local_cursor, active_orders[0])
        
#         # 订单中的四个零件箱【首尾相连】连续发车
#         for entity in current_order.entities:
#             order_info["parts"].append({
#                 "entity_id": entity.entity_id,
#                 "part_type": int(entity.entity_type),
#                 "quantity": int(entity.qty),
#                 "process_time": float(entity.p_time)
#             })

#             local_cursor += Config.DISPATCH_INTERVAL
#             delay_before_launch = max(0, local_cursor - sim_env.now)
            
#             # 将每个箱子的生命周期任务丢给物理引擎
#             sim_env.process(
#                 deliver_box_with_trace(
#                     sim_env, target_station, entity.entity_id, current_order.order_id, delay_before_launch, 
#                     t_main, t_branch, entity.p_time, entity.entity_type, logger
#                 )
#             )
            
#         order_manifest.append(order_info)
        
#         # 时空大一统：执行 AI 的环境推演 (内部自带时间计算，与我们刚刚的计算完美一致)
#         obs, _, done, _, _ = ai_env.step(action)

#     active_status = ai_env.station_active_status
#     logger.set_power_status(active_status)
#     saved_machines_idx = [i for i, status in enumerate(active_status) if status == 0.0]
#     final_makespan = np.max(ai_env.station_workloads)

#     # 启动物理时间引擎流逝，触发所有预埋的事件
#     sim_env.run()
    
#     logger.export_to_json("weichai_ai_animation_script.json")
    
#     output_dir = os.path.join(project_root, "output/playbooks")
#     manifest_path = os.path.join(output_dir, "weichai_order_manifest.json")
#     with open(manifest_path, "w", encoding="utf-8") as f:
#         json.dump(order_manifest, f, ensure_ascii=False, indent=2)
#     print(f"📦 [2/2] 订单档案库已导出至: {manifest_path}")
    
#     display_machines = [i + 1 for i in saved_machines_idx]
    
#     print("\n" + "="*80)
#     print("🏆 【AI 降本增效 3D 可视战报】")
#     print(f"⏱️ 完工时间: {final_makespan:.1f} 秒 (死线 {Config.DEADLINE_SECONDS}s)")
#     print(f"💡 效率提升超越甲方要求，并自动为您省下 {len(saved_machines_idx)} 台机床！")
#     print(f"🔌 JSON 剧本已写入【断电熄灯】指令的站台: {display_machines}")
#     print("="*80)

# if __name__ == "__main__":
#     # 如果想看纯净版动画，直接调用；如果想看灾难版，可以传入 breakdown_events
#     export_animation_data()



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
            # 🌟 核心修复：对齐最新的订单防爆容量，弃用旧的 BUFFER_CAPACITY
            "buffer_capacity": int(getattr(Config, 'MAX_ORDERS_PER_STATION', 2)), 
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

def deliver_box_with_trace(sim_env, station, box_id, order_id, delay, t_main, t_branch, p_time, entity_type, logger):
    """独立的物理包裹投递进程"""
    if delay > 0:
        yield sim_env.timeout(delay)
    logger.log_event(sim_env.now, box_id, "spawn", station.station_id, {"type": int(entity_type)})
    
    yield sim_env.timeout(t_main)
    logger.log_event(sim_env.now, box_id, "reach_branch", station.station_id)
    
    yield sim_env.timeout(t_branch)
    
    # 兼容处理 order_id 参数
    try:
        yield sim_env.process(station.process_box(box_id, order_id, p_time, 0.0, entity_type))
    except TypeError:
        yield sim_env.process(station.process_box(box_id, p_time, 0.0, entity_type))

def auto_search_optimal_stations(model):
    print("\n🔍 智能排产大模型开始内存预演，探底极限降本方案...")
    test_env = PickingEnv()
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
            
        makespan = np.max(test_env.unwrapped.station_workloads)
        if makespan <= Config.DEADLINE_SECONDS:
            best_limit = limit
            print(f"✅ 找到全局最优解！满足交期的最小开机数为：{best_limit} 台！\n")
            break
    return best_limit

# ==============================================================================
# 🌟 极速纯净版：移除了所有宕机与插单事件，专注最优排产链路与连续发车
# ==============================================================================
def export_animation_data():
    print("="*80)
    print("🎥 启动 [3D 动画剧本导出工具] (极速洁净防爆版)...")
    print("="*80)

    ai_env = PickingEnv()
    ai_env.reset(seed=999) 
    
    # 优先加载 v4 极品大脑
    model_name = "ppo_masking_model_v4_order_level.zip"
    model_path = os.path.join(project_root, "output/models", model_name)
    if not os.path.exists(model_path):
        fallback_path = os.path.join(project_root, "output/models/ppo_masking_model_v3_order_level.zip")
        if os.path.exists(fallback_path):
            model_path = fallback_path
            print("💡 未找到 V4 模型，自动回退加载 V3 存档...")

    try:
        model = MaskablePPO.load(model_path)
    except Exception as e:
        print(f"⏳ 致命错误：找不到 AI 模型！请确保模型保存在 {model_path}")
        return

    optimal_stations = auto_search_optimal_stations(model)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

    sim_env = simpy.Environment()
    logger = TraceLogger()
    
    # 初始化物理站台，使用最新的容量参数
    physical_stations = [
        SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2), logger) 
        for i in range(Config.NUM_STATIONS)
    ]

    done = False
    order_manifest = []
    
    print("🧠 正在使用 AI 策略进行物理推演与剧本刻录...")

    while not done:
        dispatch_time_cursor = ai_env.last_dispatch_time 

        try:
            env_internal_mask = ai_env.action_masks()
        except AttributeError:
            env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
        combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
        
        if not np.any(combined_masks):
            combined_masks = energy_saving_mask

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

        # ==========================================================
        # 🌟 核心：订单级物理死等与首尾相连连续发车
        # ==========================================================
        local_cursor = dispatch_time_cursor
        
        if hasattr(ai_env, 'station_active_orders'):
            active_orders = [t for t in ai_env.station_active_orders[action] if t > local_cursor]
            max_orders = getattr(Config, 'MAX_ORDERS_PER_STATION', 2)
            if len(active_orders) >= max_orders:
                # 传送带拉手刹，死等第一个订单完工腾出坑位
                local_cursor = max(local_cursor, active_orders[0])
        
        for entity in current_order.entities:
            order_info["parts"].append({
                "entity_id": entity.entity_id,
                "part_type": int(entity.entity_type),
                "quantity": int(entity.qty),
                "process_time": float(entity.p_time)
            })

            local_cursor += Config.DISPATCH_INTERVAL
            delay_before_launch = max(0, local_cursor - sim_env.now)
            
            sim_env.process(
                deliver_box_with_trace(
                    sim_env, target_station, entity.entity_id, current_order.order_id, delay_before_launch, 
                    t_main, t_branch, entity.p_time, entity.entity_type, logger
                )
            )
            
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
    print("🏆 【AI 降本增效 3D 可视战报 (极速纯净版)】")
    print(f"⏱️ 完工时间: {final_makespan:.1f} 秒 (死线 {Config.DEADLINE_SECONDS}s)")
    print(f"💡 自动为您省下 {len(saved_machines_idx)} 台机床！")
    print(f"🔌 JSON 剧本已写入【断电熄灯】指令的站台: {display_machines}")
    print("="*80)

if __name__ == "__main__":
    export_animation_data()