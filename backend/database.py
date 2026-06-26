# # 文件路径: backend/database.py

# import os
# import sys
# import datetime
# from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, BigInteger
# from sqlalchemy.orm import declarative_base, sessionmaker

# # ==========================================
# # 🌟 寻路雷达：确保能找到 scenarios 里的 config.py
# # ==========================================
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
# if project_root not in sys.path:
#     sys.path.append(project_root)

# scenario_dir = os.path.join(project_root, 'scenarios', 'order_picking')
# if scenario_dir not in sys.path:
#     sys.path.append(scenario_dir)

# from config import Config

# # ==========================================
# # 🔌 第一步：配置数据库连接管道
# # ==========================================
# DATABASE_URL = "mysql+pymysql://root:mengdi@127.0.0.1:3306/weichai_aps"

# # create_engine 建立连接池
# engine = create_engine(DATABASE_URL, echo=False)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# # ==========================================
# # 🏗️ 第二步：定义核心数据库表 (Python 类映射)
# # ==========================================

# # --- 【基础主数据层】 ---

# class PartMaster(Base):
#     """1. 零件工艺主表：存储不同零件的标准加工时间"""
#     __tablename__ = "t_part_master"
    
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     part_type = Column(String(50), nullable=False, comment="零件类型")
#     standard_p_time = Column(Float, nullable=False, comment="标准加工耗时(秒)")
#     variance_p_time = Column(Float, default=0.0, comment="耗时波动方差(模拟工人疲劳)")

# class StationMaster(Base):
#     """2. 车间物理站台主表：记录 1-16 号机床的全量真实物理状态 (对齐 Config)"""
#     __tablename__ = "t_station_master"
    
#     # 🌟 核心修复：强制关闭自增 (autoincrement=False)，避免 MySQL 把 0 变成 1 引发冲突
#     station_id = Column(Integer, primary_key=True, autoincrement=False, comment="站台编号 (1-16)")
#     main_distance_m = Column(Float, nullable=False, comment="主线物理距离(米)")
#     branch_length_m = Column(Float, nullable=False, comment="支线物理长度(米)")
#     is_upper = Column(Boolean, nullable=False, comment="是否为上层支线")
#     status = Column(String(20), default="ACTIVE", comment="状态: ACTIVE / BROKEN")

# # --- 【真实业务输入层】 ---

# class OrderPool(Base):
#     """3. 历史真实订单表：存放海量订单"""
#     __tablename__ = "t_order_pool"
    
#     order_id = Column(String(100), primary_key=True, comment="订单流水号")
#     batch_no = Column(String(100), nullable=False, comment="生产批次号")
#     priority_level = Column(Integer, default=1, comment="优先级")
#     deadline_time = Column(DateTime, default=datetime.datetime.now, comment="甲方要求的交期")
#     is_simulated = Column(Boolean, default=False, comment="是否已被推演过")

# class OrderBOM(Base):
#     """4. 订单物料明细表：一个订单需要多少个、什么类型的零件"""
#     __tablename__ = "t_order_bom"
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     order_id = Column(String(100), nullable=False, index=True, comment="关联订单号")
#     part_type = Column(String(50), nullable=False, comment="零件类型")
#     quantity = Column(Integer, nullable=False, comment="需求数量")

# # --- 【仿真沙盘输出层】 ---

# class SimulationTask(Base):
#     """5. 宏观仿真任务批次表：记录 AI 与传统算法的总耗时与启用站台数"""
#     __tablename__ = "t_simulation_task"
    
#     task_id = Column(String(100), primary_key=True, comment="推演任务批次号")
#     batch_no = Column(String(100), nullable=False, comment="推演的订单批次")
#     strategy_type = Column(String(50), nullable=False, comment="策略: AI_RL / TRADITIONAL / RANDOM")
    
#     active_stations = Column(Integer, comment="推演最终确定的启用站台数")  
#     total_makespan_sec = Column(Float, comment="计算出的总完工时间(秒)")
    
#     created_at = Column(DateTime, default=datetime.datetime.now)

# class DispatchResult(Base):
#     """6. 微观派工结果表：海量数据，前端 Vue3 画甘特图、3D 大屏推演的基石"""
#     __tablename__ = "t_dispatch_result"
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     task_id = Column(String(100), nullable=False, index=True, comment="关联推演任务")
#     order_id = Column(String(100), nullable=False)
#     box_id = Column(String(150), nullable=False, index=True, comment="实体箱ID")
#     target_station = Column(Integer, nullable=False, comment="派往几号站台")
#     predicted_start_time = Column(DateTime, nullable=False, comment="预测开工时间")
#     predicted_end_time = Column(DateTime, nullable=False, comment="预测完工时间")


# # ==========================================
# # 🚀 第三步：自动建表与灌入初始化数据
# # ==========================================
# def init_db():
#     """将上述的 Python 类转换为 MySQL 里的真实表结构"""
#     print("="*60)
#     print("⏳ 正在连接 MySQL 并初始化工业数据库结构...")
#     Base.metadata.create_all(bind=engine)
#     print("✅ 所有数据表结构创建/映射完毕！")

# def seed_test_data():
#     """根据 Config 物理引擎参数，自动灌入 16 台机床的真实空间数据"""
#     db = SessionLocal()
    
#     try:
#         # 检查机床表是否为空
#         if db.query(StationMaster).count() == 0:
#             print("⏳ 检测到站台表为空，正在根据物理引擎 Config 自动灌入 16 台机床配置...")
#             stations = []
            
#             # 🌟 自动从 config.py 中提取 16 台机床的物理距离和支线长度
#             for i in range(Config.NUM_STATIONS):
#                 info = Config.get_branch_info(i)
#                 stations.append(StationMaster(
#                     station_id=i + 1,  # 👈 核心修复：把 AI 的 0-15 翻译成车间的 1-16
#                     main_distance_m=Config.get_station_main_distance(i),
#                     branch_length_m=info["length_m"],
#                     is_upper=info["is_upper"]
#                 ))
            
#             db.add_all(stations)
#             db.commit()
#             print("✅ 16 台机床物理底座数据灌入成功！这回全满编了，编号严格从 1 到 16！")
#         else:
#             print("💡 数据库中已有站台主数据，跳过初始化。")
            
#     except Exception as e:
#         db.rollback()
#         print(f"❌ 数据库操作失败: {e}")
#     finally:
#         db.close()

# if __name__ == "__main__":
#     init_db()
#     seed_test_data()


# 文件路径: backend/database.py

import os
import sys
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from scenarios.order_picking.config import Config

# ==========================================
# 🔌 第一步：配置数据库连接管道
# ==========================================
DATABASE_URL = "mysql+pymysql://root:mengdi@127.0.0.1:3306/weichai_aps"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# 🏗️ 第二步：定义核心数据库表
# ==========================================
class PartMaster(Base):
    __tablename__ = "t_part_master"
    id = Column(Integer, primary_key=True, autoincrement=True)
    part_type = Column(String(50), nullable=False, comment="零件类型")
    standard_p_time = Column(Float, nullable=False, comment="标准加工耗时(秒)")
    variance_p_time = Column(Float, default=0.0, comment="耗时波动方差")

class StationMaster(Base):
    __tablename__ = "t_station_master"
    station_id = Column(Integer, primary_key=True, autoincrement=False, comment="站台编号 (1-16)")
    main_distance_m = Column(Float, nullable=False, comment="主线物理距离(米) - 真实测绘")
    branch_length_m = Column(Float, nullable=False, comment="支线物理长度(米)")
    status = Column(String(20), default="ACTIVE", comment="状态: ACTIVE / BROKEN")

class OrderPool(Base):
    __tablename__ = "t_order_pool"
    order_id = Column(String(100), primary_key=True, comment="订单/拣选流水号")
    batch_no = Column(String(100), nullable=False, comment="生产批次号/波次名")
    
    # 🚨 已删除不合理的 start_time 字段！
    
    priority_level = Column(Integer, default=1, comment="优先级")
    deadline_time = Column(DateTime, default=datetime.datetime.now, comment="交期死线")
    is_simulated = Column(Boolean, default=False, comment="是否已推演")
    
class OrderBOM(Base):
    __tablename__ = "t_order_bom"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(String(100), nullable=False, index=True, comment="关联拣选单号")
    part_type = Column(String(50), nullable=False, comment="零件类型(SKU)")
    quantity = Column(Integer, nullable=False, comment="需求数量")

class SimulationTask(Base):
    __tablename__ = "t_simulation_task"
    task_id = Column(String(100), primary_key=True, comment="推演任务批次号")
    batch_no = Column(String(100), nullable=False, comment="推演的订单批次")
    strategy_type = Column(String(50), nullable=False, comment="策略")
    active_stations = Column(Integer, comment="启用站台数")  
    total_makespan_sec = Column(Float, comment="总完工时间(秒)")
    created_at = Column(DateTime, default=datetime.datetime.now)

class DispatchResult(Base):
    __tablename__ = "t_dispatch_result"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(100), nullable=False, index=True, comment="关联推演任务")
    order_id = Column(String(100), nullable=False)
    box_id = Column(String(150), nullable=False, index=True, comment="实体箱ID")
    target_station = Column(Integer, nullable=False, comment="派往几号站台")
    
    predicted_spawn_time = Column(DateTime, nullable=False, comment="预测发车时间")
    predicted_start_time = Column(DateTime, nullable=False, comment="预测开工时间")
    predicted_end_time = Column(DateTime, nullable=False, comment="预测完工时间")

# ==========================================
# 🚀 第三步：自动建表与初始化
# ==========================================
def init_db():
    print("="*60)
    print("⏳ 正在连接 MySQL 并初始化工业数据库结构...")
    Base.metadata.create_all(bind=engine)
    print("✅ 所有数据表结构创建/映射完毕！")

def seed_test_data():
    db = SessionLocal()
    try:
        if db.query(StationMaster).count() == 0:
            stations = []
            for i in range(Config.NUM_STATIONS):
                info = Config.get_branch_info(i)
                # 🌟 完美适配你最新 config.py 里的测绘级数组
                stations.append(StationMaster(
                    station_id=i + 1,
                    main_distance_m=Config.STATION_EXIT_FAR_DISTANCES[i], 
                    branch_length_m=info["branch_length"]
                ))
            db.add_all(stations)
            db.commit()
            print("✅ 16台机床真实物理参数(精确测绘版)写入数据库成功！")
    except Exception as e:
        db.rollback()
        print(f"❌ 数据库操作失败: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    seed_test_data()
