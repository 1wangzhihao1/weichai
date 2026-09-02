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
    ORDER_ID_COLUMN,
    available_history_dates,
    build_historical_orders,
    clean_history_rows,
    load_history_frame,
    save_json,
)
from backend.sku_avg_time import build_sku_average_times
from backend.simulation_runner import run_assignment_simulation
from backend.simpy_simulation_runner import run_assignment_simpy_simulation
from scenarios.order_picking.app_config import get_config_value
from scenarios.order_picking.config import Config
from scenarios.order_picking.data_paths import historical_picking_excel


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate historical assignment simulation against real historical makespan."
    )
    parser.add_argument("--excel", default=str(historical_picking_excel()))
    parser.add_argument("--date", action="append")
    parser.add_argument("--date-from", dest="date_from")
    parser.add_argument("--date-to", dest="date_to")
    parser.add_argument("--month", help="Validate one natural month, for example 2026-03.")
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
        "--operation-gap-seconds",
        type=float,
        default=None,
        help="Use the same operation gap for every process-time source.",
    )
    parser.add_argument(
        "--calibration-report",
        help="Read recommended operation gaps from calibrate_operation_gap.py output.",
    )
    parser.add_argument(
        "--reference-exclude-stations",
        default="1,2",
        help=(
            "Optional reference-only station exclusion list, for example 1,2. "
            "The main validation still uses all stations."
        ),
    )
    parser.add_argument(
        "--exclude-station-orders",
        default="",
        help=(
            "Data-scope exclusion list, for example 1,2. Orders with any historical row "
            "on these stations are removed before simulation and real-time calculation."
        ),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "history_simulation_validation.json"),
    )
    return parser.parse_args()


def parse_station_ids(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_parts = value
    else:
        raw_parts = str(value).replace("，", ",").split(",")
    station_ids = []
    for part in raw_parts:
        text = str(part).strip()
        if not text:
            continue
        station_ids.append(int(text))
    return sorted(set(station_ids))


def scoped_history_rows(history_df, target_date, exclude_station_orders=None):
    clean = clean_history_rows(history_df, target_date)
    excluded = set(parse_station_ids(exclude_station_orders))
    if not excluded:
        return clean, {
            "excluded_stations": [],
            "removed_orders": 0,
            "removed_rows": 0,
            "kept_orders": int(clean[ORDER_ID_COLUMN].nunique()),
            "kept_rows": int(len(clean)),
        }

    order_ids = clean[ORDER_ID_COLUMN].astype(str).str.strip()
    removed_order_ids = set(order_ids[clean["站台号"].isin(excluded)].tolist())
    kept = clean[~order_ids.isin(removed_order_ids)].copy()
    return kept, {
        "excluded_stations": sorted(excluded),
        "removed_orders": int(len(removed_order_ids)),
        "removed_rows": int(len(clean) - len(kept)),
        "kept_orders": int(kept[ORDER_ID_COLUMN].nunique()) if not kept.empty else 0,
        "kept_rows": int(len(kept)),
    }


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


def load_calibration_gaps(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fp:
        payload = json.load(fp)
    reports = payload.get("reports")
    if reports:
        return {
            source: float(report.get("summary", {}).get("recommended_operation_gap_seconds", 0.0) or 0.0)
            for source, report in reports.items()
        }
    summary = payload.get("summary", {})
    source = summary.get("process_time_source")
    if source:
        return {source: float(summary.get("recommended_operation_gap_seconds", 0.0) or 0.0)}
    return {}


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


def calculate_real_time_metrics(
    history_df,
    target_date,
    mode="net",
    global_break_threshold_seconds=1800.0,
    exclude_stations=None,
    exclude_station_orders=None,
):
    clean, scope_summary = scoped_history_rows(history_df, target_date, exclude_station_orders)
    excluded = set(parse_station_ids(exclude_stations))
    if excluded:
        clean = clean[~clean["站台号"].isin(excluded)].copy()
    if clean.empty:
        raise ValueError(f"No valid historical picking rows for {target_date}")

    real_start = clean["开始时间"].min()
    real_end = clean["结束时间"].max()
    gross = float((real_end - real_start).total_seconds())
    break_threshold = max(0.0, float(global_break_threshold_seconds or 0.0))

    intervals = [
        (row["开始时间"], row["结束时间"])
        for _, row in clean[["开始时间", "结束时间"]]
        .sort_values(["开始时间", "结束时间"])
        .iterrows()
    ]

    merged_intervals = []
    current_start, current_end = intervals[0]
    for start_time, end_time in intervals[1:]:
        if start_time <= current_end:
            current_end = max(current_end, end_time)
        else:
            merged_intervals.append((current_start, current_end))
            current_start, current_end = start_time, end_time
    merged_intervals.append((current_start, current_end))

    global_breaks = []
    for (_, previous_end), (next_start, _) in zip(merged_intervals, merged_intervals[1:]):
        break_seconds = float((next_start - previous_end).total_seconds())
        if break_seconds > break_threshold:
            global_breaks.append(
                {
                    "start_time": previous_end.isoformat(),
                    "end_time": next_start.isoformat(),
                    "seconds": round(break_seconds, 3),
                }
            )

    break_total = sum(item["seconds"] for item in global_breaks)
    net = max(0.0, gross - break_total)
    selected = net if mode == "net" else gross
    return {
        "real_time_mode": mode,
        "real_start_time": real_start.isoformat(),
        "real_end_time": real_end.isoformat(),
        "gross_makespan_seconds": gross,
        "net_makespan_seconds": net,
        "real_makespan_seconds": selected,
        "scope_excluded_station_orders": scope_summary,
        "excluded_stations": sorted(excluded),
        "global_break_threshold_seconds": break_threshold,
        "global_break_count": len(global_breaks),
        "global_break_total_seconds": break_total,
        "global_breaks": global_breaks,
    }


def validate_day(
    history_df,
    target_date,
    process_time_source,
    operation_gap_seconds,
    real_time_mode="net",
    global_break_threshold_seconds=1800.0,
    reference_exclude_stations=None,
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
    sim = run_engine(
        engine,
        orders,
        assignments,
        task_id=f"HISTORY-VALIDATE-{target_date}",
        active_station_limit=Config.NUM_STATIONS,
        operation_gap_seconds=operation_gap_seconds,
    )
    real_metrics = calculate_real_time_metrics(
        history_df,
        target_date,
        mode=real_time_mode,
        global_break_threshold_seconds=global_break_threshold_seconds,
        exclude_station_orders=exclude_station_orders,
    )
    real = float(real_metrics["real_makespan_seconds"])
    simulated = float(sim["total_makespan"])
    error = abs(simulated - real) / real * 100.0 if real > 0 else 0.0
    result = {
        "date": target_date,
        "engine": engine,
        "valid_rows": metadata["valid_rows"],
        "orders": metadata["order_count"],
        "boxes": metadata["box_count"],
        "stations": metadata["station_count"],
        "operation_gap_seconds": round(float(operation_gap_seconds), 3),
        "real_time_mode": real_metrics["real_time_mode"],
        "real_makespan_seconds": round(real, 3),
        "gross_real_makespan_seconds": round(float(real_metrics["gross_makespan_seconds"]), 3),
        "net_real_makespan_seconds": round(float(real_metrics["net_makespan_seconds"]), 3),
        "global_break_threshold_seconds": round(float(real_metrics["global_break_threshold_seconds"]), 3),
        "global_break_count": int(real_metrics["global_break_count"]),
        "global_break_total_seconds": round(float(real_metrics["global_break_total_seconds"]), 3),
        "simulated_makespan_seconds": round(simulated, 3),
        "error_pct": round(float(error), 3),
        "within_10_pct": bool(error <= 10.0),
        "critical_station": sim["critical_station"],
        "critical_station_box_count": sim["critical_station_box_count"],
        "scope_excluded_station_orders": scope_summary,
    }
    excluded = parse_station_ids(reference_exclude_stations)
    if excluded:
        station_stats = [
            stat
            for stat in sim["station_stats"]
            if int(stat["station_id"]) not in set(excluded) and int(stat.get("box_count", 0)) > 0
        ]
        if station_stats:
            ref_simulated = max(float(stat["available_time_seconds"]) for stat in station_stats)
            ref_real_metrics = calculate_real_time_metrics(
                history_df,
                target_date,
                mode=real_time_mode,
                global_break_threshold_seconds=global_break_threshold_seconds,
                exclude_stations=excluded,
                exclude_station_orders=exclude_station_orders,
            )
            ref_real = float(ref_real_metrics["real_makespan_seconds"])
            ref_error = abs(ref_simulated - ref_real) / ref_real * 100.0 if ref_real > 0 else 0.0
            ref_critical = max(station_stats, key=lambda stat: float(stat["available_time_seconds"]))
            result["reference_excluding_stations"] = {
                "excluded_stations": excluded,
                "real_time_mode": ref_real_metrics["real_time_mode"],
                "real_makespan_seconds": round(ref_real, 3),
                "gross_real_makespan_seconds": round(float(ref_real_metrics["gross_makespan_seconds"]), 3),
                "net_real_makespan_seconds": round(float(ref_real_metrics["net_makespan_seconds"]), 3),
                "global_break_count": int(ref_real_metrics["global_break_count"]),
                "global_break_total_seconds": round(float(ref_real_metrics["global_break_total_seconds"]), 3),
                "simulated_makespan_seconds": round(ref_simulated, 3),
                "error_pct": round(float(ref_error), 3),
                "within_10_pct": bool(ref_error <= 10.0),
                "critical_station": int(ref_critical["station_id"]),
                "critical_station_box_count": int(ref_critical["box_count"]),
            }
    return result


def summarize_results(args, source_file, source, gap, dates, results):
    errors = [row["error_pct"] for row in results]
    within_count = sum(1 for row in results if row["within_10_pct"])
    summary = {
        "generated_on": date.today().isoformat(),
        "source_file": os.path.abspath(source_file),
        "process_time_source": source,
        "engine": args.engine,
        "selected_dates": dates,
        "real_time_mode": args.real_time_mode,
        "global_break_threshold_seconds": round(float(args.global_break_threshold_seconds), 3),
        "operation_gap_seconds": round(gap, 3),
        "scope_excluded_station_orders": results[0].get("scope_excluded_station_orders", {}) if results else {},
        "validated_days": len(results),
        "within_10_pct_days": within_count,
        "within_10_pct_ratio": round(within_count / len(results), 3) if results else 0.0,
        "mean_error_pct": round(float(mean(errors)), 3) if errors else 0.0,
        "median_error_pct": round(float(median(errors)), 3) if errors else 0.0,
        "max_error_pct": round(float(max(errors)), 3) if errors else 0.0,
        "failed_days": [row["date"] for row in results if not row["within_10_pct"]],
    }
    reference_rows = [row["reference_excluding_stations"] for row in results if row.get("reference_excluding_stations")]
    if reference_rows:
        reference_errors = [row["error_pct"] for row in reference_rows]
        reference_within_count = sum(1 for row in reference_rows if row["within_10_pct"])
        summary["reference_excluding_stations"] = {
            "excluded_stations": reference_rows[0]["excluded_stations"],
            "validated_days": len(reference_rows),
            "within_10_pct_days": reference_within_count,
            "within_10_pct_ratio": round(reference_within_count / len(reference_rows), 3),
            "mean_error_pct": round(float(mean(reference_errors)), 3),
            "median_error_pct": round(float(median(reference_errors)), 3),
            "max_error_pct": round(float(max(reference_errors)), 3),
            "failed_days": [
                row["date"]
                for row in results
                if row.get("reference_excluding_stations")
                and not row["reference_excluding_stations"]["within_10_pct"]
            ],
        }
    return summary


def validate_source(history_df, dates, source, gap, args, part_time_dict=None):
    results = []
    for idx, target_date in enumerate(dates, start=1):
        print(f"[{idx}/{len(dates)}] Validating {target_date} ({source})", flush=True)
        try:
            row = validate_day(
                history_df,
                target_date,
                source,
                gap,
                real_time_mode=args.real_time_mode,
                global_break_threshold_seconds=args.global_break_threshold_seconds,
                reference_exclude_stations=args.reference_exclude_stations,
                exclude_station_orders=args.exclude_station_orders,
                engine=args.engine,
                part_time_dict=part_time_dict,
            )
            results.append(row)
            reference = row.get("reference_excluding_stations")
            reference_text = (
                f", ref_excl_{'_'.join(str(x) for x in reference['excluded_stations'])}"
                f"={reference['error_pct']:.2f}%"
                if reference
                else ""
            )
            print(
                f"  real({row['real_time_mode']})={row['real_makespan_seconds']:.1f}s, "
                f"break={row['global_break_total_seconds']:.1f}s, "
                f"sim={row['simulated_makespan_seconds']:.1f}s, "
                f"error={row['error_pct']:.2f}%"
                f"{reference_text}",
                flush=True,
            )
        except Exception as exc:
            print(f"  WARN: skipped {target_date}: {exc}", flush=True)
    return results


def main():
    args = parse_args()
    calibration_gaps = load_calibration_gaps(args.calibration_report)
    default_gap = float(args.operation_gap_seconds) if args.operation_gap_seconds is not None else float(
        get_config_value("simulation", "operation_gap_seconds", 0.0)
    )
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
        gap = float(calibration_gaps.get(source, default_gap))
        results = validate_source(history_df, dates, source, gap, args, part_time_dict=part_time_dict)
        source_reports[source] = {
            "summary": summarize_results(args, args.excel, source, gap, dates, results),
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
                "operation_gap_seconds_by_source": {
                    source: round(float(source_reports[source]["summary"]["operation_gap_seconds"]), 3)
                    for source in sources
                },
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
    print(f"Validation report: {output_path}")


if __name__ == "__main__":
    main()
