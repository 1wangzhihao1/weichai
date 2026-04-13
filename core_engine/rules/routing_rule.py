# 文件路径: core_engine/rules/routing_rules.py
import math
from typing import List

class RoutingRules:
    """
    【通用规则库：物理运动与路由法则】
    积木特性：提供纯粹的数学与物理计算支持，没有任何业务属性。
    无论是简单的匀速直线，还是带加减速的复杂运动，全天下所有的位移计算都在这里。
    """

    @staticmethod
    def calculate_uniform_time(distance: float, speed: float) -> float:
        """
        【基础物理法则】：绝对匀速直线运动耗时
        适用场景：理想状态下的传送带、无视起步刹车的理论计算。
        """
        if speed <= 0:
            raise ValueError("速度必须严格大于 0！")
        return distance / speed

    @staticmethod
    def calculate_network_travel_time(segments: List[float], speed: float) -> float:
        """
        【复合路由法则】：多段路径的总耗时计算
        适用场景：主线 + 支线 + 爬坡等多段折线路径的联合计算。
        外部调用示例：RoutingRules.calculate_network_travel_time([d_main, d_branch], speed)
        """
        total_distance = sum(segments)
        return RoutingRules.calculate_uniform_time(total_distance, speed)

    @staticmethod
    def calculate_kinematic_time(distance: float, max_speed: float, acceleration: float) -> float:
        """
        【高级物理法则】：带加减速的真实运动学计算
        适用场景：给未来预留的后门！如果甲方要求上 AGV 小车，或者要求模拟电机真实的启动刹车延迟。
        包含匀加速起步和匀减速刹车的物理测算。
        """
        if distance <= 0: 
            return 0.0
        if max_speed <= 0 or acceleration <= 0:
            raise ValueError("最大速度和加速度必须严格大于 0！")

        # 达到最大速度所需的单边加速/减速距离 (S = V^2 / 2a)
        accel_dist = (max_speed ** 2) / (2 * acceleration)

        if distance >= 2 * accel_dist:
            # 距离足够长，运动轨迹为：加速段 -> 匀速段 -> 减速段
            accel_time = max_speed / acceleration
            uniform_dist = distance - 2 * accel_dist
            uniform_time = uniform_dist / max_speed
            return (2 * accel_time) + uniform_time
        else:
            # 距离太短，还没加速到最大速度就要开始刹车了：加速段 -> 减速段 (无匀速)
            peak_speed = math.sqrt(distance * acceleration)
            return 2 * (peak_speed / acceleration)