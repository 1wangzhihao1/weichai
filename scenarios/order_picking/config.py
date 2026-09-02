
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
