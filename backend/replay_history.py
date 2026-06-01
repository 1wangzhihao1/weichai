# 文件路径: backend/replay_history.py

import pandas as pd
import simpy
import sys
import os
import re
import random
from datetime import timedelta

# ==========================================
# 🌟 寻路雷达
# ==========================================
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from scenarios.order_picking.config import Config
from database import SessionLocal, PartMaster

EXCEL_PATH = "../raw_data/2月1号.xlsx"
random.seed(42)

# ==========================================
# 🛠️ 核心组件：双重硬红线约束物理站台
# ==========================================
class HighFidelityStation:
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.machine = simpy.Resource(env, capacity=1)
        self.active_orders = {}
        self.processed_boxes = 0

    @property
    def current_total_boxes(self):
        return sum(info['count'] for info in self.active_orders.values())

    @property
    def current_unique_orders(self):
        return len(self.active_orders)

    def can_accept_box(self, order_id):
        if self.current_total_boxes >= Config.MAX_BOXES_PER_STATION:
            return False
        if order_id not in self.active_orders:
            if self.current_unique_orders >= Config.MAX_ORDERS_PER_STATION:
                return False
        return True

    def process_box(self, box_id, order_id, p_time, transit_in_time, far_exit_dist):
        yield self.env.timeout(transit_in_time)
        
        if order_id not in self.active_orders:
            self.active_orders[order_id] = {'count': 1}
        else:
            self.active_orders[order_id]['count'] += 1
            
        with self.machine.request() as req:
            yield req
            yield self.env.timeout(p_time)
            
        self.processed_boxes += 1
        
        self.active_orders[order_id]['count'] -= 1
        if self.active_orders[order_id]['count'] == 0:
            del self.active_orders[order_id]
            
        is_far_exit = random.random() < 0.5
        actual_exit_dist = far_exit_dist if is_far_exit else (far_exit_dist - Config.EXIT_PORT_DELTA)
        transit_out_time = (Config.BRANCH_OUT_LENGTH + actual_exit_dist) / Config.BELT_SPEED
        yield self.env.timeout(transit_out_time)

# ==========================================
# 🌟 时间轴区间合并算法 (去除并行重叠)
# ==========================================
def merge_time_intervals(intervals):
    if not intervals:
        return 0.0
    
    # 按照开始时间排序
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    
    for current in sorted_intervals[1:]:
        previous = merged[-1]
        
        # 如果当前区间的开始时间 <= 上一个区间的结束时间，说明有重叠/相连
        if current[0] <= previous[1]:
            # 合并区间：取两者结束时间中较大的一个
            merged[-1] = (previous[0], max(previous[1], current[1]))
        else:
            # 没有重叠，独立新区间
            merged.append(current)
            
    # 累加合并后所有独立线段的长度
    total_seconds = sum((iv[1] - iv[0]).total_seconds() for iv in merged)
    return total_seconds

# ==========================================
# 🚀 仿真引擎主程序
# ==========================================
def run_high_fidelity_simulation():
    print("==================================================")
    print(" 潍柴数字孪生 - V1.5 终极物理对齐 (含去重叠净工时) ")
    print("==================================================")
    
    db = SessionLocal()
    if hasattr(db, '__next__'): db = next(db)
    
    try:
        all_parts = db.query(PartMaster).all()
        part_time_dict = {str(p.part_type).strip(): float(p.standard_p_time) for p in all_parts}
        print(f"✅ 成功装载 {len(part_time_dict)} 种 SKU 的官方纯净单件定额！")
    except Exception as e:
        print(f"❌ 读取工艺库失败，错误: {e}")
        db.close()
        return
    finally:
        db.close()

    if not os.path.exists(EXCEL_PATH):
        print(f"❌ 未找到账本文件: {EXCEL_PATH}")
        return
        
    print(f"📂 正在读入生产账本，进行微观订单抽取与工时盘点...")
    df = pd.read_excel(EXCEL_PATH, header=None, engine='openpyxl')
    
    parsed_records = []
    stats = {'total': len(df), 'skip_qty': 0, 'skip_time': 0, 'skip_status': 0, 'skip_parse': 0}
    
    # 用于收集全天所有作业的起止时间区间
    all_time_intervals = []
    
    for index, row in df.iterrows():
        row_vals = row.values
        
        if len(row_vals) < 13:
            stats['skip_parse'] += 1
            continue
            
        try:
            time_start = pd.to_datetime(row_vals[2])
            time_end = pd.to_datetime(row_vals[3])
            
            # 第 7 列才是真·微观拣选单！
            order_id = str(row_vals[6]).strip()
            
            status = str(row_vals[8]).strip()
            sku = str(row_vals[9]).strip()
            qty = float(row_vals[11])
            
            station_idx = None
            for val in row_vals:
                val_str = str(val).strip()
                if re.match(r'^D\d{4}$', val_str):
                    station_idx = int(val_str[1:]) - 1
                    break
                elif val_str.startswith('DMS_') and val_str[-2:].isdigit():
                    station_idx = int(val_str[-2:]) - 1
                    break
                    
        except Exception:
            stats['skip_parse'] += 1
            continue

        if not (station_idx is not None and sku and order_id and pd.notnull(time_start) and pd.notnull(time_end)):
            stats['skip_parse'] += 1
            continue
            
        if status not in ['确定', '完成']:
            stats['skip_status'] += 1
            continue
            
        if qty <= 0:
            stats['skip_qty'] += 1
            continue
            
        duration = (time_end - time_start).total_seconds()
        if duration <= 0:
            stats['skip_time'] += 1
            continue
            
        # 记录通过检查的合法包裹
        parsed_records.append({
            'start_time': time_start,
            'station_idx': station_idx,
            'sku': sku,
            'order_id': order_id, 
            'qty': int(qty),
            'original_index': index
        })
        
        # 将合法的时间段收集起来
        all_time_intervals.append((time_start, time_end))

    if not parsed_records:
        print("\n🚨 所有的包裹都被拦截器干掉了！请核对列索引！")
        return

    clean_df = pd.DataFrame(parsed_records).sort_values('start_time')
    
    print("\n" + "-"*40)
    print("🧹 【数据清洗拦截报告】")
    print(f"总扫描行数: {stats['total']}")
    print(f"拦截异常包裹数: {stats['skip_parse'] + stats['skip_status'] + stats['skip_qty'] + stats['skip_time']} 个")
    print(f"📦 最终成功参与推演的合法微观包裹: {len(clean_df)} 个！")
    print("-"*40 + "\n")

    sim_env = simpy.Environment()
    physical_stations = [HighFidelityStation(sim_env, i) for i in range(Config.NUM_STATIONS)]

    def system_定频_dispatch(env):
        for _, row in clean_df.iterrows():
            st_idx = max(0, min(row['station_idx'], Config.NUM_STATIONS - 1))
            target_station = physical_stations[st_idx]
            order_id = row['order_id']
            
            t_main_in = (st_idx * 5.0) / Config.BELT_SPEED 
            t_trans_in = t_main_in + Config.get_branch_info(st_idx)["transit_time_s"]
            
            single_time = part_time_dict.get(str(row['sku']), 4.5)
            total_process_time = single_time * row['qty']
            
            while not target_station.can_accept_box(order_id):
                yield env.timeout(1.0) 
                
            yield env.timeout(Config.DISPATCH_INTERVAL)
            
            box_id = f"BOX-{row['original_index']}-{row['sku']}"
            env.process(target_station.process_box(
                box_id, order_id, total_process_time, t_trans_in, 
                Config.STATION_EXIT_FAR_DISTANCES[st_idx]
            ))

        print("⏳ 系统打单完毕！沙盘正在依靠物理限制消纳拥堵...")
        while any(s.machine.count > 0 or s.current_total_boxes > 0 for s in physical_stations):
            yield env.timeout(1.0)

    sim_env.process(system_定频_dispatch(sim_env))
    sim_env.run()

    # 🌟 核心计算
    if all_time_intervals:
        first_time = min(iv[0] for iv in all_time_intervals)
        last_time = max(iv[1] for iv in all_time_intervals)
        real_span_hours = (last_time - first_time).total_seconds() / 3600.0
    else:
        real_span_hours = 0.0

    # 调用剔除重叠后的净干活时间计算
    net_work_seconds = merge_time_intervals(all_time_intervals)
    real_net_hours = net_work_seconds / 3600.0
    
    sim_hours = sim_env.now / 3600.0

    print("\n" + "🔥"*45)
    print("📊 【第一阶段终结：历史基线 vs 纯净物理推演 巅峰对决战报】")
    print("🔥"*45)
    print(f"▶️ 甲方现实打卡流逝跨度 (Real Span):      {round(real_span_hours, 2)} 小时")
    print(f"▶️ 🌟 现实去重叠纯净干活 (Real Net):       {round(real_net_hours, 2)} 小时")
    print("-"*45)
    print(f"▶️ 沙盘纯物理极限推演跨度 (Sim Makespan):   {round(sim_hours, 2)} 小时")
    print("="*45)
    print(f"💡 战报分析：")
    print(f"   如果 [Sim Makespan] 大于 [Real Net]，说明即使工人都按标准工时拼命干，")
    print(f"   【8箱/2单】的残酷物理红线依然会把车间卡死！必须马上呼叫 AI 炼丹介入！")
    print("="*45)

if __name__ == "__main__":
    run_high_fidelity_simulation()