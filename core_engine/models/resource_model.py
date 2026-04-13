
# # 文件路径: core_engine/models/resource_models.py
# import simpy

# class LogicalStation:
#     """
#     【逻辑站台积木】：专供 RL (强化学习) 训练环境使用的轻量级站台。
#     特点：无物理阻塞锁，通过纯数学时间戳列表来瞬间推演负载状态，极大提升百万步的矩阵训练速度。
#     """
#     def __init__(self, station_id: int, capacity: int):
#         """
#         初始化逻辑站台
#         :param station_id: 站台的唯一数字编号 (例如: 0 到 15)
#         :param capacity: 站台缓存区的最大物理容量限制 (例如: 8 个箱子)
#         """
#         self.station_id = station_id
#         self.capacity = capacity
#         # 记录当前在站台内的所有箱子的【预计完工离开时间】
#         self.box_finish_times = []
#         # 记录站台工人（或机械臂）下一次彻底空闲的绝对时间戳
#         self.free_at = 0.0

#     def update_load_at_time(self, current_time: float):
#         """
#         时间流逝推演：根据当前给定的上帝时间，自动清理掉那些已经完工离开的箱子。
#         :param current_time: 当前正在推演的全局环境时间戳 (秒)
#         """
#         # 只保留那些【完工时间】大于【当前时间】的箱子，其余的视为已经物理离开站台
#         self.box_finish_times = [ft for ft in self.box_finish_times if ft > current_time]
#         # 确保时间戳按从小到大的顺序严谨排列，方便后续取值和队列逻辑推算
#         self.box_finish_times.sort()
        
#     @property
#     def current_load(self) -> int:
#         """
#         获取当前站台缓存区内的真实占用数量。
#         :return: 当前队列中正在排队+正在加工的箱子总数量
#         """
#         return len(self.box_finish_times)
        
#     def reset(self):
#         """
#         重置站台状态，供强化学习环境在每个 Episode (回合) 开始时调用。
#         """
#         self.box_finish_times = []
#         self.free_at = 0.0


# class SimpyStation:
#     """
#     【物理站台积木】：专供 SimPy 连续时间物理沙盘与 3D 可视化验证使用的重型站台。
#     特点：包含极其严苛的物理互斥锁，真实模拟空间抢占和工人排队，彻底杜绝穿模和超载超限。
#     """
#     def __init__(self, env: simpy.Environment, station_id: int, capacity: int, logger=None):
#         """
#         初始化高保真物理站台
#         :param env: SimPy 的全局离散事件仿真环境 (Environment)
#         :param station_id: 站台的唯一数字编号 (例如: 0 到 15)
#         :param capacity: 站台排队缓存区的物理坑位上限 (如 8 个，通过 simpy.Resource 硬性限制)
#         :param logger: (可选) 场记员对象，如果传入则会自动在各个物理节点刻录 3D 动画需要的 JSON 日志
#         """
#         self.env = env
#         self.station_id = station_id
#         # 物理限制锁 1：排队区的坑位。最多同时容纳 capacity 个箱子，满了后继箱子必须在主线上死等
#         self.buffer_spots = simpy.Resource(env, capacity=capacity)
#         # 物理限制锁 2：工作台的机械臂/工人。永远只能有 1 个干活的资源，箱子必须挨个排队等待加工
#         self.worker = simpy.Resource(env, capacity=1)
#         # 日志刻录器探针
#         self.logger = logger
#         # 统计指标：该站台历史累计处理完成的箱子总数
#         self.processed_boxes = 0

#     def process_box(self, box_id: str, p_time: float, entity_type: int = 0):
#         """
#         【核心协程】物理分拣流水线逻辑：申请进站 -> 申请工人 -> 消耗时间加工 -> 完工释放坑位
#         :param box_id: 实体箱子的唯一标识符 (例如: 'ORD-001-P05')
#         :param p_time: 该箱子需要被加工的分拣物理耗时 (秒)
#         :param entity_type: 该箱子装载的零件种类 ID (供前端 3D 渲染特定颜色及工具使用)
#         """
#         # 步骤 1: 申请排队坑位 (如果坑位已满，协程会在此处物理挂起，直到有空位腾出)
#         with self.buffer_spots.request() as spot_req:
#             yield spot_req
            
#             # 🌟 核心修复：只有真正成功挤进坑位了，才允许通过 logger 打上进站的烙印！
#             # 这彻底消除了前端 3D 大屏中，排队箱子瞬间扎堆重叠的恶性穿模假象
#             if self.logger:
#                 self.logger.log_event(
#                     time=self.env.now, 
#                     entity_id=box_id, 
#                     event_type="enter_buffer", 
#                     station_id=self.station_id, 
#                     details={"type": int(entity_type)}
#                 )
                
#             # 步骤 2: 在缓存区内继续排队，申请唯一的工人资源进行加工
#             with self.worker.request() as worker_req:
#                 yield worker_req
                
#                 # 成功抢到工人，记录开始加工的动画事件，此时前端会激活红色激光和屏幕特效
#                 if self.logger:
#                     self.logger.log_event(
#                         time=self.env.now, 
#                         entity_id=box_id, 
#                         event_type="start_process", 
#                         station_id=self.station_id
#                     )
                
#                 # 步骤 3: 模拟机械臂/工人处理箱子的绝对物理耗时 (SimPy 时间流逝)
#                 yield self.env.timeout(p_time)
                
#                 # 加工完成，记录结束事件，前端接收到该事件后会让箱子驶出产线离场
#                 if self.logger:
#                     self.logger.log_event(
#                         time=self.env.now, 
#                         entity_id=box_id, 
#                         event_type="end_process", 
#                         station_id=self.station_id
#                     )
                    
#                 # 业绩统计递增
#                 self.processed_boxes += 1
#         # 离开 with 语句块后，Python 会自动向 SimPy 引擎释放 worker 锁和 buffer_spots 锁，放行下一箱

# 文件路径: core_engine/models/resource_models.py

import simpy

# =====================================================================
# [第一部分] 现有模型：固定站台 (完全保留，未做任何修改)
# =====================================================================

class LogicalStation:
    """供强化学习矩阵高速推演使用的逻辑站台"""
    def __init__(self, station_id, capacity):
        self.station_id = station_id
        self.capacity = capacity
        self.box_finish_times = []
        self.free_at = 0.0

    def current_load(self):
        return len(self.box_finish_times)

    @property
    def current_load(self):
        return len(self.box_finish_times)

    def update_load_at_time(self, current_time):
        self.box_finish_times = [t for t in self.box_finish_times if t > current_time]

    def reset(self):
        self.box_finish_times = []
        self.free_at = 0.0

class SimpyStation:
    """供连续时间沙盘高保真推演的物理站台 (带互斥锁与在途雷达)"""
    def __init__(self, env: simpy.Environment, station_id: int, capacity: int, logger=None):
        self.env = env
        self.station_id = station_id
        self.capacity = capacity
        self.logger = logger
        
        self.buffer_spots = simpy.Resource(env, capacity=capacity)
        self.worker = simpy.Resource(env, capacity=1)
        self.processed_boxes = 0
        
        # 🌟 核心升级：在途库存雷达（记录已经发车但还在传送带上滑行的箱子）
        self.in_transit = 0 

    @property
    def total_future_load(self):
        """获取绝对真实负载：在途滑行的 + 门口排队的 + 正在干活的"""
        return self.in_transit + len(self.buffer_spots.queue) + self.buffer_spots.count

    def process_box(self, box_id: str, p_time: float, travel_time: float, entity_type: int):
        """完整的物理流转协程：包含传送带滑行与进站加工"""
        # 1. 传送带物理滑行阶段
        self.in_transit += 1
        yield self.env.timeout(travel_time) # 真实空间位移延迟
        self.in_transit -= 1
        
        # 2. 到达站台，开始申请进站坑位
        if self.logger:
            self.logger.log_event(self.env.now, box_id, "enter_buffer", self.station_id)
            
        with self.buffer_spots.request() as spot_req:
            yield spot_req # 坑位满则在此物理死等，不穿模
            
            with self.worker.request() as worker_req:
                yield worker_req # 等待工人空闲
                if self.logger:
                    self.logger.log_event(self.env.now, box_id, "start_process", self.station_id)
                
                # 3. 真实加工时间消耗
                yield self.env.timeout(p_time)
                self.processed_boxes += 1
                
                if self.logger:
                    self.logger.log_event(self.env.now, box_id, "end_process", self.station_id)


# =====================================================================
# [第二部分] 新增模型：通用动态物流资源 (证明通用性与二次开发能力)
# =====================================================================

class AGVRobot:
    """
    【新增】通用 AGV/AMR 移动机器人模型
    用途：用于模拟复杂车间内的点到点柔性搬运，支持电量损耗与充电逻辑。
    """
    def __init__(self, env: simpy.Environment, agv_id: str, speed: float, battery_capacity: float = 100.0):
        self.env = env
        self.agv_id = agv_id
        self.speed = speed
        self.battery = simpy.Container(env, capacity=battery_capacity, init=battery_capacity)
        self.resource = simpy.Resource(env, capacity=1) # 互斥锁：同一时间只能执行一个搬运任务
        self.total_distance = 0.0

    def move_and_deliver(self, distance: float, load_time: float, unload_time: float):
        """完整的 AGV 搬运生命周期"""
        with self.resource.request() as req:
            yield req
            # 1. 装货耗时
            yield self.env.timeout(load_time)
            # 2. 行驶耗时 (时间 = 距离 / 速度)
            travel_time = distance / self.speed
            yield self.env.timeout(travel_time)
            # 3. 电量损耗 (假设每跑1米消耗 0.1 单位电量)
            power_consumed = distance * 0.1
            if self.battery.level > power_consumed:
                yield self.battery.get(power_consumed)
            self.total_distance += distance
            # 4. 卸货耗时
            yield self.env.timeout(unload_time)

class ConveyorBelt:
    """
    【新增】通用连续传送带模型
    用途：模拟流水线上的物理空间占用和固定节拍运输。
    """
    def __init__(self, env: simpy.Environment, length: float, speed: float, capacity: int):
        self.env = env
        self.length = length
        self.speed = speed
        self.travel_time = length / speed
        # 传送带上最多能同时容纳多少个物理箱子
        self.slots = simpy.Resource(env, capacity=capacity)

    def transport_item(self, item_id: str):
        """物品在传送带上的流转过程"""
        with self.slots.request() as req:
            yield req
            # 占用传送带物理空间，经过指定时间后离开
            yield self.env.timeout(self.travel_time)
# 将此代码追加到 core_engine/models/resource_models.py 末尾

class ReliableMachine:
    """
    【高级模型】带随机故障与维修机制的设备模型
    用途：模拟真实工业环境中设备的不可靠性。
    """
    def __init__(self, env: simpy.Environment, machine_id: str, capacity: int, mtbf: float, mttr: float):
        """
        :param mtbf: Mean Time Between Failures (平均故障间隔时间)
        :param mttr: Mean Time To Repair (平均维修时间)
        """
        self.env = env
        self.machine_id = machine_id
        self.resource = simpy.Resource(env, capacity=capacity)
        self.mtbf = mtbf
        self.mttr = mttr
        self.broken = False
        
        # 启动后台的“故障发生器”进程
        self.env.process(self._breakdown_process())

    def _breakdown_process(self):
        """后台进程：周期性触发设备故障"""
        while True:
            # 正常运行一段时间 (服从指数分布)
            yield self.env.timeout(np.random.exponential(self.mtbf))
            
            # 设备宕机
            self.broken = True
            print(f"[⏱️ {self.env.now:.1f}s] ⚠️ 设备 {self.machine_id} 发生突发故障！")
            
            # 维修时间
            repair_time = np.random.exponential(self.mttr)
            yield self.env.timeout(repair_time)
            
            # 维修完成
            self.broken = False
            print(f"[⏱️ {self.env.now:.1f}s] 🔧 设备 {self.machine_id} 维修完成，恢复运行。")

    def process_item(self, item_id: str, p_time: float):
        """处理物料的生命周期"""
        with self.resource.request() as req:
            yield req
            
            # 如果设备正在维修，必须等待它修好才能开始干活
            while self.broken:
                yield self.env.timeout(1.0) # 每秒检查一次是否修好
                
            # 正常加工
            yield self.env.timeout(p_time)
# 将此代码追加到 core_engine/models/resource_models.py 末尾

class SetupStation:
    """
    【高级模型】带有换模/准备时间的工位模型
    用途：模拟工人处理不同批次或不同型号零件时的切换成本。
    """
    def __init__(self, env: simpy.Environment, station_id: str):
        self.env = env
        self.station_id = station_id
        self.worker = simpy.Resource(env, capacity=1)
        self.current_part_type = None # 记录当前正在处理的零件类型

    def process_with_setup(self, item_id: str, p_time: float, part_type: int, setup_time: float = 15.0):
        with self.worker.request() as req:
            yield req
            
            # 如果来的零件型号和上次处理的不一样，就需要花时间换模
            if self.current_part_type is not None and self.current_part_type != part_type:
                # 记录换模事件
                yield self.env.timeout(setup_time)
                
            # 更新当前处理的零件型号
            self.current_part_type = part_type
            
            # 正式加工
            yield self.env.timeout(p_time)