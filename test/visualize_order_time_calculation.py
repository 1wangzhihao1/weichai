import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import PartMaster, SessionLocal, engine  # noqa: E402
from scenarios.order_picking.rl_environment import load_and_aggregate_real_orders  # noqa: E402


def load_part_times():
    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        rows = db.query(PartMaster).all()
        return {str(row.part_type).strip(): float(row.standard_p_time) for row in rows}
    finally:
        db.close()


def order_date(order):
    start_time = order.get("start_time")
    if hasattr(start_time, "date"):
        return start_time.date().isoformat()
    return str(start_time)[:10]


def select_order(orders, target_date, order_id=None):
    date_orders = [order for order in orders if order_date(order) == target_date]
    if not date_orders:
        raise RuntimeError(f"No aggregated orders found for date {target_date}.")

    if order_id:
        for order in date_orders:
            if str(order["order_id"]) == str(order_id):
                return order, len(date_orders)
        raise RuntimeError(f"Order {order_id} was not found on {target_date}.")

    # Pick a visually useful sample: the order with the most SKU boxes.
    return max(date_orders, key=lambda item: (len(item.get("boxes", [])), item.get("total_p_time", 0))), len(date_orders)


def build_rows(order, part_times):
    rows = []
    total_from_boxes = 0.0
    for box in order.get("boxes", []):
        sku = str(box["sku"]).strip()
        qty = float(box.get("qty", 0))
        p_time = float(box.get("p_time", 0))
        standard_p_time = part_times.get(sku)
        fallback_used = standard_p_time is None
        if fallback_used and qty:
            standard_p_time = p_time / qty

        total_from_boxes += p_time
        rows.append(
            {
                "sku": sku,
                "qty": qty,
                "standard_p_time": round(float(standard_p_time or 0), 6),
                "formula": f"{round(float(standard_p_time or 0), 6)} x {int(qty) if qty.is_integer() else qty}",
                "p_time": round(p_time, 6),
                "fallback_4_5_used": fallback_used,
            }
        )

    rows.sort(key=lambda item: item["p_time"], reverse=True)
    return rows, total_from_boxes


def save_json(payload, output_path):
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def save_chart(rows, payload, output_path, top_n):
    top_rows = rows[:top_n]
    labels = [row["sku"] for row in top_rows]
    values = [row["p_time"] for row in top_rows]
    annotations = [f"qty={row['qty']:g}\\nstd={row['standard_p_time']:g}s" for row in top_rows]

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.figure(figsize=(13, 7))
    bars = plt.bar(range(len(top_rows)), values, color="#2f6f9f")
    plt.xticks(range(len(top_rows)), labels, rotation=40, ha="right", fontsize=9)
    plt.ylabel("p_time seconds")
    plt.title(
        "Order processing time calculation: "
        f"sum(box p_time)={payload['total_from_boxes']:.3f}s, "
        f"order total_p_time={payload['order_total_p_time']:.3f}s"
    )
    plt.grid(axis="y", alpha=0.25)

    for bar, note in zip(bars, annotations):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            note,
            ha="center",
            va="bottom",
            fontsize=8,
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def print_table(payload, rows, max_rows):
    print("=" * 100)
    print("ORDER TIME CALCULATION EVIDENCE")
    print("=" * 100)
    print(f"date              : {payload['date']}")
    print(f"orders on date    : {payload['orders_on_date']}")
    print(f"selected order_id : {payload['order_id']}")
    print(f"start_time        : {payload['start_time']}")
    print(f"box/SKU count     : {payload['box_count']}")
    print(f"order total_p_time: {payload['order_total_p_time']:.3f} seconds")
    print(f"sum box p_time    : {payload['total_from_boxes']:.3f} seconds")
    print(f"difference        : {payload['difference']:.6f} seconds")
    print("-" * 100)
    print(f"{'SKU':<26} {'qty':>8} {'standard_p_time':>18} {'formula':>22} {'p_time':>14} {'fallback':>10}")
    print("-" * 100)
    for row in rows[:max_rows]:
        print(
            f"{row['sku']:<26} "
            f"{row['qty']:>8g} "
            f"{row['standard_p_time']:>18g} "
            f"{row['formula']:>22} "
            f"{row['p_time']:>14g} "
            f"{str(row['fallback_4_5_used']):>10}"
        )
    if len(rows) > max_rows:
        print(f"... {len(rows) - max_rows} more row(s) written to JSON.")
    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description="Visualize how SKU standard process times are multiplied by quantities and summed into order total_p_time."
    )
    parser.add_argument("--date", default="2026-04-11", help="Order date to inspect.")
    parser.add_argument("--order-id", help="Optional order_id. If omitted, the order with the most SKU boxes is selected.")
    parser.add_argument("--top-n", type=int, default=12, help="Number of SKU rows shown in the chart.")
    parser.add_argument("--print-rows", type=int, default=20, help="Number of rows printed in the terminal table.")
    args = parser.parse_args()

    os.makedirs(PROJECT_ROOT / "test", exist_ok=True)
    print("Loading PartMaster standard process times from database...")
    part_times = load_part_times()
    print(f"Loaded {len(part_times)} PartMaster records.")

    print("Loading and aggregating raw DMS picking orders through rl_environment.py...")
    orders = load_and_aggregate_real_orders()
    order, orders_on_date = select_order(orders, args.date, args.order_id)
    rows, total_from_boxes = build_rows(order, part_times)

    payload = {
        "date": args.date,
        "orders_on_date": orders_on_date,
        "order_id": str(order["order_id"]),
        "start_time": str(order.get("start_time")),
        "box_count": len(rows),
        "order_total_p_time": round(float(order.get("total_p_time", 0)), 6),
        "total_from_boxes": round(float(total_from_boxes), 6),
        "difference": round(abs(float(order.get("total_p_time", 0)) - total_from_boxes), 9),
        "calculation_rule": "box p_time = PartMaster.standard_p_time * qty; order total_p_time = sum(box p_time)",
        "rows": rows,
    }

    stem = f"order_time_calculation_{args.date}"
    if args.order_id:
        stem += f"_{args.order_id}"
    json_path = PROJECT_ROOT / "test" / f"{stem}.json"
    png_path = PROJECT_ROOT / "test" / f"{stem}.png"

    save_json(payload, json_path)
    save_chart(rows, payload, png_path, max(1, args.top_n))
    print_table(payload, rows, max(1, args.print_rows))

    print(f"JSON evidence : {json_path}")
    print(f"Chart evidence: {png_path}")


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception:
        exit_code = 1
        raise
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(exit_code)
