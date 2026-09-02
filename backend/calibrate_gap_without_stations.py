import argparse
import json
import os
import sys
from datetime import date

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.calibrate_operation_gap import (
    build_part_time_dict,
    calibrate_source,
    select_dates,
    summarize_calibration,
)
from backend.historical_orders import load_history_frame, save_json
from scenarios.order_picking.data_paths import historical_picking_excel


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate operation gap after removing orders related to selected stations. "
            "Default removes station 1 and 2 orders."
        )
    )
    parser.add_argument("--excel", default=str(historical_picking_excel()))
    parser.add_argument("--date", action="append", help="Specific date. Can be provided multiple times.")
    parser.add_argument("--date-from", dest="date_from")
    parser.add_argument("--date-to", dest="date_to")
    parser.add_argument("--month", default="2026-03", help="Calibrate one natural month, for example 2026-03.")
    parser.add_argument("--min-rows", type=int, default=1000)
    parser.add_argument("--process-time-source", choices=["actual", "sku_average", "both"], default="sku_average")
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
    parser.add_argument("--real-time-mode", choices=["net", "gross"], default="net")
    parser.add_argument("--global-break-threshold-seconds", type=float, default=1800.0)
    parser.add_argument("--exclude-station-orders", default="1,2")
    parser.add_argument(
        "--output",
        default=os.path.join(project_root, "output", "operation_gap_calibration_without_s01_s02.json"),
    )
    return parser.parse_args()


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
                "exclude_station_orders": args.exclude_station_orders,
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
