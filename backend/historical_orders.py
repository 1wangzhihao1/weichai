import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.database import PartMaster, SessionLocal
from scenarios.order_picking.data_paths import historical_picking_excel


ORDER_ID_COLUMN = "拣选列表"
DEFAULT_STATUS_VALUES = {"完成", "确定", ""}


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.replace("\n", "").str.replace("\r", "")
    return df


def require_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"Excel missing required columns by name: {missing}")


def parse_station_id(value) -> int:
    if pd.isna(value):
        return -1
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else -1


def load_history_frame(excel_path: Optional[str] = None) -> pd.DataFrame:
    path = str(excel_path or historical_picking_excel())
    if not os.path.exists(path):
        raise FileNotFoundError(f"Historical picking Excel not found: {path}")
    df = pd.read_excel(path, sheet_name=0)
    df = clean_columns(df)
    require_columns(
        df,
        [
            "开始时间",
            "结束时间",
            ORDER_ID_COLUMN,
            "状态",
            "SKU",
            "目标数量",
            "已拣选数量",
            "拣选员 ID",
        ],
    )
    df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
    df["结束时间"] = pd.to_datetime(df["结束时间"], errors="coerce")
    df["测试日期"] = df["开始时间"].dt.strftime("%Y-%m-%d")
    return df


def clean_history_rows(history_df: pd.DataFrame, target_date: Optional[str] = None) -> pd.DataFrame:
    df = clean_columns(history_df)
    require_columns(
        df,
        [
            "开始时间",
            "结束时间",
            ORDER_ID_COLUMN,
            "状态",
            "SKU",
            "目标数量",
            "已拣选数量",
            "拣选员 ID",
        ],
    )

    if "测试日期" not in df.columns:
        df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
        df["测试日期"] = df["开始时间"].dt.strftime("%Y-%m-%d")
    if target_date:
        df = df[df["测试日期"] == target_date].copy()
    else:
        df = df.copy()

    df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
    df["结束时间"] = pd.to_datetime(df["结束时间"], errors="coerce")
    df["目标数量"] = pd.to_numeric(df["目标数量"], errors="coerce")
    df["已拣选数量"] = pd.to_numeric(df["已拣选数量"], errors="coerce")

    df = df.dropna(
        subset=[
            "开始时间",
            "结束时间",
            ORDER_ID_COLUMN,
            "SKU",
            "目标数量",
            "已拣选数量",
            "拣选员 ID",
        ]
    )
    df = df[df["状态"].astype(str).str.strip().isin(DEFAULT_STATUS_VALUES)]
    df = df[(df["目标数量"] > 0) & (df["已拣选数量"] > 0)]
    df["耗时秒"] = (df["结束时间"] - df["开始时间"]).dt.total_seconds()
    df = df[df["耗时秒"] > 0]
    df["站台号"] = df["拣选员 ID"].apply(parse_station_id)
    df = df[df["站台号"] > 0]
    return df.sort_values(["开始时间", "结束时间"]).copy()


def load_part_times_from_db() -> Dict[str, float]:
    db = SessionLocal()
    if hasattr(db, "__next__"):
        db = next(db)
    try:
        return {str(row.part_type).strip(): float(row.standard_p_time) for row in db.query(PartMaster).all()}
    except Exception:
        return {}
    finally:
        try:
            db.close()
        except Exception:
            pass


def _choose_order_station(rows: pd.DataFrame) -> int:
    counts = Counter(int(value) for value in rows["站台号"].tolist())
    return counts.most_common(1)[0][0]


def build_historical_orders(
    history_df: pd.DataFrame,
    target_date: str,
    process_time_source: str = "actual",
    part_time_dict: Optional[Dict[str, float]] = None,
    default_unit_time: float = 4.5,
) -> Tuple[List[dict], List[dict], dict]:
    """Convert historical picking rows into the current simulation order-SKU box abstraction."""
    clean = clean_history_rows(history_df, target_date)
    if clean.empty:
        raise ValueError(f"No valid historical picking rows for {target_date}")

    process_time_key = (process_time_source or "actual").lower()
    if process_time_key not in {"actual", "sku_average", "part_master"}:
        raise ValueError(f"Unsupported process_time_source: {process_time_source}")
    if process_time_key in {"sku_average", "part_master"} and part_time_dict is None:
        part_time_dict = load_part_times_from_db()
    part_time_dict = part_time_dict or {}

    orders_by_id: Dict[str, dict] = {}
    order_first_start: Dict[str, pd.Timestamp] = {}
    order_rows: Dict[str, pd.DataFrame] = {}
    grouped = clean.groupby([ORDER_ID_COLUMN, "SKU"], sort=False)

    for (order_id_raw, sku_raw), group in grouped:
        order_id = str(order_id_raw).strip()
        sku = str(sku_raw).strip()
        if not order_id or not sku or order_id.lower() == "nan" or sku.lower() == "nan":
            continue

        qty = float(group["已拣选数量"].sum())
        if process_time_key == "actual":
            p_time = float(group["耗时秒"].sum())
        else:
            p_time = float(part_time_dict.get(sku, default_unit_time)) * qty
        station_id = _choose_order_station(group)
        first_start = group["开始时间"].min()

        if order_id not in orders_by_id:
            orders_by_id[order_id] = {
                "order_id": order_id,
                "boxes": [],
                "total_p_time": 0.0,
                "historical_station": station_id,
                "start_time": first_start,
            }
            order_first_start[order_id] = first_start
            order_rows[order_id] = group
        else:
            order_first_start[order_id] = min(order_first_start[order_id], first_start)
            order_rows[order_id] = pd.concat([order_rows[order_id], group], ignore_index=True)

        box = {
            "sku": sku,
            "qty": int(qty) if float(qty).is_integer() else qty,
            "p_time": p_time,
            "historical_station": station_id,
            "source_line_count": int(len(group)),
        }
        orders_by_id[order_id]["boxes"].append(box)
        orders_by_id[order_id]["total_p_time"] += p_time

    orders = list(orders_by_id.values())
    for order in orders:
        rows = order_rows[order["order_id"]]
        order["historical_station"] = _choose_order_station(rows)
        order["start_time"] = order_first_start[order["order_id"]]

    orders.sort(key=lambda item: (item["start_time"], item["order_id"]))
    assignments = [
        {
            "sequence": idx,
            "order_id": order["order_id"],
            "target_station": int(order["historical_station"]),
        }
        for idx, order in enumerate(orders, start=1)
    ]

    real_start = clean["开始时间"].min()
    real_end = clean["结束时间"].max()
    real_makespan = float((real_end - real_start).total_seconds())
    station_ids = sorted(int(value) for value in clean["站台号"].dropna().unique())
    metadata = {
        "date": target_date,
        "process_time_source": process_time_key,
        "valid_rows": int(len(clean)),
        "order_count": int(clean[ORDER_ID_COLUMN].nunique()),
        "box_count": int(sum(len(order["boxes"]) for order in orders)),
        "station_count": int(len(station_ids)),
        "station_ids": station_ids,
        "real_start_time": real_start.isoformat(),
        "real_end_time": real_end.isoformat(),
        "real_makespan_seconds": real_makespan,
        "real_makespan_hours": round(real_makespan / 3600.0, 3),
    }
    return orders, assignments, metadata


def available_history_dates(history_df: pd.DataFrame, min_rows: int = 1) -> List[str]:
    clean = clean_history_rows(history_df)
    counts = clean.groupby("测试日期").size()
    return sorted(str(day) for day, count in counts.items() if int(count) >= min_rows)


def save_json(path: str | Path, payload: dict) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fp:
        import json

        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return str(output_path)
