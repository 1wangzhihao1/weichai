# 文件路径: core_engine/models/resource_model.py

import simpy
import numpy as np

# =====================================================================
# [第一部分] 现有模型：固定站台 
# =====================================================================

class LogicalStation:
    """供强化学习矩阵高速推演使用的逻辑站台"""
    def __init__(self, station_id, capacity):
        self.station_id = station_id
        self.capacity = capacity
        self.box_finish_times = []
        self.free_at = 0.0

    @property
    def current_load(self):
        return len(self.box_finish_times)

    def update_load_at_time(self, current_time):
        self.box_finish_times = [t for t in self.box_finish_times if t > current_time]

    def reset(self):
        self.box_finish_times = []
        self.free_at = 0.0


class SimpyStation:
    """
    供连续时间沙盘高保真推演的物理站台 (已升级柔性抗扰动能力)
    具备缓存排队死等、独立加工耗时、以及基于 simpy.Interrupt 的故障抢修自愈能力
    """
    def __init__(self, env: simpy.Environment, station_id: int, capacity: int, logger=None):
        self.env = env
        self.station_id = station_id
        self.capacity = capacity
        self.logger = logger
        
        # 🌟 核心升级 1：使用 Store 替代 Resource 管理缓存区，便于后台协程独立拉取，完美实现死等
        self.buffer = simpy.Store(env, capacity=capacity)
        # 机床核心加工资源
        self.machine = simpy.Resource(env, capacity=1)
        
        self.processed_boxes = 0
        self.in_transit = 0 
        
        # 故障状态标识
        self.is_broken = False
        
        # 🌟 核心升级 2：启动站台后台持续运行的加工协程守护进程
        self.process_coroutine = self.env.process(self._run_process())

    @property
    def total_future_load(self):
        """获取绝对真实负载：在途滑行的 + 门口排队的 + 正在干活的"""
        # len(self.buffer.items) 是在排队的，self.machine.count 是在机床里的
        return self.in_transit + len(self.buffer.items) + self.machine.count

    def process_box(self, box_id: str, p_time: float, travel_time: float, entity_type: int):
        """
        前端入口协程：只负责传送带物理滑行与投递入列。
        一旦投递进缓存区，后续生死由 _run_process 接管。
        """
        # 1. 传送带物理滑行阶段
        self.in_transit += 1
        yield self.env.timeout(travel_time) # 真实空间位移延迟
        self.in_transit -= 1
        
        # 2. 到达站台，开始申请进站坑位
        if self.logger:
            self.logger.log_event(self.env.now, box_id, "enter_buffer", self.station_id)
            
        # 打包箱子数据
        box_data = {
            "box_id": box_id,
            "p_time": p_time,
            "entity_type": entity_type
        }
        
        # 3. 投放入物理缓存区。如果坑位满了，此 put 操作会自动阻塞挂起 (物理死等，不穿模)
        yield self.buffer.put(box_data)

    def _run_process(self):
        """后台核心协程：持续从缓存区取货并加工 (已修复空闲宕机崩溃Bug)"""
        while True:
            # ==========================================
            # 🛡️ 终极修复 1：给机器的“空闲等货”状态套上防雷罩
            # ==========================================
            try:
                # 机器闲置时如果被触发故障，会在这个等待环节被强行打断
                box = yield self.buffer.get()
            except simpy.Interrupt as interrupt:
                self.is_broken = True
                repair_time = interrupt.cause if interrupt.cause else 600
                if self.logger:
                    self.logger.log_event(self.env.now, "STATION", "breakdown", self.station_id, {"msg": "待机时突发故障"})
                
                # 模拟抢修时间流逝
                yield self.env.timeout(repair_time)
                
                self.is_broken = False
                if self.logger:
                    self.logger.log_event(self.env.now, "STATION", "fixed", self.station_id, {"msg": "抢修完成，继续待命"})
                
                # 核心机制：修好后，直接进入下一个 while 循环，重新去等货
                continue 
            
            # 2. 拿到货了，开始申请工人/机床加工
            with self.machine.request() as worker_req:
                yield worker_req
                
                if self.logger:
                    self.logger.log_event(self.env.now, box['box_id'], "start_process", self.station_id)
                
                remaining_time = box['p_time']
                
                # 3. 循环处理直到加工完成 (期间可能遭遇多次打断)
                while remaining_time > 0:
                    try:
                        start_time = self.env.now
                        # 正常耗时加工
                        yield self.env.timeout(remaining_time)
                        remaining_time = 0 # 顺利完成
                        
                    except simpy.Interrupt as interrupt:
                        # 🛡️ 修复 2：保留原有的“加工中途”被打断的冻结逻辑
                        self.is_broken = True
                        repair_time = interrupt.cause if interrupt.cause else 600 
                        
                        worked_time = self.env.now - start_time
                        remaining_time -= worked_time # 冻结并精准记录剩余没加工完的时间
                        
                        if self.logger:
                            self.logger.log_event(self.env.now, "STATION", "breakdown", self.station_id, {"msg": "加工中突发故障"})
                        
                        # 模拟抢修过程
                        yield self.env.timeout(repair_time)
                        
                        # 抢修完成，恢复状态
                        self.is_broken = False
                        if self.logger:
                            self.logger.log_event(self.env.now, "STATION", "fixed", self.station_id, {"msg": "抢修完成，继续加工"})
                        # while 循环继续，丝滑接着加工刚才剩下的 remaining_time
                
                # 彻底加工完成
                self.processed_boxes += 1
                if self.logger:
                    self.logger.log_event(self.env.now, box['box_id'], "end_process", self.station_id)

    def trigger_breakdown(self, repair_time: float = 600):
        """外部触发站台故障的强制钩子"""
        # 如果当前机床正常，且后台协程处于活跃状态，则强行打断它！
        if not self.is_broken and self.process_coroutine and self.process_coroutine.is_alive:
            self.process_coroutine.interrupt(cause=repair_time)


# =====================================================================
# [第二部分] 新增模型：通用动态物流资源 (完全保留)
# =====================================================================

class AGVRobot:
    """【新增】通用 AGV/AMR 移动机器人模型"""
    def __init__(self, env: simpy.Environment, agv_id: str, speed: float, battery_capacity: float = 100.0):
        self.env = env
        self.agv_id = agv_id
        self.speed = speed
        self.battery = simpy.Container(env, capacity=battery_capacity, init=battery_capacity)
        self.resource = simpy.Resource(env, capacity=1)
        self.total_distance = 0.0

    def move_and_deliver(self, distance: float, load_time: float, unload_time: float):
        with self.resource.request() as req:
            yield req
            yield self.env.timeout(load_time)
            travel_time = distance / self.speed
            yield self.env.timeout(travel_time)
            power_consumed = distance * 0.1
            if self.battery.level > power_consumed:
                yield self.battery.get(power_consumed)
            self.total_distance += distance
            yield self.env.timeout(unload_time)


class ConveyorBelt:
    """【新增】通用连续传送带模型"""
    def __init__(self, env: simpy.Environment, length: float, speed: float, capacity: int):
        self.env = env
        self.length = length
        self.speed = speed
        self.travel_time = length / speed
        self.slots = simpy.Resource(env, capacity=capacity)

    def transport_item(self, item_id: str):
        with self.slots.request() as req:
            yield req
            yield self.env.timeout(self.travel_time)


class ReliableMachine:
    """【高级模型】带随机故障与维修机制的设备模型"""
    def __init__(self, env: simpy.Environment, machine_id: str, capacity: int, mtbf: float, mttr: float):
        self.env = env
        self.machine_id = machine_id
        self.resource = simpy.Resource(env, capacity=capacity)
        self.mtbf = mtbf
        self.mttr = mttr
        self.broken = False
        self.env.process(self._breakdown_process())

    def _breakdown_process(self):
        while True:
            yield self.env.timeout(np.random.exponential(self.mtbf))
            self.broken = True
            print(f"[⏱️ {self.env.now:.1f}s] ⚠️ 设备 {self.machine_id} 发生突发故障！")
            repair_time = np.random.exponential(self.mttr)
            yield self.env.timeout(repair_time)
            self.broken = False
            print(f"[⏱️ {self.env.now:.1f}s] 🔧 设备 {self.machine_id} 维修完成，恢复运行。")

    def process_item(self, item_id: str, p_time: float):
        with self.resource.request() as req:
            yield req
            while self.broken:
                yield self.env.timeout(1.0)
            yield self.env.timeout(p_time)


class SetupStation:
    """【高级模型】带有换模/准备时间的工位模型"""
    def __init__(self, env: simpy.Environment, station_id: str):
        self.env = env
        self.station_id = station_id
        self.worker = simpy.Resource(env, capacity=1)
        self.current_part_type = None

    def process_with_setup(self, item_id: str, p_time: float, part_type: int, setup_time: float = 15.0):
        with self.worker.request() as req:
            yield req
            if self.current_part_type is not None and self.current_part_type != part_type:
                yield self.env.timeout(setup_time)
            self.current_part_type = part_type
            yield self.env.timeout(p_time)