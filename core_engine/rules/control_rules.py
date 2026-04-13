# 文件路径: core_engine/rules/control_rules.py
import numpy as np
from typing import List, Any

class ControlRules:
    """
    【通用规则库：产线控制与安检法则】
    积木特性：负责红线控制、异常拦截和准入校验。
    在强化学习中，它生成动作掩码 (Action Masks)；在传统仿真中，它是发车推杆的物理锁。
    """

    @staticmethod
    def generate_capacity_masks(stations: List[Any], incoming_qty: int = 1) -> np.ndarray:
        """
        【红线控制】：生成容量准入掩码 (防爆仓安检门)
        判断每个站台当前的负载加上即将到来的货物，是否会超出其物理容量上限。
        参数:
            - stations: 站台对象列表 (传入我们在 resource_models 里定义的积木)
            - incoming_qty: 即将发往该站台的实体数量
        返回:
            - 布尔数组 (True表示允许进件，False表示已爆仓禁止进件)
        """
        num_stations = len(stations)
        masks = np.ones(num_stations, dtype=bool)
        
        for i, station in enumerate(stations):
            # 🦆 鸭子类型检测：只要传入的模型有当前负载和容量上限，就能做安检
            if hasattr(station, 'current_load') and hasattr(station, 'capacity'):
                if station.current_load + incoming_qty > station.capacity:
                    masks[i] = False
            # 兼容字典格式（如果在极简环境中用字典记录状态）
            elif isinstance(station, dict) and 'load' in station and 'capacity' in station:
                if station['load'] + incoming_qty > station['capacity']:
                    masks[i] = False

        # 🚨 RL 框架防崩溃兜底机制 (极其重要) 🚨
        # 在极端堵车情况下，如果 16 个站台全部爆仓，masks 会全为 False。
        # sb3_contrib 的 MaskablePPO 遇到全 False 会直接引发底层的概率计算除以 0 崩溃！
        # 物理世界的处理是“停机死等”，但在单步决策矩阵中，我们必须强制开放所有动作，
        # 并让环境 (Environment) 通过物理时间的暴增来给予 AI 巨额扣分。
        if not np.any(masks):
            return np.ones(num_stations, dtype=bool)
            
        return masks

    @staticmethod
    def check_global_starvation(stations: List[Any]) -> bool:
        """
        【状态探针】：检测是否全线饥饿 (所有站台都处于空闲/无货状态)
        适用场景：可用于触发仓库的“批量盲发”逻辑，或者在仿真时用来加速时钟跳跃。
        """
        for station in stations:
            if hasattr(station, 'current_load') and station.current_load > 0:
                return False
        return True