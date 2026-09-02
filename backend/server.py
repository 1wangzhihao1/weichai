



# 文件路径: backend/server.py

import os
import sys
import datetime
import json
import re
from copy import deepcopy
import numpy as np
import uvicorn
import simpy
import glob
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from typing import List
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# 🌟 寻路雷达
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from scenarios.order_picking.config import Config
from backend.database import SessionLocal, OrderPool, OrderBOM, SimulationTask, PartMaster, DispatchResult, ensure_schema_updates
from sb3_contrib import MaskablePPO
from scenarios.order_picking.rl_environment import PickingEnv
from scenarios.order_picking.app_config import get_config_value
from scenarios.order_picking.data_paths import DEFAULT_DAILY_DATE, MODEL_DIR, resolve_model_path
from scenarios.order_picking.inventory_preprocess import list_snapshots, load_snapshot
from scenarios.order_picking.order_preprocessor import preprocess_orders
from backend.sku_avg_time import rebuild_sku_avg_time
from backend.dispatch_strategies import dispatch_orders
from backend.historical_orders import build_historical_orders, load_history_frame, load_part_times_from_db
from backend.simpy_simulation_runner import run_assignment_simpy_simulation
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
ORDER_PREPROCESS_SORT_ENABLED = "--noorder" not in sys.argv
DEFAULT_BATCH_NO = str(get_config_value("simulation", "default_batch_no", f"ORDER_WAVE_{DEFAULT_DAILY_DATE}"))
DEFAULT_INITIAL_SNAPSHOT_ID = str(
    get_config_value("simulation", "default_initial_snapshot_id", f"{DEFAULT_DAILY_DATE}-morning")
)
DEFAULT_EVENING_SNAPSHOT_ID = str(
    get_config_value("simulation", "default_evening_snapshot_id", f"{DEFAULT_DAILY_DATE}-evening")
)
DEFAULT_STRATEGY = str(get_config_value("simulation", "default_strategy", "ai"))
DEFAULT_ACTIVE_STATION_LIMIT = int(get_config_value("simulation", "default_active_station_limit", Config.NUM_STATIONS))
AUTO_REBUILD_SKU_TIME = bool(get_config_value("simulation", "auto_rebuild_sku_time", True))
DEFAULT_OPERATION_GAP_SECONDS = float(get_config_value("simulation", "operation_gap_seconds", 0.0))
HISTORY_ACTUAL_OPERATION_GAP_SECONDS = float(
    get_config_value("simulation", "history_actual_operation_gap_seconds", DEFAULT_OPERATION_GAP_SECONDS)
)
HISTORY_SKU_AVERAGE_OPERATION_GAP_SECONDS = float(
    get_config_value("simulation", "history_sku_average_operation_gap_seconds", DEFAULT_OPERATION_GAP_SECONDS)
)
ensure_schema_updates()
print(
    "Order preprocess sorting: "
    f"{'enabled' if ORDER_PREPROCESS_SORT_ENABLED else 'disabled (--noorder, using upload order)'}"
)

# ==========================================
# 🌟 全局定义进度推送工具，彻底解决找不到变量的报错！
# ==========================================
def update_progress(task_id, progress, message):
    print(f"\n🔄 [前端拉取进度 {progress}] {message}")
    TASK_PROGRESS[task_id] = {"status": "running", "progress": progress, "message": message}


def default_operation_gap_for(strategy_key: str, process_time_source: str) -> float:
    key = (strategy_key or "").lower()
    source = (process_time_source or "").lower()
    if key == "history_actual" or (key.startswith("history") and source == "actual"):
        return HISTORY_ACTUAL_OPERATION_GAP_SECONDS
    if key in {"history_sku_avg", "history_part_master"} or (
        key.startswith("history") and source in {"sku_average", "part_master"}
    ):
        return HISTORY_SKU_AVERAGE_OPERATION_GAP_SECONDS
    return DEFAULT_OPERATION_GAP_SECONDS

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
    replace_existing: bool = True

class SimulationRequest(BaseModel):
    batch_no: str = DEFAULT_BATCH_NO
    inventory_snapshot_id: str = DEFAULT_INITIAL_SNAPSHOT_ID
    evening_snapshot_id: str = DEFAULT_EVENING_SNAPSHOT_ID
    shortage_policy: str = "exception_queue"
    strategy: str = DEFAULT_STRATEGY
    active_station_limit: int = DEFAULT_ACTIVE_STATION_LIMIT
    history_date: str | None = None
    process_time_source: str = "sku_average"
    operation_gap_seconds: float | None = None

class ScheduleDispatchRequest(BaseModel):
    batch_no: str = DEFAULT_BATCH_NO
    inventory_snapshot_id: str = DEFAULT_INITIAL_SNAPSHOT_ID
    strategy: str = DEFAULT_STRATEGY
    active_station_limit: int = DEFAULT_ACTIVE_STATION_LIMIT

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
    db_orders = (
        db.query(OrderPool)
        .filter(OrderPool.batch_no == batch_no)
        .order_by(OrderPool.sequence_no.asc(), OrderPool.order_id.asc())
        .all()
    )
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
    model_path = resolve_model_path()
    if not model_path or not model_path.exists():
        raise FileNotFoundError(f"找不到 AI 模型文件：{MODEL_DIR}")
    return MaskablePPO.load(str(model_path), env=rl_env)


def select_processable_order_sequence(logical_orders, preprocessed):
    if ORDER_PREPROCESS_SORT_ENABLED:
        return preprocessed["processable_orders"]

    processable_order_ids = {str(order["order_id"]) for order in preprocessed["processable_orders"]}
    return [
        order for order in logical_orders
        if str(order["order_id"]) in processable_order_ids
    ]


def prepare_orders_with_inventory(batch_no: str, inventory_snapshot_id: str, db):
    logical_orders = build_logical_orders(db, batch_no)
    inventory_snapshot = load_snapshot(inventory_snapshot_id) if inventory_snapshot_id else None
    preprocessed = preprocess_orders(logical_orders, inventory_snapshot)
    processable_orders = select_processable_order_sequence(logical_orders, preprocessed)
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


def infer_history_date(batch_no: str) -> str | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(batch_no or ""))
    return match.group(0) if match else None


def task_strategy_label(strategy: str, process_time_source: str = "") -> str:
    key = (strategy or "ai").lower()
    if key == "ai":
        return "AI_RL"
    if key == "round_robin":
        return "ROUND_ROBIN"
    if key == "random":
        return "RANDOM"
    if key.startswith("history"):
        return f"HISTORY_{(process_time_source or 'actual').upper()}"
    return key.upper()


def build_strategy_comparison(
    orders: List[dict],
    max_station_limit: int,
    operation_gap_seconds: float,
    ai_model=None,
):
    max_limit = max(1, min(int(max_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
    strategies = ["ai", "round_robin", "random"]
    results = {}

    for strategy_name in strategies:
        strategy_runs = []
        for limit in range(max_limit, 0, -1):
            model = ai_model if strategy_name == "ai" else None
            assignments = dispatch_orders(
                deepcopy(orders),
                strategy_name,
                active_station_limit=limit,
                model=model,
                seed=999,
            )
            sim_result = run_assignment_simpy_simulation(
                deepcopy(orders),
                assignments,
                task_id=f"comparison-{strategy_name}-{limit}",
                active_station_limit=limit,
                operation_gap_seconds=operation_gap_seconds,
            )
            makespan = float(sim_result["total_makespan"])
            strategy_runs.append((limit, makespan))
            if makespan > Config.DEADLINE_SECONDS:
                break

        valid = [item for item in strategy_runs if item[1] <= Config.DEADLINE_SECONDS]
        best_limit, best_makespan = min(valid, key=lambda item: item[0]) if valid else strategy_runs[0]
        results[strategy_name] = {
            "active_stations": int(best_limit),
            "total_makespan": round(float(best_makespan), 2),
            "within_deadline": bool(best_makespan <= Config.DEADLINE_SECONDS),
            "deadline_seconds": float(Config.DEADLINE_SECONDS),
            "tested": [
                {
                    "active_stations": int(limit),
                    "total_makespan": round(float(makespan), 2),
                    "within_deadline": bool(makespan <= Config.DEADLINE_SECONDS),
                }
                for limit, makespan in strategy_runs
            ],
        }

    def station_hour_efficiency(baseline, candidate):
        baseline_station_time = float(baseline["active_stations"]) * float(baseline["total_makespan"])
        candidate_station_time = float(candidate["active_stations"]) * float(candidate["total_makespan"])
        if baseline_station_time <= 0:
            return 0.0
        return (1 - candidate_station_time / baseline_station_time) * 100.0

    ai_result = results["ai"]
    eff_vs_round = station_hour_efficiency(results["round_robin"], ai_result)
    eff_vs_random = station_hour_efficiency(results["random"], ai_result)
    return {
        "ai_result": ai_result,
        "trad_result": results["round_robin"],
        "rand_result": results["random"],
        "efficiency_up": f"{eff_vs_round:.2f}%",
        "efficiency_vs_round_robin": f"{eff_vs_round:.2f}%",
        "efficiency_vs_random": f"{eff_vs_random:.2f}%",
        "efficiency_formula": "1 - (ai_stations * ai_makespan) / (baseline_stations * baseline_makespan)",
    }


def run_unified_simulation_task(
    task_id: str,
    batch_no: str = DEFAULT_BATCH_NO,
    inventory_snapshot_id: str = DEFAULT_INITIAL_SNAPSHOT_ID,
    evening_snapshot_id: str = DEFAULT_EVENING_SNAPSHOT_ID,
    strategy: str = DEFAULT_STRATEGY,
    active_station_limit: int = DEFAULT_ACTIVE_STATION_LIMIT,
    history_date: str | None = None,
    process_time_source: str = "sku_average",
    operation_gap_seconds: float | None = None,
):
    db = SessionLocal()
    try:
        strategy_key = (strategy or "ai").lower()
        gap_seconds = float(operation_gap_seconds) if operation_gap_seconds is not None else None
        station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
        update_progress(task_id, "10%", f"正在准备 {task_strategy_label(strategy_key, process_time_source)} 策略订单...")

        real_makespan = None
        error_pct = None
        preprocess_stats = {}
        shortage_orders = []
        inventory_summary = {}
        model = None
        comparison_result = None
        simulation_station_limit = station_limit
        display_active_stations = station_limit
        active_station_ids = []

        if strategy_key.startswith("history"):
            target_date = history_date or infer_history_date(batch_no)
            if not target_date:
                raise ValueError("历史分配策略需要 history_date，或 batch_no 中包含 YYYY-MM-DD。")
            source = "actual" if strategy_key == "history_actual" else process_time_source
            if strategy_key in {"history_sku_avg", "history_part_master"}:
                source = "sku_average"
            history_df = load_history_frame()
            part_times = load_part_times_from_db() if source == "sku_average" else None
            orders, assignments, metadata = build_historical_orders(
                history_df,
                target_date=target_date,
                process_time_source=source,
                part_time_dict=part_times,
            )
            batch_no_for_db = batch_no or f"HISTORY_{target_date}"
            real_makespan = float(metadata["real_makespan_seconds"])
            active_station_ids = [int(item) for item in metadata.get("station_ids", [])]
            if active_station_ids:
                simulation_station_limit = max(active_station_ids)
                display_active_stations = len(active_station_ids)
            process_time_used = source
            inventory_summary = {
                "history_date": target_date,
                "valid_rows": metadata["valid_rows"],
                "historical_station_count": metadata.get("station_count"),
                "historical_station_ids": active_station_ids,
                "historical_real_makespan_seconds": round(real_makespan, 3),
            }
            env = PickingEnv(dataset_type="test")
            env.unwrapped.set_orders(deepcopy(orders), episode_length=len(orders))
            model = load_latest_ai_model(env)
        else:
            if AUTO_REBUILD_SKU_TIME:
                update_progress(task_id, "12%", "正在刷新 SKU 平均处理时间...")
                rebuild_sku_avg_time()
            _, inventory_snapshot, orders, shortage_orders, preprocess_stats = prepare_orders_with_inventory(
                batch_no,
                inventory_snapshot_id,
                db,
            )
            batch_no_for_db = batch_no
            process_time_used = "sku_average"
            inventory_summary = (inventory_snapshot or {}).get("summary", {})
            env = PickingEnv(dataset_type="test")
            env.unwrapped.set_orders(deepcopy(orders), episode_length=len(orders))
            model = load_latest_ai_model(env)

        if gap_seconds is None:
            gap_seconds = default_operation_gap_for(strategy_key, process_time_used)

        update_progress(task_id, "35%", "正在补算 AI、轮询、随机三策略对比...")
        comparison_result = build_strategy_comparison(
            orders,
            max_station_limit=station_limit,
            operation_gap_seconds=gap_seconds,
            ai_model=model,
        )

        if not strategy_key.startswith("history"):
            selected_comparison_key = {
                "ai": "ai_result",
                "round_robin": "trad_result",
                "random": "rand_result",
            }.get(strategy_key)
            if selected_comparison_key and comparison_result.get(selected_comparison_key):
                simulation_station_limit = int(comparison_result[selected_comparison_key]["active_stations"])
                display_active_stations = simulation_station_limit

            assignments = dispatch_orders(
                orders,
                strategy_key,
                active_station_limit=simulation_station_limit,
                model=model,
                seed=999,
            )

        update_progress(task_id, "45%", "派工表已生成，正在执行统一仿真引擎...")
        sim_result = run_assignment_simpy_simulation(
            orders,
            assignments,
            task_id=task_id,
            active_station_limit=simulation_station_limit,
            operation_gap_seconds=gap_seconds,
        )
        makespan = float(sim_result["total_makespan"])
        if real_makespan and real_makespan > 0:
            error_pct = abs(makespan - real_makespan) / real_makespan * 100.0

        db.add_all(sim_result["db_records"])
        db.add(
            SimulationTask(
                task_id=task_id,
                batch_no=batch_no_for_db,
                strategy_type=task_strategy_label(strategy_key, process_time_used),
                active_stations=display_active_stations,
                total_makespan_sec=makespan,
                process_time_source=process_time_used,
                operation_gap_seconds=gap_seconds,
                real_makespan_sec=real_makespan,
                error_pct=error_pct,
            )
        )
        db.commit()

        update_progress(task_id, "100%", "仿真完成，3D 剧本已生成。")
        TASK_PROGRESS[task_id].update(
            {
                "status": "completed",
                "strategy": task_strategy_label(strategy_key, process_time_used),
                "active_stations": display_active_stations,
                "active_station_ids": active_station_ids,
                "max_station_limit": station_limit,
                "operation_gap_seconds": round(gap_seconds, 3),
                "total_makespan": round(makespan, 3),
                "real_makespan_seconds": round(real_makespan, 3) if real_makespan else None,
                "error_pct": round(error_pct, 3) if error_pct is not None else None,
                "within_10_pct": bool(error_pct <= 10.0) if error_pct is not None else None,
                "ai_result": comparison_result["ai_result"],
                "trad_result": comparison_result["trad_result"],
                "rand_result": comparison_result["rand_result"],
                "efficiency_up": comparison_result["efficiency_up"],
                "efficiency_vs_round_robin": comparison_result["efficiency_vs_round_robin"],
                "efficiency_vs_random": comparison_result["efficiency_vs_random"],
                "efficiency_formula": comparison_result["efficiency_formula"],
                "inventory_result": {
                    "initial_snapshot_id": inventory_snapshot_id,
                    "evening_snapshot_id": evening_snapshot_id,
                    "summary": inventory_summary,
                    "preprocess_stats": preprocess_stats,
                    "exception_order_count": len(shortage_orders),
                    "evening_validation": None,
                    "shortage_policy": "exception_queue",
                },
            }
        )
    except Exception as exc:
        db.rollback()
        import traceback

        traceback.print_exc()
        TASK_PROGRESS[task_id] = {
            "status": "failed",
            "progress": "failed",
            "message": f"报错中断: {str(exc)}",
        }
    finally:
        db.close()


def simpy_dispatch_engine(
    env,
    stations,
    rl_env,
    model,
    optimal_stations,
    dispatch_records,
    task_id,
    base_time,
    strategy="ai",
    save_records=True,
    random_seed=20260729,
    use_action_mask=True,
):
    db_logger = DBLogger(dispatch_records, task_id, base_time) if save_records else None
    for s in stations:
        s.logger = db_logger
        
    obs, _ = rl_env.reset(seed=999)
    energy_saving_mask = np.array([True] * optimal_stations + [False] * (Config.NUM_STATIONS - optimal_stations))
    
    done = False
    step = 0
    dispatch_time_cursor = 0.0
    rng = np.random.default_rng(random_seed)

    while not done:
        strategy_key = str(strategy or "ai").lower()
        if strategy_key == "ai":
            try:
                env_internal_mask = rl_env.unwrapped.action_masks()
            except AttributeError:
                env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

            combined_masks = np.logical_and(energy_saving_mask, env_internal_mask) if use_action_mask else energy_saving_mask
            if not np.any(combined_masks):
                combined_masks = energy_saving_mask

            obs_state = rl_env.unwrapped._get_obs()
            action = int(DispatchRules.rule_ai_policy(model, obs=obs_state, valid_masks=combined_masks))
        elif strategy_key == "round_robin":
            action = int(step % optimal_stations)
        elif strategy_key == "random":
            action = int(rng.integers(0, optimal_stations))
        else:
            raise ValueError(f"Unsupported simulation strategy: {strategy}")
        
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
        step += 1
        
    while any(s.machine.count > 0 or len(s.machine.queue) > 0 for s in stations):
        yield env.timeout(1.0)


# ==========================================
# 核心任务主引擎
# ==========================================
def run_simulation_task(
    task_id: str,
    batch_no: str = DEFAULT_BATCH_NO,
    inventory_snapshot_id: str = DEFAULT_INITIAL_SNAPSHOT_ID,
    evening_snapshot_id: str = DEFAULT_EVENING_SNAPSHOT_ID,
):
    db = SessionLocal()
    try:
        update_progress(task_id, "10%", f"正在提取波次 {batch_no} 的时空档案...")
        
        if AUTO_REBUILD_SKU_TIME:
            update_progress(task_id, "12%", "正在刷新 SKU 平均处理时间...")
            sku_time_result = rebuild_sku_avg_time()
            print(
                "SKU average picking time refreshed: "
                f"inserted={sku_time_result['inserted']}, "
                f"source_files={len(sku_time_result['source_files'])}"
            )

        update_progress(task_id, "15%", f"正在提取波次 {batch_no} 的订单数据...")
        db_orders = (
            db.query(OrderPool)
            .filter(OrderPool.batch_no == batch_no)
            .order_by(OrderPool.sequence_no.asc(), OrderPool.order_id.asc())
            .all()
        )
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
        processable_orders = select_processable_order_sequence(logical_orders, preprocessed)
        preprocess_stats = preprocessed["preprocess_stats"]
        shortage_orders = preprocessed["shortage_orders"]
        baseline_orders = processable_orders

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
        
        model_path = resolve_model_path()
        if not model_path or not model_path.exists():
            raise FileNotFoundError(f"找不到 AI 模型文件：{MODEL_DIR}")
        model = MaskablePPO.load(str(model_path), env=rl_env)

        def run_simpy_strategy(strategy, limit, save_records=False, result_task_id=None, seed_offset=0):
            strategy_key = str(strategy or "ai").lower()
            strategy_orders = processable_orders if strategy_key == "ai" else baseline_orders
            strategy_env = PickingEnv(dataset_type='test')
            strategy_env.unwrapped.set_orders(strategy_orders, episode_length=len(strategy_orders))
            sim_env = simpy.Environment()
            records = []
            base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
            physical_stations = [
                SimpyStation(sim_env, i, getattr(Config, 'MAX_ORDERS_PER_STATION', 2))
                for i in range(Config.NUM_STATIONS)
            ]
            sim_env.process(simpy_dispatch_engine(
                sim_env,
                physical_stations,
                strategy_env,
                model,
                limit,
                records,
                result_task_id or task_id,
                base_time,
                strategy=strategy,
                save_records=save_records,
                random_seed=20260729 + seed_offset,
                use_action_mask=(strategy_key == "ai"),
            ))
            sim_env.run()
            return {
                "strategy": strategy,
                "active_stations": limit,
                "total_makespan": float(sim_env.now),
                "dispatch_records": records,
            }

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
                ms = run_simpy_strategy(strategy, limit, save_records=False, seed_offset=limit)["total_makespan"]
                results[strategy].append((limit, ms))
                if ms > Config.DEADLINE_SECONDS:
                    print(f"  - active stations: {limit:02d} | SimPy makespan: {ms:.1f}s | timeout")
                    break
                status_txt = "✅ 满足" if ms <= Config.DEADLINE_SECONDS else "❌ 超时"
                print(f"  └─ 开机数: {limit:02d} | 完工耗时: {ms:.1f}s | {status_txt}")

        update_progress(task_id, "85%", "已锁定最优资源配比！准备刻录物理引擎与 3D 剧本...")

        def get_best(strat):
            valid = [r for r in results[strat] if r[1] <= Config.DEADLINE_SECONDS]
            # results are scanned from 16 stations down to 1 station. If a strategy
            # cannot meet the deadline, show its 16-station result instead of the
            # 1-station tail result; otherwise the frontend comparison is misleading.
            return min(valid, key=lambda x: x[0]) if valid else results[strat][0]

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

        def station_hour_efficiency(baseline_st, baseline_tm, ai_station_count, ai_makespan):
            baseline_station_time = float(baseline_st) * float(baseline_tm)
            ai_station_time = float(ai_station_count) * float(ai_makespan)
            if baseline_station_time <= 0:
                return 0.0
            return (1 - ai_station_time / baseline_station_time) * 100

        eff_vs_trad = station_hour_efficiency(trad_st, trad_tm, ai_st, ai_real_makespan)
        eff_vs_rand = station_hour_efficiency(rand_st, rand_tm, ai_st, ai_real_makespan)
        inventory_summary = (initial_inventory_snapshot or {}).get("summary", {})

        update_progress(task_id, "100%", "✅ 战报生成完毕！大屏可提取渲染！")
        TASK_PROGRESS[task_id].update({
            "status": "completed", "deadline": Config.DEADLINE_SECONDS,
            "ai_result": {"active_stations": ai_st, "total_makespan": round(ai_real_makespan, 2)},
            "trad_result": {"active_stations": trad_st, "total_makespan": round(trad_tm, 2)},
            "rand_result": {"active_stations": rand_st, "total_makespan": round(rand_tm, 2)},
            "efficiency_up": f"{eff_vs_trad:.2f}%",
            "efficiency_vs_round_robin": f"{eff_vs_trad:.2f}%",
            "efficiency_vs_random": f"{eff_vs_rand:.2f}%",
            "efficiency_formula": "1 - (ai_stations * ai_makespan) / (baseline_stations * baseline_makespan)",
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
        ordered_order_ids = []
        seen_order_ids = set()
        for item in batch_data.orders:
            if item.order_id not in seen_order_ids:
                seen_order_ids.add(item.order_id)
                ordered_order_ids.append(item.order_id)

        if not ordered_order_ids:
            raise ValueError("上传订单为空")

        if batch_data.replace_existing:
            old_order_ids = [
                row[0]
                for row in db.query(OrderPool.order_id)
                .filter(OrderPool.batch_no == batch_data.batch_no)
                .all()
            ]
            if old_order_ids:
                db.query(OrderBOM).filter(OrderBOM.order_id.in_(old_order_ids)).delete(synchronize_session=False)
                db.query(OrderPool).filter(OrderPool.batch_no == batch_data.batch_no).delete(synchronize_session=False)
                db.flush()

        db.query(OrderBOM).filter(OrderBOM.order_id.in_(ordered_order_ids)).delete(synchronize_session=False)
        db.query(OrderPool).filter(OrderPool.order_id.in_(ordered_order_ids)).delete(synchronize_session=False)
        db.flush()

        current_max_sequence = (
            db.query(func.max(OrderPool.sequence_no))
            .filter(OrderPool.batch_no == batch_data.batch_no)
            .scalar()
        )
        sequence_base = int(current_max_sequence or 0)
        for idx, o_id in enumerate(ordered_order_ids, start=1):
            db.add(
                OrderPool(
                    order_id=o_id,
                    batch_no=batch_data.batch_no,
                    priority_level=1,
                    sequence_no=sequence_base + idx,
                )
            )
        for item in batch_data.orders:
            db.add(OrderBOM(order_id=item.order_id, part_type=item.part_type, quantity=item.quantity))
        db.commit()
        return {"code": 200, "message": f"成功入库 {len(ordered_order_ids)} 个真实拣选单的数据！"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/orders/batches")
def list_order_batches(db: SessionLocal = Depends(get_db)):
    rows = (
        db.query(OrderPool.batch_no, func.count(OrderPool.order_id))
        .filter(OrderPool.batch_no.isnot(None))
        .group_by(OrderPool.batch_no)
        .order_by(OrderPool.batch_no.desc())
        .all()
    )
    batches = [
        {"batch_no": str(batch_no), "order_count": int(order_count)}
        for batch_no, order_count in rows
        if batch_no
    ]
    if DEFAULT_BATCH_NO and not any(item["batch_no"] == DEFAULT_BATCH_NO for item in batches):
        batches.insert(0, {"batch_no": DEFAULT_BATCH_NO, "order_count": 0})
    return {"code": 200, "data": batches}

@app.post("/api/v1/sku-time/rebuild")
def rebuild_sku_time():
    try:
        result = rebuild_sku_avg_time()
        return {
            "code": 200,
            "message": "SKU average picking time refreshed",
            "data": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/simulation/start")
def start_simulation(req: SimulationRequest, bg_tasks: BackgroundTasks):
    task_id = f"TASK-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    bg_tasks.add_task(
        run_unified_simulation_task,
        task_id,
        req.batch_no,
        req.inventory_snapshot_id,
        req.evening_snapshot_id,
        req.strategy,
        req.active_station_limit,
        req.history_date,
        req.process_time_source,
        req.operation_gap_seconds,
    )
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

@app.get("/api/v1/app/config")
def get_app_config():
    return {
        "code": 200,
        "data": {
            "active_date": DEFAULT_DAILY_DATE,
            "default_batch_no": DEFAULT_BATCH_NO,
            "default_initial_snapshot_id": DEFAULT_INITIAL_SNAPSHOT_ID,
            "default_evening_snapshot_id": DEFAULT_EVENING_SNAPSHOT_ID,
            "default_strategy": DEFAULT_STRATEGY,
            "default_active_station_limit": DEFAULT_ACTIVE_STATION_LIMIT,
            "operation_gap_seconds": DEFAULT_OPERATION_GAP_SECONDS,
            "operation_gap_seconds_by_strategy": {
                "ai": DEFAULT_OPERATION_GAP_SECONDS,
                "random": DEFAULT_OPERATION_GAP_SECONDS,
                "round_robin": DEFAULT_OPERATION_GAP_SECONDS,
                "history_actual": HISTORY_ACTUAL_OPERATION_GAP_SECONDS,
                "history_sku_avg": HISTORY_SKU_AVERAGE_OPERATION_GAP_SECONDS,
            },
        },
    }

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
        task_info = db.query(SimulationTask).filter(SimulationTask.task_id == task_id).first()
        if not task_info:
            ai_task_id = f"{task_id}-AI"
            task_info = db.query(SimulationTask).filter(SimulationTask.task_id == ai_task_id).first()
        if not task_info: raise HTTPException(status_code=404, detail="未找到任务宏观战报")
            
        records = db.query(DispatchResult).filter(DispatchResult.task_id == task_id).order_by(DispatchResult.predicted_spawn_time).all()
        if not records: raise HTTPException(status_code=404, detail="未找到派工明细")
        active_station_ids = sorted({int(r.target_station) for r in records if getattr(r, "target_station", None)})
        is_history_task = str(task_info.strategy_type or "").upper().startswith("HISTORY")

        playbook = {
            "task_id": task_id, "strategy": task_info.strategy_type,
            "active_stations": len(active_station_ids) if is_history_task and active_station_ids else task_info.active_stations,
            "active_station_ids": active_station_ids if is_history_task else [],
            "total_makespan_sec": task_info.total_makespan_sec, "total_boxes": len(records),
            "operation_gap_seconds": getattr(task_info, "operation_gap_seconds", 0.0),
            "real_makespan_sec": getattr(task_info, "real_makespan_sec", None),
            "error_pct": getattr(task_info, "error_pct", None),
            "timeline": []
        }
        for r in records:
            item = {
                "order_id": r.order_id,
                "box_id": r.box_id,
                "target_station": r.target_station,
                "sku": getattr(r, "sku", ""),
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
