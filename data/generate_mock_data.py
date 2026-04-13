# 文件路径: data/generate_mock_data.py

import json
import random
import os

def generate_parts_master(filename="weichai_parts_master.json"):
    """生成 50 种零件的标准工时档案"""
    parts_data = {}
    
    # 模拟 50 种完全不同的潍柴/重卡真实零件
    part_names = [
        "传动齿轮", "承载法兰", "高压油管", "气缸盖", "喷油嘴", 
        "活塞环", "曲轴瓦", "连杆总成", "进气凸轮", "排气歧管",
        "机油泵", "水泵叶轮", "飞轮壳", "皮带轮", "张紧轮",
        "气门弹簧", "摇臂轴", "节温器", "涡轮增压器", "中冷器",
        "燃油滤清器", "机油滤清器", "空气滤清器", "启动马达", "交流发电机",
        "转向助力泵", "空调压缩机", "离合器摩擦片", "压盘总成", "分离轴承",
        "变速箱前壳", "换挡同步器", "主传动轴", "十字万向节", "差速器壳体",
        "驱动半轴", "阻尼减震器", "通风刹车盘", "制动卡钳", "转向横拉杆",
        "独立悬挂下摆臂", "轮毂轴承", "排气消音筒", "三元催化器", "前置氧传感器",
        "压电爆震传感器", "曲轴位置传感器", "进气压力传感器", "冷却水温传感器", "机油压力传感器"
    ]
    
    for i in range(1, 51):
        name_suffix = part_names[i-1] 
        p_time = round(random.uniform(20.0, 150.0), 1)
        
        parts_data[str(i)] = {
            "name": f"P{i:02d}_{name_suffix}",
            "process_time_sec": p_time
        }
        
    filepath = os.path.join(os.path.dirname(__file__), filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(parts_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 零件主数据字典已生成: {filepath} (共 50 种零件)")
    
    return parts_data # 🌟 返回字典，供订单生成器查询打印

def generate_history_orders(parts_data, filename="weichai_history_orders.json", num_orders=100):
    """生成历史订单，并进行控制台核验打印"""
    orders_data = []
    
    # 🚨 潍柴核心业务规则死锁：每个订单最多允许 4 种零件箱
    MAX_PART_TYPES = 4 
    
    for i in range(1, num_orders + 1):
        order_id = f"ORD-2026-{i:03d}"
        
        # 严格限制：随机包含 1 到 4 种不同的零件
        num_items = random.randint(1, MAX_PART_TYPES)
        
        # 从 1-50 号零件中随机抽样（不重复）
        selected_parts = random.sample(range(1, 51), num_items)
        
        items = []
        for part_type in selected_parts:
            # 每种零件随机需求 5 到 40 个
            qty = random.randint(5, 40)
            items.append({
                "part_type": part_type,
                "quantity": qty
            })
            
        orders_data.append({
            "order_id": order_id,
            "items": items
        })
        
    # 写入 JSON
    filepath = os.path.join(os.path.dirname(__file__), filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(orders_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 历史订单流已生成: {filepath} (共 {num_orders} 个订单)")

    # ==========================================
    # 🚨 控制台可视化输出：让你一眼看清订单 BOM 明细！
    # ==========================================
    print("\n" + "="*60)
    print("📋 潍柴订单 BOM (物料清单) 详情核验")
    print("="*60)
    
    # 为了不在控制台刷屏太多，我们只打印前 10 个订单供你检查核对
    preview_limit = 10 
    for order in orders_data[:preview_limit]:
        print(f"📦 【{order['order_id']}】 (合规校验：共 {len(order['items'])} 种零件):")
        
        # 联动 parts_data，把零件的具体名字和单箱耗时查出来打印
        for item in order["items"]:
            p_id = str(item["part_type"])
            p_name = parts_data[p_id]["name"]
            p_time = parts_data[p_id]["process_time_sec"]
            qty = item["quantity"]
            
            # 使用格式化对齐，让强迫症极度舒适
            print(f"   ├─ 零件 {p_name:<15} : 需求 {qty:>2} 箱 (单箱耗时: {p_time:>5}s)")
        print("-" * 45)
        
    print(f"   ... (剩余 {num_orders - preview_limit} 个订单已隐藏打印，可查看 JSON 文件) ...")
    print(f"\n✅ 数据生成与规则校验完毕！绝对没有超过 {MAX_PART_TYPES} 种零件的订单！\n")

if __name__ == "__main__":
    print("="*60)
    print("🏭 正在生成潍柴数字化工厂测试底座数据...")
    print("="*60)
    
    # 1. 先生成 50 种字典，并把数据拿在手里
    master_parts = generate_parts_master()
    
    # 2. 把字典喂给订单生成器，生成订单并打印战报
    generate_history_orders(master_parts)
    
    print("="*60)
    print("🎉 Step 1.1 数据底座建立完毕！")