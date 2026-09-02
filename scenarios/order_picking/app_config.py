from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "app_config.toml"


DEFAULT_CONFIG = {
    "app": {
        "backend_port": 8088,
        "api_base_url": "http://127.0.0.1:8088/api/v1",
    },
    "datasets": {
        "active_date": "2025-07-01",
        "historical_picking_excel": "raw_data/historical/picking/DMS拣选20260201-0429.XLSX",
        "daily_data_root": "raw_data/daily",
    },
    "inventory": {
        "cache_dir": "data/inventory",
        "morning_file_hint": "早库存单元",
        "evening_file_hint": "晚库存单元",
    },
    "simulation": {
        "default_batch_no": "ORDER_WAVE_2025-07-01",
        "default_initial_snapshot_id": "2025-07-01-morning",
        "default_evening_snapshot_id": "2025-07-01-evening",
        "default_strategy": "ai",
        "default_active_station_limit": 16,
        "operation_gap_seconds": 4.139,
        "history_actual_operation_gap_seconds": 5.824,
        "history_sku_average_operation_gap_seconds": 9.415,
    },
    "system": {
        "num_stations": 16,
        "deadline_seconds": 30600.0,
        "max_orders_per_station": 2,
        "max_boxes_per_station": 8,
    },
    "model": {
        "active_model": "ppo_masking_model_v6.zip",
        "model_dir": "output/models",
        "checkpoint_dir": "scenarios/order_picking/checkpoints_v6",
        "tensorboard_dir": "scenarios/order_picking/ppo_tensorboard_logs_v6",
    },
    "training": {
        "total_timesteps": 3_000_000,
        "initial_learning_rate": 3e-4,
        "final_learning_rate": 3e-5,
        "n_steps": 4000,
        "batch_size": 1000,
        "ent_coef": 0.005,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_app_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG
    if tomllib is None:
        return DEFAULT_CONFIG
    with CONFIG_PATH.open("rb") as fp:
        loaded = tomllib.load(fp)
    return _deep_merge(DEFAULT_CONFIG, loaded)


def get_config_value(section: str, key: str, default: Any = None) -> Any:
    return load_app_config().get(section, {}).get(key, default)


def project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
