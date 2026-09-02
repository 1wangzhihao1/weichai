import argparse
import json
import os
import sys
from collections import defaultdict

import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.database import OrderBOM, OrderPool, SessionLocal
from scenarios.order_picking.data_paths import DEFAULT_DAILY_DATE, find_daily_picking_excel


DEFAULT_IMPORT_DATE = DEFAULT_DAILY_DATE
DEFAULT_BATCH_NO = f"ORDER_WAVE_{DEFAULT_IMPORT_DATE}"


def find_default_excel(date: str = DEFAULT_IMPORT_DATE) -> str:
    path = find_daily_picking_excel(date)
    if path is None:
        raise FileNotFoundError(f"No daily picking Excel found for {date}")
    return str(path)


def parse_orders(excel_path: str, qty_column: str = "目标数量") -> dict:
    df = pd.read_excel(excel_path, sheet_name=0)
    df.columns = df.columns.astype(str).str.strip().str.replace("\n", "").str.replace("\r", "")
    required_columns = ["拣选列表", "状态", "SKU", "目标数量", "已拣选数量", qty_column]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Excel missing required columns: {missing}")

    orders = defaultdict(lambda: defaultdict(float))
    order_sequence = []
    skipped = 0
    for _, row in df.iterrows():
        status = str(row.get("状态", "")).strip()
        if status and status not in {"完成", "确定"}:
            skipped += 1
            continue

        order_id = str(row.get("拣选列表", "")).strip()
        sku = str(row.get("SKU", "")).strip()
        try:
            qty = float(row.get(qty_column, 0) or 0)
            target_qty = float(row.get("目标数量", 0) or 0)
            picked_qty = float(row.get("已拣选数量", 0) or 0)
        except Exception:
            qty = 0.0
            target_qty = 0.0
            picked_qty = 0.0

        if (
            not order_id
            or order_id.lower() == "nan"
            or not sku
            or sku.lower() == "nan"
            or qty <= 0
            or target_qty <= 0
            or picked_qty <= 0
        ):
            skipped += 1
            continue
        if order_id not in orders:
            order_sequence.append(order_id)
        orders[order_id][sku] += qty

    items = []
    for order_id in order_sequence:
        for sku, qty in orders[order_id].items():
            items.append(
                {
                    "order_id": order_id,
                    "part_type": sku,
                    "quantity": int(qty) if float(qty).is_integer() else qty,
                }
            )
    return {
        "order_count": len(orders),
        "item_count": len(items),
        "skipped_rows": skipped,
        "order_sequence": order_sequence,
        "items": items,
    }


def import_direct_to_db(batch_no: str, items: list, dry_run: bool = False) -> dict:
    order_ids = []
    seen_order_ids = set()
    for item in items:
        order_id = item["order_id"]
        if order_id not in seen_order_ids:
            seen_order_ids.add(order_id)
            order_ids.append(order_id)
    if dry_run:
        return {"mode": "db", "dry_run": True, "batch_no": batch_no, "order_count": len(order_ids), "item_count": len(items)}

    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        old_order_ids = [
            row[0]
            for row in db.query(OrderPool.order_id)
            .filter(OrderPool.batch_no == batch_no)
            .all()
        ]
        if old_order_ids:
            db.query(OrderBOM).filter(OrderBOM.order_id.in_(old_order_ids)).delete(synchronize_session=False)
            db.query(OrderPool).filter(OrderPool.batch_no == batch_no).delete(synchronize_session=False)
            db.flush()

        db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).delete(synchronize_session=False)
        db.query(OrderPool).filter(OrderPool.order_id.in_(order_ids)).delete(synchronize_session=False)
        db.flush()
        for sequence_no, order_id in enumerate(order_ids, start=1):
            db.add(OrderPool(order_id=order_id, batch_no=batch_no, priority_level=1, sequence_no=sequence_no))

        for item in items:
            db.add(
                OrderBOM(
                    order_id=item["order_id"],
                    part_type=item["part_type"],
                    quantity=int(item["quantity"]),
                )
            )
        db.commit()
        return {"mode": "db", "batch_no": batch_no, "order_count": len(order_ids), "item_count": len(items)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def import_via_api(batch_no: str, items: list, api_url: str, chunk_orders: int, dry_run: bool = False) -> dict:
    import requests

    grouped = defaultdict(list)
    order_ids = []
    seen_order_ids = set()
    for item in items:
        if item["order_id"] not in seen_order_ids:
            seen_order_ids.add(item["order_id"])
            order_ids.append(item["order_id"])
        grouped[item["order_id"]].append(item)
    if dry_run:
        return {"mode": "api", "dry_run": True, "batch_no": batch_no, "order_count": len(order_ids), "item_count": len(items)}

    target_url = api_url.rstrip("/") + "/orders/upload"
    sent_items = 0
    for start in range(0, len(order_ids), chunk_orders):
        chunk_ids = order_ids[start : start + chunk_orders]
        chunk_items = []
        for order_id in chunk_ids:
            chunk_items.extend(grouped[order_id])
        response = requests.post(
            target_url,
            json={"batch_no": batch_no, "orders": chunk_items, "replace_existing": start == 0},
            timeout=60,
        )
        response.raise_for_status()
        sent_items += len(chunk_items)
        print(f"Uploaded orders {start + 1}-{start + len(chunk_ids)} / {len(order_ids)}")
    return {"mode": "api", "batch_no": batch_no, "order_count": len(order_ids), "item_count": sent_items}


def main():
    parser = argparse.ArgumentParser(description="Import one daily picking order file into APS database.")
    parser.add_argument("--date", default=DEFAULT_IMPORT_DATE, help="Daily data date, for example 2025-07-01.")
    parser.add_argument("--excel", default=None, help="Path to daily picking Excel. Default: raw_data/daily/<date>/picking/*拣选*.XLSX")
    parser.add_argument("--batch-no", default=None)
    parser.add_argument("--qty-column", default="目标数量", choices=["目标数量", "已拣选数量"])
    parser.add_argument("--mode", choices=["db", "api"], default="db")
    parser.add_argument("--api-url", default="http://127.0.0.1:8088/api/v1")
    parser.add_argument("--chunk-orders", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    batch_no = args.batch_no or f"ORDER_WAVE_{args.date}"
    excel_path = os.path.abspath(args.excel or find_default_excel(args.date))
    parsed = parse_orders(excel_path, qty_column=args.qty_column)
    print("=" * 80)
    print("Daily picking import")
    print("=" * 80)
    print(f"Excel       : {excel_path}")
    print(f"Date        : {args.date}")
    print(f"Batch       : {batch_no}")
    print(f"Qty column  : {args.qty_column}")
    print(f"Mode        : {args.mode}")
    print(f"Orders      : {parsed['order_count']}")
    print(f"SKU lines   : {parsed['item_count']}")
    print(f"Skipped rows: {parsed['skipped_rows']}")

    if args.mode == "db":
        result = import_direct_to_db(batch_no, parsed["items"], dry_run=args.dry_run)
    else:
        result = import_via_api(batch_no, parsed["items"], args.api_url, args.chunk_orders, dry_run=args.dry_run)

    print("Result      : " + json.dumps(result, ensure_ascii=False))
    print("=" * 80)


if __name__ == "__main__":
    main()
