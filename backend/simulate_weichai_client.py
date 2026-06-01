# 文件路径: backend/simulate_weichai_client.py

import os
import json
import requests
import time
import pandas as pd
from collections import defaultdict

current_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(current_dir, '../'))
EXCEL_PATH = os.path.join(project_root, "raw_data", "DMS拣选20260201-0429.XLSX")
JSON_OUTPUT_PATH = os.path.join(current_dir, "weichai_waves.json")

BASE_URL = "http://127.0.0.1:8088/api/v1"

def extract_excel_to_json():
    """第一阶段：模拟甲方系统，从 Excel 提取数据并生成标准 JSON 报文"""
    print("\n" + "="*60)
    print(f"⏳ 正在模拟甲方系统生成 JSON 报文...")
    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(f"🚨 找不到 Excel 文件: {EXCEL_PATH}")

    df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    orders_by_date = defaultdict(dict) 

    for index, row in df.iterrows():
        try:
            row_vals = row.values
            if len(row_vals) < 13: continue
            
            time_start = pd.to_datetime(row_vals[2])
            date_str = time_start.date().isoformat() 
            
            order_id = str(row_vals[6]).strip()
            status = str(row_vals[8]).strip()
            sku = str(row_vals[9]).strip()
            qty = float(row_vals[11])
            
            if status not in ['确定', '完成'] or qty <= 0: continue
            
            if order_id not in orders_by_date[date_str]:
                orders_by_date[date_str][order_id] = {
                    "order_id": order_id,
                    "items": []
                }
            orders_by_date[date_str][order_id]["items"].append({
                "part_type": sku,
                "quantity": int(qty)
            })
        except Exception as e:
            continue
            
    # 构建最终的 JSON 结构
    waves_payload = []
    for date_str, orders in sorted(orders_by_date.items()):
        waves_payload.append({
            "wave_name": f"ORDER_WAVE_{date_str}", # 波次名称 (比如 ORDER_WAVE_2026-04-15)
            "orders": list(orders.values())
        })
        
    # 保存为 JSON 文件
    with open(JSON_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(waves_payload, f, ensure_ascii=False, indent=2)
        
    print(f"✅ JSON 报文生成完毕！共 {len(waves_payload)} 个波次，保存在: {JSON_OUTPUT_PATH}")

def send_json_to_server(chunk_size=400):
    """第二阶段：读取标准 JSON 报文，只负责发送网络请求"""
    print("\n" + "="*60)
    print(f"📡 正在向 AI 中枢发送 JSON 订单报文...")
    
    if not os.path.exists(JSON_OUTPUT_PATH):
         print("🚨 找不到 JSON 文件！")
         return
         
    with open(JSON_OUTPUT_PATH, 'r', encoding='utf-8') as f:
        waves_payload = json.load(f)
        
    target_url = f"{BASE_URL}/orders/upload"
    
    # 按波次（天）发送
    for wave in waves_payload:
        batch_no = wave["wave_name"]
        all_orders = wave["orders"]
        print(f"\n📅 开始传输波次: 【{batch_no}】 (共 {len(all_orders)} 个订单)")

        # 分块传输防止爆内存
        for i in range(0, len(all_orders), chunk_size):
            chunk_orders = all_orders[i : i + chunk_size]
            formatted_payload = []

            for order in chunk_orders:
                for item in order["items"]:
                    formatted_payload.append({
                        "order_id": order["order_id"],
                        "part_type": item["part_type"],
                        "quantity": item["quantity"]
                    })

            payload = {
                "batch_no": batch_no,
                "orders": formatted_payload
            }

            print(f"  🚀 发送数据块 {i//chunk_size + 1} ...", end="")
            try:
                response = requests.post(target_url, json=payload, timeout=60)
                if response.status_code == 200:
                    print(f" ✅ 成功")
                else:
                    print(f" ❌ 失败 (状态码: {response.status_code})")
            except Exception as e:
                print(f" 🚨 网络异常：{e}")
                break
            time.sleep(0.1)

    print("\n🏁 [传输任务完成] 所有 JSON 波次已全部注入数据库！")

if __name__ == "__main__":
    print("🤖 [潍柴 MES 数据中间件] 启动...")
    extract_excel_to_json()
    send_json_to_server()