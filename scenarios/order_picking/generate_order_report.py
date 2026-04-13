import json
import os

def generate_txt_report(json_file="weichai_order_manifest.json", txt_file="weichai_order_report.txt"):
    """
    读取数字孪生沙盘产出的 JSON 档案，转换为极客范儿的终端战报，并导出为 TXT 文件。
    """
    if not os.path.exists(json_file):
        print(f"❌ 找不到数据源 {json_file}，请先运行 export_sim_data.py 生成底层数据！")
        return

    # 1. 读取 JSON 档案
    with open(json_file, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    print("="*90)
    print("📊 [潍柴数字孪生分拣系统] - 核心 AI 派发终端战报")
    print("="*90)

    output_lines = []
    
    # 2. 遍历每一个订单，进行格式化排版
    for order in manifest:
        order_id = order["order_id"]
        
        # 组装零件清单，例如: "P09x39件, P39x31件, P48x39件"
        parts_str_list = []
        for p in order["parts"]:
            parts_str_list.append(f"P{p['part_type']:02d}x{p['quantity']}件")
        parts_str = ", ".join(parts_str_list)
        
        # 格式化站台和耗时
        station = f"站台  {order['target_station']:02d}"
        p_time = f"{order['total_process_time']:.6f}"
        
        # 🌟 核心排版魔法：利用 Python 的 f-string 对齐功能，完美复刻你的截图！
        # <10 表示左对齐占 10 格， >55 表示右对齐占 55 格
        line = f"{order_id:<10} {parts_str:>55}  {station}  {p_time}"
        
        print(line)
        output_lines.append(line)

    # 3. 顺手把这份绝美的终端输出保存成 .txt 纯文本文件
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(output_lines))
    
    print("="*90)
    print(f"✅ 战报已在终端全量输出，并成功刻录至纯文本文件: {txt_file}")

if __name__ == "__main__":
    generate_txt_report()