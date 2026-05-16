


# # 文件路径: core_engine/models/resource_model.py

# import simpy
# import numpy as np

# # =====================================================================
# # [第一部分] 现有模型：固定站台 
# # =====================================================================

# class LogicalStation:
#     """供强化学习矩阵高速推演使用的逻辑站台"""
#     def __init__(self, station_id, capacity):
#         self.station_id = station_id
#         self.capacity = capacity
#         self.box_finish_times = []
#         self.free_at = 0.0

#     @property
#     def current_load(self):
#         return len(self.box_finish_times)

#     def update_load_at_time(self, current_time):
#         self.box_finish_times = [t for t in self.box_finish_times if t > current_time]

#     def reset(self):
#         self.box_finish_times = []
#         self.free_at = 0.0


# class SimpyStation:
#     """
#     供连续时间沙盘高保真推演的物理站台 (纯净高效排产版)
#     具备订单级连续加工锁与订单级死等排队能力。
#     """
#     def __init__(self, env: simpy.Environment, station_id: int, capacity: int, logger=None):
#         self.env = env
#         self.station_id = station_id
#         self.logger = logger
        
#         # 🌟 核心升级 1：安检门由外部按“最多2个订单”的红线严格控制，内部使用无限量 Store 防止报错
#         self.buffer = simpy.Store(env)
#         # 机床核心加工资源 (单线程绝对锁死，保证同一个订单的 4 种零件首尾相连被处理)
#         self.machine = simpy.Resource(env, capacity=1)
        
#         self.processed_boxes = 0
        
#         # 🌟 核心升级 2：废除箱子统计，建立【订单级】在途追踪账本！
#         # 格式为 {"订单A": 4(箱), "订单B": 2(箱)}
#         self.active_orders = {}
        
#         # 启动后台机床不间断循环
#         self.process_coroutine = self.env.process(self._run_process())

#     @property
#     def active_order_count(self):
#         """🌟 返回当前这台机器手头正在负责的所有订单数（含排队 + 正在切削）"""
#         return len(self.active_orders)

#     def process_box(self, box_id: str, order_id: str, p_time: float, travel_time: float, entity_type: int):
#         """
#         前端入口协程：处理物理发车。
#         外部（server.py）连发 4 个箱子时，会在这里立刻登记入账！
#         """
#         # 1. 履带发车的瞬间，立刻在这台机器的账本上记下这个订单的到来
#         if order_id not in self.active_orders:
#             self.active_orders[order_id] = 0
#         self.active_orders[order_id] += 1
        
#         # 2. 传送带物理滑行阶段（延迟）
#         yield self.env.timeout(travel_time) 
        
#         # 3. 到达站台物理缓存区
#         if self.logger:
#             self.logger.log_event(self.env.now, box_id, "enter_buffer", self.station_id)
            
#         box_data = {
#             "box_id": box_id,
#             "order_id": order_id, 
#             "p_time": p_time,
#             "entity_type": entity_type
#         }
#         yield self.buffer.put(box_data)

#     def _run_process(self):
#         """后台纯净版协程：不间断从缓存区取货加工，没有宕机干扰，只拼效率"""
#         while True:
#             # 1. 取货排队死等
#             box = yield self.buffer.get()
#             o_id = box['order_id']
            
#             # 2. 申请刀具锁死加工
#             with self.machine.request() as worker_req:
#                 yield worker_req
                
#                 if self.logger:
#                     self.logger.log_event(self.env.now, box['box_id'], "start_process", self.station_id)
                
#                 # 3. 真实物理消耗时间
#                 yield self.env.timeout(box['p_time'])
                
#                 # 4. 加工完成
#                 self.processed_boxes += 1
#                 if self.logger:
#                     self.logger.log_event(self.env.now, box['box_id'], "end_process", self.station_id)
                
#                 # 🌟 5. 从账本里精准销账！当前零件箱完工，减 1
#                 self.active_orders[o_id] -= 1
                
#                 # 当这个订单的 4 个箱子（或 2、3个）全部在机床里加工完毕，清零除名！
#                 # 此时该站台的 active_order_count 才会下降，外部履带才能被放行塞入下一个订单！
#                 if self.active_orders[o_id] <= 0:
#                     del self.active_orders[o_id]


# # =====================================================================
# # [第二部分] 新增模型：通用动态物流资源 (完全保留防误删)
# # =====================================================================

# class AGVRobot:
#     """【新增】通用 AGV/AMR 移动机器人模型"""
#     def __init__(self, env: simpy.Environment, agv_id: str, speed: float, battery_capacity: float = 100.0):
#         self.env = env
#         self.agv_id = agv_id
#         self.speed = speed
#         self.battery = simpy.Container(env, capacity=battery_capacity, init=battery_capacity)
#         self.resource = simpy.Resource(env, capacity=1)
#         self.total_distance = 0.0

#     def move_and_deliver(self, distance: float, load_time: float, unload_time: float):
#         with self.resource.request() as req:
#             yield req
#             yield self.env.timeout(load_time)
#             travel_time = distance / self.speed
#             yield self.env.timeout(travel_time)
#             power_consumed = distance * 0.1
#             if self.battery.level > power_consumed:
#                 yield self.battery.get(power_consumed)
#             self.total_distance += distance
#             yield self.env.timeout(unload_time)

# class ConveyorBelt:
#     """【新增】通用连续传送带模型"""
#     def __init__(self, env: simpy.Environment, length: float, speed: float, capacity: int):
#         self.env = env
#         self.length = length
#         self.speed = speed
#         self.travel_time = length / speed
#         self.slots = simpy.Resource(env, capacity=capacity)

#     def transport_item(self, item_id: str):
#         with self.slots.request() as req:
#             yield req
#             yield self.env.timeout(self.travel_time)

# class SetupStation:
#     """【高级模型】带有换模/准备时间的工位模型"""
#     def __init__(self, env: simpy.Environment, station_id: str):
#         self.env = env
#         self.station_id = station_id
#         self.worker = simpy.Resource(env, capacity=1)
#         self.current_part_type = None

#     def process_with_setup(self, item_id: str, p_time: float, part_type: int, setup_time: float = 15.0):
#         with self.worker.request() as req:
#             yield req
#             if self.current_part_type is not None and self.current_part_type != part_type:
#                 yield self.env.timeout(setup_time)
#             self.current_part_type = part_type
#             yield self.env.timeout(p_time)



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
    供连续时间沙盘高保真推演的物理站台 (纯净直线排产版)
    具备订单级连续加工锁与订单级死等排队能力。
    """
    def __init__(self, env: simpy.Environment, station_id: int, capacity: int, logger=None):
        self.env = env
        self.station_id = station_id
        self.logger = logger
        
        # 🌟 核心修复：废弃 Store 和守护进程，直接使用 Resource 锁，实现天然的物理死等排队！
        self.machine = simpy.Resource(env, capacity=1)
        self.processed_boxes = 0
        self.active_orders = {}

    @property
    def active_order_count(self):
        """返回当前这台机器手头正在负责的所有订单数"""
        return len(self.active_orders)

    def process_box(self, box_id: str, order_id: str, p_time: float, travel_time: float, entity_type: int):
        """
        全生命周期协程：滑行 -> 排队 -> 加工 -> 完工
        任何调用它的外部脚本，都会被强制绑定在这个时间轴上！
        """
        # 1. 履带发车，订单记账
        if order_id not in self.active_orders:
            self.active_orders[order_id] = 0
        self.active_orders[order_id] += 1
        
        # 2. 传送带物理滑行阶段（延迟）
        if travel_time > 0:
            yield self.env.timeout(travel_time) 
        
        # 3. 到达站台物理缓存区 (开始排队)
        if self.logger:
            self.logger.log_event(self.env.now, box_id, "enter_buffer", self.station_id)
            
        # 4. 申请刀具锁死加工 (这一步会自动阻塞，直到机床空闲，完美防止穿模)
        with self.machine.request() as worker_req:
            yield worker_req
            
            if self.logger:
                self.logger.log_event(self.env.now, box_id, "start_process", self.station_id)
            
            # 5. 真实物理消耗工艺时间！绝不会再出现 0 秒的情况！
            yield self.env.timeout(p_time)
            
            # 6. 加工完成
            self.processed_boxes += 1
            if self.logger:
                self.logger.log_event(self.env.now, box_id, "end_process", self.station_id)
            
            # 7. 从账本里精准销账！
            self.active_orders[order_id] -= 1
            if self.active_orders[order_id] <= 0:
                del self.active_orders[order_id]


# =====================================================================
# [第二部分] 新增模型：通用动态物流资源 (完全保留防误删)
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