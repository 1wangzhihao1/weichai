import argparse
import glob
import json
import os
import sys
from copy import deepcopy
from datetime import date

import numpy as np
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from database import PartMaster, SessionLocal
from scenarios.order_picking.config import Config
from scenarios.order_picking.inventory_preprocess import load_snapshot
from scenarios.order_picking.order_preprocessor import preprocess_orders
from scenarios.order_picking.rl_environment import PickingEnv


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare order preprocessing with dynamic inventory resource simulation on July 1 data."
    )
    parser.add_argument("--picking-file", default=None, help="July 1 picking Excel file.")
    parser.add_argument("--snapshot-id", default="2025-07-01-morning")
    parser.add_argument("--strategy", choices=["ai", "round_robin", "random"], default="ai")
    parser.add_argument("--station-limit", type=int, default=Config.NUM_STATIONS)
    parser.add_argument("--seed", type=int, default=888)
    parser.add_argument("--max-orders", type=int, default=0, help="0 means use all July 1 orders.")
    parser.add_argument(
        "--order-mode",
        choices=["default", "random"],
        default="default",
        help="Baseline dispatch order before preprocessing.",
    )
    parser.add_argument(
        "--shortage-mode",
        choices=["keep", "exclude"],
        default="keep",
        help="keep keeps shortage orders in the comparison; exclude removes them before dispatch.",
    )
    parser.add_argument(
        "--unit-release",
        choices=["after_pick", "after_order"],
        default="after_pick",
        help="When the occupied base loading unit is released.",
    )
    parser.add_argument(
        "--unit-select-policy",
        choices=["best_fit", "max_remaining", "first_ready"],
        default="best_fit",
        help="How to choose an inventory unit when multiple units can satisfy one SKU pick.",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "order_preprocessing_comparison.json"),
    )
    return parser.parse_args()


def find_default_picking_file():
    base_dir = os.path.join(project_root, "raw_data", "7.1")
    candidates = []
    for pattern in ("*.XLSX", "*.xlsx"):
        candidates.extend(glob.glob(os.path.join(base_dir, pattern)))
    for path in candidates:
        name = os.path.basename(path)
        if "拣选" in name:
            return path
    for path in candidates:
        name = os.path.basename(path)
        if "库存" not in name:
            return path
    raise FileNotFoundError(f"No July 1 picking Excel file found under {base_dir}")


def load_part_time_dict():
    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        return {str(p.part_type).strip(): float(p.standard_p_time) for p in db.query(PartMaster).all()}
    except Exception:
        return {}
    finally:
        db.close()


def normalize_sku(value):
    return str(value or "").strip()


def load_pick_orders_from_excel(path):
    path = os.path.abspath(path or find_default_picking_file())
    if not os.path.exists(path):
        raise FileNotFoundError(f"Picking file not found: {path}")

    part_time_dict = load_part_time_dict()
    df = pd.read_excel(path, sheet_name=0)
    order_aggregation = {}

    for _, row in df.iterrows():
        try:
            row_vals = row.values
            if len(row_vals) < 12:
                continue
            time_start = pd.to_datetime(row_vals[2])
            order_id = str(row_vals[6]).strip()
            status = str(row_vals[8]).strip()
            sku = normalize_sku(row_vals[9])
            qty = float(row_vals[11])
        except Exception:
            continue

        if qty <= 0:
            continue
        if status and status.lower() != "nan" and status not in {"确定", "完成", "纭畾", "瀹屾垚"}:
            continue

        if order_id not in order_aggregation:
            order_aggregation[order_id] = {
                "order_id": order_id,
                "start_time": time_start,
                "sku_map": {},
                "total_p_time": 0.0,
            }

        sku_slot = order_aggregation[order_id]["sku_map"].setdefault(sku, {"qty": 0.0, "p_time": 0.0})
        p_time = part_time_dict.get(sku, 4.5) * qty
        sku_slot["qty"] += qty
        sku_slot["p_time"] += p_time
        order_aggregation[order_id]["total_p_time"] += p_time

    aggregated_orders = []
    for data in order_aggregation.values():
        data["boxes"] = [
            {"sku": sku, "qty": box["qty"], "p_time": box["p_time"]}
            for sku, box in data["sku_map"].items()
        ]
        del data["sku_map"]
        aggregated_orders.append(data)

    aggregated_orders.sort(key=lambda x: x["start_time"])
    return aggregated_orders, path


def load_latest_model(env):
    from sb3_contrib import MaskablePPO

    model_dir = os.path.join(project_root, "output", "models")
    zip_files = glob.glob(os.path.join(model_dir, "*.zip"))
    if not zip_files:
        return None, None
    model_path = max(zip_files, key=os.path.getctime)
    return MaskablePPO.load(model_path, env=env), model_path


def set_orders(env, orders):
    env.unwrapped.set_orders(deepcopy(orders), episode_length=len(orders))


def build_station_mapping(orders, strategy, station_limit, seed, model=None):
    station_limit = max(1, min(int(station_limit), Config.NUM_STATIONS))
    env = PickingEnv(dataset_type="all", initial_orders=orders)
    set_orders(env, orders)
    rng = np.random.default_rng(seed)
    obs, _ = env.reset(seed=seed)
    done = False
    step = 0
    mapping = []

    while not done:
        current_order = env.unwrapped.real_world_orders[env.unwrapped.current_step]
        station_mask = np.array([True] * station_limit + [False] * (Config.NUM_STATIONS - station_limit))
        try:
            env_mask = env.unwrapped.action_masks()
        except AttributeError:
            env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
        combined_mask = np.logical_and(station_mask, env_mask)
        if not np.any(combined_mask):
            combined_mask = station_mask

        if strategy == "ai":
            if model is None:
                raise RuntimeError("AI strategy requested, but no model was found under output/models.")
            action = int(model.predict(obs, action_masks=combined_mask, deterministic=True)[0])
        elif strategy == "round_robin":
            valid_actions = np.flatnonzero(combined_mask)
            action = int(valid_actions[step % len(valid_actions)])
        elif strategy == "random":
            valid_actions = np.flatnonzero(combined_mask)
            action = int(rng.choice(valid_actions))
        else:
            raise ValueError(f"Unsupported strategy: {strategy}")

        mapping.append(
            {
                "sequence": step + 1,
                "order_id": current_order.get("order_id", ""),
                "target_station": action + 1,
                "box_count": len(current_order.get("boxes", [])),
                "total_p_time": round(float(current_order.get("total_p_time", 0.0)), 3),
            }
        )
        obs, _, done, _, _ = env.step(action)
        step += 1

    return mapping


def build_inventory_state(snapshot):
    state = {}
    for raw_sku, units in snapshot.get("sku_units", {}).items():
        sku = normalize_sku(raw_sku)
        state[sku] = []
        for unit in units or []:
            qty = float(unit.get("remaining_qty", unit.get("qty", 0.0)) or 0.0)
            if qty <= 0:
                continue
            state[sku].append(
                {
                    "unit_id": str(unit.get("unit_id", unit.get("load_unit_id", ""))).strip(),
                    "remaining_qty": qty,
                    "available_at": float(unit.get("available_at", 0.0) or 0.0),
                }
            )
        state[sku].sort(key=lambda item: (item["available_at"], item["unit_id"]))
    return state


def choose_inventory_unit(candidates, qty, request_time, policy):
    if policy == "max_remaining":
        return max(candidates, key=lambda unit: (unit["remaining_qty"], -unit["available_at"], unit["unit_id"]))
    if policy == "first_ready":
        return min(candidates, key=lambda unit: (unit["available_at"], unit["unit_id"]))
    return min(
        candidates,
        key=lambda unit: (
            max(unit["available_at"] - request_time, 0.0),
            unit["remaining_qty"] - qty,
            unit["available_at"],
            unit["unit_id"],
        ),
    )


def reserve_inventory_unit(inventory_state, sku, qty, request_time, unit_select_policy):
    units = inventory_state.get(sku, [])
    enough_units = [unit for unit in units if unit["remaining_qty"] >= qty]
    if not enough_units:
        existing_qty = sum(unit["remaining_qty"] for unit in units)
        return None, request_time, 0.0, "insufficient_qty" if units else "missing_sku", existing_qty

    ready_units = [unit for unit in enough_units if unit["available_at"] <= request_time]
    if ready_units:
        selected = choose_inventory_unit(ready_units, qty, request_time, unit_select_policy)
        return selected, request_time, 0.0, None, selected["remaining_qty"]

    selected = choose_inventory_unit(enough_units, qty, request_time, unit_select_policy)
    wait = selected["available_at"] - request_time
    return selected, selected["available_at"], wait, None, selected["remaining_qty"]


def simulate_dynamic_inventory(orders, mapping, inventory_snapshot, shortage_mode, unit_release, unit_select_policy):
    inventory_state = build_inventory_state(inventory_snapshot)
    station_available_time = np.zeros(Config.NUM_STATIONS, dtype=np.float64)
    station_active_boxes = [[] for _ in range(Config.NUM_STATIONS)]
    dispatch_cursor = 0.0

    order_by_id = {order["order_id"]: order for order in orders}
    total_inventory_wait = 0.0
    inventory_wait_events = 0
    shortage_events = []
    unit_empty_count = 0
    timeline_sample = []

    for item in mapping:
        order = order_by_id[item["order_id"]]
        action = int(item["target_station"]) - 1
        order_start = None
        order_finish = 0.0
        occupied_units = []

        for box in order.get("boxes", []):
            sku = normalize_sku(box.get("sku"))
            qty = float(box.get("qty", 1.0) or 1.0)
            p_time = float(box.get("p_time", 0.0) or 0.0)

            local_cursor = dispatch_cursor
            while True:
                station_active_boxes[action] = [
                    b for b in station_active_boxes[action] if b["finish_time"] > local_cursor
                ]
                active_boxes = len(station_active_boxes[action])
                active_order_ids = {b["order_id"] for b in station_active_boxes[action]}
                is_new_order = order["order_id"] not in active_order_ids
                order_limit_hit = is_new_order and len(active_order_ids) >= Config.MAX_ORDERS_PER_STATION
                box_limit_hit = active_boxes >= Config.MAX_BOXES_PER_STATION
                if not order_limit_hit and not box_limit_hit:
                    break
                local_cursor = min(b["finish_time"] for b in station_active_boxes[action]) if station_active_boxes[action] else local_cursor + 1.0

            launch_time = local_cursor + Config.DISPATCH_INTERVAL
            unit, inventory_ready_time, wait_time, shortage_reason, before_qty = reserve_inventory_unit(
                inventory_state, sku, qty, launch_time, unit_select_policy
            )
            total_inventory_wait += wait_time
            if wait_time > 0:
                inventory_wait_events += 1

            if shortage_reason:
                shortage_events.append(
                    {
                        "order_id": order["order_id"],
                        "sku": sku,
                        "qty": qty,
                        "reason": shortage_reason,
                        "available_qty": round(float(before_qty), 3),
                        "request_time": round(float(launch_time), 3),
                    }
                )
                if shortage_mode == "exclude":
                    continue
                inventory_ready_time = launch_time
                unit_id = None
                remaining_after = None
            else:
                unit_id = unit["unit_id"]
                unit["remaining_qty"] -= qty
                remaining_after = unit["remaining_qty"]
                if remaining_after <= 0.000001:
                    unit_empty_count += 1

            dispatch_cursor = max(launch_time, inventory_ready_time)
            t_trans_in = ((action * 5.0) / Config.BELT_SPEED) + Config.get_branch_info(action)["transit_time_s"]
            arrival_time = dispatch_cursor + t_trans_in
            start_process = max(station_available_time[action], arrival_time)
            finish_process = start_process + p_time

            station_available_time[action] = finish_process
            station_active_boxes[action].append({"finish_time": finish_process, "order_id": order["order_id"]})
            if unit is not None:
                occupied_units.append(unit)
                unit["available_at"] = finish_process

            order_start = start_process if order_start is None else min(order_start, start_process)
            order_finish = max(order_finish, finish_process)

            if len(timeline_sample) < 80:
                timeline_sample.append(
                    {
                        "order_id": order["order_id"],
                        "sku": sku,
                        "target_station": action + 1,
                        "unit_id": unit_id,
                        "qty": qty,
                        "inventory_wait_sec": round(float(wait_time), 3),
                        "start_process": round(float(start_process), 3),
                        "finish_process": round(float(finish_process), 3),
                        "remaining_qty": round(float(remaining_after), 3) if remaining_after is not None else None,
                        "shortage_reason": shortage_reason,
                    }
                )

        if unit_release == "after_order":
            for unit in occupied_units:
                unit["available_at"] = order_finish

    makespan = max(float(np.max(station_available_time)), dispatch_cursor)
    return {
        "orders": len(orders),
        "boxes": int(sum(len(order.get("boxes", [])) for order in orders)),
        "makespan_sec": round(float(makespan), 3),
        "total_inventory_wait_sec": round(float(total_inventory_wait), 3),
        "inventory_wait_events": inventory_wait_events,
        "shortage_event_count": len(shortage_events),
        "unit_empty_count": unit_empty_count,
        "mapping_sample": mapping[:50],
        "timeline_sample": timeline_sample,
        "shortage_event_sample": shortage_events[:80],
    }


def summarize_case(name, orders, result, extra=None):
    summary = {
        "case": name,
        "order_count": len(orders),
        "box_count": int(sum(len(order.get("boxes", [])) for order in orders)),
        "makespan_sec": result["makespan_sec"],
        "total_inventory_wait_sec": result["total_inventory_wait_sec"],
        "inventory_wait_events": result["inventory_wait_events"],
        "shortage_event_count": result["shortage_event_count"],
        "unit_empty_count": result["unit_empty_count"],
        "mapping_sample": result["mapping_sample"],
        "timeline_sample": result["timeline_sample"],
        "shortage_event_sample": result["shortage_event_sample"],
    }
    if extra:
        summary.update(extra)
    return summary


def main():
    args = parse_args()
    original_orders, picking_file = load_pick_orders_from_excel(args.picking_file)
    if args.max_orders and args.max_orders > 0:
        original_orders = original_orders[: args.max_orders]

    if args.order_mode == "random":
        rng = np.random.default_rng(args.seed)
        original_orders = list(original_orders)
        rng.shuffle(original_orders)

    if not original_orders:
        raise RuntimeError("No orders loaded from the July 1 picking file.")

    inventory_snapshot = load_snapshot(args.snapshot_id)
    preprocessed = preprocess_orders(
        deepcopy(original_orders),
        inventory_snapshot,
        exclude_shortage=(args.shortage_mode == "exclude"),
    )
    preprocessed_orders = preprocessed["processable_orders"]
    shortage_orders = preprocessed["shortage_orders"]
    if not preprocessed_orders:
        raise RuntimeError("Order preprocessing produced zero processable orders.")

    model_env = PickingEnv(dataset_type="all", initial_orders=original_orders)
    model, model_path = load_latest_model(model_env) if args.strategy == "ai" else (None, None)

    baseline_mapping = build_station_mapping(
        original_orders,
        args.strategy,
        args.station_limit,
        args.seed,
        model=model,
    )
    preprocessed_mapping = build_station_mapping(
        preprocessed_orders,
        args.strategy,
        args.station_limit,
        args.seed,
        model=model,
    )

    baseline_result = simulate_dynamic_inventory(
        deepcopy(original_orders),
        baseline_mapping,
        deepcopy(inventory_snapshot),
        args.shortage_mode,
        args.unit_release,
        args.unit_select_policy,
    )
    preprocessed_result = simulate_dynamic_inventory(
        deepcopy(preprocessed_orders),
        preprocessed_mapping,
        deepcopy(inventory_snapshot),
        args.shortage_mode,
        args.unit_release,
        args.unit_select_policy,
    )

    baseline_ms = baseline_result["makespan_sec"]
    preprocessed_ms = preprocessed_result["makespan_sec"]
    baseline_wait = baseline_result["total_inventory_wait_sec"]
    preprocessed_wait = preprocessed_result["total_inventory_wait_sec"]
    improvement_pct = round((baseline_ms - preprocessed_ms) / baseline_ms * 100, 3) if baseline_ms > 0 else None
    wait_improvement_pct = round((baseline_wait - preprocessed_wait) / baseline_wait * 100, 3) if baseline_wait > 0 else None

    report = {
        "generated_on": date.today().isoformat(),
        "dataset": "2025-07-01-picking-file",
        "picking_file": os.path.abspath(picking_file),
        "snapshot_id": args.snapshot_id,
        "strategy": args.strategy,
        "station_limit": max(1, min(int(args.station_limit), Config.NUM_STATIONS)),
        "order_mode": args.order_mode,
        "shortage_mode": args.shortage_mode,
        "unit_release": args.unit_release,
        "unit_select_policy": args.unit_select_policy,
        "seed": args.seed,
        "model_path": model_path,
        "preprocess_stats": preprocessed["preprocess_stats"],
        "shortage_order_count": len(shortage_orders),
        "shortage_order_sample": [
            {"order_id": order.get("order_id", ""), "shortage_skus": order.get("shortage_skus", [])}
            for order in shortage_orders[:80]
        ],
        "cases": [
            summarize_case("without_order_preprocessing", original_orders, baseline_result),
            summarize_case(
                "with_order_preprocessing",
                preprocessed_orders,
                preprocessed_result,
                {"removed_shortage_orders": len(shortage_orders) if args.shortage_mode == "exclude" else 0},
            ),
        ],
        "comparison": {
            "baseline_makespan_sec": baseline_ms,
            "preprocessed_makespan_sec": preprocessed_ms,
            "makespan_delta_sec": round(preprocessed_ms - baseline_ms, 3),
            "preprocessing_improvement_pct": improvement_pct,
            "baseline_inventory_wait_sec": baseline_wait,
            "preprocessed_inventory_wait_sec": preprocessed_wait,
            "inventory_wait_delta_sec": round(preprocessed_wait - baseline_wait, 3),
            "inventory_wait_improvement_pct": wait_improvement_pct,
        },
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)

    print("=" * 80)
    print("Order preprocessing comparison with dynamic inventory simulation")
    print("=" * 80)
    print("Dataset       : 2025-07-01 picking file")
    print(f"Picking file  : {os.path.abspath(picking_file)}")
    print(f"Snapshot      : {args.snapshot_id}")
    print(f"Strategy      : {args.strategy}")
    print(f"Stations      : {report['station_limit']}")
    print(f"Shortage mode : {args.shortage_mode}")
    print(f"Unit release  : {args.unit_release}")
    print(f"Unit select   : {args.unit_select_policy}")
    print(f"Baseline      : {baseline_ms:.3f}s / wait {baseline_wait:.3f}s / {len(original_orders)} orders")
    print(f"Preprocessed  : {preprocessed_ms:.3f}s / wait {preprocessed_wait:.3f}s / {len(preprocessed_orders)} orders")
    print(f"Shortage      : {len(shortage_orders)} orders")
    print(f"Makespan delta: {report['comparison']['makespan_delta_sec']:.3f}s")
    print(f"Wait delta    : {report['comparison']['inventory_wait_delta_sec']:.3f}s")
    print(f"Output        : {args.output}")
    print("=" * 80)


if __name__ == "__main__":
    main()
