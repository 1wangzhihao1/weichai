import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY_DIR = PROJECT_ROOT / "raw_data" / "7.1"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "inventory"

COLUMN_CANDIDATES = {
    "sku": ["物料编号/SKU", "鐗╂枡缂栧彿/SKU", "SKU"],
    "sku_name": ["物料名称/SKU", "鐗╂枡鍚嶇О/SKU", "物料名称"],
    "qty": ["数量", "鏁伴噺"],
    "free_qty": ["空闲数量", "绌洪棽鏁伴噺"],
    "base_unit": ["ID/基础装载单元", "ID/鍩虹瑁呰浇鍗曞厓"],
    "base_status": ["状态/基础装载单元", "鐘舵€?鍩虹瑁呰浇鍗曞厓"],
    "load_unit": ["ID/装载单元", "ID/瑁呰浇鍗曞厓"],
    "location": ["详细位置/装载单元", "璇︾粏浣嶇疆/瑁呰浇鍗曞厓"],
    "lock_status": ["锁定状态/装载单元", "閿佸畾鐘舵€?瑁呰浇鍗曞厓"],
    "availability": ["可用性状态", "鍙敤鎬х姸鎬?"],
}


def normalize_sku(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _snapshot_path(snapshot_id: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"{snapshot_id}.json"


def _find_file(name_hint: str, base_dir: Path = DEFAULT_INVENTORY_DIR) -> Optional[Path]:
    if not base_dir.exists():
        return None
    for suffix in ("*.XLSX", "*.xlsx"):
        for path in base_dir.glob(suffix):
            if name_hint in path.name:
                return path
    return None


def _resolve_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    columns = {str(col).strip(): col for col in df.columns}
    resolved: Dict[str, Optional[str]] = {}
    for key, candidates in COLUMN_CANDIDATES.items():
        resolved[key] = next((columns[name] for name in candidates if name in columns), None)
    return resolved


def _get(row, columns: Dict[str, Optional[str]], key: str, default=""):
    col = columns.get(key)
    if col is None:
        return default
    return row.get(col, default)


def read_inventory_excel(path: os.PathLike, snapshot_id: Optional[str] = None) -> dict:
    """Read raw inventory Excel and aggregate positive available quantity by SKU/base unit."""
    path = Path(path)
    df = pd.read_excel(path, sheet_name=0)
    columns = _resolve_columns(df)
    if not columns.get("sku") or not columns.get("base_unit"):
        raise ValueError(f"Inventory file is missing SKU/base-unit columns: {path}")

    units_by_sku: Dict[str, Dict[str, dict]] = {}
    for _, row in df.iterrows():
        sku = normalize_sku(_get(row, columns, "sku"))
        unit_id = str(_get(row, columns, "base_unit", "")).strip()
        if not sku or not unit_id or unit_id.lower() == "nan":
            continue

        qty = _safe_float(_get(row, columns, "free_qty", None), default=None)
        if qty is None:
            qty = _safe_float(_get(row, columns, "qty", 0.0), default=0.0)
        if qty <= 0:
            continue

        locked = str(_get(row, columns, "lock_status", "")).strip()
        availability = str(_get(row, columns, "availability", "")).strip()
        if "锁" in locked or "閿" in locked or "冻结" in availability or "鍐荤粨" in availability:
            continue

        sku_units = units_by_sku.setdefault(sku, {})
        unit = sku_units.setdefault(
            unit_id,
            {
                "unit_id": unit_id,
                "sku": sku,
                "sku_name": str(_get(row, columns, "sku_name", "")).strip(),
                "qty": 0.0,
                "remaining_qty": 0.0,
                "available_at": 0.0,
                "status": str(_get(row, columns, "base_status", "存储")).strip() or "存储",
                "load_unit_id": str(_get(row, columns, "load_unit", "")).strip(),
                "location": str(_get(row, columns, "location", "")).strip(),
            },
        )
        unit["qty"] += qty
        unit["remaining_qty"] += qty

    sku_units = {
        sku: sorted(units.values(), key=lambda u: (u["available_at"], u["unit_id"]))
        for sku, units in units_by_sku.items()
    }
    total_units = sum(len(units) for units in sku_units.values())
    total_qty = sum(unit["remaining_qty"] for units in sku_units.values() for unit in units)

    return {
        "snapshot_id": snapshot_id or path.stem,
        "source_file": str(path),
        "sku_units": sku_units,
        "summary": {
            "sku_count": len(sku_units),
            "base_unit_count": total_units,
            "total_qty": total_qty,
        },
    }


def save_snapshot(snapshot: dict, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(snapshot["snapshot_id"], cache_dir)
    with path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return path


def load_snapshot(snapshot_id: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> dict:
    path = _snapshot_path(snapshot_id, cache_dir)
    if not path.exists():
        generated = ensure_default_snapshots(cache_dir=cache_dir)
        if snapshot_id not in generated and not path.exists():
            raise FileNotFoundError(f"Inventory snapshot not found: {snapshot_id}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_snapshots(cache_dir: Path = DEFAULT_CACHE_DIR) -> List[dict]:
    ensure_default_snapshots(cache_dir=cache_dir)
    snapshots = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            snapshots.append(
                {
                    "snapshot_id": data.get("snapshot_id", path.stem),
                    "source_file": data.get("source_file", ""),
                    "summary": data.get("summary", {}),
                }
            )
        except Exception:
            continue
    return snapshots


@lru_cache(maxsize=1)
def ensure_default_snapshots(cache_dir: Path = DEFAULT_CACHE_DIR) -> tuple:
    generated = []
    for snapshot_id, hint in (("2025-07-01-morning", "早库存单元"), ("2025-07-01-evening", "晚库存单元")):
        path = _snapshot_path(snapshot_id, cache_dir)
        if path.exists():
            generated.append(snapshot_id)
            continue
        source = _find_file(hint)
        if source is None:
            continue
        snapshot = read_inventory_excel(source, snapshot_id=snapshot_id)
        save_snapshot(snapshot, cache_dir=cache_dir)
        generated.append(snapshot_id)
    return tuple(generated)
