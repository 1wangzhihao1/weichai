


# 文件路径: backend/database.py

import os
import sys
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, BigInteger, inspect, text
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
    sequence_no = Column(Integer, default=0, comment="订单在当前波次中的上传顺序")
    
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
    process_time_source = Column(String(50), default="", comment="工时来源")
    operation_gap_seconds = Column(Float, default=0.0, comment="综合作业间隔(秒)")
    real_makespan_sec = Column(Float, comment="历史真实总工作时间(秒)")
    error_pct = Column(Float, comment="仿真与真实时间误差百分比")
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
    sku = Column(String(100), default="", comment="SKU")

# ==========================================
# 🚀 第三步：自动建表与初始化
# ==========================================
def init_db():
    print("="*60)
    print("⏳ 正在连接 MySQL 并初始化工业数据库结构...")
    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()
    print("✅ 所有数据表结构创建/映射完毕！")


def ensure_schema_updates():
    inspector = inspect(engine)
    if "t_order_pool" not in inspector.get_table_names():
        return

    order_pool_columns = {col["name"] for col in inspector.get_columns("t_order_pool")}
    if "sequence_no" not in order_pool_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE t_order_pool ADD COLUMN sequence_no INT DEFAULT 0"))
        print("✅ t_order_pool.sequence_no 字段已补充，用于保留订单上传顺序。")

    if "t_simulation_task" in inspector.get_table_names():
        task_columns = {col["name"] for col in inspector.get_columns("t_simulation_task")}
        task_updates = {
            "process_time_source": "ALTER TABLE t_simulation_task ADD COLUMN process_time_source VARCHAR(50) DEFAULT ''",
            "operation_gap_seconds": "ALTER TABLE t_simulation_task ADD COLUMN operation_gap_seconds DOUBLE DEFAULT 0",
            "real_makespan_sec": "ALTER TABLE t_simulation_task ADD COLUMN real_makespan_sec DOUBLE NULL",
            "error_pct": "ALTER TABLE t_simulation_task ADD COLUMN error_pct DOUBLE NULL",
        }
        for column_name, ddl in task_updates.items():
            if column_name not in task_columns:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                print(f"✅ t_simulation_task.{column_name} 字段已补充。")

    if "t_dispatch_result" in inspector.get_table_names():
        dispatch_columns = {col["name"] for col in inspector.get_columns("t_dispatch_result")}
        if "sku" not in dispatch_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE t_dispatch_result ADD COLUMN sku VARCHAR(100) DEFAULT ''"))
            print("✅ t_dispatch_result.sku 字段已补充。")

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
