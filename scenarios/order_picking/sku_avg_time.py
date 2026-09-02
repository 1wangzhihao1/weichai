import pandas as pd
import numpy as np
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from scenarios.order_picking.data_paths import historical_picking_excel

# ============================================================
# 计算每种SKU的平均单件分拣时间
# 公式：SKU单件耗时 = 所有行的耗时总和 / 所有行的已拣选数量总和
# ============================================================

# ---------- 1. 读取数据 ----------
df = pd.read_excel(historical_picking_excel(), sheet_name=0)
print(f'原始数据行数: {len(df)}')

# ---------- 2. 计算每行耗时（秒）----------
df['开始时间'] = pd.to_datetime(df['开始时间'])
df['结束时间'] = pd.to_datetime(df['结束时间'])
df['耗时秒'] = (df['结束时间'] - df['开始时间']).dt.total_seconds()

# ---------- 3. 排除异常行 ----------

# 规则1：已拣选数量=0（Tote溢出标记行或未实际拣选）
mask1 = df['已拣选数量'] > 0
print(f'排除已拣选数量=0的行: {(~mask1).sum()} 行')

# 规则2：耗时<=0（时间戳异常，结束时间早于或等于开始时间）
mask2 = df['耗时秒'] > 0
print(f'排除耗时<=0的行: {(~mask2).sum()} 行')

# 规则3：确认代码不是"确定"（非正常完成的行）
mask3 = df['确认代码'] == '确定'
print(f'排除确认代码非"确定"的行: {(~mask3).sum()} 行')

# 规则4：保留DMS相关数据（区域含DMS 或 终端ID含DMS 的行都保留）
mask4_service = (
    df['服务限定符'].isin(['DMS', 'DMS_URGENT']) |
    df['区域'].str.contains('DMS', na=False) |
    df['终端 ID'].str.contains('DMS', na=False)
)
print(f'排除非DMS相关的行: {(~mask4_service).sum()} 行（保留：服务类型/区域/终端ID任一含DMS）')

# 合并规则，得到有效数据
df_valid = df[mask1 & mask2 & mask3 & mask4_service].copy()
print(f'过滤后有效数据行数: {len(df_valid)}')
print()

# ---------- 4. 保留整装与拆零的全部正常耗时 ----------
# 计算单件耗时（每行）
df_valid['单件耗时'] = df_valid['耗时秒'] / df_valid['已拣选数量']

df_clean = df_valid.copy()
fast_rows = int((df_clean['单件耗时'] <= 0.5).sum())
print(f'保留整装/拆零全部正常耗时记录，最终参与计算的行数: {len(df_clean)}')
print(f'其中单件耗时 <= 0.5 秒的快速整装/短耗时记录: {fast_rows} 行')
print()

# ---------- 5. 计算每种SKU的加权平均单件耗时 ----------
# 公式：单件平均耗时 = sum(耗时秒) / sum(已拣选数量)
sku_stats = df_clean.groupby('SKU').agg(
    物料名称        = ('物料名称', 'first'),
    出现行数        = ('耗时秒', 'count'),
    总已拣选数量    = ('已拣选数量', 'sum'),
    总耗时秒        = ('耗时秒', 'sum'),
).reset_index()

sku_stats['单件平均耗时秒'] = (sku_stats['总耗时秒'] / sku_stats['总已拣选数量']).round(3)
sku_stats = sku_stats.sort_values('单件平均耗时秒', ascending=False).reset_index(drop=True)

# ---------- 6. 只保留3列，重命名 ----------
result = sku_stats[['SKU', '物料名称', '单件平均耗时秒']].copy()
result.columns = ['SKU', '物料名称', '单个SKU拣选时间(秒)']
result = result.sort_values('单个SKU拣选时间(秒)', ascending=False).reset_index(drop=True)

# ---------- 7. 保存到 TXT ----------
output_txt = 'DMS拣选20260201-0429_SKU平均分拣时间.txt'
with open(output_txt, 'w', encoding='utf-8') as f:
    f.write(f'{"SKU":<25} {"物料名称":<25} {"单个SKU拣选时间(秒)":>18}\n')
    f.write('-' * 72 + '\n')
    for _, row in result.iterrows():
        f.write(f'{row["SKU"]:<25} {row["物料名称"]:<25} {row["单个SKU拣选时间(秒)"]:>18.3f}\n')
print(f'共 {len(result)} 种SKU，结果已保存至: {output_txt}')

# ---------- 8. 打印前20行预览 ----------
print()
print(result.head(20).to_string(index=False))
