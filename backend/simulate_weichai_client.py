# 文件路径: backend/simulate_weichai_client.py

import os
import sys
import json
import requests
import time

# 🌟 寻路雷达：定位数据源文件
current_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(current_dir, '../'))
master_json_file = os.path.join(project_root, "data", "weichai_parts_master.json")
orders_json_file = os.path.join(project_root, "data", "weichai_history_orders.json")

BASE_URL = "http://127.0.0.1:8088/api/v1"

def sync_master_data():
    """
    第一阶段：模拟潍柴系统同步零件主数据（工艺标准）
    """
    print("\n" + "="*60)
    print("📡 [第一阶段] 正在同步零件主数据字典...")
    
    if not os.path.exists(master_json_file):
        print(f"🚨 找不到零件主数据文件: {master_json_file}")
        return False

    with open(master_json_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    formatted_parts = []
    for part_id, info in raw_data.items():
        formatted_parts.append({
            "part_type": str(part_id),
            "part_name": info["name"],
            "process_time": float(info["process_time_sec"])
        })
        
    payload = {"parts": formatted_parts}
    target_url = f"{BASE_URL}/master_data/upload"
    
    try:
        res = requests.post(target_url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"✅ {res.json()['message']}")
            return True
        else:
            print(f"❌ 主数据同步失败: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        print(f"🚨 网络异常: {e}")
        return False

def send_orders_in_batches(batch_size=100):
    """
    第二阶段：模拟潍柴系统分批次下发生产订单
    """
    print("\n" + "="*60)
    print("📡 [第二阶段] 正在分批下发生产订单...")
    
    if not os.path.exists(orders_json_file):
        print(f"🚨 找不到历史订单文件: {orders_json_file}")
        return

    with open(orders_json_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    
    total_count = len(raw_data)
    print(f"📦 共发现 {total_count} 个订单待传输。")

    target_url = f"{BASE_URL}/orders/upload"
    
    for i in range(0, total_count, batch_size):
        chunk = raw_data[i : i + batch_size]
        formatted_orders = []

        for item in chunk:
            order_id = str(item.get("order_id", item.get("vip_order_id", "UNKNOWN")))
            parts_list = item.get("parts") or item.get("entities") or item.get("items") or []
            
            for p in parts_list:
                p_type_raw = str(p.get("type", p.get("part_type", p.get("entity_type", "1"))))
                p_type = f"零件{p_type_raw}" if "零件" not in p_type_raw else p_type_raw
                qty = p.get("qty", p.get("quantity", 1))
                
                formatted_orders.append({
                    "order_id": order_id,
                    "priority": item.get("priority", 1),
                    "part_type": p_type,
                    "quantity": qty
                })

        if not formatted_orders:
            continue

        payload = {
            "batch_no": "WEICHAI_API_STRESS_TEST",
            "orders": formatted_orders
        }

        print(f"🚀 发送第 {i//batch_size + 1} 批次 ({len(formatted_orders)} 条记录)...", end="")
        
        try:
            response = requests.post(target_url, json=payload, timeout=30)
            if response.status_code == 200:
                print(f" ✅ {response.json().get('message', '成功')}")
            else:
                print(f" ❌ 失败 (状态码: {response.status_code})")
        except Exception as e:
            print(f" 🚨 网络异常：{e}")
            break
        
        time.sleep(0.5)

    print("\n🏁 [传输任务完成] 主数据与订单全部同步完毕！")
    print("="*60)

if __name__ == "__main__":
    print("🤖 [潍柴 MES 客户端模拟器] 全链路启动...")
    # 第一阶段：必须先同步基础规则（主数据），如果失败则停止发单
    if sync_master_data():
        # 第二阶段：主数据同步成功后，开始疯狂发单
        send_orders_in_batches(batch_size=50)
    else:
        print("🛑 主数据同步失败，为防止产生脏数据，已终止订单传输！")