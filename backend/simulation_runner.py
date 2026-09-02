import datetime
import os
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.database import DispatchResult
from scenarios.order_picking.config import Config


@dataclass
class TimelineRecord:
    task_id: str
    order_id: str
    box_id: str
    sku: str
    target_station: int
    spawn_time: float
    start_time: float
    end_time: float
    process_time: float


def station_inbound_travel_time(station_idx: int) -> float:
    try:
        d_main = Config.get_station_main_distance(station_idx)
        t_branch = Config.get_branch_info(station_idx)["transit_time_s"]
        return (d_main / Config.BELT_SPEED) + t_branch
    except AttributeError:
        d_main = Config.STATION_EXIT_FAR_DISTANCES[station_idx] - (Config.EXIT_PORT_DELTA / 2.0)
        return (d_main / Config.BELT_SPEED) + (Config.BRANCH_IN_LENGTH / Config.BELT_SPEED)


def run_assignment_simulation(
    orders: List[dict],
    assignments: Iterable[dict],
    task_id: str,
    active_station_limit: int = Config.NUM_STATIONS,
    operation_gap_seconds: float = 0.0,
    base_time: Optional[datetime.datetime] = None,
) -> dict:
    """Run the physical timing model from an already-decided order-to-station assignment list."""
    order_by_id = {str(order["order_id"]): order for order in orders}
    station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
    gap = max(0.0, float(operation_gap_seconds or 0.0))
    base_dt = base_time or datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    station_available = [0.0 for _ in range(Config.NUM_STATIONS)]
    station_active_boxes: List[List[dict]] = [[] for _ in range(Config.NUM_STATIONS)]
    station_box_counts = [0 for _ in range(Config.NUM_STATIONS)]
    station_busy_seconds = [0.0 for _ in range(Config.NUM_STATIONS)]
    dispatch_time_cursor = 0.0
    records: List[TimelineRecord] = []

    for assignment in sorted(assignments, key=lambda item: int(item.get("sequence", 0))):
        order_id = str(assignment["order_id"])
        if order_id not in order_by_id:
            continue
        order = order_by_id[order_id]
        station_id = int(assignment["target_station"])
        action = max(0, min(station_id - 1, station_limit - 1, Config.NUM_STATIONS - 1))
        t_trans = station_inbound_travel_time(action)
        local_cursor = dispatch_time_cursor

        for box_idx, box in enumerate(order.get("boxes", []), start=1):
            while True:
                active_boxes = [item for item in station_active_boxes[action] if item["finish_time"] > local_cursor]
                station_active_boxes[action] = active_boxes
                active_order_ids = {item["order_id"] for item in active_boxes}
                is_new_order = order_id not in active_order_ids

                order_limit_hit = is_new_order and len(active_order_ids) >= getattr(Config, "MAX_ORDERS_PER_STATION", 2)
                box_limit_hit = len(active_boxes) >= getattr(Config, "MAX_BOXES_PER_STATION", 8)
                if not order_limit_hit and not box_limit_hit:
                    break
                if active_boxes:
                    local_cursor = max(local_cursor, min(item["finish_time"] for item in active_boxes))
                else:
                    local_cursor += 1.0

            local_cursor += Config.DISPATCH_INTERVAL
            spawn_time = local_cursor
            arrival_time = spawn_time + t_trans
            start_time = max(station_available[action], arrival_time)
            raw_process_time = float(box.get("p_time", 0.0))
            end_time = start_time + raw_process_time + gap

            station_available[action] = end_time
            station_active_boxes[action].append({"finish_time": end_time, "order_id": order_id})
            station_box_counts[action] += 1
            station_busy_seconds[action] += raw_process_time + gap
            records.append(
                TimelineRecord(
                    task_id=task_id,
                    order_id=order_id,
                    box_id=f"{order_id}-P{box.get('sku', '')}-{box_idx}",
                    sku=str(box.get("sku", "")),
                    target_station=action + 1,
                    spawn_time=spawn_time,
                    start_time=start_time,
                    end_time=end_time,
                    process_time=raw_process_time,
                )
            )
        dispatch_time_cursor = local_cursor

    total_makespan = max(station_available) if station_available else 0.0
    critical_station_idx = int(max(range(Config.NUM_STATIONS), key=lambda idx: station_available[idx]))
    db_records = [
        DispatchResult(
            task_id=record.task_id,
            order_id=record.order_id,
            box_id=record.box_id,
            target_station=record.target_station,
            predicted_spawn_time=base_dt + datetime.timedelta(seconds=float(record.spawn_time)),
            predicted_start_time=base_dt + datetime.timedelta(seconds=float(record.start_time)),
            predicted_end_time=base_dt + datetime.timedelta(seconds=float(record.end_time)),
            sku=record.sku,
        )
        for record in records
    ]
    timeline = [
        {
            "order_id": record.order_id,
            "box_id": record.box_id,
            "sku": record.sku,
            "target_station": record.target_station,
            "spawn_time": (base_dt + datetime.timedelta(seconds=float(record.spawn_time))).isoformat(),
            "start_time": (base_dt + datetime.timedelta(seconds=float(record.start_time))).isoformat(),
            "end_time": (base_dt + datetime.timedelta(seconds=float(record.end_time))).isoformat(),
            "process_time": round(float(record.process_time), 3),
        }
        for record in records
    ]
    station_stats = [
        {
            "station_id": idx + 1,
            "enabled": idx < station_limit,
            "box_count": int(station_box_counts[idx]),
            "available_time_seconds": round(float(station_available[idx]), 3),
            "busy_seconds": round(float(station_busy_seconds[idx]), 3),
        }
        for idx in range(Config.NUM_STATIONS)
    ]
    return {
        "task_id": task_id,
        "active_stations": station_limit,
        "operation_gap_seconds": gap,
        "total_makespan": float(total_makespan),
        "critical_station": critical_station_idx + 1,
        "critical_station_box_count": int(station_box_counts[critical_station_idx]),
        "timeline": timeline,
        "db_records": db_records,
        "station_stats": station_stats,
    }
