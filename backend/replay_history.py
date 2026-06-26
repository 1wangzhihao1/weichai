import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import simpy

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from backend.database import PartMaster, SessionLocal
from scenarios.order_picking.config import Config

EXCEL_PATH = os.path.join(project_root, "raw_data", "DMS拣选20260201-0429.XLSX")
DEFAULT_DATE = "2026-04-11"
DEFAULT_PICK_GAP_SECONDS = 3.0
DEFAULT_GLOBAL_BREAK_THRESHOLD_SECONDS = 30 * 60
ORDER_ID_COLUMN = "拣选列表"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay historical order picking allocations with the project physical constraints."
    )
    parser.add_argument("date", nargs="?", help="Optional date, for example 2026-04-11.")
    parser.add_argument("--date", dest="date_option", help="Date to replay, for example 2026-04-11.")
    parser.add_argument("--date-from", dest="date_from", help="Inclusive start date.")
    parser.add_argument("--date-to", dest="date_to", help="Inclusive end date.")
    parser.add_argument("--excel", default=EXCEL_PATH, help="Historical picking Excel file to replay.")
    parser.add_argument(
        "--pick-gap-seconds",
        type=float,
        default=DEFAULT_PICK_GAP_SECONDS,
        help="Fixed worker gap after each base loading unit is picked.",
    )
    parser.add_argument(
        "--global-break-threshold-seconds",
        type=float,
        default=DEFAULT_GLOBAL_BREAK_THRESHOLD_SECONDS,
        help="Global no-work interval longer than this threshold is excluded from observed makespan.",
    )
    parser.add_argument(
        "--process-time-source",
        choices=["actual", "part_master"],
        default="part_master",
        help="Use Excel actual duration or PartMaster average SKU time as process time.",
    )
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


def load_history_frame(excel_path=EXCEL_PATH):
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Historical Excel file not found: {excel_path}")

    print(f"Reading historical Excel file: {excel_path}")
    df = pd.read_excel(excel_path, sheet_name=0)
    df.columns = df.columns.astype(str).str.strip().str.replace("\n", "").str.replace("\r", "")
    df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
    if "结束时间" in df.columns:
        df["结束时间"] = pd.to_datetime(df["结束时间"], errors="coerce")
    df["测试日期"] = df["开始时间"].dt.strftime("%Y-%m-%d")
    return df


def load_historical_orders(df, target_date):
    df_target = df[df["测试日期"] == target_date].copy()
    if df_target.empty:
        return None

    if "状态" in df_target.columns:
        df_target = df_target[df_target["状态"].astype(str).str.strip().isin(["完成", "确定"])]

    required_columns = ["已拣选数量", "SKU", ORDER_ID_COLUMN, "拣选员 ID", "开始时间", "结束时间"]
    df_target = df_target.dropna(subset=required_columns)
    if df_target.empty:
        return None

    df_target["已拣选数量"] = pd.to_numeric(df_target["已拣选数量"], errors="coerce")
    df_target = df_target[df_target["已拣选数量"] > 0]
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


def calculate_observed_metrics(df_target, global_break_threshold_seconds=DEFAULT_GLOBAL_BREAK_THRESHOLD_SECONDS):
    valid = df_target.dropna(subset=["开始时间", "结束时间"]).copy()
    if valid.empty:
        return {}

    start_min = valid["开始时间"].min()
    end_max = valid["结束时间"].max()
    actual_span_sec = (end_max - start_min).total_seconds()

    intervals = sorted(
        (start.to_pydatetime(), end.to_pydatetime())
        for start, end in zip(valid["开始时间"], valid["结束时间"])
        if end >= start
    )
    merged_intervals = []
    for start, end in intervals:
        if not merged_intervals or start > merged_intervals[-1][1]:
            merged_intervals.append([start, end])
        elif end > merged_intervals[-1][1]:
            merged_intervals[-1][1] = end

    global_breaks = []
    for (_, prev_end), (next_start, _) in zip(merged_intervals, merged_intervals[1:]):
        gap = (next_start - prev_end).total_seconds()
        if gap > global_break_threshold_seconds:
            global_breaks.append(
                {
                    "from": prev_end.isoformat(),
                    "to": next_start.isoformat(),
                    "seconds": round(float(gap), 3),
                    "minutes": round(float(gap) / 60.0, 3),
                }
            )
    global_break_total_sec = sum(item["seconds"] for item in global_breaks)
    observed_net_span_sec = actual_span_sec - global_break_total_sec

    group_col = "终端 ID" if "终端 ID" in valid.columns else "拣选员 ID"
    gaps = []
    for _, group in valid.sort_values(["开始时间", "结束时间"]).groupby(group_col):
        prev_end = None
        for _, row in group.iterrows():
            if prev_end is not None:
                gap = (row["开始时间"] - prev_end).total_seconds()
                if gap >= 0:
                    gaps.append(float(gap))
            prev_end = row["结束时间"]

    gap_stats = {"group_col": group_col, "sample_count": len(gaps)}
    if gaps:
        s = pd.Series(gaps, dtype="float64")
        p95 = float(s.quantile(0.95))
        gap_stats.update(
            {
                "median_sec": round(float(s.median()), 3),
                "p75_sec": round(float(s.quantile(0.75)), 3),
                "p90_sec": round(float(s.quantile(0.90)), 3),
                "p95_sec": round(p95, 3),
                "mean_sec": round(float(s.mean()), 3),
                "trimmed_mean_le_p95_sec": round(float(s[s <= p95].mean()), 3),
            }
        )

    return {
        "actual_start_time": start_min.isoformat(),
        "actual_end_time": end_max.isoformat(),
        "actual_span_seconds": round(float(actual_span_sec), 3),
        "actual_span_hours": round(float(actual_span_sec) / 3600.0, 3),
        "global_break_threshold_seconds": round(float(global_break_threshold_seconds), 3),
        "global_break_count": len(global_breaks),
        "global_breaks": global_breaks,
        "global_break_total_seconds": round(float(global_break_total_sec), 3),
        "global_break_total_hours": round(float(global_break_total_sec) / 3600.0, 3),
        "actual_net_span_excluding_global_breaks_seconds": round(float(observed_net_span_sec), 3),
        "actual_net_span_excluding_global_breaks_hours": round(float(observed_net_span_sec) / 3600.0, 3),
        "observed_gap_stats": gap_stats,
    }


class HighFidelityStation:
    def __init__(self, env, station_id, pick_gap_seconds=0.0):
        self.env = env
        self.station_id = station_id
        self.pick_gap_seconds = max(0.0, float(pick_gap_seconds or 0.0))
        self.machine = simpy.Resource(env, capacity=1)
        self.active_boxes = []
        self.processed_boxes = 0

    def process_box(self, box_id, order_id, process_time, t_trans_in, d_out):
        yield self.env.timeout(t_trans_in)

        with self.machine.request() as req:
            yield req
            yield self.env.timeout(process_time)
            if self.pick_gap_seconds > 0:
                yield self.env.timeout(self.pick_gap_seconds)
            self.active_boxes.append({"finish_time": self.env.now, "order_id": order_id})

        self.processed_boxes += 1
        yield self.env.timeout(d_out / Config.BELT_SPEED)


def replay_historical_data(
    target_date=DEFAULT_DATE,
    history_df=None,
    part_time_dict=None,
    pick_gap_seconds=DEFAULT_PICK_GAP_SECONDS,
    process_time_source="part_master",
    global_break_threshold_seconds=DEFAULT_GLOBAL_BREAK_THRESHOLD_SECONDS,
):
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
    station_order_counts = (
        df_target.groupby("站台号")[ORDER_ID_COLUMN].nunique().astype(int).to_dict()
    )
    observed_metrics = calculate_observed_metrics(
        df_target,
        global_break_threshold_seconds=global_break_threshold_seconds,
    )
    sim_env = simpy.Environment()
    physical_stations = {
        st_id: HighFidelityStation(sim_env, st_id, pick_gap_seconds=pick_gap_seconds)
        for st_id in unique_historical_stations
    }

    def historical_dispatch_engine(env):
        dispatch_time_cursor = 0.0

        for _, row in df_target.iterrows():
            order_id = str(row[ORDER_ID_COLUMN])
            sku = str(row["SKU"]).strip()
            raw_qty = row["已拣选数量"]
            st_id = int(row["站台号"])
            if st_id not in physical_stations:
                continue

            base_p_time = part_time_dict.get(sku, 15.0)
            qty = max(1, int(raw_qty) if pd.notna(raw_qty) else 1)
            target_station = physical_stations[st_id]
            actual_process_time = (row["结束时间"] - row["开始时间"]).total_seconds()
            if process_time_source == "actual" and actual_process_time > 0:
                total_process_time = float(actual_process_time)
            else:
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
        "order_count": int(df_target[ORDER_ID_COLUMN].nunique()),
        "sku_count": int(df_target["SKU"].nunique()),
        "historical_station_count": int(len(unique_historical_stations)),
        "historical_station_ids": unique_historical_stations,
        "station_task_counts": {str(k): int(v) for k, v in sorted(station_counts.items())},
        "station_order_counts": {str(k): int(v) for k, v in sorted(station_order_counts.items())},
        "pick_gap_seconds": round(float(pick_gap_seconds), 3),
        "process_time_source": process_time_source,
        **observed_metrics,
        "historical_replay_makespan_seconds": round(float(sim_env.now), 3),
        "historical_replay_makespan_hours": round(float(sim_env.now) / 3600.0, 3),
        "deadline_seconds": Config.DEADLINE_SECONDS,
    }

    print(
        f"{target_date}: stations={result['historical_station_count']}, "
        f"orders={result['order_count']}, boxes={result['valid_rows']}, "
        f"actual={result.get('actual_span_hours', 'n/a')}h, "
        f"net_actual={result.get('actual_net_span_excluding_global_breaks_hours', 'n/a')}h, "
        f"replay={result['historical_replay_makespan_hours']}h, "
        f"gap={result['pick_gap_seconds']}s"
    )
    return result


def save_results(results, output_path, source_file):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    payload = {
        "generated_on": date.today().isoformat(),
        "source_file": source_file,
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return output_path


def main():
    args = parse_args()
    excel_path = str(Path(args.excel).resolve())
    history_df = load_history_frame(excel_path)
    available_dates = set(history_df["测试日期"].dropna().unique().tolist())
    selected_dates = get_requested_dates(args, available_dates)
    if not selected_dates:
        raise RuntimeError("No historical records found for the requested date/date range.")

    part_time_dict = get_db_part_times()
    results = []
    print(f"Replaying {len(selected_dates)} date(s): {selected_dates[0]} to {selected_dates[-1]}")
    for idx, target_date in enumerate(selected_dates, start=1):
        print(f"[{idx}/{len(selected_dates)}] {target_date}")
        result = replay_historical_data(
            target_date,
            history_df,
            part_time_dict,
            pick_gap_seconds=args.pick_gap_seconds,
            process_time_source=args.process_time_source,
            global_break_threshold_seconds=args.global_break_threshold_seconds,
        )
        if result:
            results.append(result)

    output_path = save_results(results, args.output, excel_path)
    print(f"Replay result JSON: {output_path}")


if __name__ == "__main__":
    main()
