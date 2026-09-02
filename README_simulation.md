# 订单分拣仿真系统运行说明

本文档说明当前项目从数据准备、数据库初始化、订单导入、库存快照生成、后端启动、前端启动，到多策略仿真、历史验证和 3D 可视化展示的完整运行流程。

## 1. 项目定位

本项目是订单分拣智能调度与数字孪生仿真系统，当前主要能力包括：

- 从接口导入订单数据到数据库。
- 从拣选 Excel 重建 SKU 平均处理时间。
- 从库存 Excel 生成轻量化库存快照。
- 对普通日订单在仿真前按库存快照做订单预处理，将缺料订单放入异常队列。
- 支持多种订单分配策略：AI 强化学习、轮询、随机、历史分配-真实耗时、历史分配-SKU 平均耗时。
- 将“策略决策”和“仿真执行”解耦：策略层输出订单到站台的分配结果，SimPy 仿真层统一接收分配结果并生成完工时间和 3D 剧本。
- 前端可选择策略、启用站台数、综合作业间隔，并进行 3D 数字孪生演示。
- 后端会补算 AI、轮询、随机三种策略对比，不管当前选择哪个普通策略，都能在前端展示对比结果。
- 支持历史数据验证：比较历史真实净工作时间与仿真完工时间的误差。

## 2. 目录约定

当前项目推荐使用统一数据目录结构：

```text
raw_data/
  historical/
    picking/
      DMS拣选20260201-0429.XLSX
  daily/
    2025-07-01/
      picking/
        2025-07-01_拣选.XLSX
      inventory/
        2025-07-01_早库存单元.XLSX
        2025-07-01_晚库存单元.XLSX
  sku_time/
    其他用于更新 SKU 工时的拣选 Excel

data/
  inventory/
    库存快照 JSON

output/
  models/
    强化学习模型
  playbooks/
    3D 播放剧本和仿真报告
  schedule_results/
    纯调度接口输出
  model_selection/
    最优模型筛选使用的固定测试订单
  docs/
    验证说明、设计说明等 Word 文档
```

新增某一天业务数据时，建议按下面格式放置：

```text
raw_data/daily/YYYY-MM-DD/picking/YYYY-MM-DD_拣选.XLSX
raw_data/daily/YYYY-MM-DD/inventory/YYYY-MM-DD_早库存单元.XLSX
raw_data/daily/YYYY-MM-DD/inventory/YYYY-MM-DD_晚库存单元.XLSX
```

文件名不要求完全固定，但建议包含日期和关键字。库存预处理会根据配置里的关键字查找早库、晚库文件。

## 3. 统一配置文件

主要配置文件：

```text
config/app_config.toml
```

常用配置项：

```toml
[datasets]
active_date = "2025-07-01"
historical_picking_excel = "raw_data/historical/picking/DMS拣选20260201-0429.XLSX"
daily_data_root = "raw_data/daily"

[simulation]
default_batch_no = "ORDER_WAVE_2025-07-01"
default_initial_snapshot_id = "2025-07-01-morning"
default_evening_snapshot_id = "2025-07-01-evening"
default_strategy = "ai"
default_active_station_limit = 16
auto_rebuild_sku_time = false

# AI / 轮询 / 随机等新策略默认使用的综合作业间隔
operation_gap_seconds = 4.139

# 历史分配-真实订单耗时模式使用的综合作业间隔
history_actual_operation_gap_seconds = 5.824

# 历史分配-SKU 平均工时模式使用的综合作业间隔
history_sku_average_operation_gap_seconds = 9.415

[model]
active_model = "ppo_masking_model_v6.zip"
model_dir = "output/models"
```

切换仿真日期时，通常需要改：

- `datasets.active_date`
- `simulation.default_batch_no`
- `simulation.default_initial_snapshot_id`
- `simulation.default_evening_snapshot_id`

切换模型时，通常只需要改：

- `model.active_model`

综合作业间隔说明：

- `operation_gap_seconds = 4.139`：用于 AI、轮询、随机等新策略仿真。该值来自删除 1、2 特殊站台相关订单后的诊断口径，用于表达规范执行下的作业间隔。
- `history_actual_operation_gap_seconds = 5.824`：用于历史分配-真实耗时模式，来自 2026-03 全量站台二分校准。
- `history_sku_average_operation_gap_seconds = 9.415`：用于历史分配-SKU 平均工时模式，来自 2026-03 全量站台二分校准。

## 4. Python 环境

首次运行前安装依赖：

```powershell
cd D:\weichai\weichai_model_rules_malfunction
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

如果读取 Excel 报 `openpyxl` 缺失，说明当前虚拟环境依赖没有装完整，需要重新执行：

```powershell
pip install -r requirements.txt
```

## 5. 数据库初始化

项目使用 MySQL。默认数据库连接在：

```text
backend/database.py
```

默认数据库：

```text
weichai_aps
```

先在 MySQL 中创建数据库：

```sql
CREATE DATABASE weichai_aps DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后初始化表结构：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python database.py
```

主要表：

```text
t_part_master       SKU 标准处理时间
t_station_master    站台基础信息
t_order_pool        订单主表
t_order_bom         订单 SKU 明细
t_simulation_task   仿真任务表
t_dispatch_result   调度结果表 / 3D 剧本时间线来源
```

当前没有新增单独的剧本表。每次仿真结果仍写入 `t_simulation_task` 和 `t_dispatch_result`，因此数据库会保留已经完成任务的派工时间线；前端通过 task_id 获取对应 playbook。

## 6. SKU 平均处理时间

SKU 平均处理时间由：

```text
backend/sku_avg_time.py
```

负责重建，数据写入数据库表：

```text
t_part_master
```

当前规则：

- 按 Excel 数据列名读取字段，不再依赖固定列序号。
- 保留完整 SKU 编码，区分 `D00` 和 `A01`。
- 保留极短整装拣选记录。
- 只过滤极长异常值。
- 剔除目标数量为 0 或已拣选数量为 0 的错误数据。
- 默认扫描 `raw_data/sku_time/` 下所有拣选 Excel。
- 如果手动传入 `--excel`，则只使用命令行指定的 Excel 文件。
- 多份 Excel 中同一 SKU 会合并统计：该 SKU 总耗时除以该 SKU 总已拣选数量。

手动重建：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python sku_avg_time.py
```

指定某几份 Excel 重建：

```powershell
python sku_avg_time.py --excel ..\raw_data\sku_time\DMS拣选20260201-0429.XLSX --excel ..\raw_data\sku_time\7.1拣选.XLSX
```

后端仿真启动时，如果 `config/app_config.toml` 中：

```toml
auto_rebuild_sku_time = true
```

则 `/api/v1/simulation/start` 会在仿真前自动刷新 SKU 平均处理时间。当前默认值为 `false`，建议在手动确认数据源后再刷新。

## 7. 库存快照预处理

库存 Excel 不会在每次环境 reset 时反复读取。系统会先把库存 Excel 预处理成轻量 JSON 快照。

手动生成库存快照：

```powershell
cd D:\weichai\weichai_model_rules_malfunction
.\venv\Scripts\activate
python scenarios\order_picking\inventory_preprocess.py
```

生成位置：

```text
data/inventory/
```

例如：

```text
data/inventory/2025-07-01-morning.json
data/inventory/2025-07-01-evening.json
```

前端下拉框读取的也是这些库存快照。

普通策略与库存关系：

- AI、轮询、随机策略会读取日初库存快照，并在仿真前做订单预处理。
- 如果该日期没有库存快照，普通策略会因为无法加载库存而报错。
- `python server.py --noorder` 只是不按预处理结果重排订单顺序，不代表跳过库存读取。

历史策略与库存关系：

- `历史分配-真实耗时` 和 `历史分配-SKU平均耗时` 直接读取历史拣选 Excel，不依赖日初库存快照。
- 即使某个历史日期没有库存文件，历史策略仍可用于历史复现和 3D 演示。

## 8. 订单导入

正式订单导入接口：

```http
POST /api/v1/orders/upload
```

如果甲方已经有订单 JSON 文件，可以直接通过接口导入。

JSON 格式示例：

```json
{
  "batch_no": "ORDER_WAVE_2025-07-01",
  "orders": [
    {
      "order_id": "PICK001",
      "part_type": "610800050009:D00",
      "quantity": 10
    },
    {
      "order_id": "PICK001",
      "part_type": "610800050010:D00",
      "quantity": 2
    }
  ]
}
```

字段说明：

```text
batch_no    订单波次号，前端按这个波次启动仿真
order_id    订单号
part_type   SKU 编码
quantity    该订单需要的 SKU 数量
```

PowerShell 上传示例：

```powershell
$json = Get-Content D:\weichai\customer_orders\orders_2025_07_01.json -Raw -Encoding UTF8
Invoke-RestMethod `
  -Uri http://127.0.0.1:8088/api/v1/orders/upload `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $json
```

项目内置脚本也可以模拟甲方系统调用接口导入。

导入 7 月 1 日拣选订单：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python import_july1_picking.py --mode api --api-url http://127.0.0.1:8088/api/v1
```

导入历史 DMS 拣选订单：

```powershell
python simulate_weichai_client.py
```

这些脚本的作用是把 Excel 转成接口 JSON，再调用 `/api/v1/orders/upload`，不是绕过接口直接给前端使用。

## 9. 启动后端

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python server.py
```

默认地址：

```text
http://127.0.0.1:8088
```

接口文档：

```text
http://127.0.0.1:8088/docs
```

如果想保留上传订单原始顺序，不使用订单预处理排序启动：

```powershell
python server.py --noorder
```

注意：`--noorder` 不会跳过库存加载，只影响普通策略订单排序。

如果出现 PyTorch 的 `WinError 1455 页面文件太小`，通常是内存或虚拟内存不足。可以关闭占用内存的程序，或调大 Windows 页面文件。

## 10. 启动前端

```powershell
cd D:\weichai\weichai_model_rules_malfunction\weichai-aps-frontend
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

前端会通过 `/api/v1/app/config`、`/api/v1/orders/batches`、`/api/v1/inventory/snapshots` 获取默认波次、默认策略、综合作业间隔和下拉框数据。

## 11. 前端仿真流程

前端控制区当前可选择：

```text
订单波次
分配策略
启用站台 / 站台上限
历史日期
综合间隔(秒)
日初库存快照
日末校验快照
```

策略说明：

```text
AI强化学习              使用 PPO 模型进行订单到站台分配
随机分配                在启用站台范围内随机分配
轮询分配                按站台序号循环分配
历史分配-真实耗时        按历史站台分配，处理时间使用历史订单真实耗时
历史分配-SKU平均耗时     按历史站台分配，处理时间使用 SKU 平均工时
```

点击“启动”后，主要流程是：

1. 前端调用 `/api/v1/simulation/start`。
2. 后端根据策略准备订单。
3. 普通策略读取库存快照并做订单预处理；历史策略读取历史拣选 Excel。
4. 策略层生成订单到站台的派工结果。
5. 后端补算 AI、轮询、随机三策略对比。
6. SimPy 仿真引擎根据派工结果推进站台排队、运输、处理和综合间隔。
7. SimPy 输出总完工时间、站台统计和每个仿真箱的 `spawn/start/end` 时间线。
8. 后端写入 `t_simulation_task` 和 `t_dispatch_result`。
9. 前端轮询 `/api/v1/simulation/status/{task_id}`。
10. 任务完成后，前端读取 `/api/v1/simulation/playbook/{task_id}` 并渲染 3D 动画。

启动仿真接口：

```http
POST /api/v1/simulation/start
```

请求示例：

```json
{
  "batch_no": "ORDER_WAVE_2025-07-01",
  "inventory_snapshot_id": "2025-07-01-morning",
  "evening_snapshot_id": "2025-07-01-evening",
  "strategy": "ai",
  "active_station_limit": 16,
  "history_date": null,
  "process_time_source": "sku_average",
  "operation_gap_seconds": null
}
```

历史策略请求示例：

```json
{
  "batch_no": "HISTORY_2026-03-09",
  "strategy": "history_actual",
  "active_station_limit": 16,
  "history_date": "2026-03-09",
  "process_time_source": "actual",
  "operation_gap_seconds": null
}
```

`operation_gap_seconds = null` 时，后端会按策略自动使用配置文件里的默认值。前端也会在切换策略时自动显示对应默认综合间隔。

返回示例：

```json
{
  "task_id": "TASK-20260828153001"
}
```

查询状态：

```http
GET /api/v1/simulation/status/{task_id}
```

获取 3D 剧本：

```http
GET /api/v1/simulation/playbook/{task_id}
```

建议等状态接口显示完成后再调用 playbook 接口。

## 12. 历史分配策略说明

历史策略用于满足“输入订单相同、订单分配策略相同，仿真计算总工作时间与真实工作时间差值不超过 10%”的验证需求。

历史分配仿真流程：

```text
读取历史拣选 Excel
  -> 按历史日期筛选有效行
  -> 剔除数量为 0、时间无效、站台无效等错误数据
  -> 按“拣选列表 + SKU”聚合成仿真箱
  -> 根据历史站台号生成派工结果 assignments
  -> SimPy 按派工结果执行仿真
  -> 生成总完工时间、站台统计和 3D 剧本时间线
```

历史分配里的“决策”不是模型重新计算，而是从历史表还原：

```text
订单历史上在哪个站台处理，仿真就派给哪个站台。
```

历史数据处理规则：

- 从配置项 `datasets.historical_picking_excel` 指向的历史拣选 Excel 读取历史拣选数据。
- 按数据列名读取，不依赖固定列序号。
- 剔除目标数量为 0、已拣选数量为 0、时间无效、站台无效的错误数据。
- 按当前仿真假设聚合为：一个订单的一种 SKU = 一个仿真箱。
- 历史分配策略按历史站台分配订单。
- 历史表没有真实发车时间，因此订单顺序使用订单最早拣选开始时间近似。

两种处理时间来源：

- `history_actual`：同一订单、同一 SKU 的历史有效行耗时求和。
- `history_sku_avg`：数据库 `t_part_master` 中的 SKU 平均单件工时乘以合并后的数量。

注意：

- 历史策略用于历史复现和验证，不依赖库存快照。
- 前端历史策略仍使用全量站台和全量订单，不默认排除 1、2 站台。
- 删除 1、2 站台相关订单只在测试脚本中作为诊断口径使用。
- 如果前端历史日期有订单波次，但历史 Excel 里没有该日期的有效拣选行，会报 `No valid historical picking rows for YYYY-MM-DD`。

## 13. 缺料异常队列

当前缺料处理逻辑发生在普通策略仿真前的订单预处理阶段。

逻辑如下：

1. 读取订单需要的 SKU。
2. 读取日初库存快照中的 SKU 和基础装载单元信息。
3. 判断订单是否能被当前库存满足。
4. 能满足的订单进入调度和仿真。
5. 不能满足的订单进入异常队列。

例如终端输出：

```text
库存预处理完成：输入 581 单，可执行 522 单，缺料异常 59 单。
```

含义是：

- 522 单会继续参与调度和仿真。
- 59 单被记录为缺料异常，不会被处理。

## 14. 纯智能调度接口

如果只需要“订单到站台的映射结果”，不需要完整 3D 仿真，可以使用纯调度接口：

```http
POST /api/v1/schedule/dispatch
GET  /api/v1/schedule/result/{task_id}
```

输出目录：

```text
output/schedule_results/
```

该接口适合验证调度算法输出，不适合展示完整分拣过程动画。

## 15. 历史验证与综合间隔校准


综合作业间隔由二分法离线校准，不是手动一点点调出来的。

```powershell
cd D:\weichai\weichai_model_rules_malfunction
.\venv\Scripts\activate
python backend\calibrate_operation_gap.py --excel raw_data\historical\picking\DMS拣选20260201-0429.XLSX --month 2026-03 --process-time-source both --sku-time-source db --engine simpy --real-time-mode net --output output\operation_gap_calibration_2026-03_both_net_simpy_db.json
```

当前 2026-03 校准结果：

```text
历史分配-真实耗时：5.824 秒
历史分配-SKU平均耗时：9.415 秒
```

真实时间口径：

```text
真实净工作时间 = 当天最早开始时间到最晚结束时间 - 超过 30 分钟的全局无作业空档
```

SKU 工时来源：

```text
默认 --sku-time-source db，使用数据库 t_part_master，和前端正式仿真一致。
仅做离线复现实验时，才使用 --sku-time-source excel --sku-time-excel xxx.xlsx 从指定 Excel 临时重算。
```



## 16. 强化学习训练

训练脚本：

```text
scenarios/order_picking/train_agent_v1.py
```

进入目录：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\scenarios\order_picking
..\..\venv\Scripts\activate
```

重新训练：

```powershell
set PICKING_RESUME=0
python train_agent_v1.py
```

在已有模型基础上继续训练：

```powershell
set PICKING_RESUME=1
python train_agent_v1.py
```

训练步数、学习率、checkpoint 目录和模型名都来自：

```text
config/app_config.toml
```

正式模型位置：

```text
output/models/ppo_masking_model_v6.zip
```

手动筛选最优模型：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\scenarios\order_picking
..\..\venv\Scripts\activate
python select_best_model.py
```

## 17. 常规完整运行顺序

推荐按以下顺序运行：

```powershell
# 1. 进入项目
cd D:\weichai\weichai_model_rules_malfunction

# 2. 激活 Python 环境
.\venv\Scripts\activate

# 3. 初始化数据库
cd backend
python database.py

# 4. 启动后端
python server.py
```

另开一个终端导入订单：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python import_july1_picking.py --mode api --api-url http://127.0.0.1:8088/api/v1
```

另开一个终端生成库存快照：

```powershell
cd D:\weichai\weichai_model_rules_malfunction
.\venv\Scripts\activate
python scenarios\order_picking\inventory_preprocess.py
```

另开一个终端启动前端：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\weichai-aps-frontend
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

普通策略前端选择：

```text
订单波次：ORDER_WAVE_2025-07-01
策略：AI强化学习 / 轮询分配 / 随机分配
日初库存快照：2025-07-01-morning
日末校验快照：2025-07-01-evening
综合间隔：默认 4.139 秒
```

历史策略前端选择：

```text
策略：历史分配-真实耗时 / 历史分配-SKU平均耗时
历史日期：例如 2026-03-09
综合间隔：前端会自动切换为对应默认值
```

然后点击“启动”。

## 18. 输出文件

常见输出：

```text
output/playbooks/
output/schedule_results/
output/models/
output/model_selection/
output/history_validation_*.json
output/operation_gap_calibration_*.json
output/docs/
```

其中：

- `playbooks/` 保存 3D 动画相关剧本和报告。
- `schedule_results/` 保存纯调度接口输出。
- `models/` 保存正式强化学习模型。
- `model_selection/` 保存最优模型筛选使用的固定测试订单和结果。
- `history_validation_*.json` 保存历史真实时间与仿真完工时间验证结果。
- `operation_gap_calibration_*.json` 保存综合作业间隔校准结果。
- `docs/` 保存 Word 说明材料，例如历史验证说明。

## 19. 常见问题

### 19.1 为什么某天订单全部缺料

通常是订单日期和库存快照日期不匹配。例如用 4 月订单去匹配 7 月 1 日库存，很可能大量 SKU 对不上。建议使用同一天的订单和库存快照。

### 19.2 `/simulation/start` 返回 task_id 后要等终端跑完吗

不需要。`/simulation/start` 会立即返回 `task_id`，任务在后端后台执行。前端或调用方可以立刻轮询：

```http
GET /api/v1/simulation/status/{task_id}
```

但是 playbook 建议等任务完成后再读取。

### 19.3 `/docs` 页面卡住怎么办

如果后端正在跑仿真或生成 playbook，`/docs` 页面可能看起来卡顿。优先看终端输出和状态接口。任务完成后再访问 playbook。

### 19.4 新增 SKU 后是否必须重新训练模型

不一定。新增 SKU 后，优先更新 SKU 平均处理时间，也就是重建 `t_part_master`。只有当订单结构、SKU 工时分布、站台规则明显变化时，才建议重新训练模型。

### 19.5 训练时是否考虑库存

当前强化学习训练主要学习订单到站台的分配策略，不把库存动态约束塞进 RL 环境。库存约束主要在仿真前的订单预处理阶段处理。

### 19.6 为什么历史策略没有库存也能跑

历史策略的目标是复现历史分配和历史处理过程，订单来源是历史拣选 Excel，不走普通日订单库存预处理。因此没有对应日期库存文件时，历史策略仍可以运行。

### 19.7 用历史策略仿真某天，但没有该天库存，算法对比页怎么办

历史策略本身不依赖库存；但算法对比页中的 AI、轮询、随机属于普通策略，会按前端选择的日初库存快照做库存预处理。如果没有对应日期库存快照，却选择了其他日期库存，算法对比页会按被选择的库存快照计算可执行订单、缺料异常订单、稀缺 SKU 等统计，这不是该历史日期的真实库存口径。

`python server.py --noorder` 只关闭订单预处理排序，不关闭库存校验和缺料统计。


