import datetime
import os
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional

import simpy

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.database import DispatchResult
from backend.simulation_runner import station_inbound_travel_time
from scenarios.order_picking.config import Config


@dataclass
class SimpyTimelineRecord:
    task_id: str
    order_id: str
    box_id: str
    sku: str
    target_station: int
    spawn_time: float
    start_time: float
    end_time: float
    process_time: float


class AssignmentStation:
    def __init__(self, env: simpy.Environment, station_idx: int, operation_gap_seconds: float):
        self.env = env
        self.station_idx = station_idx
        self.operation_gap_seconds = max(0.0, float(operation_gap_seconds or 0.0))
        self.machine = simpy.Resource(env, capacity=1)
        self.active_boxes = {}
        self.completed = env.event()
        self.records: List[SimpyTimelineRecord] = []
        self.box_count = 0
        self.busy_seconds = 0.0
        self.available_time = 0.0

    def can_accept(self, order_id: str) -> bool:
        active_order_ids = {item["order_id"] for item in self.active_boxes.values()}
        is_new_order = str(order_id) not in active_order_ids
        if is_new_order and len(active_order_ids) >= getattr(Config, "MAX_ORDERS_PER_STATION", 2):
            return False
        if len(self.active_boxes) >= getattr(Config, "MAX_BOXES_PER_STATION", 8):
            return False
        return True

    def wait_for_capacity(self, order_id: str):
        while not self.can_accept(order_id):
            event = self.completed
            yield event

    def process_box(
        self,
        task_id: str,
        order_id: str,
        box_id: str,
        sku: str,
        process_time: float,
        travel_time: float,
        spawn_time: float,
    ):
        self.active_boxes[box_id] = {"order_id": str(order_id)}
        if travel_time > 0:
            yield self.env.timeout(float(travel_time))

        with self.machine.request() as request:
            yield request
            start_time = float(self.env.now)
            duration = max(0.0, float(process_time or 0.0)) + self.operation_gap_seconds
            if duration > 0:
                yield self.env.timeout(duration)
            end_time = float(self.env.now)

        self.box_count += 1
        self.busy_seconds += duration
        self.available_time = max(self.available_time, end_time)
        self.records.append(
            SimpyTimelineRecord(
                task_id=task_id,
                order_id=str(order_id),
                box_id=box_id,
                sku=str(sku or ""),
                target_station=self.station_idx + 1,
                spawn_time=float(spawn_time),
                start_time=start_time,
                end_time=end_time,
                process_time=float(process_time or 0.0),
            )
        )
        self.active_boxes.pop(box_id, None)
        old_event = self.completed
        if not old_event.triggered:
            old_event.succeed()
        self.completed = self.env.event()


def run_assignment_simpy_simulation(
    orders: List[dict],
    assignments: Iterable[dict],
    task_id: str,
    active_station_limit: int = Config.NUM_STATIONS,
    operation_gap_seconds: float = 0.0,
    base_time: Optional[datetime.datetime] = None,
) -> dict:
    """Run a SimPy discrete-event simulation from a precomputed assignment list."""
    order_by_id = {str(order["order_id"]): order for order in orders}
    station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
    gap = max(0.0, float(operation_gap_seconds or 0.0))
    base_dt = base_time or datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    env = simpy.Environment()
    stations = [AssignmentStation(env, idx, gap) for idx in range(Config.NUM_STATIONS)]

    def dispatch_process():
        for assignment in sorted(assignments, key=lambda item: int(item.get("sequence", 0))):
            order_id = str(assignment["order_id"])
            if order_id not in order_by_id:
                continue
            order = order_by_id[order_id]
            station_id = int(assignment["target_station"])
            action = max(0, min(station_id - 1, station_limit - 1, Config.NUM_STATIONS - 1))
            station = stations[action]
            travel_time = station_inbound_travel_time(action)

            for box_idx, box in enumerate(order.get("boxes", []), start=1):
                yield env.process(station.wait_for_capacity(order_id))
                yield env.timeout(float(getattr(Config, "DISPATCH_INTERVAL", 0.0)))
                spawn_time = float(env.now)
                box_id = f"{order_id}-P{box.get('sku', '')}-{box_idx}"
                env.process(
                    station.process_box(
                        task_id=task_id,
                        order_id=order_id,
                        box_id=box_id,
                        sku=str(box.get("sku", "")),
                        process_time=float(box.get("p_time", 0.0)),
                        travel_time=travel_time,
                        spawn_time=spawn_time,
                    )
                )

    env.process(dispatch_process())
    env.run()

    records = [record for station in stations for record in station.records]
    records.sort(key=lambda record: (record.spawn_time, record.start_time, record.end_time, record.box_id))
    station_available = [station.available_time for station in stations]
    station_box_counts = [station.box_count for station in stations]
    station_busy_seconds = [station.busy_seconds for station in stations]
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
        "engine": "simpy",
        "active_stations": station_limit,
        "operation_gap_seconds": gap,
        "total_makespan": float(total_makespan),
        "critical_station": critical_station_idx + 1,
        "critical_station_box_count": int(station_box_counts[critical_station_idx]),
        "timeline": timeline,
        "db_records": db_records,
        "station_stats": station_stats,
    }
