import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date

import numpy as np
import simpy
from sb3_contrib import MaskablePPO

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import Config
from core_engine.models.resource_model import SimpyStation
from rl_environment import PickingEnv


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run a SimPy physical verification for the current order-picking RL logic. "
            "The script uses the same 33% test split and station deadline scan as compare.py."
        )
    )
    parser.add_argument("--date", help="Verify one date, for example 2026-04-11.")
    parser.add_argument("--date-from", dest="date_from", help="Inclusive start date.")
    parser.add_argument("--date-to", dest="date_to", help="Inclusive end date.")
    parser.add_argument("--min-stations", type=int, default=1, help="Minimum station count for deadline scan.")
    parser.add_argument("--max-stations", type=int, default=Config.NUM_STATIONS, help="Maximum station count for deadline scan.")
    parser.add_argument(
        "--optimize-deadline",
        action="store_true",
        help="Choose the minimum AI station count satisfying Config.DEADLINE_SECONDS.",
    )
    parser.add_argument("--station-limit", type=int, help="Use a fixed station count instead of scanning.")
    parser.add_argument("--model", help="Optional model .zip path. Defaults to the newest file under output/models.")
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument(
        "--max-orders",
        type=int,
        help="Optional cap for quick screenshots. The default verifies all selected orders.",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "simpy_verify_results.json"),
        help="JSON output path.",
    )
    return parser.parse_args()


def order_date(order):
    start_time = order.get("start_time")
    if hasattr(start_time, "date"):
        return start_time.date().isoformat()
    return str(start_time)[:10]


def select_dates(orders_by_date, args):
    dates = sorted(orders_by_date)
    if args.date:
        return [args.date] if args.date in orders_by_date else []
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    return dates


def set_orders(env, orders):
    env.unwrapped.episode_mode = "sequential"
    env.unwrapped.max_episode_orders = None
    if hasattr(env.unwrapped, "set_orders"):
        env.unwrapped.set_orders(orders, episode_length=len(orders))
    else:
        env.unwrapped.base_orders = list(orders)
        env.unwrapped.real_world_orders = list(orders)
        env.unwrapped.total_orders = len(orders)
        env.unwrapped.episode_length = len(orders)


def load_model(model_path, env):
    if model_path:
        resolved = model_path
    else:
        model_dir = os.path.join(project_root, "output", "models")
        candidates = glob.glob(os.path.join(model_dir, "*.zip"))
        if not candidates:
            raise FileNotFoundError(f"No .zip model found under {model_dir}.")
        resolved = max(candidates, key=os.path.getctime)
    model = MaskablePPO.load(resolved, env=env)
    return model, resolved


def run_rl_episode(orders, model, station_limit, seed):
    rl_env = PickingEnv(dataset_type="test", episode_mode="sequential", enable_inventory=False)
    set_orders(rl_env, orders)
    obs, _ = rl_env.reset(seed=seed)
    done = False
    actions = []
    enabled_mask = np.array(
        [True] * station_limit + [False] * (Config.NUM_STATIONS - station_limit),
        dtype=bool,
    )

    while not done:
        try:
            env_mask = rl_env.unwrapped.action_masks()
        except AttributeError:
            env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
        mask = np.logical_and(enabled_mask, env_mask)
        if not np.any(mask):
            mask = enabled_mask

        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        action = int(action)
        actions.append(action)
        obs, _, done, _, _ = rl_env.step(action)

    return {
        "makespan": float(rl_env.unwrapped.global_time),
        "actions": actions,
        "orders": list(rl_env.unwrapped.real_world_orders),
    }


def choose_station_limit(orders, model, args):
    if args.station_limit:
        limit = max(1, min(args.station_limit, Config.NUM_STATIONS))
        rl_result = run_rl_episode(orders, model, limit, args.seed + limit)
        return limit, rl_result, [{"station_limit": limit, "ai_makespan": round(rl_result["makespan"], 3)}]

    min_stations = max(1, min(args.min_stations, Config.NUM_STATIONS))
    max_stations = max(min_stations, min(args.max_stations, Config.NUM_STATIONS))
    scan = []
    selected_limit = max_stations
    selected_result = None

    for limit in range(min_stations, max_stations + 1):
        rl_result = run_rl_episode(orders, model, limit, args.seed + limit)
        scan.append({"station_limit": limit, "ai_makespan": round(rl_result["makespan"], 3)})
        print(f"  scan stations={limit:02d}, rl_makespan={rl_result['makespan']:.1f}s")
        if args.optimize_deadline and rl_result["makespan"] <= Config.DEADLINE_SECONDS:
            selected_limit = limit
            selected_result = rl_result
            break

    if selected_result is None:
        best = min(scan, key=lambda item: item["ai_makespan"])
        selected_limit = int(best["station_limit"])
        selected_result = run_rl_episode(orders, model, selected_limit, args.seed + selected_limit)

    return selected_limit, selected_result, scan


def station_active_box_count(station):
    return int(sum(station.active_orders.values()))


def station_inbound_travel_time(station_idx):
    if hasattr(Config, "get_station_main_distance"):
        main_distance = Config.get_station_main_distance(station_idx)
    elif hasattr(Config, "STATION_EXIT_FAR_DISTANCES"):
        main_distance = Config.STATION_EXIT_FAR_DISTANCES[station_idx] - (
            getattr(Config, "EXIT_PORT_DELTA", 0.0) / 2.0
        )
    else:
        main_distance = station_idx * 5.0

    branch_info = Config.get_branch_info(station_idx)
    branch_time = float(branch_info.get("transit_time_s", 0.0))
    return (main_distance / Config.BELT_SPEED) + branch_time


def make_stats():
    return {
        "peak_active_orders": np.zeros(Config.NUM_STATIONS, dtype=int),
        "peak_active_boxes": np.zeros(Config.NUM_STATIONS, dtype=int),
        "busy_times": np.zeros(Config.NUM_STATIONS, dtype=float),
        "processed_boxes": np.zeros(Config.NUM_STATIONS, dtype=int),
        "total_boxes": 0,
    }


def monitor_process(env, stations, stats):
    while True:
        for station in stations:
            sid = station.station_id
            stats["peak_active_orders"][sid] = max(stats["peak_active_orders"][sid], station.active_order_count)
            stats["peak_active_boxes"][sid] = max(stats["peak_active_boxes"][sid], station_active_box_count(station))
        yield env.timeout(0.1)


def dispatch_physical_orders(env, stations, orders, actions, stats):
    for order, action in zip(orders, actions):
        target_station = stations[action]
        order_id = str(order["order_id"])

        t_trans = station_inbound_travel_time(action)

        for box in order["boxes"]:
            while True:
                active_boxes = station_active_box_count(target_station)
                active_order_ids = set(target_station.active_orders)
                is_new_order = order_id not in active_order_ids
                order_limit_hit = is_new_order and len(active_order_ids) >= Config.MAX_ORDERS_PER_STATION
                box_limit_hit = active_boxes >= Config.MAX_BOXES_PER_STATION
                if not order_limit_hit and not box_limit_hit:
                    break
                yield env.timeout(0.5)

            sku = str(box["sku"])
            p_time = float(box["p_time"])
            box_id = f"{order_id}-P{sku}-{stats['total_boxes'] + 1}"

            stats["total_boxes"] += 1
            stats["busy_times"][action] += p_time
            env.process(target_station.process_box(box_id, order_id, p_time, t_trans, sku))
            yield env.timeout(Config.DISPATCH_INTERVAL)

    while any(station.active_order_count > 0 for station in stations):
        yield env.timeout(1.0)


def run_simpy_verification(orders, actions):
    sim_env = simpy.Environment()
    stations = [
        SimpyStation(sim_env, i, getattr(Config, "MAX_ORDERS_PER_STATION", 2))
        for i in range(Config.NUM_STATIONS)
    ]
    stats = make_stats()
    sim_env.process(monitor_process(sim_env, stations, stats))
    process = sim_env.process(dispatch_physical_orders(sim_env, stations, orders, actions, stats))

    start = time.time()
    sim_env.run(until=process)
    elapsed = time.time() - start

    for station in stations:
        stats["processed_boxes"][station.station_id] = station.processed_boxes

    return sim_env.now, elapsed, stats


def stats_to_records(stats, makespan, station_limit):
    records = []
    for station_id in range(Config.NUM_STATIONS):
        busy = float(stats["busy_times"][station_id])
        records.append(
            {
                "station_id": station_id + 1,
                "enabled": station_id < station_limit,
                "peak_active_orders": int(stats["peak_active_orders"][station_id]),
                "peak_active_boxes": int(stats["peak_active_boxes"][station_id]),
                "processed_boxes": int(stats["processed_boxes"][station_id]),
                "busy_seconds": round(busy, 3),
                "utilization_pct": round((busy / makespan * 100.0), 3) if makespan > 0 else 0.0,
            }
        )
    return records


def save_results(payload, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def main():
    args = parse_args()
    print("=" * 80)
    print("SimPy physical verification for current order-picking RL logic")
    print("=" * 80)

    base_env = PickingEnv(dataset_type="test", episode_mode="sequential", enable_inventory=False)
    model, model_path = load_model(args.model, base_env)
    print(f"Loaded model: {model_path}")

    orders_by_date = defaultdict(list)
    for order in base_env.unwrapped.base_orders:
        orders_by_date[order_date(order)].append(order)

    selected_dates = select_dates(orders_by_date, args)
    if not selected_dates:
        raise RuntimeError("No orders found for requested date range in the 33% test split.")

    results = []
    for idx, day in enumerate(selected_dates, start=1):
        orders = list(orders_by_date[day])
        if args.max_orders:
            orders = orders[: args.max_orders]
        print(f"[{idx}/{len(selected_dates)}] {day}: {len(orders)} order(s)")

        station_limit, rl_result, station_scan = choose_station_limit(orders, model, args)
        print(f"  selected station_limit={station_limit}, rl_makespan={rl_result['makespan']:.1f}s")

        simpy_makespan, runtime_seconds, stats = run_simpy_verification(
            rl_result["orders"], rl_result["actions"]
        )
        station_records = stats_to_records(stats, simpy_makespan, station_limit)
        order_limit_ok = all(
            row["peak_active_orders"] <= Config.MAX_ORDERS_PER_STATION for row in station_records
        )
        box_limit_ok = all(row["peak_active_boxes"] <= Config.MAX_BOXES_PER_STATION for row in station_records)
        processed_boxes = int(sum(row["processed_boxes"] for row in station_records))

        result = {
            "date": day,
            "orders": len(orders),
            "boxes": processed_boxes,
            "station_limit": station_limit,
            "deadline_seconds": Config.DEADLINE_SECONDS,
            "rl_makespan_seconds": round(float(rl_result["makespan"]), 3),
            "simpy_makespan_seconds": round(float(simpy_makespan), 3),
            "runtime_seconds": round(float(runtime_seconds), 3),
            "deadline_met_by_rl": rl_result["makespan"] <= Config.DEADLINE_SECONDS,
            "deadline_met_by_simpy": simpy_makespan <= Config.DEADLINE_SECONDS,
            "order_limit_ok": order_limit_ok,
            "box_limit_ok": box_limit_ok,
            "station_scan": station_scan,
            "stations": station_records,
        }
        results.append(result)

        print(
            f"  simpy_makespan={simpy_makespan:.1f}s, boxes={processed_boxes}, "
            f"order_limit_ok={order_limit_ok}, box_limit_ok={box_limit_ok}"
        )

    payload = {
        "generated_on": date.today().isoformat(),
        "dataset_type": "test",
        "split_rule": "rl_environment.py uses 67% train and 33% test split.",
        "model_path": model_path,
        "results": results,
    }
    save_results(payload, args.output)

    print("=" * 80)
    print(f"Result JSON: {args.output}")
    print("=" * 80)


if __name__ == "__main__":
    main()
