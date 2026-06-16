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


DEFAULT_BATCH_NO = "ORDER_WAVE_2025-07-01"


def find_default_excel() -> str:
    base_dir = os.path.join(project_root, "raw_data", "7.1")
    candidates = []
    for name in os.listdir(base_dir):
        if name.startswith("~$"):
            continue
        lower_name = name.lower()
        if lower_name.endswith((".xlsx", ".xls")) and "拣选" in name:
            candidates.append(os.path.join(base_dir, name))
    if not candidates:
        raise FileNotFoundError(f"No July 1 picking Excel found under {base_dir}")
    return sorted(candidates)[0]


def parse_orders(excel_path: str, qty_column: str = "目标数量") -> dict:
    df = pd.read_excel(excel_path, sheet_name=0)
    required_columns = ["拣选列表", "状态", "SKU", qty_column]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Excel missing required columns: {missing}")

    orders = defaultdict(lambda: defaultdict(float))
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
        except Exception:
            qty = 0.0

        if not order_id or order_id.lower() == "nan" or not sku or sku.lower() == "nan" or qty <= 0:
            skipped += 1
            continue
        orders[order_id][sku] += qty

    items = []
    for order_id, sku_qty in sorted(orders.items()):
        for sku, qty in sorted(sku_qty.items()):
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
        "items": items,
    }


def import_direct_to_db(batch_no: str, items: list, dry_run: bool = False) -> dict:
    order_ids = sorted({item["order_id"] for item in items})
    if dry_run:
        return {"mode": "db", "dry_run": True, "batch_no": batch_no, "order_count": len(order_ids), "item_count": len(items)}

    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        db.query(OrderBOM).filter(OrderBOM.order_id.in_(order_ids)).delete(synchronize_session=False)
        for order_id in order_ids:
            existing = db.query(OrderPool).filter(OrderPool.order_id == order_id).first()
            if existing:
                existing.batch_no = batch_no
                existing.priority_level = existing.priority_level or 1
            else:
                db.add(OrderPool(order_id=order_id, batch_no=batch_no, priority_level=1))

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
    for item in items:
        grouped[item["order_id"]].append(item)
    order_ids = sorted(grouped)
    if dry_run:
        return {"mode": "api", "dry_run": True, "batch_no": batch_no, "order_count": len(order_ids), "item_count": len(items)}

    target_url = api_url.rstrip("/") + "/orders/upload"
    sent_items = 0
    for start in range(0, len(order_ids), chunk_orders):
        chunk_ids = order_ids[start : start + chunk_orders]
        chunk_items = []
        for order_id in chunk_ids:
            chunk_items.extend(grouped[order_id])
        response = requests.post(target_url, json={"batch_no": batch_no, "orders": chunk_items}, timeout=60)
        response.raise_for_status()
        sent_items += len(chunk_items)
        print(f"Uploaded orders {start + 1}-{start + len(chunk_ids)} / {len(order_ids)}")
    return {"mode": "api", "batch_no": batch_no, "order_count": len(order_ids), "item_count": sent_items}


def main():
    parser = argparse.ArgumentParser(description="Import July 1 picking orders into APS database.")
    parser.add_argument("--excel", default=None, help="Path to 7.1 picking Excel. Default: raw_data/7.1/*拣选*.XLSX")
    parser.add_argument("--batch-no", default=DEFAULT_BATCH_NO)
    parser.add_argument("--qty-column", default="目标数量", choices=["目标数量", "已拣选数量"])
    parser.add_argument("--mode", choices=["db", "api"], default="db")
    parser.add_argument("--api-url", default="http://127.0.0.1:8088/api/v1")
    parser.add_argument("--chunk-orders", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    excel_path = os.path.abspath(args.excel or find_default_excel())
    parsed = parse_orders(excel_path, qty_column=args.qty_column)
    print("=" * 80)
    print("July 1 picking import")
    print("=" * 80)
    print(f"Excel       : {excel_path}")
    print(f"Batch       : {args.batch_no}")
    print(f"Qty column  : {args.qty_column}")
    print(f"Mode        : {args.mode}")
    print(f"Orders      : {parsed['order_count']}")
    print(f"SKU lines   : {parsed['item_count']}")
    print(f"Skipped rows: {parsed['skipped_rows']}")

    if args.mode == "db":
        result = import_direct_to_db(args.batch_no, parsed["items"], dry_run=args.dry_run)
    else:
        result = import_via_api(args.batch_no, parsed["items"], args.api_url, args.chunk_orders, dry_run=args.dry_run)

    print("Result      : " + json.dumps(result, ensure_ascii=False))
    print("=" * 80)


if __name__ == "__main__":
    main()
