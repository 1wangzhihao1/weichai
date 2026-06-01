# import pandas as pd
# import numpy as np
# import sys, io
# import os

# sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# # ============================================================
# # 🌟 寻路雷达：精准定位 raw_data 文件夹
# # ============================================================
# # 无论你把这个脚本放在 backend 还是 data_pipeline 下，它都会往上找 raw_data
# current_dir = os.path.dirname(os.path.abspath(__file__))
# project_root = os.path.abspath(os.path.join(current_dir, '../')) 
# FILE_PATH = os.path.join(project_root, 'raw_data', 'DMS拣选20260201-0429.XLSX')

# # 如果上面的寻路没找到，做一个极简的 fallback 兜底
# if not os.path.exists(FILE_PATH):
#     FILE_PATH = "../raw_data/DMS拣选20260201-0429.XLSX"

# print(f"📂 正在读取数据文件: {FILE_PATH}")

# # ============================================================
# # 计算每种SKU的平均单件分拣时间
# # 公式：SKU单件耗时 = 所有行的耗时总和 / 所有行的已拣选数量总和
# # ============================================================

# # ---------- 1. 读取数据 ----------
# try:
#     df = pd.read_excel(FILE_PATH, sheet_name=0)
#     print(f'✅ 成功装载原始数据行数: {len(df)}')
# except Exception as e:
#     print(f"❌ 读取文件失败，请确保 {FILE_PATH} 存在！报错: {e}")
#     sys.exit(1)

# # ---------- 2. 计算每行耗时（秒）----------
# df['开始时间'] = pd.to_datetime(df['开始时间'])
# df['结束时间'] = pd.to_datetime(df['结束时间'])
# df['耗时秒'] = (df['结束时间'] - df['开始时间']).dt.total_seconds()

# # ---------- 3. 排除异常行 ----------

# # 规则1：已拣选数量=0（Tote溢出标记行或未实际拣选）
# mask1 = df['已拣选数量'] > 0
# print(f'排除已拣选数量=0的行: {(~mask1).sum()} 行')

# # 规则2：耗时<=0（时间戳异常，结束时间早于或等于开始时间）
# mask2 = df['耗时秒'] > 0
# print(f'排除耗时<=0的行: {(~mask2).sum()} 行')

# # 规则3：确认代码不是"确定"（非正常完成的行）
# mask3 = df['确认代码'] == '确定'
# print(f'排除确认代码非"确定"的行: {(~mask3).sum()} 行')

# # 规则4：保留DMS相关数据（区域含DMS 或 终端ID含DMS 的行都保留）
# mask4_service = (
#     df['服务限定符'].isin(['DMS', 'DMS_URGENT']) |
#     df['区域'].str.contains('DMS', na=False) |
#     df['终端 ID'].str.contains('DMS', na=False)
# )
# print(f'排除非DMS相关的行: {(~mask4_service).sum()} 行（保留：服务类型/区域/终端ID任一含DMS）')

# # 合并规则，得到有效数据
# df_valid = df[mask1 & mask2 & mask3 & mask4_service].copy()
# print(f'过滤后有效数据行数: {len(df_valid)}')
# print()

# # ---------- 4. 排除耗时极端异常值（IQR方法，按SKU内部过滤）----------
# # 计算单件耗时（每行）
# df_valid['单件耗时'] = df_valid['耗时秒'] / df_valid['已拣选数量']

# # 用全局IQR过滤极端值（3倍IQR以外）
# Q1 = df_valid['单件耗时'].quantile(0.25)
# Q3 = df_valid['单件耗时'].quantile(0.75)
# IQR = Q3 - Q1
# lower = Q1 - 3 * IQR
# upper = Q3 + 3 * IQR

# mask4 = df_valid['单件耗时'].between(lower, upper)
# print(f'单件耗时 IQR范围: [{lower:.2f}s, {upper:.2f}s]')
# print(f'排除IQR极端异常行: {(~mask4).sum()} 行')

# df_clean = df_valid[mask4].copy()
# print(f'最终参与计算的行数: {len(df_clean)}')
# print()

# # ---------- 5. 计算每种SKU的加权平均单件耗时 ----------
# # 公式：单件平均耗时 = sum(耗时秒) / sum(已拣选数量)
# sku_stats = df_clean.groupby('SKU').agg(
#     物料名称        = ('物料名称', 'first'),
#     出现行数        = ('耗时秒', 'count'),
#     总已拣选数量    = ('已拣选数量', 'sum'),
#     总耗时秒        = ('耗时秒', 'sum'),
# ).reset_index()

# sku_stats['单件平均耗时秒'] = (sku_stats['总耗时秒'] / sku_stats['总已拣选数量']).round(3)
# sku_stats = sku_stats.sort_values('单件平均耗时秒', ascending=False).reset_index(drop=True)

# # ---------- 6. 只保留3列，重命名 ----------
# result = sku_stats[['SKU', '物料名称', '单件平均耗时秒']].copy()
# result.columns = ['SKU', '物料名称', '单个SKU拣选时间(秒)']
# result = result.sort_values('单个SKU拣选时间(秒)', ascending=False).reset_index(drop=True)

# # ---------- 7. 保存到 TXT ----------
# output_txt = 'DMS拣选20260201-0429_SKU平均分拣时间.txt'
# with open(output_txt, 'w', encoding='utf-8') as f:
#     f.write(f'{"SKU":<25} {"物料名称":<25} {"单个SKU拣选时间(秒)":>18}\n')
#     f.write('-' * 72 + '\n')
#     for _, row in result.iterrows():
#         f.write(f'{row["SKU"]:<25} {row["物料名称"]:<25} {row["单个SKU拣选时间(秒)"]:>18.3f}\n')
# print(f'共 {len(result)} 种SKU，结果已保存至: {output_txt}')

# # ---------- 8. 打印前20行预览 ----------
# print()
# print(result.head(20).to_string(index=False))



# 文件路径: backend/sku_avg_time.py
import pandas as pd
import numpy as np
import sys
import io
import os

# 强制输出流采用 UTF-8 编码，防止 Windows 终端打印物料名称时出现中文乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ============================================================
# 🌟 寻路雷达：精准定位 raw_data 和 数据库
# ============================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '../')) 

if project_root not in sys.path:
    sys.path.append(project_root)

from database import SessionLocal, PartMaster

FILE_PATH = os.path.join(project_root, 'raw_data', 'DMS拣选20260201-0429.XLSX')
if not os.path.exists(FILE_PATH):
    FILE_PATH = "../raw_data/DMS拣选20260201-0429.XLSX"

print(f"📂 正在读取原始生产大账本: {FILE_PATH}")

# ============================================================
# 核心工艺清洗算法 (保留甲方提供的原生 Excel IQR 过滤逻辑)
# ============================================================

# ---------- 1. 读取历史全量数据 ----------
try:
    df = pd.read_excel(FILE_PATH, sheet_name=0)
    print(f'✅ 成功装载原始数据行数: {len(df)}')
except Exception as e:
    print(f"❌ 读取文件失败，请检查路径！报错: {e}")
    sys.exit(1)

# ---------- 2. 计算每行实际动作耗时（秒）----------
df['开始时间'] = pd.to_datetime(df['开始时间'])
df['结束时间'] = pd.to_datetime(df['结束时间'])
df['耗时秒'] = (df['结束时间'] - df['开始时间']).dt.total_seconds()

# ---------- 3. 排除异常怠工与干扰数据 ----------
mask1 = df['已拣选数量'] > 0
mask2 = df['耗时秒'] > 0
mask3 = df['确认代码'] == '确定'

df_valid = df[mask1 & mask2 & mask3].copy()
df_valid['单件耗时'] = df_valid['耗时秒'] / df_valid['已拣选数量']

# ---------- 4. 利用 IQR 算法进行物理去噪 ----------
Q1 = df_valid['单件耗时'].quantile(0.25)
Q3 = df_valid['单件耗时'].quantile(0.75)
IQR = Q3 - Q1
lower = Q1 - 3 * IQR
upper = Q3 + 3 * IQR

df_clean = df_valid[df_valid['单件耗时'].between(lower, upper)].copy()
print(f'🚀 过滤干扰后，参与标准提纯的有效行数: {len(df_clean)}')

# ---------- 5. 按真实 SKU 分组计算加权单件平均分拣时间 ----------
sku_stats = df_clean.groupby('SKU').agg(
    物料名称        = ('物料名称', 'first'),
    总已拣选数量    = ('已拣选数量', 'sum'),
    总耗时秒        = ('耗时秒', 'sum'),
).reset_index()

sku_stats['单件平均耗时秒'] = (sku_stats['总耗时秒'] / sku_stats['总已拣选数量']).round(3)
sku_stats = sku_stats.sort_values('单件平均耗时秒', ascending=False).reset_index(drop=True)

print("\n📝 【提纯后的真实 SKU 工艺耗时库 (Top 5)】")
print(sku_stats[['SKU', '物料名称', '单件平均耗时秒']].head(5).to_string(index=False))

# ============================================================
# 💾 将算法生成的干净数据直插数据库 (大扫除覆盖模式)
# ============================================================
print("\n🔄 开始向数据库同步纯净的工艺定额...")

db = SessionLocal()
if hasattr(db, '__next__'): 
    db = next(db)

try:
    # 🌟 核心：先无情清空历史所有的废弃假数据
    deleted_rows = db.query(PartMaster).delete()
    print(f"🧹 已清空历史废弃工艺数据: {deleted_rows} 条")
    
    insert_count = 0
    
    # 遍历我们刚用算法算出来的 DataFrame，全部作为新数据插入
    for _, row in sku_stats.iterrows():
        raw_sku = str(row['SKU']).strip()  
        avg_time = float(row['单件平均耗时秒'])
        
        new_part = PartMaster(
            part_type=raw_sku,        
            standard_p_time=avg_time  
        )
        db.add(new_part)
        insert_count += 1
            
    # 提交事务
    db.commit()
    print("=" * 50)
    print(f"🎉 算法清洗端到端同步大捷！")
    print(f"▶️ 成功录入纯净的真实物理 SKU: {insert_count} 条")
    print("=" * 50)

except Exception as e:
    db.rollback()
    print(f"❌ 写入数据库失败，事务已回滚！详细错误: {e}")
finally:
    db.close()
    print("🔌 数据库连接已安全断开。")