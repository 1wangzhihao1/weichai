# 文件路径: scenarios/order_picking/config.py

class Config:
    """
    【业务场景配置表：潍柴数字孪生分拣线 (回归绝对物理法则版)】
    """
    
    # ==========================================
    # 1. 神经网络维度与缓冲约束
    # ==========================================
    NUM_STATIONS = 16           
    NUM_PART_TYPES = 50         
    BUFFER_CAPACITY = 8         

    # ==========================================
    # 2. 传送带空间与运动学约束 (对齐 3D 视觉与 SimPy)
    # ==========================================
    DISPATCH_INTERVAL = 1.5     
    BELT_SPEED = 1.0            # 🌟 绝对物理法则：传送带全线匀速 (1.0米/秒)
    STATION_DISTANCE = 5.0      
    MAIN_LINE_OFFSET = 6.0      
    
    # 支线真实物理长度
    UPPER_BRANCH_LENGTH = 10.4  # 上层支线长度 (米)
    LOWER_BRANCH_LENGTH = 9.3   # 下层支线长度 (米)

    # ==========================================
    # 3. 降本增效多目标优化约束
    # ==========================================
    DEADLINE_SECONDS = 55000.0   
    STATION_OPEN_PENALTY = 10.0 

    # ==========================================
    # 4. 场景辅助换算接口
    # ==========================================
    @classmethod
    def get_station_main_distance(cls, station_idx: int) -> float:
        """计算主线绝对距离"""
        return cls.MAIN_LINE_OFFSET + station_idx * cls.STATION_DISTANCE

    @classmethod
    def get_branch_info(cls, station_idx: int) -> dict:
        """
        🌟 核心换算：速度锁死，时间按真实距离推演！
        """
        is_upper = (station_idx % 2 != 0)
        actual_length = cls.UPPER_BRANCH_LENGTH if is_upper else cls.LOWER_BRANCH_LENGTH
        
        # 物理真理：时间 = 距离 / 速度
        transit_time = actual_length / cls.BELT_SPEED
        
        return {
            "is_upper": is_upper,
            "length_m": actual_length,
            "transit_time_s": round(transit_time, 3), # 上层将耗时10.4s，下层将耗时9.3s
            "visual_speed_m_s": cls.BELT_SPEED        # 前端渲染速度也严格保持一致
        }