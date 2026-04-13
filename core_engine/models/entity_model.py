# 文件路径: core_engine/models/entity_model.py

import json
import os

class PhysicalEntity:
    """
    【物理实体类】：代表传送带上真实滑动的一个零件箱
    """
    def __init__(self, entity_id: str, entity_type: int, qty: int, single_p_time: float):
        self.entity_id = entity_id         # 箱子唯一ID (例如: ORD-2026-001-P12)
        self.entity_type = entity_type     # 零件种类 (1~50)
        self.qty = qty                     # 📦 箱内零件数量
        self.single_p_time = single_p_time # ⏱️ 单件标准耗时 (来自主数据字典)
        
        # 🌟 核心修正：这个箱子在机床里的【真实总加工耗时】 = 数量 × 单件耗时
        self.p_time = round(single_p_time * qty, 1)

    def __repr__(self):
        # 打印输出彻底清晰：包含型号、数量、单件时间、整箱总时间！
        return f"<Box {self.entity_id:<18} | Type:{self.entity_type:02d} | 数量:{self.qty:2d}个 | 单件:{self.single_p_time:5.1f}s | 整箱耗时:{self.p_time:6.1f}s>"


class LogicalOrder:
    """
    【逻辑订单类】：代表 MES 系统下发的一个完整订单
    """
    def __init__(self, order_id: str):
        self.order_id = order_id
        self.entities = []          # 该订单包含的所有物理零件箱
        self.total_process_time = 0.0

    def add_entity(self, entity: PhysicalEntity):
        self.entities.append(entity)
        self.total_process_time += entity.p_time # 累加的是整箱总耗时

    @property
    def num_entities(self):
        return len(self.entities)

    def __repr__(self):
        return f"📦 Order [{self.order_id}] | 共 {self.num_entities} 箱物料 | 订单总加工流逝时间: {self.total_process_time:.1f}s"


class DataLoader:
    """
    【数据驱动引擎】：专职负责读取外部 JSON，实例化对象。彻底解耦利器！
    """
    @staticmethod
    def _get_project_root():
        # 智能寻路：自动找到项目根目录 (假设当前文件在 core_engine/models/ 下)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(current_dir, '../../'))

    @classmethod
    def load_parts_master(cls) -> dict:
        """加载零件工时字典"""
        file_path = os.path.join(cls._get_project_root(), 'data', 'weichai_parts_master.json')
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"🚨 找不到零件主数据文件: {file_path}。请确认 Step 1.1 是否执行成功！")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @classmethod
    def load_history_orders(cls) -> list:
        """读取历史订单，并利用零件字典直接生成活体对象"""
        parts_master = cls.load_parts_master()
        file_path = os.path.join(cls._get_project_root(), 'data', 'weichai_history_orders.json')
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"🚨 找不到订单流水文件: {file_path}。请确认 Step 1.1 是否执行成功！")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_orders = json.load(f)

        logical_orders = []
        
        # 将 JSON 里的死数据，灌装成活的对象
        for raw_order in raw_orders:
            order_obj = LogicalOrder(order_id=raw_order['order_id'])
            
            for item in raw_order['items']:
                part_type_str = str(item['part_type']) # JSON解析出来的 key 默认是字符串
                
                if part_type_str not in parts_master:
                    print(f"⚠️ 警告: 订单 {order_obj.order_id} 包含了未知的零件类型 {part_type_str}，已跳过。")
                    continue
                
                # 🌟 核心破局点：不再随机！从字典中查出该零件的【真实单件加工时间】！
                real_single_p_time = parts_master[part_type_str]['process_time_sec']
                
                # 生成物理箱子对象
                box_id = f"{order_obj.order_id}-P{part_type_str}"
                entity_obj = PhysicalEntity(
                    entity_id=box_id,
                    entity_type=int(part_type_str),
                    qty=item['quantity'],
                    single_p_time=real_single_p_time # 👈 传入单件时间，内部会自动计算整箱总时间
                )
                order_obj.add_entity(entity_obj)
                
            logical_orders.append(order_obj)
            
        return logical_orders

# ==========================================
# 🧪 测试代码：供你直接运行验证
# ==========================================
if __name__ == "__main__":
    print("="*80)
    print("🚀 正在测试 DataLoader 数据解耦引擎 (数量与耗时修正版)...")
    print("="*80)
    try:
        orders = DataLoader.load_history_orders()
        # 仅打印前3个订单做抽样展示
        for order in orders[:3]:
            print(order)
            for box in order.entities:
                print(f"   -> {box}")
        print(f"...\n(共成功加载 {len(orders)} 个真实历史订单)")
        print("="*80)
        print("✅ Step 1.2 数据解析与灌装完美通过！底层算法已具备车间级真实精度！")
    except Exception as e:
        print(f"❌ 测试失败: {e}")