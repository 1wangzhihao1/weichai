import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import date

import matplotlib.pyplot as plt
import numpy as np

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO

from scenarios.order_picking.config import Config
from scenarios.order_picking.data_paths import OUTPUT_DIR, MODEL_DIR, resolve_model_path
from scenarios.order_picking.rl_environment import PickingEnv

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare AI, random and round-robin order picking strategies on the test split."
    )
    parser.add_argument("--date", help="Only run one day, for example 2026-04-11.")
    parser.add_argument("--date-from", dest="date_from", help="Inclusive start date, for example 2026-04-01.")
    parser.add_argument("--date-to", dest="date_to", help="Inclusive end date, for example 2026-04-29.")
    parser.add_argument("--min-stations", type=int, default=1, help="Minimum enabled stations.")
    parser.add_argument("--max-stations", type=int, default=Config.NUM_STATIONS, help="Maximum enabled stations.")
    parser.add_argument(
        "--optimize-deadline",
        action="store_true",
        help="For each day, choose the minimum AI station count that satisfies Config.DEADLINE_SECONDS.",
    )
    parser.add_argument("--seed", type=int, default=888, help="Simulation seed.")
    return parser.parse_args()


def order_date(order):
    start_time = order.get("start_time")
    if hasattr(start_time, "date"):
        return start_time.date().isoformat()
    return str(start_time)[:10]


def filter_dates(orders_by_date, args):
    dates = sorted(orders_by_date)
    if args.date:
        return [args.date] if args.date in orders_by_date else []

    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    return dates


def set_daily_orders(env, daily_orders):
    env.unwrapped.episode_mode = "sequential"
    env.unwrapped.max_episode_orders = None
    if hasattr(env.unwrapped, "set_orders"):
        env.unwrapped.set_orders(daily_orders, episode_length=len(daily_orders))
    else:
        env.unwrapped.base_orders = list(daily_orders)
        env.unwrapped.real_world_orders = list(daily_orders)
        env.unwrapped.total_orders = len(daily_orders)
        env.unwrapped.episode_length = len(daily_orders)


def load_latest_model(env):
    model_path = resolve_model_path()
    if not model_path or not model_path.exists():
        print(f"WARN: No configured or fallback .zip model found under {MODEL_DIR}; AI strategy will be skipped.")
        return None, None

    try:
        model = MaskablePPO.load(str(model_path), env=env)
        print(f"Loaded model: {model_path.name}")
        return model, str(model_path)
    except Exception as exc:
        print(f"WARN: Model load failed: {exc}; AI strategy will be skipped.")
        return None, str(model_path)


def run_simulation(env, strategy, max_stations, model=None, seed=888):
    rng = np.random.default_rng(seed)
    obs, _ = env.reset(seed=seed)
    if env.unwrapped.total_orders == 0:
        raise RuntimeError("No orders available after reset. Please check the selected dataset/date range.")
    done = False
    step_count = 0

    while not done:
        if strategy == "round_robin":
            action = step_count % max_stations
        elif strategy == "random":
            action = int(rng.integers(0, max_stations))
        elif strategy == "ai":
            if model is None:
                raise ValueError("AI strategy requested but model is not loaded.")

            enabled_mask = np.array(
                [True] * max_stations + [False] * (Config.NUM_STATIONS - max_stations),
                dtype=bool,
            )
            try:
                env_mask = env.unwrapped.action_masks()
            except AttributeError:
                env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

            combined_mask = np.logical_and(enabled_mask, env_mask)
            if not np.any(combined_mask):
                combined_mask = enabled_mask

            action, _ = model.predict(obs, action_masks=combined_mask, deterministic=True)
            action = int(action)
        else:
            raise ValueError(f"Unsupported strategy: {strategy}")

        obs, _, done, _, _ = env.step(action)
        step_count += 1

    return float(env.unwrapped.global_time)


def summarize_records(records, selected_dates, orders_by_date, model_path):
    by_limit = defaultdict(list)
    daily_best = defaultdict(dict)
    for record in records:
        by_limit[record["station_limit"]].append(record)
        daily_best[record["date"]][record["station_limit"]] = record

    strategies = ["round_robin", "random"]
    if any(record.get("ai_makespan") is not None for record in records):
        strategies.append("ai")

    station_summary = []
    for station_limit in sorted(by_limit):
        row = {"station_limit": station_limit}
        rows = by_limit[station_limit]
        for strategy in strategies:
            key = f"{strategy}_makespan"
            values = [r[key] for r in rows if r.get(key) is not None]
            row[f"{strategy}_avg_seconds"] = round(float(np.mean(values)), 3) if values else None
            row[f"{strategy}_max_seconds"] = round(float(np.max(values)), 3) if values else None
            row[f"{strategy}_deadline_pass_days"] = sum(v <= Config.DEADLINE_SECONDS for v in values)
        station_summary.append(row)

    total_orders = sum(len(orders_by_date[d]) for d in selected_dates)
    summary = {
        "generated_on": date.today().isoformat(),
        "dataset_type": "test",
        "split_rule": "The rl_environment.py dataset split remains 67% train and 33% test.",
        "date_from": selected_dates[0] if selected_dates else None,
        "date_to": selected_dates[-1] if selected_dates else None,
        "dates_tested": len(selected_dates),
        "total_orders": total_orders,
        "deadline_seconds": Config.DEADLINE_SECONDS,
        "station_summary": station_summary,
        "avg_selected_stations": round(float(np.mean([r["station_limit"] for r in records])), 3) if records else None,
        "deadline_met_days": sum(
            1 for r in records if r.get("ai_makespan") is not None and r["ai_makespan"] <= Config.DEADLINE_SECONDS
        ),
        "model_path": model_path,
    }

    if "ai" in strategies:
        for station_row in station_summary:
            ai_avg = station_row.get("ai_avg_seconds")
            rr_avg = station_row.get("round_robin_avg_seconds")
            rand_avg = station_row.get("random_avg_seconds")
            station_row["ai_vs_round_robin_avg_improvement_pct"] = (
                round((rr_avg - ai_avg) / rr_avg * 100, 3) if ai_avg and rr_avg else None
            )
            station_row["ai_vs_random_avg_improvement_pct"] = (
                round((rand_avg - ai_avg) / rand_avg * 100, 3) if ai_avg and rand_avg else None
            )

    return summary


def save_results(records, summary):
    output_dir = str(OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    detail_path = os.path.join(output_dir, "comparison_daily_results.json")
    summary_path = os.path.join(output_dir, "comparison_daily_summary.json")

    with open(detail_path, "w", encoding="utf-8") as fp:
        json.dump(records, fp, ensure_ascii=False, indent=2)
    with open(summary_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)

    return detail_path, summary_path


def plot_summary(summary):
    station_summary = summary["station_summary"]
    station_limits = [row["station_limit"] for row in station_summary]
    plt.figure(figsize=(10, 6))
    plt.plot(
        station_limits,
        [row["random_avg_seconds"] for row in station_summary],
        marker="x",
        linestyle=":",
        color="gray",
        label="Random avg",
        linewidth=2,
    )
    plt.plot(
        station_limits,
        [row["round_robin_avg_seconds"] for row in station_summary],
        marker="o",
        linestyle="--",
        color="blue",
        label="Round-robin avg",
        linewidth=2,
    )

    if any(row.get("ai_avg_seconds") is not None for row in station_summary):
        plt.plot(
            station_limits,
            [row["ai_avg_seconds"] for row in station_summary],
            marker="D",
            linestyle="-",
            color="red",
            label="RL-Agent avg",
            linewidth=3,
        )

    plt.axhline(
        y=Config.DEADLINE_SECONDS,
        color="darkred",
        linestyle="-.",
        linewidth=2,
        label=f"Deadline ({Config.DEADLINE_SECONDS:.0f}s)",
    )
    plt.title(
        f"测试集日期范围 {summary['date_from']} 至 {summary['date_to']} 平均完工时间对比",
        fontsize=14,
        pad=14,
    )
    plt.xlabel("允许启用的最大站台数量")
    plt.ylabel("平均 Makespan（秒）")
    plt.xticks(station_limits)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=10)

    output_img = os.path.join(str(OUTPUT_DIR), "performance_comparison.png")
    plt.savefig(output_img, dpi=300, bbox_inches="tight")
    plt.close()
    return output_img


def main():
    args = parse_args()
    min_stations = max(1, min(args.min_stations, Config.NUM_STATIONS))
    max_stations = max(min_stations, min(args.max_stations, Config.NUM_STATIONS))
    station_limits = list(range(min_stations, max_stations + 1))

    print("=" * 80)
    print("Order picking strategy comparison on the 33% test split")
    print("=" * 80)

    env = PickingEnv(dataset_type="test", episode_mode="sequential", enable_inventory=False)
    test_orders = list(getattr(env.unwrapped, "base_orders", env.unwrapped.real_world_orders))
    if not test_orders:
        raise RuntimeError("The test split is empty. Please check raw data and rl_environment.py.")

    orders_by_date = defaultdict(list)
    for order in test_orders:
        orders_by_date[order_date(order)].append(order)

    selected_dates = filter_dates(orders_by_date, args)
    if not selected_dates:
        raise RuntimeError("No orders found for the requested date range in the test split.")

    model, model_path = load_latest_model(env)
    if args.optimize_deadline and model is None:
        raise RuntimeError("--optimize-deadline requires an AI model.")
    records = []
    print(
        f"Running {len(selected_dates)} date(s), {sum(len(orders_by_date[d]) for d in selected_dates)} orders, "
        f"stations {min_stations}-{max_stations}."
    )

    for date_idx, day in enumerate(selected_dates, start=1):
        daily_orders = orders_by_date[day]
        set_daily_orders(env, daily_orders)
        print(f"[{date_idx}/{len(selected_dates)}] {day}: {len(daily_orders)} orders")

        if args.optimize_deadline:
            ai_scans = []
            selected_limit = None
            selected_ai = None

            for limit in station_limits:
                ai_ms = run_simulation(env, "ai", limit, model=model, seed=args.seed + limit)
                ai_scans.append({"station_limit": limit, "ai_makespan": round(ai_ms, 3)})
                print(f"  scan AI stations={limit:02d} makespan={ai_ms:9.1f}s")
                if ai_ms <= Config.DEADLINE_SECONDS:
                    selected_limit = limit
                    selected_ai = ai_ms
                    break

            if selected_limit is None:
                best = min(ai_scans, key=lambda item: item["ai_makespan"])
                selected_limit = best["station_limit"]
                selected_ai = best["ai_makespan"]

            rr = run_simulation(env, "round_robin", selected_limit, seed=args.seed + selected_limit)
            random_ms = run_simulation(env, "random", selected_limit, seed=args.seed + selected_limit + 10000)
            records.append(
                {
                    "date": day,
                    "orders": len(daily_orders),
                    "station_limit": selected_limit,
                    "deadline_seconds": Config.DEADLINE_SECONDS,
                    "deadline_met": selected_ai <= Config.DEADLINE_SECONDS,
                    "round_robin_makespan": round(rr, 3),
                    "random_makespan": round(random_ms, 3),
                    "ai_makespan": round(float(selected_ai), 3),
                    "ai_station_scan": ai_scans,
                }
            )
            print(
                f"  selected={selected_limit:02d} AI={selected_ai:9.1f}s "
                f"RR={rr:9.1f}s Random={random_ms:9.1f}s"
            )
            continue

        for limit in station_limits:
            rr = run_simulation(env, "round_robin", limit, seed=args.seed + limit)
            random_ms = run_simulation(env, "random", limit, seed=args.seed + limit + 10000)
            ai_ms = run_simulation(env, "ai", limit, model=model, seed=args.seed + limit) if model else None
            records.append(
                {
                    "date": day,
                    "orders": len(daily_orders),
                    "station_limit": limit,
                    "round_robin_makespan": round(rr, 3),
                    "random_makespan": round(random_ms, 3),
                    "ai_makespan": round(ai_ms, 3) if ai_ms is not None else None,
                }
            )
            if model:
                print(
                    f"  stations={limit:02d} AI={ai_ms:9.1f}s RR={rr:9.1f}s Random={random_ms:9.1f}s"
                )
            else:
                print(f"  stations={limit:02d} RR={rr:9.1f}s Random={random_ms:9.1f}s")

    summary = summarize_records(records, selected_dates, orders_by_date, model_path)
    detail_path, summary_path = save_results(records, summary)
    image_path = plot_summary(summary)

    print("=" * 80)
    print(f"Detail JSON : {detail_path}")
    print(f"Summary JSON: {summary_path}")
    print(f"Chart       : {image_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
