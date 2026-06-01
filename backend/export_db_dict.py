# 文件路径: backend/export_db_dict.py
import pandas as pd
from sqlalchemy import inspect
from database import engine  # 假设你在 database.py 中定义了 engine

def export_data_dictionary():
    print("🔍 正在扫描数据库结构...")
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    
    all_columns = []
    
    for table in table_names:
        columns = inspector.get_columns(table)
        for col in columns:
            all_columns.append({
                "表名 (Table)": table,
                "字段名 (Column)": col['name'],
                "数据类型 (Type)": str(col['type']),
                "是否主键 (Primary Key)": "是" if col.get('primary_key') else "否",
                "是否允许为空 (Nullable)": "是" if col.get('nullable') else "否",
                "备注说明 (Comment)": col.get('comment') or ""
            })
            
    df = pd.DataFrame(all_columns)
    
    # 导出为 CSV（用 Excel 打开即可）
    csv_path = "潍柴数字孪生_数据字典.csv"
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    
    print(f"✅ 成功生成数据字典！共扫描了 {len(table_names)} 张表。")
    print(f"📁 文件已保存至: {csv_path}")

if __name__ == "__main__":
    export_data_dictionary()