import argparse
import calendar
import json
import os
import sys
from datetime import date
from statistics import mean, median

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.historical_orders import (
    available_history_dates,
    build_historical_orders,
    load_history_frame,
    save_json,
)
from backend.sku_avg_time import build_sku_average_times
from backend.simulation_runner import run_assignment_simulation
from backend.simpy_simulation_runner import run_assignment_simpy_simulation
from backend.validate_history_simulation import calculate_real_time_metrics, scoped_history_rows
from scenarios.order_picking.config import Config
from scenarios.order_picking.data_paths import historical_picking_excel


def parse_args():
    parser = argparse.ArgumentParser(
        description="Calibrate the operation gap used by the simplified order-SKU box simulation."
    )
    parser.add_argument("--excel", default=str(historical_picking_excel()))
    parser.add_argument("--date", action="append", help="Specific date. Can be provided multiple times.")
    parser.add_argument("--date-from", dest="date_from")
    parser.add_argument("--date-to", dest="date_to")
    parser.add_argument("--month", help="Calibrate one natural month, for example 2026-03.")
    parser.add_argument("--min-rows", type=int, default=1000)
    parser.add_argument("--process-time-source", choices=["actual", "sku_average", "both"], default="both")
    parser.add_argument("--engine", choices=["simpy", "simple"], default="simpy")
    parser.add_argument(
        "--sku-time-source",
        choices=["db", "excel"],
        default="db",
        help="Use t_part_master by default. Use excel only for offline reproducibility experiments.",
    )
    parser.add_argument(
        "--sku-time-excel",
        action="append",
        help=(
            "Excel file used to calculate SKU average picking times for sku_average mode. "
            "Can be provided multiple times. Only used when --sku-time-source excel. Defaults to --excel."
        ),
    )
    parser.add_argument(
        "--real-time-mode",
        choices=["net", "gross"],
        default="net",
        help="gross uses first start to last end; net subtracts global no-work gaps above the threshold.",
    )
    parser.add_argument(
        "--global-break-threshold-seconds",
        type=float,
        default=1800.0,
        help="Only used by --real-time-mode net. Default is 1800 seconds, i.e. 30 minutes.",
    )
    parser.add_argument(
        "--exclude-station-orders",
        default="",
        help=(
            "Data-scope exclusion list, for example 1,2. Orders with any historical row "
            "on these stations are removed before calibration."
        ),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "operation_gap_calibration.json"),
    )
    return parser.parse_args()


def select_dates(history_df, args):
    if args.date:
        return sorted(set(args.date))
    if args.month:
        try:
            year, month = (int(part) for part in args.month.split("-", 1))
            last_day = calendar.monthrange(year, month)[1]
        except Exception as exc:
            raise ValueError("--month must use YYYY-MM, for example 2026-03") from exc
        args.date_from = f"{year:04d}-{month:02d}-01"
        args.date_to = f"{year:04d}-{month:02d}-{last_day:02d}"
    dates = available_history_dates(history_df, min_rows=args.min_rows)
    if args.date_from:
        dates = [day for day in dates if day >= args.date_from]
    if args.date_to:
        dates = [day for day in dates if day <= args.date_to]
    return dates


def trimmed_mean(values, trim_ratio=0.1):
    values = sorted(float(value) for value in values)
    if not values:
        return 0.0
    trim = int(len(values) * trim_ratio)
    kept = values[trim : len(values) - trim] if len(values) > trim * 2 else values
    return mean(kept)


def run_engine(engine, orders, assignments, task_id, active_station_limit, operation_gap_seconds):
    runner = run_assignment_simpy_simulation if engine == "simpy" else run_assignment_simulation
    return runner(
        orders,
        assignments,
        task_id=task_id,
        active_station_limit=active_station_limit,
        operation_gap_seconds=operation_gap_seconds,
    )


def build_part_time_dict(source_files):
    stats = build_sku_average_times(source_files)
    return {
        str(row["SKU"]).strip(): float(row["单件平均耗时秒"])
        for _, row in stats.iterrows()
        if str(row["SKU"]).strip()
    }


def calibrate_day(
    history_df,
    target_date,
    process_time_source,
    real_time_mode="net",
    global_break_threshold_seconds=1800.0,
    exclude_station_orders=None,
    engine="simpy",
    part_time_dict=None,
):
    scoped_history_df, scope_summary = scoped_history_rows(history_df, target_date, exclude_station_orders)
    orders, assignments, metadata = build_historical_orders(
        scoped_history_df,
        target_date=target_date,
        process_time_source=process_time_source,
        part_time_dict=part_time_dict if process_time_source in {"sku_average", "part_master"} else None,
    )
    zero_gap = run_engine(
        engine,
        orders,
        assignments,
        task_id=f"GAP-CAL-{target_date}",
        active_station_limit=Config.NUM_STATIONS,
        operation_gap_seconds=0.0,
    )
    real_metrics = calculate_real_time_metrics(
        history_df,
        target_date,
        mode=real_time_mode,
        global_break_threshold_seconds=global_break_threshold_seconds,
        exclude_station_orders=exclude_station_orders,
    )
    real_makespan = float(real_metrics["real_makespan_seconds"])
    delta = real_makespan - float(zero_gap["total_makespan"])
    critical_boxes = int(zero_gap["critical_station_box_count"])
    formula_gap_seconds = max(0.0, delta / critical_boxes) if critical_boxes > 0 else 0.0

    lo = 0.0
    hi = max(1.0, formula_gap_seconds * 2.0)
    while True:
        high_sim = run_engine(
            engine,
            orders,
            assignments,
            task_id=f"GAP-CAL-{target_date}",
            active_station_limit=Config.NUM_STATIONS,
            operation_gap_seconds=hi,
        )
        if float(high_sim["total_makespan"]) >= real_makespan or hi >= 600.0:
            break
        hi *= 2.0

    for _ in range(30):
        mid = (lo + hi) / 2.0
        mid_sim = run_engine(
            engine,
            orders,
            assignments,
            task_id=f"GAP-CAL-{target_date}",
            active_station_limit=Config.NUM_STATIONS,
            operation_gap_seconds=mid,
        )
        if float(mid_sim["total_makespan"]) < real_makespan:
            lo = mid
        else:
            hi = mid
    gap_seconds = (lo + hi) / 2.0

    calibrated = run_engine(
        engine,
        orders,
        assignments,
        task_id=f"GAP-CAL-{target_date}",
        active_station_limit=Config.NUM_STATIONS,
        operation_gap_seconds=gap_seconds,
    )
    calibrated_error = (
        abs(float(calibrated["total_makespan"]) - real_makespan)
        / real_makespan
        * 100.0
        if real_makespan > 0
        else 0.0
    )
    return {
        "date": target_date,
        "engine": engine,
        "valid_rows": metadata["valid_rows"],
        "orders": metadata["order_count"],
        "boxes": metadata["box_count"],
        "stations": metadata["station_count"],
        "scope_excluded_station_orders": scope_summary,
        "real_time_mode": real_metrics["real_time_mode"],
        "real_makespan_seconds": round(real_makespan, 3),
        "gross_real_makespan_seconds": round(float(real_metrics["gross_makespan_seconds"]), 3),
        "net_real_makespan_seconds": round(float(real_metrics["net_makespan_seconds"]), 3),
        "global_break_threshold_seconds": round(float(real_metrics["global_break_threshold_seconds"]), 3),
        "global_break_count": int(real_metrics["global_break_count"]),
        "global_break_total_seconds": round(float(real_metrics["global_break_total_seconds"]), 3),
        "zero_gap_makespan_seconds": round(float(zero_gap["total_makespan"]), 3),
        "critical_station": zero_gap["critical_station"],
        "critical_station_box_count": critical_boxes,
        "formula_gap_seconds": round(float(formula_gap_seconds), 3),
        "gap_seconds": round(float(gap_seconds), 3),
        "calibrated_makespan_seconds": round(float(calibrated["total_makespan"]), 3),
        "calibrated_error_pct": round(float(calibrated_error), 3),
    }


def calibrate_source(history_df, dates, source, args, part_time_dict=None):
    results = []
    for idx, target_date in enumerate(dates, start=1):
        print(f"[{idx}/{len(dates)}] Calibrating {target_date} ({source})", flush=True)
        try:
            row = calibrate_day(
                history_df,
                target_date,
                source,
                real_time_mode=args.real_time_mode,
                global_break_threshold_seconds=args.global_break_threshold_seconds,
                exclude_station_orders=args.exclude_station_orders,
                engine=args.engine,
                part_time_dict=part_time_dict,
            )
            results.append(row)
            print(
                f"  real({row['real_time_mode']})={row['real_makespan_seconds']:.1f}s, "
                f"zero_gap={row['zero_gap_makespan_seconds']:.1f}s, "
                f"gap={row['gap_seconds']:.3f}s, "
                f"break={row['global_break_total_seconds']:.1f}s",
                flush=True,
            )
        except Exception as exc:
            print(f"  WARN: skipped {target_date}: {exc}", flush=True)
    return results


def summarize_calibration(args, source_file, source, dates, results):
    gaps = [row["gap_seconds"] for row in results if row["gap_seconds"] > 0]
    return {
        "generated_on": date.today().isoformat(),
        "source_file": os.path.abspath(source_file),
        "process_time_source": source,
        "engine": args.engine,
        "selected_dates": dates,
        "real_time_mode": args.real_time_mode,
        "global_break_threshold_seconds": round(float(args.global_break_threshold_seconds), 3),
        "scope_excluded_station_orders": results[0].get("scope_excluded_station_orders", {}) if results else {},
        "calibrated_days": len(results),
        "recommended_operation_gap_seconds": round(float(median(gaps)), 3) if gaps else 0.0,
        "recommended_method": "median",
        "gap_mean_seconds": round(float(mean(gaps)), 3) if gaps else 0.0,
        "gap_median_seconds": round(float(median(gaps)), 3) if gaps else 0.0,
        "gap_trimmed_mean_seconds": round(float(trimmed_mean(gaps)), 3) if gaps else 0.0,
        "config_hint": "Use this value with validate_history_simulation.py --operation-gap-seconds, or set [simulation].operation_gap_seconds.",
    }


def main():
    args = parse_args()
    history_df = load_history_frame(args.excel)
    dates = select_dates(history_df, args)
    if not dates:
        raise RuntimeError("No historical dates selected.")

    sources = ["actual", "sku_average"] if args.process_time_source == "both" else [args.process_time_source]
    part_time_dict = None
    if "sku_average" in sources and args.sku_time_source == "excel":
        sku_time_files = args.sku_time_excel or [args.excel]
        part_time_dict = build_part_time_dict(sku_time_files)
    source_reports = {}
    for source in sources:
        results = calibrate_source(history_df, dates, source, args, part_time_dict=part_time_dict)
        source_reports[source] = {
            "summary": summarize_calibration(args, args.excel, source, dates, results),
            "results": results,
        }

    payload = (
        {"summary": source_reports[sources[0]]["summary"], "results": source_reports[sources[0]]["results"]}
        if len(sources) == 1
        else {
            "summary": {
                "generated_on": date.today().isoformat(),
                "source_file": os.path.abspath(args.excel),
                "process_time_source": "both",
                "engine": args.engine,
                "selected_dates": dates,
                "real_time_mode": args.real_time_mode,
                "global_break_threshold_seconds": round(float(args.global_break_threshold_seconds), 3),
            },
            "reports": source_reports,
        }
    )
    output_path = save_json(args.output, payload)
    print("=" * 80)
    if len(sources) == 1:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps({source: report["summary"] for source, report in source_reports.items()}, ensure_ascii=False, indent=2))
    print(f"Calibration report: {output_path}")


if __name__ == "__main__":
    main()
