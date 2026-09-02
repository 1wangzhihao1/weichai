import os
import sys
from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional

import numpy as np

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scenarios.order_picking.config import Config
from scenarios.order_picking.rl_environment import PickingEnv


class DispatchStrategy(ABC):
    name = "base"

    @abstractmethod
    def dispatch(self, orders: List[dict], active_station_limit: int = Config.NUM_STATIONS, **kwargs) -> List[dict]:
        raise NotImplementedError


def _enabled_mask(active_station_limit: int) -> np.ndarray:
    station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
    return np.array([True] * station_limit + [False] * (Config.NUM_STATIONS - station_limit), dtype=bool)


def _make_env(orders: List[dict]) -> PickingEnv:
    env = PickingEnv(dataset_type="test")
    env.unwrapped.set_orders(orders, episode_length=len(orders))
    return env


class AiDispatchStrategy(DispatchStrategy):
    name = "ai"

    def dispatch(self, orders: List[dict], active_station_limit: int = Config.NUM_STATIONS, **kwargs) -> List[dict]:
        model = kwargs.get("model")
        if model is None:
            raise ValueError("AI dispatch requires a loaded model")

        env = _make_env(orders)
        obs, _ = env.reset(seed=int(kwargs.get("seed", 999)))
        enabled = _enabled_mask(active_station_limit)
        assignments = []
        done = False
        sequence = 1
        while not done:
            current_order = env.unwrapped.real_world_orders[env.unwrapped.current_step]
            try:
                env_mask = env.unwrapped.action_masks()
            except AttributeError:
                env_mask = np.ones(Config.NUM_STATIONS, dtype=bool)
            mask = np.logical_and(enabled, env_mask)
            if not np.any(mask):
                mask = enabled
            action = int(model.predict(obs, action_masks=mask, deterministic=True)[0])
            assignments.append(
                {
                    "sequence": sequence,
                    "order_id": current_order["order_id"],
                    "target_station": action + 1,
                }
            )
            obs, _, done, _, _ = env.step(action)
            sequence += 1
        return assignments


class RoundRobinDispatchStrategy(DispatchStrategy):
    name = "round_robin"

    def dispatch(self, orders: List[dict], active_station_limit: int = Config.NUM_STATIONS, **kwargs) -> List[dict]:
        station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
        return [
            {
                "sequence": idx,
                "order_id": order["order_id"],
                "target_station": ((idx - 1) % station_limit) + 1,
            }
            for idx, order in enumerate(orders, start=1)
        ]


class RandomDispatchStrategy(DispatchStrategy):
    name = "random"

    def dispatch(self, orders: List[dict], active_station_limit: int = Config.NUM_STATIONS, **kwargs) -> List[dict]:
        station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
        rng = np.random.default_rng(int(kwargs.get("seed", 20260729)))
        return [
            {
                "sequence": idx,
                "order_id": order["order_id"],
                "target_station": int(rng.integers(1, station_limit + 1)),
            }
            for idx, order in enumerate(orders, start=1)
        ]


class HistoricalDispatchStrategy(DispatchStrategy):
    name = "history"

    def dispatch(self, orders: List[dict], active_station_limit: int = Config.NUM_STATIONS, **kwargs) -> List[dict]:
        assignments = kwargs.get("historical_assignments")
        if assignments:
            return list(assignments)
        result = []
        station_limit = max(1, min(int(active_station_limit or Config.NUM_STATIONS), Config.NUM_STATIONS))
        for idx, order in enumerate(orders, start=1):
            station = int(order.get("historical_station", 1))
            station = max(1, min(station, station_limit))
            result.append({"sequence": idx, "order_id": order["order_id"], "target_station": station})
        return result


STRATEGY_REGISTRY: Dict[str, DispatchStrategy] = {
    "ai": AiDispatchStrategy(),
    "random": RandomDispatchStrategy(),
    "round_robin": RoundRobinDispatchStrategy(),
    "history": HistoricalDispatchStrategy(),
    "history_actual": HistoricalDispatchStrategy(),
    "history_sku_avg": HistoricalDispatchStrategy(),
    "history_part_master": HistoricalDispatchStrategy(),
}


def get_dispatch_strategy(strategy: str) -> DispatchStrategy:
    key = (strategy or "ai").lower()
    if key not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported dispatch strategy: {strategy}")
    return STRATEGY_REGISTRY[key]


def dispatch_orders(
    orders: List[dict],
    strategy: str,
    active_station_limit: int = Config.NUM_STATIONS,
    **kwargs,
) -> List[dict]:
    return get_dispatch_strategy(strategy).dispatch(
        orders,
        active_station_limit=active_station_limit,
        **kwargs,
    )
