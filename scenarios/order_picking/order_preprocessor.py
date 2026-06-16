from typing import Dict, List, Optional, Tuple


def _normalize_sku(value) -> str:
    return str(value or "").strip()


def _order_time_key(order: dict):
    return order.get("order_time") or order.get("sequence_no") or order.get("original_sequence") or 0


def _build_inventory_view(inventory_snapshot: Optional[dict]) -> Tuple[Dict[str, float], Dict[str, int]]:
    qty_by_sku: Dict[str, float] = {}
    unit_count_by_sku: Dict[str, int] = {}
    if not inventory_snapshot:
        return qty_by_sku, unit_count_by_sku

    for raw_sku, units in inventory_snapshot.get("sku_units", {}).items():
        sku = _normalize_sku(raw_sku)
        if not sku:
            continue
        live_units = []
        total_qty = 0.0
        for unit in units or []:
            qty = float(unit.get("remaining_qty", unit.get("qty", 0.0)) or 0.0)
            if qty <= 0:
                continue
            live_units.append(unit)
            total_qty += qty
        qty_by_sku[sku] = qty_by_sku.get(sku, 0.0) + total_qty
        unit_count_by_sku[sku] = unit_count_by_sku.get(sku, 0) + len(live_units)
    return qty_by_sku, unit_count_by_sku


def _build_inventory_units(inventory_snapshot: Optional[dict]) -> Dict[str, List[dict]]:
    units_by_sku: Dict[str, List[dict]] = {}
    if not inventory_snapshot:
        return units_by_sku

    for raw_sku, units in inventory_snapshot.get("sku_units", {}).items():
        sku = _normalize_sku(raw_sku)
        if not sku:
            continue
        units_by_sku[sku] = []
        for unit in units or []:
            qty = float(unit.get("remaining_qty", unit.get("qty", 0.0)) or 0.0)
            if qty <= 0:
                continue
            units_by_sku[sku].append(
                {
                    "remaining_qty": qty,
                    "available_at": float(unit.get("available_at", 0.0) or 0.0),
                    "unit_id": str(unit.get("unit_id", unit.get("load_unit_id", ""))).strip(),
                }
            )
        units_by_sku[sku].sort(key=lambda item: (item["available_at"], item["remaining_qty"], item["unit_id"]))
    return units_by_sku


def _order_demand(order: dict) -> Dict[str, float]:
    demand: Dict[str, float] = {}
    for box in order.get("boxes", []):
        sku = _normalize_sku(box.get("sku"))
        if not sku:
            continue
        demand[sku] = demand.get(sku, 0.0) + float(box.get("qty", 1.0) or 1.0)
    return demand


def _build_order_demand_view(orders: List[dict]) -> Tuple[Dict[str, float], Dict[str, int]]:
    total_demand_by_sku: Dict[str, float] = {}
    order_count_by_sku: Dict[str, int] = {}
    for order in orders:
        demand = _order_demand(order)
        for sku, qty in demand.items():
            total_demand_by_sku[sku] = total_demand_by_sku.get(sku, 0.0) + qty
            order_count_by_sku[sku] = order_count_by_sku.get(sku, 0) + 1
    return total_demand_by_sku, order_count_by_sku


def _scarcity_score(order: dict, qty_by_sku: Dict[str, float], unit_count_by_sku: Dict[str, int]) -> float:
    scores = []
    for sku, qty in _order_demand(order).items():
        available_qty = qty_by_sku.get(sku, 0.0)
        available_units = unit_count_by_sku.get(sku, 0)
        if available_qty <= 0 or available_units <= 0:
            scores.append(9999.0)
            continue
        scores.append((qty / available_qty) + (1.0 / available_units))
    return max(scores) if scores else 0.0


def _estimate_inventory_wait(orders: List[dict], inventory_snapshot: Optional[dict]) -> float:
    units_by_sku = _build_inventory_units(inventory_snapshot)
    if not units_by_sku:
        return 0.0

    dispatch_cursor = 0.0
    total_wait = 0.0
    for order in orders:
        for box in order.get("boxes", []):
            sku = _normalize_sku(box.get("sku"))
            qty = float(box.get("qty", 1.0) or 1.0)
            p_time = float(box.get("p_time", 0.0) or 0.0)
            units = units_by_sku.get(sku, [])
            enough_units = [unit for unit in units if unit["remaining_qty"] >= qty]
            if not enough_units:
                continue

            ready_units = [unit for unit in enough_units if unit["available_at"] <= dispatch_cursor]
            if ready_units:
                selected = min(
                    ready_units,
                    key=lambda unit: (unit["remaining_qty"] - qty, unit["available_at"], unit["unit_id"]),
                )
            else:
                selected = min(
                    enough_units,
                    key=lambda unit: (unit["available_at"], unit["remaining_qty"] - qty, unit["unit_id"]),
                )
                wait = selected["available_at"] - dispatch_cursor
                total_wait += wait
                dispatch_cursor = selected["available_at"]

            selected["remaining_qty"] -= qty
            selected["available_at"] = dispatch_cursor + p_time
            dispatch_cursor += 1.0

    return total_wait


def _order_inventory_score(order: dict, units_by_sku: Dict[str, List[dict]], cursor: float) -> Tuple[float, float, int, int, int]:
    waits = []
    shortage_count = 0
    tight_unit_count = 0
    for box in order.get("boxes", []):
        sku = _normalize_sku(box.get("sku"))
        qty = float(box.get("qty", 1.0) or 1.0)
        enough_units = [unit for unit in units_by_sku.get(sku, []) if unit["remaining_qty"] >= qty]
        if not enough_units:
            shortage_count += 1
            waits.append(0.0)
            continue

        if len(enough_units) <= 2:
            tight_unit_count += 1
        ready_units = [unit for unit in enough_units if unit["available_at"] <= cursor]
        if ready_units:
            waits.append(0.0)
        else:
            selected = min(enough_units, key=lambda unit: (unit["available_at"], unit["remaining_qty"] - qty, unit["unit_id"]))
            waits.append(max(0.0, selected["available_at"] - cursor))

    return (
        sum(waits),
        max(waits) if waits else 0.0,
        shortage_count,
        tight_unit_count,
        int(order.get("original_sequence", 0) or 0),
    )


def _consume_order_for_inventory_sequence(order: dict, units_by_sku: Dict[str, List[dict]], cursor: float) -> float:
    finish = cursor
    for box in order.get("boxes", []):
        sku = _normalize_sku(box.get("sku"))
        qty = float(box.get("qty", 1.0) or 1.0)
        p_time = float(box.get("p_time", 0.0) or 0.0)
        enough_units = [unit for unit in units_by_sku.get(sku, []) if unit["remaining_qty"] >= qty]
        if not enough_units:
            continue

        ready_units = [unit for unit in enough_units if unit["available_at"] <= cursor]
        if ready_units:
            selected = min(ready_units, key=lambda unit: (unit["remaining_qty"] - qty, unit["available_at"], unit["unit_id"]))
            start = cursor
        else:
            selected = min(enough_units, key=lambda unit: (unit["available_at"], unit["remaining_qty"] - qty, unit["unit_id"]))
            start = selected["available_at"]

        selected["remaining_qty"] -= qty
        selected["available_at"] = start + p_time
        finish = max(finish, start + p_time)

    return max(cursor + 1.0, cursor * 0.98 + finish * 0.02)


def inventory_aware_order_sequence(
    orders: List[dict],
    inventory_snapshot: Optional[dict],
    window_size: int = 10,
) -> List[dict]:
    units_by_sku = _build_inventory_units(inventory_snapshot)
    if not units_by_sku:
        return list(orders)

    remaining = sorted(orders, key=lambda order: order.get("original_sequence", 0))
    output = []
    cursor = 0.0

    while remaining:
        window = remaining[: max(1, min(window_size, len(remaining)))]
        pick_idx, order = min(
            enumerate(window),
            key=lambda item: _order_inventory_score(item[1], units_by_sku, cursor),
        )
        output.append(order)
        remaining.pop(pick_idx)
        cursor = _consume_order_for_inventory_sequence(order, units_by_sku, cursor)

    return output


def _scarce_skus_for_order(
    order: dict,
    qty_by_sku: Dict[str, float],
    unit_count_by_sku: Dict[str, int],
    total_demand_by_sku: Optional[Dict[str, float]] = None,
    order_count_by_sku: Optional[Dict[str, int]] = None,
    scarce_unit_threshold: int = 3,
    scarce_demand_ratio: float = 0.25,
    daily_demand_ratio: float = 0.70,
) -> set:
    total_demand_by_sku = total_demand_by_sku or {}
    order_count_by_sku = order_count_by_sku or {}
    scarce = set()
    for sku, qty in _order_demand(order).items():
        available_qty = qty_by_sku.get(sku, 0.0)
        available_units = unit_count_by_sku.get(sku, 0)
        daily_demand = total_demand_by_sku.get(sku, qty)
        daily_order_count = order_count_by_sku.get(sku, 1)
        if available_qty <= 0 or available_units <= 0:
            scarce.add(sku)
            continue

        order_need_is_large = (qty / available_qty) >= scarce_demand_ratio
        daily_need_is_tight = daily_order_count > 1 and (daily_demand / available_qty) >= daily_demand_ratio
        unit_contention = daily_order_count > available_units and available_units <= scarce_unit_threshold
        daily_qty_shortage = daily_demand > available_qty

        if order_need_is_large or daily_need_is_tight or unit_contention or daily_qty_shortage:
            scarce.add(sku)
    return scarce


def preprocess_orders(
    orders: List[dict],
    inventory_snapshot: Optional[dict] = None,
    spread_scarce_skus: bool = True,
    exclude_shortage: bool = True,
) -> dict:
    """Use inventory only before the RL environment: classify shortage orders and spread scarce SKU requests."""
    qty_by_sku, unit_count_by_sku = _build_inventory_view(inventory_snapshot)
    has_inventory = bool(qty_by_sku)
    sorted_orders = sorted(orders, key=_order_time_key)
    total_demand_by_sku, order_count_by_sku = _build_order_demand_view(sorted_orders)
    processable = []
    shortage = []
    observed_scarce_skus = set()
    spread_accepted = False
    wait_estimate_before = 0.0
    wait_estimate_after = 0.0

    for idx, order in enumerate(sorted_orders):
        copied = dict(order)
        copied.setdefault("original_sequence", idx)
        demand = _order_demand(copied)
        shortage_skus = []
        if has_inventory:
            shortage_skus = [
                sku for sku, qty in demand.items()
                if qty_by_sku.get(sku, 0.0) < qty or unit_count_by_sku.get(sku, 0) <= 0
            ]

        if shortage_skus:
            shortage_order = {
                **copied,
                "exception_reason": "initial_inventory_shortage",
                "shortage_skus": shortage_skus,
                "scarce_skus": sorted(shortage_skus),
                "scarcity_score": 9999.0,
            }
            observed_scarce_skus.update(shortage_skus)
            shortage.append(shortage_order)
            if exclude_shortage:
                continue
            processable.append(shortage_order)
            continue

        copied["scarcity_score"] = _scarcity_score(copied, qty_by_sku, unit_count_by_sku) if has_inventory else 0.0
        scarce_skus = (
            _scarce_skus_for_order(
                copied,
                qty_by_sku,
                unit_count_by_sku,
                total_demand_by_sku=total_demand_by_sku,
                order_count_by_sku=order_count_by_sku,
            )
            if has_inventory
            else set()
        )
        copied["scarce_skus"] = sorted(scarce_skus)
        observed_scarce_skus.update(scarce_skus)
        processable.append(copied)

    before_spread_conflicts = count_adjacent_scarce_conflicts(processable)
    before_primary_conflicts = count_adjacent_primary_conflicts(processable)
    if spread_scarce_skus and has_inventory:
        original_processable = list(processable)
        candidate = inventory_aware_order_sequence(processable, inventory_snapshot, window_size=10)
        wait_estimate_before = _estimate_inventory_wait(original_processable, inventory_snapshot)
        wait_estimate_after = _estimate_inventory_wait(candidate, inventory_snapshot)
        processable = candidate
        spread_accepted = processable != original_processable
    after_spread_conflicts = count_adjacent_scarce_conflicts(processable)
    after_primary_conflicts = count_adjacent_primary_conflicts(processable)

    scarce_skus = {
        sku for sku, count in unit_count_by_sku.items()
        if count > 0 and count <= 2
    }
    return {
        "processable_orders": processable,
        "shortage_orders": shortage,
        "preprocess_stats": {
            "input_order_count": len(orders),
            "processable_order_count": len(processable),
            "shortage_order_count": len(shortage),
            "reordered_count": sum(1 for i, o in enumerate(processable) if o.get("original_sequence") != i),
            "moved_order_count": sum(
                1
                for previous, current in zip(sorted(processable, key=lambda o: o.get("original_sequence", 0)), processable)
                if previous.get("order_id") != current.get("order_id")
            ),
            "scarce_sku_count": len(observed_scarce_skus),
            "inventory_low_unit_sku_count": len(scarce_skus),
            "inventory_sku_count": len(qty_by_sku),
            "inventory_wait_estimate_before": round(float(wait_estimate_before), 3),
            "inventory_wait_estimate_after": round(float(wait_estimate_after), 3),
            "spread_accepted": spread_accepted,
            "adjacent_scarce_conflicts_before": before_spread_conflicts,
            "adjacent_scarce_conflicts_after": after_spread_conflicts,
            "adjacent_primary_conflicts_before": before_primary_conflicts,
            "adjacent_primary_conflicts_after": after_primary_conflicts,
        },
    }


def spread_orders_by_scarce_sku(orders: List[dict], window_size: int = 8, recent_size: int = 3) -> List[dict]:
    remaining = sorted(orders, key=lambda o: o.get("original_sequence", 0))
    output = []
    recent_scarce_skus = []
    recent_primary_skus = []

    while remaining:
        previous_scarce = recent_scarce_skus[-1] if recent_scarce_skus else set()
        recent = set().union(*recent_scarce_skus[-recent_size:]) if recent_scarce_skus else set()
        last_primary = recent_primary_skus[-1] if recent_primary_skus else ""

        first_order = remaining[0]
        first_scarce = set(first_order.get("scarce_skus", []))
        first_primary = primary_sku(first_order)
        first_conflicts = bool(first_scarce & previous_scarce) or bool(first_primary and first_primary == last_primary)

        pick_idx = 0
        if first_conflicts:
            window = remaining[: max(1, window_size)]

            def candidate_score(item):
                idx, order = item
                scarce_skus = set(order.get("scarce_skus", []))
                primary = primary_sku(order)
                is_shortage = 1 if order.get("exception_reason") else 0
                same_primary = 1 if primary and primary == last_primary else 0
                immediate_overlap = len(scarce_skus & previous_scarce)
                recent_overlap = len(scarce_skus & recent)
                return (is_shortage, same_primary, immediate_overlap, recent_overlap, idx)

            best_idx, best_order = min(enumerate(window), key=candidate_score)
            best_scarce = set(best_order.get("scarce_skus", []))
            best_primary = primary_sku(best_order)
            best_conflicts = bool(best_scarce & previous_scarce) or bool(best_primary and best_primary == last_primary)
            if not best_conflicts and not best_order.get("exception_reason"):
                pick_idx = best_idx

        order = remaining.pop(pick_idx)
        output.append(order)
        recent_scarce_skus.append(set(order.get("scarce_skus", [])))
        recent_primary_skus.append(primary_sku(order))

    return output


def primary_sku(order: dict) -> str:
    boxes = order.get("boxes", [])
    if not boxes:
        return ""
    return _normalize_sku(max(boxes, key=lambda b: float(b.get("qty", 1.0) or 1.0)).get("sku"))


def count_adjacent_scarce_conflicts(orders: List[dict]) -> int:
    conflicts = 0
    prev = set()
    for order in orders:
        current = set(order.get("scarce_skus", []))
        if prev and current and (prev & current):
            conflicts += 1
        prev = current
    return conflicts


def count_adjacent_primary_conflicts(orders: List[dict]) -> int:
    conflicts = 0
    prev = ""
    for order in orders:
        current = primary_sku(order)
        if prev and current and prev == current:
            conflicts += 1
        prev = current
    return conflicts
