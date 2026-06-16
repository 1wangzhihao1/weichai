# # 文件路径: scenarios/order_picking/config.py

# class Config:
#     """
#     【业务场景配置表：潍柴数字孪生分拣线 (回归绝对物理法则版)】
#     """
    
#     # ==========================================
#     # 1. 神经网络维度与缓冲约束
#     # ==========================================
#     NUM_STATIONS = 16           
#     NUM_PART_TYPES = 50         
#     BUFFER_CAPACITY = 8         

#     # ==========================================
#     # 2. 传送带空间与运动学约束 (对齐 3D 视觉与 SimPy)
#     # ==========================================
#     DISPATCH_INTERVAL = 1.5     
#     BELT_SPEED = 1.0            # 🌟 绝对物理法则：传送带全线匀速 (1.0米/秒)
#     STATION_DISTANCE = 5.0      
#     MAIN_LINE_OFFSET = 6.0      
    
#     # 支线真实物理长度
#     UPPER_BRANCH_LENGTH = 10.4  # 上层支线长度 (米)
#     LOWER_BRANCH_LENGTH = 9.3   # 下层支线长度 (米)

#     # ==========================================
#     # 3. 降本增效多目标优化约束
#     # ==========================================
#     DEADLINE_SECONDS = 55000.0   
#     STATION_OPEN_PENALTY = 10.0 

#     # ==========================================
#     # 4. 场景辅助换算接口
#     # ==========================================
#     @classmethod
#     def get_station_main_distance(cls, station_idx: int) -> float:
#         """计算主线绝对距离"""
#         return cls.MAIN_LINE_OFFSET + station_idx * cls.STATION_DISTANCE

#     @classmethod
#     def get_branch_info(cls, station_idx: int) -> dict:
#         """
#         🌟 核心换算：速度锁死，时间按真实距离推演！
#         """
#         is_upper = (station_idx % 2 != 0)
#         actual_length = cls.UPPER_BRANCH_LENGTH if is_upper else cls.LOWER_BRANCH_LENGTH
        
#         # 物理真理：时间 = 距离 / 速度
#         transit_time = actual_length / cls.BELT_SPEED
        
#         return {
#             "is_upper": is_upper,
#             "length_m": actual_length,
#             "transit_time_s": round(transit_time, 3), # 上层将耗时10.4s，下层将耗时9.3s
#             "visual_speed_m_s": cls.BELT_SPEED        # 前端渲染速度也严格保持一致
#         }

# 文件路径: scenarios/order_picking/config.py


class Config:
    """
    【业务场景配置表：潍柴数字孪生分拣线 (双出库口概率模型 & 双重物理红线版)】
    """
    
    # ==========================================
    # 1. 神经网络维度与站台双重缓冲区约束
    # ==========================================
    NUM_STATIONS = 16           
    NUM_PART_TYPES = 50         
    
    # 🌟 甲方双重硬红线约束（不含当前正在工位上加工的那个包裹）
    MAX_ORDERS_PER_STATION = 2    # 约束一：当前站台堆积的独立订单数上限
    MAX_BOXES_PER_STATION = 8     # 约束二：当前站台缓冲区能容纳的物理箱数上限

    # ==========================================
    # 2. 传送带空间与运动学约束 (物理测绘级)
    # ==========================================
    DISPATCH_INTERVAL = 1.5     
    BELT_SPEED = 0.7            # 绝对物理匀速 (0.7米/秒)
    
    # 各站台到【更远端出库口】的精确物理测绘距离 (单位: 米)
    STATION_EXIT_FAR_DISTANCES = [
        41.214, 44.703, 47.155, 50.811, 52.945, 56.601, 59.040, 62.696,
        70.495, 74.153, 76.335, 79.991, 83.191, 86.875, 88.517, 92.199
    ]
    
    # 远端出库口与近端出库口的固定物理位移差 (单位: 米)
    EXIT_PORT_DELTA = 3.661
    
    # 去往远、近端出库口的盲盒概率各占 50%
    PROB_FAR_EXIT = 0.5
    PROB_NEAR_EXIT = 0.5

    BRANCH_IN_LENGTH = 9.552    # 支线入库皮带线真实长度 (米)
    BRANCH_OUT_LENGTH = 10.395  # 支线出库斜坡提升机真实长度 (米)

    # ==========================================
    # 3. 降本增效多目标优化惩罚项
    # ==========================================
    DEADLINE_SECONDS = 30600.0   
    STATION_OPEN_PENALTY = 10.0 

    # ==========================================
    # 4. 离散事件引擎与 AI 大脑共享的决策换算接口
    # ==========================================
    @classmethod
    def get_expected_exit_time(cls, station_idx: int) -> float:
        """
        🚀 核心数学模型：计算零件箱离开工位后，流向出库口的【数学期望耗时】。
        期望距离 = 50% * 远端距离 + 50% * (远端距离 - 3.661)
        """
        far_dist = cls.STATION_EXIT_FAR_DISTANCES[station_idx]
        near_dist = far_dist - cls.EXIT_PORT_DELTA
        
        # 概率论期望公式
        expected_dist = (cls.PROB_FAR_EXIT * far_dist) + (cls.PROB_NEAR_EXIT * near_dist)
        
        # 总体物理位移 = 支线段 + 主线期望段
        total_expected_dist = cls.BRANCH_OUT_LENGTH + expected_dist
        return total_expected_dist / cls.BELT_SPEED

    @classmethod
    def get_branch_info(cls, station_idx: int) -> dict:
        """
        支线基础滑行常量
        """
        return {
            "branch_length": cls.BRANCH_IN_LENGTH,
            "transit_time_s": cls.BRANCH_IN_LENGTH / cls.BELT_SPEED
        }
