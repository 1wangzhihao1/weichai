import os
from pathlib import Path
from typing import Iterable, Optional

from scenarios.order_picking.app_config import get_config_value, project_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
HISTORICAL_PICKING_DIR = project_path("raw_data/historical/picking")
DAILY_DATA_DIR = project_path(get_config_value("datasets", "daily_data_root", "raw_data/daily"))
INVENTORY_CACHE_DIR = project_path(get_config_value("inventory", "cache_dir", "data/inventory"))
SKU_TIME_DIR = RAW_DATA_DIR / "sku_time"
OUTPUT_DIR = project_path("output")
MODEL_DIR = project_path(get_config_value("model", "model_dir", "output/models"))
ACTIVE_MODEL_NAME = str(get_config_value("model", "active_model", "ppo_masking_model_v6.zip"))

DEFAULT_HISTORICAL_PICKING_NAME = "DMS拣选20260201-0429.XLSX"
DEFAULT_DAILY_DATE = os.environ.get(
    "WEICHAI_ACTIVE_DATE",
    str(get_config_value("datasets", "active_date", "2025-07-01")),
)


LEGACY_DAILY_DIRS = {
    "2025-07-01": RAW_DATA_DIR / "7.1",
}


def first_existing(paths: Iterable[Path]) -> Optional[Path]:
    for path in paths:
        if path and path.exists():
            return path
    return None


def historical_picking_excel() -> Path:
    configured = project_path(
        get_config_value(
            "datasets",
            "historical_picking_excel",
            "raw_data/historical/picking/DMS拣选20260201-0429.XLSX",
        )
    )
    candidates = [
        configured,
        RAW_DATA_DIR / DEFAULT_HISTORICAL_PICKING_NAME,
        SKU_TIME_DIR / DEFAULT_HISTORICAL_PICKING_NAME,
    ]
    found = first_existing(candidates)
    return found or candidates[0]


def daily_dir(date: str = DEFAULT_DAILY_DATE) -> Path:
    return DAILY_DATA_DIR / date


def daily_picking_dir(date: str = DEFAULT_DAILY_DATE) -> Path:
    return daily_dir(date) / "picking"


def daily_inventory_dir(date: str = DEFAULT_DAILY_DATE) -> Path:
    return daily_dir(date) / "inventory"


def legacy_daily_dir(date: str = DEFAULT_DAILY_DATE) -> Optional[Path]:
    return LEGACY_DAILY_DIRS.get(date)


def _excel_files(base_dir: Path):
    if not base_dir.exists():
        return []
    files = []
    for suffix in ("*.XLSX", "*.xlsx", "*.xls"):
        files.extend(base_dir.glob(suffix))
    return sorted(path for path in files if not path.name.startswith("~$"))


def find_daily_picking_excel(date: str = DEFAULT_DAILY_DATE) -> Optional[Path]:
    search_dirs = [daily_picking_dir(date)]
    legacy_dir = legacy_daily_dir(date)
    if legacy_dir:
        search_dirs.append(legacy_dir)

    for base_dir in search_dirs:
        for path in _excel_files(base_dir):
            if "拣选" in path.name:
                return path

    for base_dir in search_dirs:
        files = _excel_files(base_dir)
        if files:
            return files[0]
    return None


def find_inventory_excel(name_hint: str, date: str = DEFAULT_DAILY_DATE) -> Optional[Path]:
    search_dirs = [daily_inventory_dir(date)]
    legacy_dir = legacy_daily_dir(date)
    if legacy_dir:
        search_dirs.append(legacy_dir)

    for base_dir in search_dirs:
        for path in _excel_files(base_dir):
            if name_hint in path.name:
                return path
    return None


def iter_sku_time_excels():
    if SKU_TIME_DIR.exists():
        yield from _excel_files(SKU_TIME_DIR)

    hist = historical_picking_excel()
    if hist.exists():
        yield hist

    daily = find_daily_picking_excel(DEFAULT_DAILY_DATE)
    if daily and daily.exists():
        yield daily


def historical_picking_excel() -> Path:
    default_name = "DMS\u62e3\u900920260201-0429.XLSX"
    configured = project_path(
        get_config_value(
            "datasets",
            "historical_picking_excel",
            f"raw_data/historical/picking/{default_name}",
        )
    )
    candidates = [
        configured,
        RAW_DATA_DIR / default_name,
        SKU_TIME_DIR / default_name,
    ]
    found = first_existing(candidates)
    return found or candidates[0]


def find_daily_picking_excel(date: str = DEFAULT_DAILY_DATE) -> Optional[Path]:
    search_dirs = [daily_picking_dir(date)]
    legacy_dir = legacy_daily_dir(date)
    if legacy_dir:
        search_dirs.append(legacy_dir)

    for base_dir in search_dirs:
        for path in _excel_files(base_dir):
            if "\u62e3\u9009" in path.name:
                return path

    for base_dir in search_dirs:
        files = _excel_files(base_dir)
        if files:
            return files[0]
    return None


def configured_model_path() -> Path:
    model_name = ACTIVE_MODEL_NAME if ACTIVE_MODEL_NAME.endswith(".zip") else f"{ACTIVE_MODEL_NAME}.zip"
    return MODEL_DIR / model_name


def latest_model_path() -> Optional[Path]:
    if not MODEL_DIR.exists():
        return None
    candidates = sorted(MODEL_DIR.glob("*.zip"), key=lambda path: path.stat().st_ctime, reverse=True)
    return candidates[0] if candidates else None


def resolve_model_path(model_path: Optional[str] = None, allow_latest: bool = True) -> Optional[Path]:
    if model_path:
        explicit = Path(model_path)
        return explicit if explicit.is_absolute() else project_path(model_path)

    configured = configured_model_path()
    if configured.exists():
        return configured

    return latest_model_path() if allow_latest else configured
