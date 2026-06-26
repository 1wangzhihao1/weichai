import os
import sys

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
try:
    from backend.database import PartMaster, SessionLocal
except Exception:
    PartMaster = None
    SessionLocal = None
from scenarios.order_picking.config import Config

EXCEL_PATH = os.path.join(project_root, "raw_data", "DMS拣选20260201-0429.XLSX")

TARGET_MAKESPAN_FACTOR = 1.2
MAKESPAN_SUCCESS_REWARD = 100.0
MAKESPAN_OVERRUN_PENALTY = 0.01
MAKESPAN_MAX_PENALTY = 300.0


def find_default_excel():
    if os.path.exists(EXCEL_PATH):
        return EXCEL_PATH

    raw_dir = os.path.join(project_root, "raw_data")
    if not os.path.isdir(raw_dir):
        return EXCEL_PATH

    for name in os.listdir(raw_dir):
        lower = name.lower()
        if name.startswith("~$"):
            continue
        if name.startswith("DMS") and lower.endswith((".xlsx", ".xls")):
            return os.path.join(raw_dir, name)

    return EXCEL_PATH


EXCEL_PATH = find_default_excel()


def load_part_times_from_database():
    if PartMaster is None or SessionLocal is None:
        return {}

    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        all_parts = db.query(PartMaster).all()
        return {str(p.part_type).strip(): float(p.standard_p_time) for p in all_parts}
    except Exception:
        return {}
    finally:
        try:
            db.close()
        except Exception:
            pass


def build_part_times_from_excel(excel_path):
    if not os.path.exists(excel_path):
        return {}

    try:
        df = pd.read_excel(excel_path, sheet_name=0)
    except Exception:
        return {}

    rows = []
    for _, row in df.iterrows():
        try:
            row_vals = row.values
            if len(row_vals) < 13:
                continue
            start_time = pd.to_datetime(row_vals[2], errors="coerce")
            end_time = pd.to_datetime(row_vals[3], errors="coerce")
            status = str(row_vals[8]).strip()
            sku = str(row_vals[9]).strip()
            picked_qty = float(row_vals[12])
            if pd.isna(start_time) or pd.isna(end_time):
                continue
            duration = (end_time - start_time).total_seconds()
            if status not in ["确定", "完成"] or not sku or picked_qty <= 0 or duration <= 0:
                continue
            rows.append((sku, duration, picked_qty, duration / picked_qty))
        except Exception:
            continue

    if not rows:
        return {}

    clean = pd.DataFrame(rows, columns=["sku", "duration", "qty", "unit_time"])
    q1 = clean["unit_time"].quantile(0.25)
    q3 = clean["unit_time"].quantile(0.75)
    upper = max(float(q3 + 3.0 * (q3 - q1)), 300.0)
    clean = clean[clean["unit_time"] <= upper]
    grouped = clean.groupby("sku").agg(duration=("duration", "sum"), qty=("qty", "sum"))
    return (grouped["duration"] / grouped["qty"]).to_dict()


def load_and_aggregate_real_orders():
    print("[RL 数据管道] 正在装载标准工艺定额...")
    part_time_dict = load_part_times_from_database()
    if part_time_dict:
        print(f"[RL 数据管道] 已从数据库读取 {len(part_time_dict)} 条 SKU 工艺定额。")
    else:
        part_time_dict = build_part_times_from_excel(EXCEL_PATH)
        print(f"[RL 数据管道] 数据库不可用，已从 Excel 计算 {len(part_time_dict)} 条 SKU 工艺定额。")

    print("[RL 数据管道] 正在按照【同订单同SKU合并为1箱】法则解析大盘...")
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    except Exception as exc:
        print(f"[RL 数据管道] 读取订单 Excel 失败: {EXCEL_PATH} ({exc})")
        return []

    order_aggregation = {}
    for _, row in df.iterrows():
        try:
            row_vals = row.values
            if len(row_vals) < 13:
                continue
            time_start = pd.to_datetime(row_vals[2])
            order_id = str(row_vals[6]).strip()
            status = str(row_vals[8]).strip()
            sku = str(row_vals[9]).strip()
            qty = float(row_vals[11])
        except Exception:
            continue

        if status not in ["确定", "完成"] or qty <= 0:
            continue

        box_process_time = part_time_dict.get(sku, 4.5) * int(qty)

        if order_id not in order_aggregation:
            order_aggregation[order_id] = {
                "order_id": order_id,
                "start_time": time_start,
                "sku_map": {},
                "total_p_time": 0.0,
            }

        if sku not in order_aggregation[order_id]["sku_map"]:
            order_aggregation[order_id]["sku_map"][sku] = 0.0

        order_aggregation[order_id]["sku_map"][sku] += box_process_time
        order_aggregation[order_id]["total_p_time"] += box_process_time

    aggregated_orders = []
    for data in order_aggregation.values():
        boxes = [{"sku": sku, "p_time": p_time} for sku, p_time in data["sku_map"].items()]
        data["boxes"] = boxes
        del data["sku_map"]
        aggregated_orders.append(data)

    aggregated_orders.sort(key=lambda x: x["start_time"])
    print(f"[RL 数据管道] 大盘聚合完成，微观订单总数: {len(aggregated_orders)}")
    return aggregated_orders


_GLOBAL_ORDERS_CACHE = None


class PickingEnv(gym.Env):
    def __init__(self, dataset_type="train", initial_orders=None, **_ignored_kwargs):
        super().__init__()
        self.action_space = spaces.Discrete(Config.NUM_STATIONS)
        self.obs_dim = Config.NUM_STATIONS * 4 + 2
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.obs_dim,), dtype=np.float32)

        if initial_orders is not None:
            self.real_world_orders = list(initial_orders)
        else:
            global _GLOBAL_ORDERS_CACHE
            if _GLOBAL_ORDERS_CACHE is None:
                _GLOBAL_ORDERS_CACHE = load_and_aggregate_real_orders()

            all_orders = _GLOBAL_ORDERS_CACHE
            train_bound = int(len(all_orders) * 0.67)

            if dataset_type == "train":
                self.real_world_orders = all_orders[:train_bound]
            elif dataset_type == "test":
                self.real_world_orders = all_orders[train_bound:]
            else:
                self.real_world_orders = all_orders

        self.total_orders = len(self.real_world_orders)
        self.episode_length = 1000
        self.expected_exit_times = np.array(
            [Config.get_expected_exit_time(i) for i in range(Config.NUM_STATIONS)], dtype=np.float32
        )

    def set_orders(self, orders, episode_length=None):
        self.real_world_orders = list(orders)
        self.total_orders = len(self.real_world_orders)
        self.episode_length = episode_length or len(self.real_world_orders)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        max_start = max(0, self.total_orders - self.episode_length)
        self.start_idx = int(self.np_random.integers(0, max_start + 1)) if max_start > 0 else 0
        self.end_idx = min(self.start_idx + self.episode_length, self.total_orders)

        self.current_step = self.start_idx
        self.global_time = 0.0
        self.station_available_time = np.zeros(Config.NUM_STATIONS, dtype=np.float32)
        self.station_active_boxes = [[] for _ in range(Config.NUM_STATIONS)]

        return self._get_obs(), {}

    def _get_obs(self):
        for i in range(Config.NUM_STATIONS):
            self.station_active_boxes[i] = [
                b for b in self.station_active_boxes[i] if b["finish_time"] > self.global_time
            ]

        workloads = np.array(
            [max(0.0, self.station_available_time[i] - self.global_time) for i in range(Config.NUM_STATIONS)],
            dtype=np.float32,
        )
        boxes_count = np.array([len(self.station_active_boxes[i]) for i in range(Config.NUM_STATIONS)], dtype=np.float32)
        orders_count = np.array(
            [len(set(b["order_id"] for b in self.station_active_boxes[i])) for i in range(Config.NUM_STATIONS)],
            dtype=np.float32,
        )

        station_state = np.column_stack((workloads, boxes_count, orders_count, self.expected_exit_times)).flatten()

        if self.current_step >= self.end_idx:
            curr_info = np.array([0.0, 0.0], dtype=np.float32)
        else:
            curr_order = self.real_world_orders[self.current_step]
            curr_info = np.array([curr_order["total_p_time"], len(curr_order["boxes"])], dtype=np.float32)

        return np.concatenate((station_state, curr_info))

    def action_masks(self):
        if self.current_step >= self.end_idx:
            return np.ones(Config.NUM_STATIONS, dtype=bool)

        curr_order = self.real_world_orders[self.current_step]
        order_id = curr_order["order_id"]
        mask = np.ones(Config.NUM_STATIONS, dtype=bool)

        for i in range(Config.NUM_STATIONS):
            self.station_active_boxes[i] = [
                b for b in self.station_active_boxes[i] if b["finish_time"] > self.global_time
            ]
            active_boxes = len(self.station_active_boxes[i])
            active_order_ids = set(b["order_id"] for b in self.station_active_boxes[i])
            is_new_order = order_id not in active_order_ids

            if active_boxes >= Config.MAX_BOXES_PER_STATION:
                mask[i] = False
            elif is_new_order and len(active_order_ids) >= Config.MAX_ORDERS_PER_STATION:
                mask[i] = False

        if not np.any(mask):
            return np.ones(Config.NUM_STATIONS, dtype=bool)

        return mask

    def step(self, action):
        if self.current_step >= self.end_idx:
            return self._get_obs(), 0.0, True, False, {}

        old_time = self.global_time
        curr_order = self.real_world_orders[self.current_step]
        order_id = curr_order["order_id"]

        for box in curr_order["boxes"]:
            p_time = box["p_time"]

            while True:
                self.station_active_boxes[action] = [
                    b for b in self.station_active_boxes[action] if b["finish_time"] > self.global_time
                ]

                active_boxes = len(self.station_active_boxes[action])
                active_order_ids = set(b["order_id"] for b in self.station_active_boxes[action])
                is_new_order = order_id not in active_order_ids

                order_limit_hit = is_new_order and len(active_order_ids) >= Config.MAX_ORDERS_PER_STATION
                box_limit_hit = active_boxes >= Config.MAX_BOXES_PER_STATION

                if not order_limit_hit and not box_limit_hit:
                    break

                if self.station_active_boxes[action]:
                    next_finish = min(b["finish_time"] for b in self.station_active_boxes[action])
                    self.global_time = max(self.global_time, next_finish)
                else:
                    self.global_time += 1.0

            self.global_time += Config.DISPATCH_INTERVAL

            t_trans_in = ((action * 5.0) / Config.BELT_SPEED) + Config.get_branch_info(action)["transit_time_s"]
            arrival_time = self.global_time + t_trans_in

            start_process = max(self.station_available_time[action], arrival_time)
            finish_process = start_process + p_time

            self.station_available_time[action] = finish_process
            self.station_active_boxes[action].append({"finish_time": finish_process, "order_id": order_id})

        self.current_step += 1
        done = self.current_step >= self.end_idx
        if done:
            self.global_time = max(self.global_time, np.max(self.station_available_time))

        time_passed = self.global_time - old_time
        expected_time = len(curr_order["boxes"]) * Config.DISPATCH_INTERVAL
        jam_delay = max(0.0, time_passed - expected_time)
        reward = -(jam_delay * 0.5)
        reward -= self.expected_exit_times[action] * 0.001
        info = {}

        if done:
            episode_orders = self.real_world_orders[self.start_idx : self.end_idx]
            total_process_time = sum(
                float(box.get("p_time", 0.0))
                for order in episode_orders
                for box in order.get("boxes", [])
            )
            target_makespan = (total_process_time / Config.NUM_STATIONS) * TARGET_MAKESPAN_FACTOR
            makespan = float(self.global_time)

            if target_makespan > 0:
                if makespan <= target_makespan:
                    terminal_reward = MAKESPAN_SUCCESS_REWARD
                else:
                    overrun = makespan - target_makespan
                    terminal_reward = -min(MAKESPAN_MAX_PENALTY, overrun * MAKESPAN_OVERRUN_PENALTY)

                reward += terminal_reward
                info.update(
                    {
                        "makespan": makespan,
                        "target_makespan": float(target_makespan),
                        "terminal_makespan_reward": float(terminal_reward),
                    }
                )

        return self._get_obs(), float(reward), done, False, info
