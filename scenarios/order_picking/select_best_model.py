import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from sb3_contrib import MaskablePPO

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scenarios.order_picking.app_config import get_config_value, project_path
from scenarios.order_picking.config import Config
from scenarios.order_picking.data_paths import configured_model_path
from scenarios.order_picking.rl_environment import PickingEnv


DEFAULT_OUTPUT_DIR = project_path("output/model_selection")
DEFAULT_EVAL_ORDERS_PATH = DEFAULT_OUTPUT_DIR / "fixed_eval_orders.json"
STEP_PATTERN = re.compile(r"_(\d+)_steps\.zip$")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Select the best PPO checkpoint by evaluating fixed test orders with AI only. "
            "The score is the sum of makespan values from max stations down to min stations."
        )
    )
    parser.add_argument("--eval-order-count", type=int, default=2000, help="Fixed sampled test order count.")
    parser.add_argument("--seed", type=int, default=20260630, help="Seed used when fixed eval orders are first created.")
    parser.add_argument("--checkpoint-stride", type=int, default=5, help="Evaluate every Nth checkpoint after sorting by step.")
    parser.add_argument("--min-stations", type=int, default=2, help="Minimum station count.")
    parser.add_argument("--max-stations", type=int, default=Config.NUM_STATIONS, help="Maximum station count.")
    parser.add_argument(
        "--checkpoint-dir",
        default=str(project_path(get_config_value("model", "checkpoint_dir", "scenarios/order_picking/checkpoints_v6"))),
        help="Directory containing checkpoint .zip files.",
    )
    parser.add_argument(
        "--target-model",
        default=str(configured_model_path()),
        help="Final model path to overwrite with the best checkpoint.",
    )
    parser.add_argument(
        "--eval-orders-file",
        default=str(DEFAULT_EVAL_ORDERS_PATH),
        help="JSON file storing fixed eval order IDs.",
    )
    parser.add_argument(
        "--refresh-eval-orders",
        action="store_true",
        help="Resample and overwrite fixed eval order IDs.",
    )
    return parser.parse_args()


def checkpoint_step(path: Path) -> int:
    match = STEP_PATTERN.search(path.name)
    return int(match.group(1)) if match else -1


def select_checkpoints(checkpoint_dir: Path, stride: int):
    checkpoints = sorted(checkpoint_dir.glob("*.zip"), key=lambda path: (checkpoint_step(path), path.name))
    if not checkpoints:
        raise FileNotFoundError(f"No checkpoint .zip files found under {checkpoint_dir}")

    stride = max(1, int(stride))
    selected = checkpoints[::stride]
    if checkpoints[-1] not in selected:
        selected.append(checkpoints[-1])
    return selected, checkpoints


def load_test_orders():
    env = PickingEnv(dataset_type="test")
    return list(getattr(env.unwrapped, "real_world_orders", []))


def order_key(order, index):
    return str(order.get("order_id") or f"__idx_{index}")


def load_or_create_fixed_orders(test_orders, args):
    output_path = Path(args.eval_orders_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    order_by_id = {order_key(order, idx): order for idx, order in enumerate(test_orders)}

    if output_path.exists() and not args.refresh_eval_orders:
        with output_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        order_ids = payload.get("order_ids", [])
        missing_ids = [order_id for order_id in order_ids if order_id not in order_by_id]
        if missing_ids:
            raise RuntimeError(
                f"Fixed eval order file contains {len(missing_ids)} missing order IDs. "
                f"Use --refresh-eval-orders if the source data changed."
            )
        return [order_by_id[order_id] for order_id in order_ids], payload

    if len(test_orders) < args.eval_order_count:
        raise RuntimeError(f"Test split has only {len(test_orders)} orders, less than {args.eval_order_count}.")

    rng = np.random.default_rng(args.seed)
    sampled_indices = sorted(rng.choice(len(test_orders), size=args.eval_order_count, replace=False).tolist())
    order_ids = [order_key(test_orders[idx], idx) for idx in sampled_indices]
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "DMS picking test split, last 33 percent orders",
        "seed": args.seed,
        "eval_order_count": args.eval_order_count,
        "order_ids": order_ids,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return [test_orders[idx] for idx in sampled_indices], payload


def set_eval_orders(env, orders):
    env.unwrapped.set_orders(list(orders), episode_length=len(orders))


def run_ai_makespan(model, env, orders, station_limit, seed):
    set_eval_orders(env, orders)
    obs, _ = env.reset(seed=seed)
    done = False
    enabled_mask = np.array(
        [True] * station_limit + [False] * (Config.NUM_STATIONS - station_limit),
        dtype=bool,
    )

    while not done:
        try:
            env_mask = env.unwrapped.action_masks()
        except AttributeError:
            env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
        action_mask = np.logical_and(enabled_mask, env_mask)
        if not np.any(action_mask):
            action_mask = enabled_mask

        action, _ = model.predict(obs, action_masks=action_mask, deterministic=True)
        obs, _, done, _, _ = env.step(int(action))

    return float(env.unwrapped.global_time)


def evaluate_checkpoint(checkpoint_path, eval_env, orders, station_limits, seed):
    model = MaskablePPO.load(str(checkpoint_path), env=eval_env)
    station_results = []
    for station_limit in station_limits:
        makespan = run_ai_makespan(model, eval_env, orders, station_limit, seed + station_limit)
        station_results.append(
            {
                "station_limit": int(station_limit),
                "ai_makespan": round(float(makespan), 3),
            }
        )
    score = sum(item["ai_makespan"] for item in station_results)
    return {
        "checkpoint": str(checkpoint_path),
        "checkpoint_name": checkpoint_path.name,
        "checkpoint_step": checkpoint_step(checkpoint_path),
        "station_results": station_results,
        "score_total_makespan": round(float(score), 3),
        "score_avg_makespan": round(float(score / len(station_results)), 3),
    }


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def select_best_model(args=None):
    if args is None:
        args = parse_args()

    checkpoint_dir = Path(args.checkpoint_dir)
    target_model = Path(args.target_model)
    output_dir = DEFAULT_OUTPUT_DIR
    station_limits = list(range(min(args.max_stations, Config.NUM_STATIONS), max(1, args.min_stations) - 1, -1))

    print("=" * 80)
    print("PPO checkpoint selection")
    print("=" * 80)
    print(f"Checkpoint dir : {checkpoint_dir}")
    print(f"Target model   : {target_model}")
    print(f"Eval orders    : {args.eval_order_count}")
    print(f"Station limits : {station_limits[0]} -> {station_limits[-1]}")
    print(f"Stride         : {args.checkpoint_stride}")

    selected_checkpoints, all_checkpoints = select_checkpoints(checkpoint_dir, args.checkpoint_stride)
    print(f"Checkpoints    : {len(selected_checkpoints)} selected / {len(all_checkpoints)} total")

    test_orders = load_test_orders()
    eval_orders, eval_payload = load_or_create_fixed_orders(test_orders, args)
    print(f"Fixed orders   : {len(eval_orders)} ({args.eval_orders_file})")
    eval_env = PickingEnv(dataset_type="test", initial_orders=eval_orders)

    results = []
    for idx, checkpoint in enumerate(selected_checkpoints, start=1):
        print(f"[{idx}/{len(selected_checkpoints)}] Evaluating {checkpoint.name}")
        result = evaluate_checkpoint(checkpoint, eval_env, eval_orders, station_limits, args.seed)
        results.append(result)
        print(
            f"  score={result['score_total_makespan']:.3f}, "
            f"avg={result['score_avg_makespan']:.3f}"
        )

    best = min(results, key=lambda item: item["score_total_makespan"])
    target_model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best["checkpoint"], target_model)

    detail_report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metric": "minimum sum of AI makespan from max stations down to min stations",
        "station_limits": station_limits,
        "checkpoint_stride": args.checkpoint_stride,
        "evaluated_checkpoint_count": len(results),
        "total_checkpoint_count": len(all_checkpoints),
        "eval_orders_file": str(Path(args.eval_orders_file)),
        "eval_order_count": len(eval_orders),
        "eval_orders_seed": eval_payload.get("seed"),
        "target_model": str(target_model),
        "results": results,
    }
    best_report = {
        "generated_at": detail_report["generated_at"],
        "best_checkpoint": best["checkpoint"],
        "best_checkpoint_name": best["checkpoint_name"],
        "best_checkpoint_step": best["checkpoint_step"],
        "target_model": str(target_model),
        "score_total_makespan": best["score_total_makespan"],
        "score_avg_makespan": best["score_avg_makespan"],
        "station_results": best["station_results"],
        "eval_order_count": len(eval_orders),
        "eval_orders_file": str(Path(args.eval_orders_file)),
    }

    detail_path = output_dir / "checkpoint_eval_results.json"
    best_path = output_dir / "best_model_report.json"
    save_json(detail_path, detail_report)
    save_json(best_path, best_report)

    print("-" * 80)
    print(f"Best checkpoint: {best['checkpoint_name']}")
    print(f"Best score     : {best['score_total_makespan']:.3f}")
    print(f"Model replaced : {target_model}")
    print(f"Detail report  : {detail_path}")
    print(f"Best report    : {best_path}")
    print("=" * 80)
    return best_report


def main():
    select_best_model(parse_args())


if __name__ == "__main__":
    main()
