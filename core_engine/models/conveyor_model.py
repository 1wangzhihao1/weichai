# 文件路径: core_engine/models/conveyor_model.py
import simpy

class ConveyorModel:
    """
    【通用模型：线性传输带 / AGV 单向导轨】
    积木特性：一维物理空间的绝对抽象。
    只负责定义空间尺度和运动学参数，提供精准的时间流逝推演。
    """
    def __init__(self, env: simpy.Environment, conveyor_id: str, length: float, speed: float):
        self.env = env
        self.conveyor_id = conveyor_id
        
        # 核心物理参数
        self.length = length
        self.speed = speed
        
        # 💡 架构师预留位：如果你未来需要模拟整条产线的“承重上限”或“电机过载”
        # self.motor_capacity = simpy.Resource(env, capacity=100) 

    def calculate_travel_time(self, start_pos: float, end_pos: float) -> float:
        """
        【物理引擎测算】：计算两点之间的绝对匀速滑行时间。
        不管外界怎么调度，物理定律不会骗人。
        """
        if self.speed <= 0:
            raise ValueError(f"[{self.conveyor_id}] 传送带速度必须大于 0！")
            
        distance = abs(end_pos - start_pos)
        
        # 🚧 物理防穿模边界：不能算出比传送带本身还长的距离
        if distance > self.length:
            raise ValueError(f"[{self.conveyor_id}] 致命越界：位移距离 ({distance}m) 超出传送带物理总长 ({self.length}m)！")
            
        return distance / self.speed

    def transport_entity(self, start_pos: float, end_pos: float):
        """
        【标准作业流】：让实体在皮带上真正“动”起来 (SimPy 进程)
        外部调度代码只需要 yield 这个方法，时间就会在沙盘中真实流逝。
        """
        travel_time = self.calculate_travel_time(start_pos, end_pos)
        
        # 模拟物理时间流逝
        yield self.env.timeout(travel_time)