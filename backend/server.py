





# # 文件路径: backend/server.py

# import os
# import sys
# import datetime
# import numpy as np
# import uvicorn
# import simpy
# import glob
# from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List
# from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

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

# # 🌟 移除了 start_time 的纯净版实体
# class OrderItem(BaseModel):
#     order_id: str
#     part_type: str
#     quantity: int

# class OrderBatch(BaseModel):
#     batch_no: str
#     orders: List[OrderItem]

# class SimulationRequest(BaseModel):
#     batch_no: str

# class DBLogger:
#     def __init__(self, dispatch_records, task_id, base_time):
#         self.dispatch_records = dispatch_records
#         self.task_id = task_id
#         self.base_time = base_time
#         self.temp_records = {} 

#     def log_event(self, time, entity_id, event_type, station_id, details=None):
#         if event_type == "spawn":
#             self.temp_records[entity_id] = {
#                 "spawn_env_time": time, 
#                 "target_station": station_id,
#                 "order_id": details.get("order_id", "") if details else ""
#             }
#         elif event_type == "start_process":
#             if entity_id in self.temp_records:
#                 self.temp_records[entity_id]["start_env_time"] = time
#         elif event_type == "end_process":
#             if entity_id in self.temp_records:
#                 record = self.temp_records[entity_id]
#                 end_env_time = time
                
#                 spawn_dt = self.base_time + datetime.timedelta(seconds=float(record["spawn_env_time"]))
#                 start_dt = self.base_time + datetime.timedelta(seconds=float(record["start_env_time"]))
#                 end_dt = self.base_time + datetime.timedelta(seconds=float(end_env_time))
                
#                 self.dispatch_records.append(
#                     DispatchResult(
#                         task_id=self.task_id,
#                         order_id=record["order_id"],
#                         box_id=entity_id,
#                         target_station=record["target_station"] + 1,
#                         predicted_spawn_time=spawn_dt,
#                         predicted_start_time=start_dt,
#                         predicted_end_time=end_dt
#                     )
#                 )
#                 del self.temp_records[entity_id]

#     def set_power_status(self, *args, **kwargs):
#         pass

# def launch_box(env, station, box_id, order_id, p_time, t_trans, entity_type, logger, delay):
#     if delay > 0:
#         yield env.timeout(delay)
#     if logger:
#         logger.log_event(env.now, box_id, "spawn", station.station_id, {"order_id": order_id})
#     try:
#         yield env.process(station.process_box(box_id, order_id, p_time, t_trans, entity_type))
#     except TypeError:
#         yield env.process(station.process_box(box_id, p_time, t_trans, entity_type))

# def simpy_dispatch_engine(env, stations, rl_env, model, optimal_stations, dispatch_records, task_id, base_time):
#     db_logger = DBLogger(dispatch_records, task_id, base_time)
#     for s in stations:
#         s.logger = db_logger
        
#     obs, _ = rl_env.reset(seed=999)
#     energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))
    
#     done = False
#     dispatch_time_cursor = 0.0

#     while not done:
#         try: env_internal_mask = rl_env.unwrapped.action_masks()
#         except AttributeError: env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
#         combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
#         if not np.any(combined_masks): combined_masks = energy_saving_mask

#         obs_state = rl_env.unwrapped._get_obs()
#         action = int(DispatchRules.rule_ai_policy(model, obs=obs_state, valid_masks=combined_masks))
        
#         current_order = rl_env.unwrapped.real_world_orders[rl_env.unwrapped.current_step]
#         target_station = stations[action]

#         d_main = Config.STATION_EXIT_FAR_DISTANCES[action] - (Config.EXIT_PORT_DELTA / 2.0)
#         t_trans = (d_main / Config.BELT_SPEED) + (Config.BRANCH_IN_LENGTH / Config.BELT_SPEED)

#         local_cursor = dispatch_time_cursor
#         if hasattr(rl_env.unwrapped, 'station_active_boxes'):
#             active_boxes = [b for b in rl_env.unwrapped.station_active_boxes[action] if b['finish_time'] > local_cursor]
#             active_order_ids = set(b['order_id'] for b in active_boxes)
#             is_new_order = current_order['order_id'] not in active_order_ids
            
#             if len(active_boxes) >= getattr(Config, 'MAX_BOXES_PER_STATION', 8) or (is_new_order and len(active_order_ids) >= getattr(Config, 'MAX_ORDERS_PER_STATION', 2)):
#                 if active_boxes:
#                     local_cursor = max(local_cursor, min(b['finish_time'] for b in active_boxes))
        
#         for box in current_order['boxes']:
#             local_cursor += Config.DISPATCH_INTERVAL
#             delay_before_launch = max(0, local_cursor - env.now)
#             env.process(launch_box(
#                 env, target_station, f"{current_order['order_id']}-P{box['sku']}", current_order['order_id'], 
#                 box['p_time'], t_trans, box['sku'], 
#                 db_logger, delay_before_launch
#             ))
            
#         dispatch_time_cursor = local_cursor
#         obs, _, done, _, _ = rl_env.step(action)
        
#     while any(s.machine.count > 0 or len(s.machine.queue) > 0 for s in stations):
#         yield env.timeout(1.0)

# def run_simulation_task(task_id: str, batch_no: str):
#     db = SessionLocal()
#     try:
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "10%", "message": f"正在提取波次 {batch_no} 的时空档案..."}
        
#         # 不再通过时间排序提取，直接捞出当前波次的所有订单
#         db_orders = db.query(OrderPool).filter(OrderPool.batch_no == batch_no).all()
#         if not db_orders: raise ValueError(f"波次 {batch_no} 下无订单数据")
            
#         order_ids = [o.order_id for o in db_orders]
#         all_boms = db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).all()
#         bom_dict = {}
#         for bom in all_boms: bom_dict.setdefault(bom.order_id, []).append(bom)

#         all_parts = db.query(PartMaster).all()
#         part_time_dict = {p.part_type: float(p.standard_p_time) for p in all_parts}
            
#         logical_orders = []
#         for d_order in db_orders:
#             boms = bom_dict.get(d_order.order_id, [])
#             sku_map = {}
#             for bom in boms:
#                 clean_id = bom.part_type.replace('零件', '') if '零件' in bom.part_type else bom.part_type
#                 # 从工艺标准库读取时间，如果遇到生僻件用 4.5s 兜底
#                 actual_p_time = part_time_dict.get(clean_id, 4.5) * bom.quantity
                
#                 if clean_id not in sku_map:
#                     sku_map[clean_id] = {'qty': 0, 'p_time': 0.0}
#                 sku_map[clean_id]['qty'] += bom.quantity
#                 sku_map[clean_id]['p_time'] += actual_p_time
                
#             boxes = [{'sku': k, 'qty': v['qty'], 'p_time': v['p_time']} for k, v in sku_map.items()]
#             total_p_time = sum(b['p_time'] for b in boxes)
            
#             logical_orders.append({
#                 'order_id': d_order.order_id,
#                 'boxes': boxes,
#                 'total_p_time': total_p_time
#             })

#         # ==========================================================
#         # 🌟 核心引擎升级：大单优先策略 (LPT) 
#         # 将无序的订单按照总加工耗时从大到小降序排列
#         # ==========================================================
#         logical_orders.sort(key=lambda x: x['total_p_time'], reverse=True)
#         print(f"\n✅ 波次加载完成！按大单优先策略已重排 {len(logical_orders)} 个订单！")

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "20%", "message": "正在挂载环境与炼丹权重..."}
        
#         rl_env = PickingEnv(dataset_type='test') 
#         rl_env.unwrapped.real_world_orders = logical_orders
#         rl_env.unwrapped.total_orders = len(logical_orders)
#         rl_env.unwrapped.episode_length = len(logical_orders)
        
#         model_dir = os.path.join(project_root, "output/models")
#         zip_files = glob.glob(os.path.join(model_dir, '*.zip'))
#         if not zip_files:
#             raise FileNotFoundError("未在 output/models 目录下找到任何 .zip 模型文件！")
#         latest_model_path = max(zip_files, key=os.path.getctime)
#         model = MaskablePPO.load(latest_model_path, env=rl_env)

#         def fast_macro_simulate(strategy, limit):
#             obs, _ = rl_env.reset(seed=999)
#             done = False
#             step_count = 0
#             while not done:
#                 mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
#                 if strategy == "ai":
#                     try: env_mask = rl_env.unwrapped.action_masks()
#                     except AttributeError: env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
#                     combined_mask = np.logical_and(mask, env_mask)
#                     if not np.any(combined_mask): combined_mask = mask 
#                     action, _ = model.predict(obs, action_masks=combined_mask, deterministic=True)
#                     action = int(action)
#                 elif strategy == "round_robin": action = step_count % limit
#                 elif strategy == "random": action = np.random.randint(0, limit)
#                 obs, _, done, _, _ = rl_env.step(int(action))
#                 step_count += 1
#             return float(np.max(rl_env.unwrapped.station_available_time if hasattr(rl_env.unwrapped, 'station_available_time') else rl_env.unwrapped.station_workloads))

#         def find_optimal(strategy):
#             best_limit = Config.NUM_STATIONS; best_ms = 0
#             for limit in range(Config.NUM_STATIONS, 0, -1):
#                 ms = fast_macro_simulate(strategy, limit)
#                 if ms <= Config.DEADLINE_SECONDS: best_limit = limit; best_ms = ms
#                 else: 
#                     if limit == Config.NUM_STATIONS: best_ms = ms 
#                     break 
#             return best_limit, best_ms

#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "30%", "message": "【第一局】预演随机分发耗时..."}
#         rand_st, rand_tm = find_optimal("random")
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "50%", "message": "【第二局】预演传统轮询耗时..."}
#         trad_st, trad_tm = find_optimal("round_robin")
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "70%", "message": "【第三局】强化学习引擎寻优..."}
#         ai_st, ai_tm = find_optimal("ai")
#         TASK_PROGRESS[task_id] = {"status": "running", "progress": "85%", "message": "已锁定最优资源配比！准备刻录数据库剧本..."}
        
#         sim_env = simpy.Environment()
#         physical_stations = [SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2)) for i in range(Config.NUM_STATIONS)]
            
#         dispatch_records = []
        
#         # 🌟 仿真零点重置：因为没有真实 historical 下发时间了，统一按仿真当天早上 8 点启动！
#         base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        
#         sim_env.process(simpy_dispatch_engine(sim_env, physical_stations, rl_env, model, ai_st, dispatch_records, task_id, base_time))
#         sim_env.run()

#         ai_real_makespan = float(sim_env.now)

#         db.add_all(dispatch_records)
#         db.add(SimulationTask(task_id=task_id+"-RAND", batch_no=batch_no, strategy_type="RANDOM", active_stations=rand_st, total_makespan_sec=rand_tm))
#         db.add(SimulationTask(task_id=task_id+"-TRAD", batch_no=batch_no, strategy_type="TRADITIONAL", active_stations=trad_st, total_makespan_sec=trad_tm))
#         db.add(SimulationTask(task_id=task_id+"-AI", batch_no=batch_no, strategy_type="AI_RL", active_stations=ai_st, total_makespan_sec=ai_real_makespan))
#         db.commit()

#         eff = (1 - (ai_st * ai_real_makespan) / (rand_st * rand_tm)) * 100 if rand_st * rand_tm > 0 else 0.0

#         TASK_PROGRESS[task_id] = {
#             "status": "completed", "progress": "100%", "deadline": Config.DEADLINE_SECONDS,
#             "ai_result": {"active_stations": ai_st, "total_makespan": round(ai_real_makespan, 2)},
#             "trad_result": {"active_stations": trad_st, "total_makespan": round(trad_tm, 2)},
#             "rand_result": {"active_stations": rand_st, "total_makespan": round(rand_tm, 2)},
#             "efficiency_up": f"{eff:.2f}%"
#         }
#     except Exception as e:
#         db.rollback()
#         import traceback
#         traceback.print_exc()
#         TASK_PROGRESS[task_id] = {"status": "failed", "message": str(e)}
#     finally:
#         db.close()

# @app.post("/api/v1/orders/upload")
# def upload_orders(batch_data: OrderBatch, db: SessionLocal = Depends(get_db)):
#     try:
#         unique_order_ids = list(set([item.order_id for item in batch_data.orders]))
#         db.query(OrderBOM).filter(OrderBOM.order_id.in_(unique_order_ids)).delete(synchronize_session=False)
#         db.flush() 
#         for o_id in unique_order_ids:
#             exists = db.query(OrderPool).filter(OrderPool.order_id == o_id).first()
#             if not exists:
#                 # 剔除了 start_time 的存库逻辑
#                 db.add(OrderPool(order_id=o_id, batch_no=batch_data.batch_no, priority_level=1))
#         for item in batch_data.orders:
#             db.add(OrderBOM(order_id=item.order_id, part_type=item.part_type, quantity=item.quantity))
#         db.commit()
#         return {"code": 200, "message": f"成功入库 {len(unique_order_ids)} 个真实拣选单的数据！"}
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
#     if task_id not in TASK_PROGRESS: raise HTTPException(status_code=404, detail="任务不存在")
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
#             "task_id": task_id, "strategy": "AI_RL", "active_stations": task_info.active_stations,
#             "total_makespan_sec": task_info.total_makespan_sec, "total_boxes": len(records),
#             "timeline": []
#         }
#         for r in records:
#             playbook["timeline"].append({
#                 "order_id": r.order_id,
#                 "box_id": r.box_id,
#                 "target_station": r.target_station,
#                 "spawn_time": r.predicted_spawn_time.isoformat() if hasattr(r, 'predicted_spawn_time') and r.predicted_spawn_time else r.predicted_start_time.isoformat(),
#                 "start_time": r.predicted_start_time.isoformat(),
#                 "end_time": r.predicted_end_time.isoformat(),
#             })
#         return {"code": 200, "data": playbook}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/v1/model/training_metrics")
# def get_training_metrics():
#     try:
#         base_dir = os.path.join(project_root, "scenarios", "order_picking")
#         tb_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if d.startswith("ppo_tensorboard_logs") and os.path.isdir(os.path.join(base_dir, d))]
#         if not tb_dirs: return {"code": 404, "message": "未找到日志"}
#         latest_tb_dir = max(tb_dirs, key=os.path.getmtime)
#         subdirs = [os.path.join(latest_tb_dir, d) for d in os.listdir(latest_tb_dir) if os.path.isdir(os.path.join(latest_tb_dir, d))]
#         log_dir = max(subdirs, key=os.path.getmtime) if subdirs else latest_tb_dir 

#         event_acc = EventAccumulator(log_dir)
#         event_acc.Reload() 
#         target_tag = 'rollout/ep_rew_mean' 
#         tags = event_acc.Tags().get('scalars', [])
#         if target_tag not in tags: return {"code": 404, "message": "无 Reward 数据"}

#         events = event_acc.Scalars(target_tag)
#         steps, rewards = [], []
#         sample_rate = max(1, len(events) // 100) 
#         for i, event in enumerate(events):
#             if i % sample_rate == 0 or i == len(events) - 1:
#                 step_str = f"{event.step / 10000:.1f}万" if event.step >= 10000 else str(event.step)
#                 steps.append(step_str); rewards.append(round(event.value, 2))
#         return {"code": 200, "data": {"steps": steps, "rewards": rewards}}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"日志解析失败: {str(e)}")

# if __name__ == "__main__":
#     uvicorn.run("server:app", host="0.0.0.0", port=8088, reload=True)


# 文件路径: backend/server.py

import os
import sys
import datetime
import json
import numpy as np
import uvicorn
import simpy
import glob
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# 🌟 寻路雷达
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from scenarios.order_picking.config import Config
from backend.database import SessionLocal, OrderPool, OrderBOM, SimulationTask, PartMaster, DispatchResult
from sb3_contrib import MaskablePPO
from scenarios.order_picking.rl_environment import PickingEnv
from scenarios.order_picking.inventory_preprocess import list_snapshots, load_snapshot
from scenarios.order_picking.order_preprocessor import preprocess_orders
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
SCHEDULE_RESULTS = {}

# ==========================================
# 🌟 全局定义进度推送工具，彻底解决找不到变量的报错！
# ==========================================
def update_progress(task_id, progress, message):
    print(f"\n🔄 [前端拉取进度 {progress}] {message}")
    TASK_PROGRESS[task_id] = {"status": "running", "progress": progress, "message": message}

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
    part_type: str
    quantity: int

class OrderBatch(BaseModel):
    batch_no: str
    orders: List[OrderItem]

class SimulationRequest(BaseModel):
    batch_no: str
    inventory_snapshot_id: str = "2025-07-01-morning"
    evening_snapshot_id: str = "2025-07-01-evening"
    shortage_policy: str = "exception_queue"

class ScheduleDispatchRequest(BaseModel):
    batch_no: str
    inventory_snapshot_id: str = "2025-07-01-morning"
    strategy: str = "ai"
    active_station_limit: int = Config.NUM_STATIONS

class DBLogger:
    def __init__(self, dispatch_records, task_id, base_time):
        self.dispatch_records = dispatch_records
        self.task_id = task_id
        self.base_time = base_time
        self.temp_records = {} 

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
    if delay > 0:
        yield env.timeout(delay)
    if logger:
        logger.log_event(env.now, box_id, "spawn", station.station_id, {"order_id": order_id})
    try:
        yield env.process(station.process_box(box_id, order_id, p_time, t_trans, entity_type))
    except TypeError:
        yield env.process(station.process_box(box_id, p_time, t_trans, entity_type))


def build_logical_orders(db, batch_no: str):
    db_orders = db.query(OrderPool).filter(OrderPool.batch_no == batch_no).all()
    if not db_orders:
        raise ValueError(f"批次 {batch_no} 下没有订单数据")

    order_ids = [o.order_id for o in db_orders]
    all_boms = db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).all()
    bom_dict = {}
    for bom in all_boms:
        bom_dict.setdefault(bom.order_id, []).append(bom)

    all_parts = db.query(PartMaster).all()
    part_time_dict = {str(p.part_type).strip(): float(p.standard_p_time) for p in all_parts}

    logical_orders = []
    for d_order in db_orders:
        boms = bom_dict.get(d_order.order_id, [])
        sku_map = {}
        for bom in boms:
            clean_id = str(bom.part_type).strip().replace("零件", "")
            actual_p_time = part_time_dict.get(clean_id, 4.5) * bom.quantity
            if clean_id not in sku_map:
                sku_map[clean_id] = {"qty": 0, "p_time": 0.0}
            sku_map[clean_id]["qty"] += bom.quantity
            sku_map[clean_id]["p_time"] += actual_p_time

        boxes = [{"sku": k, "qty": v["qty"], "p_time": v["p_time"]} for k, v in sku_map.items()]
        logical_orders.append(
            {
                "order_id": d_order.order_id,
                "boxes": boxes,
                "total_p_time": sum(b["p_time"] for b in boxes),
            }
        )
    return logical_orders


def load_latest_ai_model(rl_env):
    model_dir = os.path.join(project_root, "output", "models")
    zip_files = glob.glob(os.path.join(model_dir, "*.zip"))
    if not zip_files:
        raise FileNotFoundError("找不到 AI 模型文件！")
    return MaskablePPO.load(max(zip_files, key=os.path.getctime), env=rl_env)


def prepare_orders_with_inventory(batch_no: str, inventory_snapshot_id: str, db):
    logical_orders = build_logical_orders(db, batch_no)
    inventory_snapshot = load_snapshot(inventory_snapshot_id) if inventory_snapshot_id else None
    preprocessed = preprocess_orders(logical_orders, inventory_snapshot)
    processable_orders = preprocessed["processable_orders"]
    preprocess_stats = preprocessed["preprocess_stats"]
    shortage_orders = preprocessed["shortage_orders"]
    if not processable_orders:
        raise ValueError(
            f"库存预处理后没有可执行订单：输入 {preprocess_stats.get('input_order_count', 0)} 单，"
            f"缺料异常 {preprocess_stats.get('shortage_order_count', 0)} 单。请检查库存快照。"
        )
    return logical_orders, inventory_snapshot, processable_orders, shortage_orders, preprocess_stats


def generate_dispatch_mapping(processable_orders, strategy: str = "ai", active_station_limit: int = Config.NUM_STATIONS):
    station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
    strategy_key = (strategy or "ai").lower()

    rl_env = PickingEnv(dataset_type="test")
    rl_env.unwrapped.set_orders(processable_orders, episode_length=len(processable_orders))
    obs, _ = rl_env.reset(seed=999)
    model = load_latest_ai_model(rl_env) if strategy_key == "ai" else None

    mapping = []
    done = False
    sequence = 1
    while not done:
        current_order = rl_env.unwrapped.real_world_orders[rl_env.unwrapped.current_step]
        station_mask = np.array([True] * station_limit + [False] * (Config.NUM_STATIONS - station_limit))
        try:
            env_mask = rl_env.unwrapped.action_masks()
        except AttributeError:
            env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
        combined_mask = np.logical_and(station_mask, env_mask)
        if not np.any(combined_mask):
            combined_mask = station_mask

        if strategy_key == "ai":
            action = int(model.predict(obs, action_masks=combined_mask, deterministic=True)[0])
        elif strategy_key == "round_robin":
            valid_actions = np.flatnonzero(combined_mask)
            action = int(valid_actions[(sequence - 1) % len(valid_actions)])
        elif strategy_key == "random":
            valid_actions = np.flatnonzero(combined_mask)
            action = int(np.random.choice(valid_actions))
        else:
            raise ValueError(f"不支持的调度策略: {strategy}")

        mapping.append(
            {
                "sequence": sequence,
                "order_id": current_order["order_id"],
                "target_station": action + 1,
                "box_count": len(current_order.get("boxes", [])),
                "total_p_time": round(float(current_order.get("total_p_time", 0.0)), 3),
                "boxes": [
                    {
                        "sku": box.get("sku", ""),
                        "qty": box.get("qty", 1),
                        "p_time": round(float(box.get("p_time", 0.0)), 3),
                    }
                    for box in current_order.get("boxes", [])
                ],
            }
        )
        obs, _, done, _, _ = rl_env.step(action)
        sequence += 1

    return mapping, round(float(rl_env.unwrapped.global_time), 3), station_limit


def save_schedule_result(task_id: str, result: dict):
    output_dir = os.path.join(project_root, "output", "schedule_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{task_id}.json")
    latest_path = os.path.join(output_dir, "latest.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return output_path


def run_schedule_dispatch_task(task_id: str, batch_no: str, inventory_snapshot_id: str, strategy: str, active_station_limit: int):
    db = SessionLocal()
    try:
        SCHEDULE_RESULTS[task_id] = {
            "task_id": task_id,
            "batch_no": batch_no,
            "status": "running",
            "message": "正在执行纯智能调度...",
        }
        _, inventory_snapshot, processable_orders, shortage_orders, preprocess_stats = prepare_orders_with_inventory(
            batch_no, inventory_snapshot_id, db
        )
        mapping, estimated_makespan, station_limit = generate_dispatch_mapping(
            processable_orders,
            strategy=strategy,
            active_station_limit=active_station_limit,
        )
        result = {
            "task_id": task_id,
            "batch_no": batch_no,
            "inventory_snapshot_id": inventory_snapshot_id,
            "strategy": strategy.upper() if strategy.lower() != "ai" else "AI_RL",
            "status": "completed",
            "output_file": "",
            "summary": {
                "input_order_count": preprocess_stats.get("input_order_count", 0),
                "scheduled_order_count": len(mapping),
                "shortage_order_count": len(shortage_orders),
                "reordered_count": preprocess_stats.get("reordered_count", 0),
                "scarce_sku_count": preprocess_stats.get("scarce_sku_count", 0),
                "inventory_sku_count": preprocess_stats.get("inventory_sku_count", 0),
                "station_count": station_limit,
                "estimated_env_makespan_sec": estimated_makespan,
                "inventory_summary": (inventory_snapshot or {}).get("summary", {}),
            },
            "mapping": mapping,
            "shortage_orders": [
                {
                    "order_id": order.get("order_id", ""),
                    "exception_reason": order.get("exception_reason", ""),
                    "shortage_skus": order.get("shortage_skus", []),
                    "box_count": len(order.get("boxes", [])),
                    "total_p_time": round(float(order.get("total_p_time", 0.0)), 3),
                }
                for order in shortage_orders
            ],
        }
        output_path = save_schedule_result(task_id, result)
        result["output_file"] = os.path.relpath(output_path, project_root).replace("\\", "/")
        save_schedule_result(task_id, result)
        SCHEDULE_RESULTS[task_id] = result
    except Exception as e:
        import traceback
        traceback.print_exc()
        SCHEDULE_RESULTS[task_id] = {
            "task_id": task_id,
            "batch_no": batch_no,
            "status": "failed",
            "message": str(e),
        }
    finally:
        db.close()


def simpy_dispatch_engine(env, stations, rl_env, model, optimal_stations, dispatch_records, task_id, base_time):
    db_logger = DBLogger(dispatch_records, task_id, base_time)
    for s in stations:
        s.logger = db_logger
        
    obs, _ = rl_env.reset(seed=999)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))
    
    done = False
    dispatch_time_cursor = 0.0

    while not done:
        try: env_internal_mask = rl_env.unwrapped.action_masks()
        except AttributeError: env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            
        combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
        if not np.any(combined_masks): combined_masks = energy_saving_mask

        obs_state = rl_env.unwrapped._get_obs()
        action = int(DispatchRules.rule_ai_policy(model, obs=obs_state, valid_masks=combined_masks))
        
        current_order = rl_env.unwrapped.real_world_orders[rl_env.unwrapped.current_step]
        target_station = stations[action]

        # 计算运输时间
        try:
            d_main = Config.get_station_main_distance(action)
            t_branch = Config.get_branch_info(action)["transit_time_s"]
            t_trans = (d_main / Config.BELT_SPEED) + t_branch
        except AttributeError:
            d_main = Config.STATION_EXIT_FAR_DISTANCES[action] - (Config.EXIT_PORT_DELTA / 2.0)
            t_trans = (d_main / Config.BELT_SPEED) + (Config.BRANCH_IN_LENGTH / Config.BELT_SPEED)

        # =======================================================
        # 
        # 只有当站台彻底腾出一个订单坑位，才允许新订单进入
        # =======================================================
        local_cursor = dispatch_time_cursor
        if hasattr(rl_env.unwrapped, 'station_active_boxes'):
            while True:
                active_boxes = [b for b in rl_env.unwrapped.station_active_boxes[action] if b['finish_time'] > local_cursor]
                active_order_ids = set(b['order_id'] for b in active_boxes)
                is_new_order = current_order['order_id'] not in active_order_ids
                
                order_limit = getattr(Config, 'MAX_ORDERS_PER_STATION', 2)
                box_limit = getattr(Config, 'MAX_BOXES_PER_STATION', 8)
                
                # 如果既没有爆箱子，也没有爆订单，跳出死锁允许发车
                if not (len(active_boxes) >= box_limit or (is_new_order and len(active_order_ids) >= order_limit)):
                    break
                    
                # 否则，时间只能走到当前这批箱子最早干完的那一刻，继续下一轮 while 检查
                if active_boxes:
                    local_cursor = max(local_cursor, min(b['finish_time'] for b in active_boxes))
                else:
                    local_cursor += 1.0
        
        for box in current_order['boxes']:
            local_cursor += Config.DISPATCH_INTERVAL
            delay_before_launch = max(0, local_cursor - env.now)
            env.process(launch_box(
                env, target_station, f"{current_order['order_id']}-P{box['sku']}", current_order['order_id'], 
                box['p_time'], t_trans, box['sku'], 
                db_logger, delay_before_launch
            ))
            
        dispatch_time_cursor = local_cursor
        obs, _, done, _, _ = rl_env.step(action)
        
    while any(s.machine.count > 0 or len(s.machine.queue) > 0 for s in stations):
        yield env.timeout(1.0)


# ==========================================
# 核心任务主引擎
# ==========================================
def run_simulation_task(task_id: str, batch_no: str, inventory_snapshot_id: str = "2025-07-01-morning", evening_snapshot_id: str = "2025-07-01-evening"):
    db = SessionLocal()
    try:
        update_progress(task_id, "10%", f"正在提取波次 {batch_no} 的时空档案...")
        
        db_orders = db.query(OrderPool).filter(OrderPool.batch_no == batch_no).all()
        if not db_orders: raise ValueError(f"波次 {batch_no} 下无订单数据")
            
        order_ids = [o.order_id for o in db_orders]
        all_boms = db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).all()
        bom_dict = {}
        for bom in all_boms: bom_dict.setdefault(bom.order_id, []).append(bom)

        all_parts = db.query(PartMaster).all()
        part_time_dict = {str(p.part_type).strip(): float(p.standard_p_time) for p in all_parts}
            
        logical_orders = []
        for d_order in db_orders:
            boms = bom_dict.get(d_order.order_id, [])
            sku_map = {}
            for bom in boms:
                clean_id = str(bom.part_type).strip().replace('零件', '')
                actual_p_time = part_time_dict.get(clean_id, 4.5) * bom.quantity
                if clean_id not in sku_map: sku_map[clean_id] = {'qty': 0, 'p_time': 0.0}
                sku_map[clean_id]['qty'] += bom.quantity
                sku_map[clean_id]['p_time'] += actual_p_time
            
            boxes = [{'sku': k, 'qty': v['qty'], 'p_time': v['p_time']} for k, v in sku_map.items()]
            logical_orders.append({'order_id': d_order.order_id, 'boxes': boxes, 'total_p_time': sum(b['p_time'] for b in boxes)})

        #  注释掉 LPT（大单优先）排序，严格按历史时间顺序，对齐 compare.py 的 30194 秒成绩
        #logical_orders.sort(key=lambda x: x['total_p_time'], reverse=True)
        #print(f"\n✅ 数据提取完毕！总波次订单数: {len(logical_orders)} (已关闭大单优先，还原原版时间)")

        initial_inventory_snapshot = load_snapshot(inventory_snapshot_id) if inventory_snapshot_id else None
        preprocessed = preprocess_orders(logical_orders, initial_inventory_snapshot)
        processable_orders = preprocessed["processable_orders"]
        preprocess_stats = preprocessed["preprocess_stats"]
        shortage_orders = preprocessed["shortage_orders"]

        if not processable_orders:
            raise ValueError(
                f"库存预处理后没有可执行订单：输入 {preprocess_stats.get('input_order_count', 0)} 单，"
                f"缺料异常 {preprocess_stats.get('shortage_order_count', 0)} 单。请检查库存快照。"
            )

        rl_env = PickingEnv(dataset_type='test')
        rl_env.unwrapped.set_orders(processable_orders, episode_length=len(processable_orders))

        rl_env.reset(seed=999)
        print(
            f"库存预处理完成：输入 {preprocess_stats['input_order_count']} 单，"
            f"可执行 {preprocess_stats['processable_order_count']} 单，"
            f"缺料异常 {preprocess_stats['shortage_order_count']} 单。"
        )
        
        model_dir = os.path.join(project_root, "output/models")
        zip_files = glob.glob(os.path.join(model_dir, '*.zip'))
        if not zip_files: raise FileNotFoundError("找不到 AI 模型文件！")
        model = MaskablePPO.load(max(zip_files, key=os.path.getctime), env=rl_env)

        def fast_macro_simulate(strategy, limit):
            # 每次探测前必须归零时间
            rl_env.reset(seed=999)
            if len(rl_env.unwrapped.real_world_orders) == 0:
                raise ValueError(
                    f"库存预处理后没有可执行订单：输入 {preprocess_stats.get('input_order_count', 0)} 单，"
                    f"缺料异常 {preprocess_stats.get('shortage_order_count', 0)} 单。请检查库存快照。"
                )
            done = False
            step = 0
            while not done:
                mask = np.array([True] * limit + [False] * (Config.NUM_STATIONS - limit))
                try:
                    env_mask = rl_env.unwrapped.action_masks()
                except: env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
                combined = np.logical_and(mask, env_mask)
                if not np.any(combined): combined = mask 
                
                if strategy == "ai": action = int(model.predict(rl_env.unwrapped._get_obs(), action_masks=combined, deterministic=True)[0])
                elif strategy == "round_robin": action = step % limit
                else: action = np.random.randint(0, limit)
                
                _, _, done, _, _ = rl_env.step(action)
                step += 1
            return float(rl_env.unwrapped.global_time)

        results = {}
        strategy_list = ["random", "round_robin", "ai"]
        progress_map = {"random": "30%", "round_robin": "50%", "ai": "70%"}
        
        for strategy in strategy_list:
            results[strategy] = []
            
            # 🌟 修复进度条卡死：每个策略测算前，推送最新进度给 Swagger 前端
            update_progress(task_id, progress_map[strategy], f"正在测算 {strategy.upper()} 策略极限探底...")
            
            print(f"\n▶ 开始策略 [{strategy.upper()}] 的极限探底 (16台 -> 1台):")
            for limit in range(Config.NUM_STATIONS, 0, -1):
                ms = fast_macro_simulate(strategy, limit)
                results[strategy].append((limit, ms))
                status_txt = "✅ 满足" if ms <= Config.DEADLINE_SECONDS else "❌ 超时"
                print(f"  └─ 开机数: {limit:02d} | 完工耗时: {ms:.1f}s | {status_txt}")

        update_progress(task_id, "85%", "已锁定最优资源配比！准备刻录物理引擎与 3D 剧本...")

        def get_best(strat):
            valid = [r for r in results[strat] if r[1] <= Config.DEADLINE_SECONDS]
            return min(valid, key=lambda x: x[0]) if valid else (Config.NUM_STATIONS, results[strat][-1][1])

        rand_st, rand_tm = get_best("random")
        trad_st, trad_tm = get_best("round_robin")
        ai_st, ai_tm = get_best("ai")

        sim_env = simpy.Environment()
        
        # 实例化场地与场记员
        dispatch_records = []
        base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        physical_stations = [SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2)) for i in range(Config.NUM_STATIONS)]
        
        # 物理引擎流转
        sim_env.process(simpy_dispatch_engine(sim_env, physical_stations, rl_env, model, ai_st, dispatch_records, task_id, base_time))
        sim_env.run()
        
        ai_real_makespan = float(sim_env.now)

        db.add_all(dispatch_records)
        db.add(SimulationTask(task_id=task_id+"-RAND", batch_no=batch_no, strategy_type="RANDOM", active_stations=rand_st, total_makespan_sec=rand_tm))
        db.add(SimulationTask(task_id=task_id+"-TRAD", batch_no=batch_no, strategy_type="TRADITIONAL", active_stations=trad_st, total_makespan_sec=trad_tm))
        db.add(SimulationTask(task_id=task_id+"-AI", batch_no=batch_no, strategy_type="AI_RL", active_stations=ai_st, total_makespan_sec=ai_real_makespan))
        db.commit()

        eff = (1 - (ai_st * ai_real_makespan) / (rand_st * rand_tm)) * 100 if rand_st * rand_tm > 0 else 0.0
        inventory_summary = (initial_inventory_snapshot or {}).get("summary", {})

        update_progress(task_id, "100%", "✅ 战报生成完毕！大屏可提取渲染！")
        TASK_PROGRESS[task_id].update({
            "status": "completed", "deadline": Config.DEADLINE_SECONDS,
            "ai_result": {"active_stations": ai_st, "total_makespan": round(ai_real_makespan, 2)},
            "trad_result": {"active_stations": trad_st, "total_makespan": round(trad_tm, 2)},
            "rand_result": {"active_stations": rand_st, "total_makespan": round(rand_tm, 2)},
            "efficiency_up": f"{eff:.2f}%",
            "inventory_result": {
                "initial_snapshot_id": inventory_snapshot_id,
                "evening_snapshot_id": evening_snapshot_id,
                "summary": inventory_summary,
                "preprocess_stats": preprocess_stats,
                "exception_order_count": len(shortage_orders),
                "evening_validation": None,
                "shortage_policy": "exception_queue",
            }
        })
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        # 将报错信息推送到前端进度字典，打破挂起
        update_progress(task_id, "failed", f"报错中断: {str(e)}")
    finally:
        db.close()


@app.post("/api/v1/orders/upload")
def upload_orders(batch_data: OrderBatch, db: SessionLocal = Depends(get_db)):
    try:
        unique_order_ids = list(set([item.order_id for item in batch_data.orders]))
        db.query(OrderBOM).filter(OrderBOM.order_id.in_(unique_order_ids)).delete(synchronize_session=False)
        db.flush() 
        for o_id in unique_order_ids:
            exists = db.query(OrderPool).filter(OrderPool.order_id == o_id).first()
            if not exists:
                db.add(OrderPool(order_id=o_id, batch_no=batch_data.batch_no, priority_level=1))
        for item in batch_data.orders:
            db.add(OrderBOM(order_id=item.order_id, part_type=item.part_type, quantity=item.quantity))
        db.commit()
        return {"code": 200, "message": f"成功入库 {len(unique_order_ids)} 个真实拣选单的数据！"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/simulation/start")
def start_simulation(req: SimulationRequest, bg_tasks: BackgroundTasks):
    task_id = f"TASK-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    bg_tasks.add_task(run_simulation_task, task_id, req.batch_no, req.inventory_snapshot_id, req.evening_snapshot_id)
    return {"code": 200, "task_id": task_id}

@app.post("/api/v1/schedule/dispatch")
def start_schedule_dispatch(req: ScheduleDispatchRequest, bg_tasks: BackgroundTasks):
    task_id = f"SCHEDULE-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    bg_tasks.add_task(
        run_schedule_dispatch_task,
        task_id,
        req.batch_no,
        req.inventory_snapshot_id,
        req.strategy,
        req.active_station_limit,
    )
    SCHEDULE_RESULTS[task_id] = {
        "task_id": task_id,
        "batch_no": req.batch_no,
        "status": "queued",
        "message": "纯智能调度任务已提交",
    }
    return {"code": 200, "task_id": task_id, "message": "纯智能调度任务已启动"}

@app.get("/api/v1/schedule/result/{task_id}")
def get_schedule_result(task_id: str):
    if task_id in SCHEDULE_RESULTS:
        return {"code": 200, "data": SCHEDULE_RESULTS[task_id]}

    output_path = os.path.join(project_root, "output", "schedule_results", f"{task_id}.json")
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            return {"code": 200, "data": json.load(f)}
    raise HTTPException(status_code=404, detail="调度任务不存在")

@app.get("/api/v1/inventory/snapshots")
def get_inventory_snapshots():
    return {"code": 200, "data": list_snapshots()}

@app.get("/api/v1/inventory/summary/{snapshot_id}")
def get_inventory_summary(snapshot_id: str):
    try:
        snapshot = load_snapshot(snapshot_id)
        return {
            "code": 200,
            "data": {
                "snapshot_id": snapshot.get("snapshot_id"),
                "source_file": snapshot.get("source_file"),
                "summary": snapshot.get("summary", {}),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

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
            item = {
                "order_id": r.order_id,
                "box_id": r.box_id,
                "target_station": r.target_station,
                "spawn_time": r.predicted_spawn_time.isoformat() if hasattr(r, 'predicted_spawn_time') and r.predicted_spawn_time else r.predicted_start_time.isoformat(),
                "start_time": r.predicted_start_time.isoformat(),
                "end_time": r.predicted_end_time.isoformat(),
            }
            playbook["timeline"].append(item)
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
