



# # 文件路径: backend/server.py

# import os
# import sys
# import datetime
# import numpy as np
# import uvicorn
# import simpy
# from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List

# # 🌟 引入 TensorBoard 解析器，用于前端实时监控大屏
# from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# # 🌟 寻路雷达
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
# if project_root not in sys.path:
#     sys.path.append(project_root)

# scenario_dir = os.path.join(project_root, 'scenarios', 'order_picking')
# if scenario_dir not in sys.path:
#     sys.path.append(scenario_dir)

# from config import Config
# from database import SessionLocal, OrderPool, OrderBOM, SimulationTask, PartMaster, DispatchResult
# from sb3_contrib import MaskablePPO
# from scenarios.order_picking.rl_environment import PickingEnv
# from core_engine.models.entity_model import LogicalOrder, PhysicalEntity
# from core_engine.rules.dispatch_rules import DispatchRules
# from core_engine.models.resource_model import SimpyStation

# app = FastAPI(title="Weichai APS AI 智能排产网关")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"], 
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# TASK_PROGRESS = {}

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

# class PartMasterItem(BaseModel):
#     part_type: str
#     part_name: str
#     process_time: float

# class PartMasterBatch(BaseModel):
#     parts: List[PartMasterItem]

# class OrderItem(BaseModel):
#     order_id: str
#     priority: int = 1
#     part_type: str
#     quantity: int

# class OrderBatch(BaseModel):
#     batch_no: str
#     orders: List[OrderItem]

# class SimulationRequest(BaseModel):
#     batch_no: str

# class DummyLogger:
#     """给 SimpyStation 用的哑巴日志器，在服务端只写库不写本地文件"""
#     def log_event(self, *args, **kwargs):
#         pass
#     def set_power_status(self, *args, **kwargs):
#         pass

# # ==========================================
# # 🌟 原汁原味的剧本刻录引擎 (对齐 V4 连续发车 + 物理锁死等)
# # ==========================================
# def deliver_with_db_log(env, station, box_id, order_id, p_time, t_main, t_branch, part_type, dispatch_records, task_id, base_time, delay_before_launch):
#     """带数据库记录的独立物理包裹投递进程"""
#     # 1. 延迟发车 (连续发车的时空控制点)
#     if delay_before_launch > 0:
#         yield env.timeout(delay_before_launch)
        
#     spawn_env_time = env.now
    
#     # 2. 跑主线和支线
#     yield env.timeout(t_main)
#     yield env.timeout(t_branch)
    
#     # 🌟 3. 物理单线程锁！必须在这里排队死等机床空闲落刀！
#     with station.machine_lock.request() as req:
#         yield req
#         start_env_time = env.now 
        
#         # 兼容最新版资源模型 (带有 order_id 追踪)
#         try:
#             yield env.process(station.process_box(box_id, order_id, p_time, 0, part_type))
#         except TypeError:
#             yield env.process(station.process_box(box_id, p_time, 0, part_type))
            
#         end_env_time = env.now   
    
#     # 转化为真实日期格式并写入数据库
#     spawn_dt = base_time + datetime.timedelta(seconds=float(spawn_env_time))
#     start_dt = base_time + datetime.timedelta(seconds=float(start_env_time))
#     end_dt = base_time + datetime.timedelta(seconds=float(end_env_time))
    
#     dispatch_records.append(
#         DispatchResult(
#             task_id=task_id,
#             order_id=order_id,
#             box_id=box_id,
#             target_station=station.station_id + 1,  
#             predicted_spawn_time=spawn_dt, 
#             predicted_start_time=start_dt,
#             predicted_end_time=end_dt
#         )
#     )

# def simpy_dispatch_engine(env, stations, rl_env, model, optimal_stations, dispatch_records, task_id, base_time):
#     """【大一统主引擎】：完美 1:1 复刻前端导出的推演逻辑"""
#     obs, _ = rl_env.reset(seed=999)
#     energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))

#     done = False
#     while not done:
#         dispatch_time_cursor = rl_env.unwrapped.last_dispatch_time 

#         try:
#             env_internal_mask = rl_env.unwrapped.action_masks()
#         except AttributeError:
#             env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
#         combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
#         if not np.any(combined_masks):
#             combined_masks = energy_saving_mask

#         obs_state = rl_env.unwrapped._get_obs()
#         action = DispatchRules.rule_ai_policy(model, obs=obs_state, valid_masks=combined_masks)
#         current_order = rl_env.unwrapped.logical_orders[rl_env.unwrapped.current_step]
#         target_station = stations[action]

#         d_main = Config.get_station_main_distance(action)
#         t_main = d_main / Config.BELT_SPEED
#         branch_info = Config.get_branch_info(action)
#         t_branch = branch_info["transit_time_s"]

#         # AI 的防爆仓死等预判机制
#         local_cursor = dispatch_time_cursor
#         if hasattr(rl_env.unwrapped, 'station_active_orders'):
#             active_orders = [t for t in rl_env.unwrapped.station_active_orders[action] if t > local_cursor]
#             max_orders = getattr(Config, 'MAX_ORDERS_PER_STATION', 2)
#             if len(active_orders) >= max_orders:
#                 # 传送带拉手刹，死等
#                 local_cursor = max(local_cursor, active_orders[0])
        
#         # 订单零件【首尾相连】连续发车
#         for entity in current_order.entities:
#             local_cursor += Config.DISPATCH_INTERVAL
#             delay_before_launch = max(0, local_cursor - env.now)
            
#             env.process(
#                 deliver_with_db_log(
#                     env, target_station, entity.entity_id, current_order.order_id, 
#                     entity.p_time, t_main, t_branch, entity.entity_type, 
#                     dispatch_records, task_id, base_time, delay_before_launch
#                 )
#             )
            
#         obs, _, done, _, _ = rl_env.step(action)

#     # 阻塞主线程，必须等所有机床干完活再收工！
#     while any(s.machine_lock.count > 0 or len(s.machine_lock.queue) > 0 for s in stations):
#         yield env.timeout(1.0)


# # ==========================================
# # ⚙️ 核心异步推演微服务
# # ==========================================
# def run_simulation_task(task_id: str, batch_no: str):
#     db = SessionLocal()
#     try:
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "10%", "message": "正在加载最新订单库..."}
        
#         db_orders = db.query(OrderPool).filter(OrderPool.batch_no == batch_no).order_by(OrderPool.order_id).all()
#         if not db_orders:
#             raise ValueError(f"批次 {batch_no} 下无订单数据")
            
#         order_ids = [o.order_id for o in db_orders]
#         all_boms = db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).all()
#         bom_dict = {}
#         for bom in all_boms:
#             bom_dict.setdefault(bom.order_id, []).append(bom)

#         all_parts = db.query(PartMaster).all()
#         part_time_dict = {p.part_type: float(p.standard_p_time) for p in all_parts}
            
#         logical_orders = []
#         for d_order in db_orders:
#             boms = bom_dict.get(d_order.order_id, [])
#             entities = []
#             for bom in boms:
#                 clean_id = bom.part_type.replace('零件', '')
#                 actual_p_time = part_time_dict.get(clean_id, 45.0)
#                 entity = PhysicalEntity(
#                     entity_id=f"{d_order.order_id}-P{clean_id}",
#                     entity_type=int(clean_id),
#                     qty=bom.quantity,
#                     single_p_time=actual_p_time
#                 )
#                 entity.p_time = actual_p_time * bom.quantity
#                 entities.append(entity)
            
#             l_order = LogicalOrder(d_order.order_id)
#             l_order.entities = entities
#             l_order.total_process_time = sum(e.p_time for e in entities)
#             logical_orders.append(l_order)

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "20%", "message": "正在装载最优 V4 炼丹权重..."}

#         rl_env = PickingEnv()
#         rl_env.real_world_orders = logical_orders
#         rl_env.total_orders = len(logical_orders)
        
#         # 🌟 自动回退策略：优先找 v4，找不到找 v3
#         model_name = "ppo_masking_model_v4_order_level.zip"
#         model_path = os.path.join(project_root, "output/models", model_name)
#         if not os.path.exists(model_path):
#             fallback_path = os.path.join(project_root, "output/models/ppo_masking_model_v3_order_level.zip")
#             if os.path.exists(fallback_path):
#                 model_path = fallback_path
                
#         model = MaskablePPO.load(model_path, env=rl_env)

#         # 🌟 离线微秒级对标推演器 (高速计算时间线)
#         def fast_macro_simulate(strategy, limit):
#             obs, _ = rl_env.reset(seed=999)
#             done = False
#             step_count = 0
#             while not done:
#                 mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
#                 if strategy == "ai":
#                     try:
#                         env_mask = rl_env.unwrapped.action_masks()
#                     except AttributeError:
#                         env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
#                     combined_mask = np.logical_and(mask, env_mask)
#                     if not np.any(combined_mask):
#                         combined_mask = mask 
#                     action, _ = model.predict(obs, action_masks=combined_mask, deterministic=True)
#                     action = int(action)
#                 elif strategy == "round_robin":
#                     action = step_count % limit
#                 elif strategy == "random":
#                     action = np.random.randint(0, limit)
                    
#                 obs, _, done, _, _ = rl_env.step(int(action))
#                 step_count += 1
#             return float(np.max(rl_env.unwrapped.station_workloads))

#         # 🌟 最优解探测器
#         def find_optimal(strategy):
#             best_limit = Config.NUM_STATIONS
#             best_ms = 0
#             for limit in range(Config.NUM_STATIONS, 0, -1):
#                 ms = fast_macro_simulate(strategy, limit)
#                 if ms <= Config.DEADLINE_SECONDS:
#                     best_limit = limit
#                     best_ms = ms
#                 else:
#                     if limit == Config.NUM_STATIONS:
#                         best_ms = ms 
#                     break 
#             return best_limit, best_ms

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "30%", "message": "【第一局】计算随机分发耗时上限..."}
#         rand_st, rand_tm = find_optimal("random")

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "50%", "message": "【第二局】计算传统轮询耗时中位数..."}
#         trad_st, trad_tm = find_optimal("round_robin")

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "70%", "message": "【第三局】强化学习引擎极限压榨..."}
#         ai_st, ai_tm = find_optimal("ai")

#         # =========================================================
#         # 🌟 刻录最终落地剧本！
#         # =========================================================
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "85%", "message": "已找到最优解！正在封版数据库剧本..."}
        
#         sim_env = simpy.Environment()
#         dummy_logger = DummyLogger()
        
#         # 统一使用 MAX_ORDERS_PER_STATION 防止报错
#         physical_stations = [SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2), dummy_logger) for i in range(Config.NUM_STATIONS)]
        
#         # 给每台机床强行加锁
#         for s in physical_stations:
#             s.machine_lock = simpy.Resource(sim_env, capacity=1)
            
#         dispatch_records = []
#         base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        
#         sim_env.process(simpy_dispatch_engine(sim_env, physical_stations, rl_env, model, ai_st, dispatch_records, task_id, base_time))
#         sim_env.run()

#         ai_real_makespan = float(sim_env.now)

#         db.add_all(dispatch_records)
#         db.add(SimulationTask(task_id=task_id+"-RAND", batch_no=batch_no, strategy_type="RANDOM", active_stations=rand_st, total_makespan_sec=rand_tm))
#         db.add(SimulationTask(task_id=task_id+"-TRAD", batch_no=batch_no, strategy_type="TRADITIONAL", active_stations=trad_st, total_makespan_sec=trad_tm))
#         db.add(SimulationTask(task_id=task_id+"-AI", batch_no=batch_no, strategy_type="AI_RL", active_stations=ai_st, total_makespan_sec=ai_real_makespan))
#         db.commit()

#         if rand_st * rand_tm > 0:
#             # 严格按照甲方最新要求，对比随机分发策略
#             eff = (1 - (ai_st * ai_real_makespan) / (rand_st * rand_tm)) * 100
#         else:
#             eff = 0.0

#         TASK_PROGRESS[task_id] = {
#             "status": "completed", 
#             "progress": "100%", 
#             "deadline": Config.DEADLINE_SECONDS,
#             "ai_result": {"active_stations": ai_st, "total_makespan": round(ai_real_makespan, 2)},
#             "trad_result": {"active_stations": trad_st, "total_makespan": round(trad_tm, 2)},
#             "rand_result": {"active_stations": rand_st, "total_makespan": round(rand_tm, 2)},
#             "efficiency_up": f"{eff:.2f}%"
#         }

#     except Exception as e:
#         db.rollback()
#         TASK_PROGRESS[task_id] = {"status": "failed", "message": str(e)}
#     finally:
#         db.close()

# # ==========================================
# # 🔌 API 路由
# # ==========================================

# @app.post("/api/v1/master_data/upload")
# def upload_part_master(data: PartMasterBatch, db: SessionLocal = Depends(get_db)):
#     try:
#         for item in data.parts:
#             clean_id = item.part_type.replace('零件', '')
#             existing = db.query(PartMaster).filter(PartMaster.part_type == clean_id).first()
#             if existing: existing.standard_p_time = item.process_time
#             else: db.add(PartMaster(part_type=clean_id, standard_p_time=item.process_time))
#         db.commit()
#         return {"code": 200, "message": "工艺标准同步成功"}
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/v1/orders/upload")
# def upload_orders(batch_data: OrderBatch, db: SessionLocal = Depends(get_db)):
#     try:
#         unique_order_ids = list(set([item.order_id for item in batch_data.orders]))
#         db.query(OrderBOM).filter(OrderBOM.order_id.in_(unique_order_ids)).delete(synchronize_session=False)
#         db.flush() 
#         for o_id in unique_order_ids:
#             exists = db.query(OrderPool).filter(OrderPool.order_id == o_id).first()
#             if not exists:
#                 prio = next((x.priority for x in batch_data.orders if x.order_id == o_id), 1)
#                 db.add(OrderPool(order_id=o_id, batch_no=batch_data.batch_no, priority_level=prio))
#         for item in batch_data.orders:
#             db.add(OrderBOM(order_id=item.order_id, part_type=item.part_type, quantity=item.quantity))
#         db.commit()
#         return {"code": 200, "message": f"成功重置 {len(unique_order_ids)} 个订单的数据！"}
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/v1/simulation/start")
# def start_simulation(req: SimulationRequest, bg_tasks: BackgroundTasks):
#     task_id = f"TASK-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
#     bg_tasks.add_task(run_simulation_task, task_id, req.batch_no)
#     return {"code": 200, "task_id": task_id}

# @app.get("/api/v1/simulation/status/{task_id}")
# def get_status(task_id: str):
#     if task_id not in TASK_PROGRESS:
#         raise HTTPException(status_code=404, detail="任务不存在")
#     return {"code": 200, "data": TASK_PROGRESS[task_id]}

# @app.get("/api/v1/simulation/playbook/{task_id}")
# def get_simulation_playbook(task_id: str, db: SessionLocal = Depends(get_db)):
#     try:
#         ai_task_id = f"{task_id}-AI"
#         task_info = db.query(SimulationTask).filter(SimulationTask.task_id == ai_task_id).first()
#         if not task_info: raise HTTPException(status_code=404, detail="未找到任务宏观战报")
            
#         records = db.query(DispatchResult).filter(DispatchResult.task_id == task_id).order_by(DispatchResult.predicted_spawn_time).all()
#         if not records: raise HTTPException(status_code=404, detail="未找到派工明细")

#         playbook = {
#             "task_id": task_id,
#             "strategy": "AI_RL",
#             "active_stations": task_info.active_stations,
#             "total_makespan_sec": task_info.total_makespan_sec,
#             "total_boxes": len(records),
#             "timeline": [
#                 {
#                     "order_id": r.order_id,
#                     "box_id": r.box_id,
#                     "target_station": r.target_station,
#                     "spawn_time": r.predicted_spawn_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(r, 'predicted_spawn_time') and r.predicted_spawn_time else r.predicted_start_time.strftime("%Y-%m-%d %H:%M:%S"),
#                     "start_time": r.predicted_start_time.strftime("%Y-%m-%d %H:%M:%S"),
#                     "end_time": r.predicted_end_time.strftime("%Y-%m-%d %H:%M:%S"),
#                     "duration_sec": (r.predicted_end_time - r.predicted_start_time).total_seconds()
#                 } for r in records
#             ]
#         }
#         return {"code": 200, "data": playbook}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# # ==========================================
# # 🌟 前端直连 TensorBoard 训练监控接口 (动态寻址防报错版)
# # ==========================================
# @app.get("/api/v1/model/training_metrics")
# def get_training_metrics():
#     try:
#         base_dir = os.path.join(project_root, "scenarios", "order_picking")
        
#         # 🌟 核心修复：自动模糊搜索最新的 TensorBoard 目录，不限死 v2 或 v4
#         tb_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if d.startswith("ppo_tensorboard_logs") and os.path.isdir(os.path.join(base_dir, d))]
        
#         if not tb_dirs:
#             return {"code": 404, "message": "未找到任何训练日志根目录 (ppo_tensorboard_logs*)"}
            
#         # 挑选修改时间最新的主目录
#         latest_tb_dir = max(tb_dirs, key=os.path.getmtime)

#         # 找里面的子文件夹 (如 MaskablePPO_0)
#         subdirs = [os.path.join(latest_tb_dir, d) for d in os.listdir(latest_tb_dir) if os.path.isdir(os.path.join(latest_tb_dir, d))]
        
#         if subdirs:
#             log_dir = max(subdirs, key=os.path.getmtime) 
#         else:
#             log_dir = latest_tb_dir 

#         print(f"\n🔍 [探照灯] 正在精准读取最新子日志目录: {log_dir}")
        
#         event_acc = EventAccumulator(log_dir)
#         event_acc.Reload() 

#         target_tag = 'rollout/ep_rew_mean' 
#         tags = event_acc.Tags().get('scalars', [])
        
#         if target_tag not in tags:
#             print(f"❌ [报错] 目录找到了，但里面没有 Reward 数据！")
#             return {"code": 404, "message": f"在 {os.path.basename(log_dir)} 中未找到 Reward 数据"}

#         print("✅ [成功] 完美读取到 TensorBoard 数据，正在发送给大屏...")
#         events = event_acc.Scalars(target_tag)
#         steps, rewards = [], []
#         sample_rate = max(1, len(events) // 100) 
        
#         for i, event in enumerate(events):
#             if i % sample_rate == 0 or i == len(events) - 1:
#                 step_str = f"{event.step / 10000:.1f}万" if event.step >= 10000 else str(event.step)
#                 steps.append(step_str)
#                 rewards.append(round(event.value, 2))

#         return {"code": 200, "data": {"steps": steps, "rewards": rewards}}
        
#     except Exception as e:
#         print(f"💥 [崩溃] 日志解析发生未知错误: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"日志解析失败: {str(e)}")

# if __name__ == "__main__":
#     uvicorn.run("server:app", host="0.0.0.0", port=8088, reload=True)





# 文件路径: backend/server.py

import os
import sys
import datetime
import numpy as np
import uvicorn
import simpy
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# 🌟 寻路雷达
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
if project_root not in sys.path:
    sys.path.append(project_root)

scenario_dir = os.path.join(project_root, 'scenarios', 'order_picking')
if scenario_dir not in sys.path:
    sys.path.append(scenario_dir)

from config import Config
from database import SessionLocal, OrderPool, OrderBOM, SimulationTask, PartMaster, DispatchResult
from sb3_contrib import MaskablePPO
from scenarios.order_picking.rl_environment import PickingEnv
from core_engine.models.entity_model import LogicalOrder, PhysicalEntity
from core_engine.rules.dispatch_rules import DispatchRules
from core_engine.models.resource_model import SimpyStation

app = FastAPI(title="Weichai APS AI 智能排产网关")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASK_PROGRESS = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PartMasterItem(BaseModel):
    part_type: str
    part_name: str
    process_time: float

class PartMasterBatch(BaseModel):
    parts: List[PartMasterItem]

class OrderItem(BaseModel):
    order_id: str
    priority: int = 1
    part_type: str
    quantity: int

class OrderBatch(BaseModel):
    batch_no: str
    orders: List[OrderItem]

class SimulationRequest(BaseModel):
    batch_no: str

# =======================================================
# 🌟 终极修复：数据库日志截获器 (对标 export_sim_data.py)
# =======================================================
class DBLogger:
    """窃听 SimpyStation 的事件，自动记录出真实的 ISO 时间，无需强接管！"""
    def __init__(self, dispatch_records, task_id, base_time):
        self.dispatch_records = dispatch_records
        self.task_id = task_id
        self.base_time = base_time
        self.temp_records = {} # {box_id: {spawn, start, station, order}}

    def log_event(self, time, entity_id, event_type, station_id, details=None):
        if event_type == "spawn":
            self.temp_records[entity_id] = {
                "spawn_env_time": time, 
                "target_station": station_id,
                "order_id": details.get("order_id", "") if details else ""
            }
        elif event_type == "start_process":
            if entity_id in self.temp_records:
                self.temp_records[entity_id]["start_env_time"] = time
        elif event_type == "end_process":
            if entity_id in self.temp_records:
                record = self.temp_records[entity_id]
                end_env_time = time
                
                # 转换微秒级真实时间
                spawn_dt = self.base_time + datetime.timedelta(seconds=float(record["spawn_env_time"]))
                start_dt = self.base_time + datetime.timedelta(seconds=float(record["start_env_time"]))
                end_dt = self.base_time + datetime.timedelta(seconds=float(end_env_time))
                
                self.dispatch_records.append(
                    DispatchResult(
                        task_id=self.task_id,
                        order_id=record["order_id"],
                        box_id=entity_id,
                        target_station=record["target_station"] + 1,
                        predicted_spawn_time=spawn_dt,
                        predicted_start_time=start_dt,
                        predicted_end_time=end_dt
                    )
                )
                del self.temp_records[entity_id]

    def set_power_status(self, *args, **kwargs):
        pass

def launch_box(env, station, box_id, order_id, p_time, t_trans, entity_type, logger, delay):
    """一个小型引导舱，用于记录 spawn (出生) 时间，随后放行给 Station 处理"""
    if delay > 0:
        yield env.timeout(delay)
    if logger:
        logger.log_event(env.now, box_id, "spawn", station.station_id, {"order_id": order_id})
        
    # 彻底交出控制权，让 SimpyStation 发挥其本能！
    yield env.process(station.process_box(box_id, order_id, p_time, t_trans, entity_type))


def simpy_dispatch_engine(env, stations, rl_env, model, optimal_stations, dispatch_records, task_id, base_time):
    """AI 大脑驱动器：负责把指令下发给 Simpy 物理引擎"""
    db_logger = DBLogger(dispatch_records, task_id, base_time)
    for s in stations:
        s.logger = db_logger
        
    obs, _ = rl_env.reset(seed=999)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))
    
    done = False
    while not done:
        dispatch_time_cursor = rl_env.unwrapped.last_dispatch_time 
        try: env_internal_mask = rl_env.unwrapped.action_masks()
        except AttributeError: env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
        combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
        if not np.any(combined_masks): combined_masks = energy_saving_mask

        obs_state = rl_env.unwrapped._get_obs()
        action = int(DispatchRules.rule_ai_policy(model, obs=obs_state, valid_masks=combined_masks))
        current_order = rl_env.unwrapped.logical_orders[rl_env.unwrapped.current_step]
        target_station = stations[action]

        d_main = Config.get_station_main_distance(action)
        t_trans = (d_main / Config.BELT_SPEED) + Config.get_branch_info(action)["transit_time_s"]

        local_cursor = dispatch_time_cursor
        if hasattr(rl_env.unwrapped, 'station_active_orders'):
            active_orders = [t for t in rl_env.unwrapped.station_active_orders[action] if t > local_cursor]
            if len(active_orders) >= getattr(Config, 'MAX_ORDERS_PER_STATION', 2):
                local_cursor = max(local_cursor, active_orders[0])
        
        # 将每个包裹推入物理宇宙！
        for entity in current_order.entities:
            local_cursor += Config.DISPATCH_INTERVAL
            delay_before_launch = max(0, local_cursor - env.now)
            env.process(launch_box(
                env, target_station, entity.entity_id, current_order.order_id, 
                entity.p_time, t_trans, entity.entity_type, 
                db_logger, delay_before_launch
            ))
        obs, _, done, _, _ = rl_env.step(action)
        
    # 等待所有站台都把手头的包裹处理完再退出
    while any(s.machine.count > 0 or len(s.machine.queue) > 0 for s in stations):
        yield env.timeout(1.0)


def run_simulation_task(task_id: str, batch_no: str):
    db = SessionLocal()
    try:
        TASK_PROGRESS[task_id] = {"status": "running", "progress": "10%", "message": "正在加载最新订单库..."}
        db_orders = db.query(OrderPool).filter(OrderPool.batch_no == batch_no).order_by(OrderPool.order_id).all()
        if not db_orders: raise ValueError(f"批次 {batch_no} 下无订单数据")
            
        order_ids = [o.order_id for o in db_orders]
        all_boms = db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).all()
        bom_dict = {}
        for bom in all_boms: bom_dict.setdefault(bom.order_id, []).append(bom)

        all_parts = db.query(PartMaster).all()
        part_time_dict = {p.part_type: float(p.standard_p_time) for p in all_parts}
            
        logical_orders = []
        for d_order in db_orders:
            boms = bom_dict.get(d_order.order_id, [])
            entities = []
            for bom in boms:
                clean_id = bom.part_type.replace('零件', '')
                actual_p_time = part_time_dict.get(clean_id, 45.0)
                entity = PhysicalEntity(
                    entity_id=f"{d_order.order_id}-P{clean_id}",
                    entity_type=int(clean_id), qty=bom.quantity, single_p_time=actual_p_time
                )
                entity.p_time = actual_p_time * bom.quantity
                entities.append(entity)
            l_order = LogicalOrder(d_order.order_id)
            l_order.entities = entities; l_order.total_process_time = sum(e.p_time for e in entities)
            logical_orders.append(l_order)

        TASK_PROGRESS[task_id] = {"status": "running", "progress": "20%", "message": "正在装载最优炼丹权重..."}
        rl_env = PickingEnv()
        rl_env.real_world_orders = logical_orders; rl_env.total_orders = len(logical_orders)
        
        model_path = os.path.join(project_root, "output/models/ppo_masking_model_v3_order_level.zip")
        model = MaskablePPO.load(model_path, env=rl_env)

        def fast_macro_simulate(strategy, limit):
            obs, _ = rl_env.reset(seed=999)
            done = False
            step_count = 0
            while not done:
                mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
                if strategy == "ai":
                    try: env_mask = rl_env.unwrapped.action_masks()
                    except AttributeError: env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
                    combined_mask = np.logical_and(mask, env_mask)
                    if not np.any(combined_mask): combined_mask = mask 
                    action, _ = model.predict(obs, action_masks=combined_mask, deterministic=True)
                    action = int(action)
                elif strategy == "round_robin": action = step_count % limit
                elif strategy == "random": action = np.random.randint(0, limit)
                obs, _, done, _, _ = rl_env.step(int(action))
                step_count += 1
            return float(np.max(rl_env.unwrapped.station_workloads))

        def find_optimal(strategy):
            best_limit = Config.NUM_STATIONS; best_ms = 0
            for limit in range(Config.NUM_STATIONS, 0, -1):
                ms = fast_macro_simulate(strategy, limit)
                if ms <= Config.DEADLINE_SECONDS: best_limit = limit; best_ms = ms
                else: 
                    if limit == Config.NUM_STATIONS: best_ms = ms 
                    break 
            return best_limit, best_ms

        TASK_PROGRESS[task_id] = {"status": "running", "progress": "30%", "message": "【第一局】计算随机分发耗时..."}
        rand_st, rand_tm = find_optimal("random")
        TASK_PROGRESS[task_id] = {"status": "running", "progress": "50%", "message": "【第二局】计算传统轮询耗时..."}
        trad_st, trad_tm = find_optimal("round_robin")
        TASK_PROGRESS[task_id] = {"status": "running", "progress": "70%", "message": "【第三局】强化学习引擎寻优..."}
        ai_st, ai_tm = find_optimal("ai")
        TASK_PROGRESS[task_id] = {"status": "running", "progress": "85%", "message": "已找到最优解！正在用原味 Simpy 生成剧本..."}
        
        sim_env = simpy.Environment()
        physical_stations = [SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2)) for i in range(Config.NUM_STATIONS)]
            
        dispatch_records = []
        base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        
        sim_env.process(simpy_dispatch_engine(sim_env, physical_stations, rl_env, model, ai_st, dispatch_records, task_id, base_time))
        sim_env.run()

        ai_real_makespan = float(sim_env.now)

        db.add_all(dispatch_records)
        db.add(SimulationTask(task_id=task_id+"-RAND", batch_no=batch_no, strategy_type="RANDOM", active_stations=rand_st, total_makespan_sec=rand_tm))
        db.add(SimulationTask(task_id=task_id+"-TRAD", batch_no=batch_no, strategy_type="TRADITIONAL", active_stations=trad_st, total_makespan_sec=trad_tm))
        db.add(SimulationTask(task_id=task_id+"-AI", batch_no=batch_no, strategy_type="AI_RL", active_stations=ai_st, total_makespan_sec=ai_real_makespan))
        db.commit()

        eff = (1 - (ai_st * ai_real_makespan) / (rand_st * rand_tm)) * 100 if rand_st * rand_tm > 0 else 0.0

        TASK_PROGRESS[task_id] = {
            "status": "completed", "progress": "100%", "deadline": Config.DEADLINE_SECONDS,
            "ai_result": {"active_stations": ai_st, "total_makespan": round(ai_real_makespan, 2)},
            "trad_result": {"active_stations": trad_st, "total_makespan": round(trad_tm, 2)},
            "rand_result": {"active_stations": rand_st, "total_makespan": round(rand_tm, 2)},
            "efficiency_up": f"{eff:.2f}%"
        }
    except Exception as e:
        db.rollback()
        TASK_PROGRESS[task_id] = {"status": "failed", "message": str(e)}
    finally:
        db.close()

@app.post("/api/v1/master_data/upload")
def upload_part_master(data: PartMasterBatch, db: SessionLocal = Depends(get_db)):
    pass 

@app.post("/api/v1/orders/upload")
def upload_orders(batch_data: OrderBatch, db: SessionLocal = Depends(get_db)):
    pass 

@app.post("/api/v1/simulation/start")
def start_simulation(req: SimulationRequest, bg_tasks: BackgroundTasks):
    task_id = f"TASK-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    bg_tasks.add_task(run_simulation_task, task_id, req.batch_no)
    return {"code": 200, "task_id": task_id}

@app.get("/api/v1/simulation/status/{task_id}")
def get_status(task_id: str):
    if task_id not in TASK_PROGRESS: raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 200, "data": TASK_PROGRESS[task_id]}

@app.get("/api/v1/simulation/playbook/{task_id}")
def get_simulation_playbook(task_id: str, db: SessionLocal = Depends(get_db)):
    try:
        ai_task_id = f"{task_id}-AI"
        task_info = db.query(SimulationTask).filter(SimulationTask.task_id == ai_task_id).first()
        if not task_info: raise HTTPException(status_code=404, detail="未找到任务宏观战报")
            
        records = db.query(DispatchResult).filter(DispatchResult.task_id == task_id).order_by(DispatchResult.predicted_spawn_time).all()
        if not records: raise HTTPException(status_code=404, detail="未找到派工明细")

        playbook = {
            "task_id": task_id, "strategy": "AI_RL", "active_stations": task_info.active_stations,
            "total_makespan_sec": task_info.total_makespan_sec, "total_boxes": len(records),
            "timeline": []
        }
        for r in records:
            playbook["timeline"].append({
                "order_id": r.order_id,
                "box_id": r.box_id,
                "target_station": r.target_station,
                # 标准 ISO 输出
                "spawn_time": r.predicted_spawn_time.isoformat() if hasattr(r, 'predicted_spawn_time') and r.predicted_spawn_time else r.predicted_start_time.isoformat(),
                "start_time": r.predicted_start_time.isoformat(),
                "end_time": r.predicted_end_time.isoformat(),
            })
        return {"code": 200, "data": playbook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/model/training_metrics")
def get_training_metrics():
    try:
        base_dir = os.path.join(project_root, "scenarios", "order_picking")
        tb_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if d.startswith("ppo_tensorboard_logs") and os.path.isdir(os.path.join(base_dir, d))]
        if not tb_dirs: return {"code": 404, "message": "未找到日志"}
        latest_tb_dir = max(tb_dirs, key=os.path.getmtime)
        subdirs = [os.path.join(latest_tb_dir, d) for d in os.listdir(latest_tb_dir) if os.path.isdir(os.path.join(latest_tb_dir, d))]
        log_dir = max(subdirs, key=os.path.getmtime) if subdirs else latest_tb_dir 

        event_acc = EventAccumulator(log_dir)
        event_acc.Reload() 
        target_tag = 'rollout/ep_rew_mean' 
        tags = event_acc.Tags().get('scalars', [])
        if target_tag not in tags: return {"code": 404, "message": "无 Reward 数据"}

        events = event_acc.Scalars(target_tag)
        steps, rewards = [], []
        sample_rate = max(1, len(events) // 100) 
        for i, event in enumerate(events):
            if i % sample_rate == 0 or i == len(events) - 1:
                step_str = f"{event.step / 10000:.1f}万" if event.step >= 10000 else str(event.step)
                steps.append(step_str); rewards.append(round(event.value, 2))
        return {"code": 200, "data": {"steps": steps, "rewards": rewards}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"日志解析失败: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8088, reload=True)