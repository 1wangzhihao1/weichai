import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date

import pandas as pd
import simpy

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from database import PartMaster, SessionLocal
from scenarios.order_picking.config import Config

EXCEL_PATH = os.path.join(project_root, "raw_data", "DMS拣选20260201-0429.XLSX")
DEFAULT_DATE = "2026-04-11"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay historical order picking allocations with the project physical constraints."
    )
    parser.add_argument("date", nargs="?", help="Optional date, for example 2026-04-11.")
    parser.add_argument("--date", dest="date_option", help="Date to replay, for example 2026-04-11.")
    parser.add_argument("--date-from", dest="date_from", help="Inclusive start date.")
    parser.add_argument("--date-to", dest="date_to", help="Inclusive end date.")
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "history_replay_results.json"),
        help="Path for replay JSON results.",
    )
    return parser.parse_args()


def get_requested_dates(args, available_dates):
    explicit_date = args.date_option or args.date
    if explicit_date:
        return [explicit_date] if explicit_date in available_dates else []

    if args.date_from or args.date_to:
        selected = sorted(available_dates)
        if args.date_from:
            selected = [d for d in selected if d >= args.date_from]
        if args.date_to:
            selected = [d for d in selected if d <= args.date_to]
        return selected

    return [DEFAULT_DATE] if DEFAULT_DATE in available_dates else []


def get_db_part_times():
    print("Loading PartMaster standard process times...")
    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)

    try:
        all_parts = db.query(PartMaster).all()
        part_time_dict = {str(p.part_type).strip(): float(p.standard_p_time) for p in all_parts}
        print(f"Loaded {len(part_time_dict)} SKU process-time records.")
        return part_time_dict
    except Exception as exc:
        print(f"WARN: Failed to read PartMaster: {exc}")
        return {}
    finally:
        db.close()


def load_history_frame():
    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(f"Historical Excel file not found: {EXCEL_PATH}")

    print(f"Reading historical Excel file: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    df.columns = df.columns.astype(str).str.strip().str.replace("\n", "").str.replace("\r", "")
    df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
    df["测试日期"] = df["开始时间"].dt.strftime("%Y-%m-%d")
    return df


def load_historical_orders(df, target_date):
    df_target = df[df["测试日期"] == target_date].copy()
    if df_target.empty:
        return None

    required_columns = ["已拣选数量", "SKU", "拣选订单", "拣选员 ID"]
    df_target = df_target.dropna(subset=required_columns)
    if df_target.empty:
        return None

    df_target["站台号"] = df_target["拣选员 ID"].apply(parse_station_id)
    df_target = df_target[df_target["站台号"] != -1]
    if df_target.empty:
        return None

    return df_target.sort_values(by="开始时间")


def parse_station_id(value):
    if pd.isna(value):
        return -1
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else -1


class HighFidelityStation:
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.machine = simpy.Resource(env, capacity=1)
        self.active_boxes = []
        self.processed_boxes = 0

    def process_box(self, box_id, order_id, process_time, t_trans_in, d_out):
        yield self.env.timeout(t_trans_in)

        with self.machine.request() as req:
            yield req
            yield self.env.timeout(process_time)
            self.active_boxes.append({"finish_time": self.env.now, "order_id": order_id})

        self.processed_boxes += 1
        yield self.env.timeout(d_out / Config.BELT_SPEED)


def replay_historical_data(target_date=DEFAULT_DATE, history_df=None, part_time_dict=None):
    if history_df is None:
        history_df = load_history_frame()
    if part_time_dict is None:
        part_time_dict = get_db_part_times()

    df_target = load_historical_orders(history_df, target_date)
    if df_target is None:
        print(f"WARN: No valid historical picking records for {target_date}.")
        return None

    unique_historical_stations = sorted(df_target["站台号"].unique().tolist())
    station_counts = Counter(df_target["站台号"].tolist())
    sim_env = simpy.Environment()
    physical_stations = {
        st_id: HighFidelityStation(sim_env, st_id) for st_id in unique_historical_stations
    }

    def historical_dispatch_engine(env):
        dispatch_time_cursor = 0.0

        for _, row in df_target.iterrows():
            order_id = str(row["拣选订单"])
            sku = str(row["SKU"]).strip()
            raw_qty = row["已拣选数量"]
            st_id = int(row["站台号"])
            if st_id not in physical_stations:
                continue

            base_p_time = part_time_dict.get(sku, 15.0)
            qty = max(1, int(raw_qty) if pd.notna(raw_qty) else 1)
            target_station = physical_stations[st_id]
            total_process_time = qty * base_p_time
            local_cursor = dispatch_time_cursor

            order_limit = getattr(Config, "MAX_ORDERS_PER_STATION", 2)
            box_limit = getattr(Config, "MAX_BOXES_PER_STATION", 8)
            while True:
                active_boxes = [b for b in target_station.active_boxes if b["finish_time"] > local_cursor]
                active_order_ids = {b["order_id"] for b in active_boxes}
                is_new_order = order_id not in active_order_ids

                if not (len(active_boxes) >= box_limit or (is_new_order and len(active_order_ids) >= order_limit)):
                    break

                if active_boxes:
                    local_cursor = max(local_cursor, min(b["finish_time"] for b in active_boxes))
                else:
                    local_cursor += 1.0

            dispatch_time_cursor = local_cursor + Config.DISPATCH_INTERVAL

            station_idx = max(0, min(st_id - 1, Config.NUM_STATIONS - 1))
            d_main = Config.STATION_EXIT_FAR_DISTANCES[station_idx] - (
                Config.EXIT_PORT_DELTA / 2.0
            )
            t_trans_in = (d_main / Config.BELT_SPEED) + Config.get_branch_info(station_idx)[
                "transit_time_s"
            ]
            delay_before_launch = max(0.0, dispatch_time_cursor - env.now)

            def launch_box(env, station, box_id, order_id, p_time, t_in, delay):
                yield env.timeout(delay)
                out_idx = max(0, min(station.station_id - 1, Config.NUM_STATIONS - 1))
                env.process(
                    station.process_box(
                        box_id,
                        order_id,
                        p_time,
                        t_in,
                        Config.STATION_EXIT_FAR_DISTANCES[out_idx],
                    )
                )

            box_id = f"{order_id}-{sku}-TOTE"
            env.process(
                launch_box(
                    env,
                    target_station,
                    box_id,
                    order_id,
                    total_process_time,
                    t_trans_in,
                    delay_before_launch,
                )
            )

        print(f"{target_date}: dispatched {len(df_target)} historical boxes; draining stations...")
        while any(s.machine.count > 0 for s in physical_stations.values()):
            yield env.timeout(10.0)

    sim_env.process(historical_dispatch_engine(sim_env))
    sim_env.run()

    result = {
        "date": target_date,
        "valid_rows": int(len(df_target)),
        "order_count": int(df_target["拣选订单"].nunique()),
        "sku_count": int(df_target["SKU"].nunique()),
        "historical_station_count": int(len(unique_historical_stations)),
        "historical_station_ids": unique_historical_stations,
        "station_task_counts": {str(k): int(v) for k, v in sorted(station_counts.items())},
        "historical_replay_makespan_seconds": round(float(sim_env.now), 3),
        "historical_replay_makespan_hours": round(float(sim_env.now) / 3600.0, 3),
        "deadline_seconds": Config.DEADLINE_SECONDS,
    }

    print(
        f"{target_date}: stations={result['historical_station_count']}, "
        f"orders={result['order_count']}, boxes={result['valid_rows']}, "
        f"makespan={result['historical_replay_makespan_hours']}h"
    )
    return result


def save_results(results, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    payload = {
        "generated_on": date.today().isoformat(),
        "source_file": EXCEL_PATH,
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return output_path


def main():
    args = parse_args()
    history_df = load_history_frame()
    available_dates = set(history_df["测试日期"].dropna().unique().tolist())
    selected_dates = get_requested_dates(args, available_dates)
    if not selected_dates:
        raise RuntimeError("No historical records found for the requested date/date range.")

    part_time_dict = get_db_part_times()
    results = []
    print(f"Replaying {len(selected_dates)} date(s): {selected_dates[0]} to {selected_dates[-1]}")
    for idx, target_date in enumerate(selected_dates, start=1):
        print(f"[{idx}/{len(selected_dates)}] {target_date}")
        result = replay_historical_data(target_date, history_df, part_time_dict)
        if result:
            results.append(result)

    output_path = save_results(results, args.output)
    print(f"Replay result JSON: {output_path}")


if __name__ == "__main__":
    main()
