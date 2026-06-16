# 订单分拣仿真系统仓库

本仓库用于运行完整的订单分拣智能调度与数字孪生仿真系统。系统包含 MySQL 数据库、FastAPI 后端、强化学习调度模型、SimPy 离散事件仿真、库存预处理、订单导入接口和 Vue 3 前端大屏。

## 1. 仓库范围

仿真仓库建议保留当前项目的全部内容：

```text
backend/                    # FastAPI 服务、数据库模型、订单导入、SKU 平均耗时计算
core_engine/                # 仿真资源模型和规则
scenarios/                  # 强化学习环境、训练脚本、库存预处理、对比脚本
weichai-aps-frontend/       # Vue 3 + Three.js 数字孪生大屏
data/                       # 轻量输入数据和库存快照
raw_data/                   # 原始 Excel 数据
output/                     # 模型、playbook、调度结果、前端渲染数据
requirements.txt            # Python 依赖
README_simulation.md        # 本说明文件
```

`venv/` 通常不建议提交到 Git。如果甲方要求离线复制后即可运行，可以随交付包保留；如果走标准代码仓库，建议通过 `requirements.txt` 重新安装依赖。

## 2. 系统功能

本系统实现以下流程：

1. 从 Excel 或 JSON 导入订单到数据库。
2. 从历史拣选数据重建 SKU 平均拣选时间。
3. 将库存 Excel 预处理为库存快照 JSON。
4. 根据库存快照进行订单预处理：可执行订单进入调度，缺料订单进入异常队列。
5. 使用强化学习模型生成订单到站台的分配策略。
6. 使用 SimPy 按站台资源、传送带、缓冲区等约束进行离散事件仿真。
7. 输出仿真任务状态、调度结果、playbook 和前端 3D 渲染数据。
8. 前端大屏展示策略对比、订单进度、站台状态和 3D 数字孪生动画。

## 3. 技术栈

后端：

```text
Python
FastAPI
Uvicorn
SQLAlchemy
MySQL
SimPy
Gymnasium
Stable-Baselines3
sb3-contrib MaskablePPO
Pandas / OpenPyXL
```

前端：

```text
Vue 3
Vite
Element Plus
Three.js
ECharts
Axios
```

## 4. 数据库准备

当前数据库连接配置在：

```text
backend/database.py
```

默认连接：

```text
mysql+pymysql://root:mengdi@127.0.0.1:3306/weichai_aps
```

请先在 MySQL 中创建数据库：

```sql
CREATE DATABASE weichai_aps DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后初始化数据库表：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python database.py
```

主要表：

```text
t_part_master       SKU 标准拣选时间
t_station_master    站台物理参数
t_order_pool        订单主表
t_order_bom         订单 SKU 明细
t_simulation_task   仿真任务汇总
t_dispatch_result   订单/箱体到站台的仿真结果
```

## 5. Python 环境

```powershell
cd D:\weichai\weichai_model_rules_malfunction
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

如果运行 Excel 读取脚本，必须有：

```text
openpyxl
pandas
```

当前 `requirements.txt` 已包含这些依赖。

## 6. 前端环境

```powershell
cd D:\weichai\weichai_model_rules_malfunction\weichai-aps-frontend
npm install
```

启动前端：

```powershell
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

## 7. 数据准备

项目当前依赖的原始数据：

```text
raw_data/DMS拣选20260201-0429.XLSX
raw_data/7.1/7.1拣选.XLSX
raw_data/7.1/7.1早库存单元.XLSX
raw_data/7.1/7.1晚库存单元.XLSX
```

库存快照缓存：

```text
data/inventory/2025-07-01-morning.json
data/inventory/2025-07-01-evening.json
```

如果库存快照不存在，运行：

```powershell
python scenarios\order_picking\inventory_preprocess.py
```

或在后端接口加载库存时自动生成默认快照。

## 8. 重建 SKU 平均拣选时间

首次运行或更新拣选数据后，建议重建 `t_part_master`：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
python sku_avg_time.py
```

当前规则：

1. 使用完整 SKU 编码，区分 `D00` 和 `A01` 后缀。
2. 保留极短整装拣选记录。
3. 只过滤极长异常值。
4. 加权平均计算单件 SKU 拣选时间。
5. 写入数据库表 `t_part_master`。

## 9. 导入订单

订单正式导入入口是后端接口：

```http
POST /api/v1/orders/upload
```

实际对接甲方系统时，甲方只需要按接口格式提交 JSON 报文。下面先说明“甲方已有订单 JSON 文件”的导入方式，然后再说明项目内置的 Excel 客户端模拟脚本。

### 9.1 甲方已有订单 JSON 文件时如何导入

订单 JSON 文件需要符合以下格式：

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
    },
    {
      "order_id": "PICK002",
      "part_type": "610800050011:A01",
      "quantity": 1
    }
  ]
}
```

字段含义：

```text
batch_no    订单波次号，例如 ORDER_WAVE_2025-07-01
order_id    订单号或拣选单号
part_type   SKU 编码，建议保留完整编码和后缀，例如 610800050009:D00
quantity    该订单需要的 SKU 数量
```

假设甲方提供的文件路径是：

```text
D:\weichai\customer_orders\orders_2025_07_01.json
```

先启动后端服务：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python server.py
```

然后另开一个终端，通过接口上传 JSON 文件：

```powershell
$json = Get-Content D:\weichai\customer_orders\orders_2025_07_01.json -Raw -Encoding UTF8
Invoke-RestMethod `
  -Uri http://127.0.0.1:8088/api/v1/orders/upload `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $json
```

上传成功后，数据库中的 `t_order_pool` 和 `t_order_bom` 会写入该波次订单。之后仿真或纯调度接口使用同一个 `batch_no` 即可，例如：

```json
{
  "batch_no": "ORDER_WAVE_2025-07-01",
  "inventory_snapshot_id": "2025-07-01-morning",
  "evening_snapshot_id": "2025-07-01-evening"
}
```

### 9.2 使用脚本模拟甲方系统导入历史 DMS 拣选订单

下面两个脚本只是本项目提供的“客户端模拟器”，用于模拟甲方系统把 Excel 解析成 JSON 后，再通过 `/api/v1/orders/upload` 导入数据库。

启动后端服务后，可以运行：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
python simulate_weichai_client.py
```

该脚本流程：

1. 读取 `raw_data/DMS拣选20260201-0429.XLSX`。
2. 按日期生成波次，例如 `ORDER_WAVE_2026-04-11`。
3. 将 Excel 转为 JSON 报文。
4. 调用后端接口 `/api/v1/orders/upload` 写入数据库。

也就是说，`simulate_weichai_client.py` 不是绕过接口直接写库，而是模拟甲方通过接口上传订单。

### 9.3 使用脚本模拟甲方系统导入 7 月 1 日拣选订单

推荐使用接口模式：

```powershell
cd D:\weichai\weichai_model_rules_malfunction\backend
python import_july1_picking.py --mode api --api-url http://127.0.0.1:8088/api/v1
```

该脚本流程：

1. 读取 `raw_data/7.1/7.1拣选.XLSX`。
2. 聚合同一订单下的 SKU 数量。
3. 生成 `/api/v1/orders/upload` 所需的 JSON 报文。
4. 调用后端接口写入数据库。

脚本仍保留 `--mode db`，用于本地调试时直接写数据库；正式说明和演示建议使用 `--mode api`，这样更贴近甲方系统接入方式。

默认波次号：

```text
ORDER_WAVE_2025-07-01
```

如果只想检查解析结果，不写数据库：

```powershell
python import_july1_picking.py --dry-run
```

## 10. 启动后端服务

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

如果 Windows 报 PyTorch DLL 加载失败或页面文件太小，需要关闭占用内存的程序，或调大系统页面文件。

## 11. 主要 API

### 11.1 上传订单

```http
POST /api/v1/orders/upload
```

请求示例：

```json
{
  "batch_no": "ORDER_WAVE_2025-07-01",
  "orders": [
    {
      "order_id": "PICK001",
      "part_type": "610800050009:D00",
      "quantity": 10
    }
  ]
}
```

### 11.2 启动完整仿真

```http
POST /api/v1/simulation/start
```

请求示例：

```json
{
  "batch_no": "ORDER_WAVE_2025-07-01",
  "inventory_snapshot_id": "2025-07-01-morning",
  "evening_snapshot_id": "2025-07-01-evening",
  "shortage_policy": "exception_queue"
}
```

返回：

```json
{
  "task_id": "TASK-20260614195057"
}
```

### 11.3 查询仿真状态

```http
GET /api/v1/simulation/status/{task_id}
```

仿真运行时会不断更新进度。`/simulation/start` 返回 `task_id` 后，不需要等待终端全部输出完再查状态，可以立即轮询该接口。

### 11.4 获取 3D playbook

```http
GET /api/v1/simulation/playbook/{task_id}
```

建议等 `/simulation/status/{task_id}` 返回完成后再调用，否则可能拿不到完整剧本。

### 11.5 纯调度接口

```http
POST /api/v1/schedule/dispatch
GET  /api/v1/schedule/result/{task_id}
```

该接口用于只生成订单到站台的映射结果，不启动完整 3D 仿真。输出文件保存在：

```text
output/schedule_results/
```

## 12. 前后端完整运行步骤

推荐按以下顺序运行：

```powershell
# 1. 进入项目
cd D:\weichai\weichai_model_rules_malfunction

# 2. 激活 Python 环境
.\venv\Scripts\activate

# 3. 初始化数据库
cd backend
python database.py

# 4. 重建 SKU 平均拣选时间
python sku_avg_time.py

# 5. 启动后端
python server.py
```

另开一个终端：

```powershell
# 6. 导入订单，可按需要选择历史订单或 7.1 订单
cd D:\weichai\weichai_model_rules_malfunction\backend
..\venv\Scripts\activate
python import_july1_picking.py --mode api --api-url http://127.0.0.1:8088/api/v1
```

再开一个终端：

```powershell
# 7. 启动前端
cd D:\weichai\weichai_model_rules_malfunction\weichai-aps-frontend
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

在前端选择：

```text
订单波次：ORDER_WAVE_2025-07-01
日初库存快照：2025-07-01-morning
日末校验快照：2025-07-01-evening
```

然后启动仿真。

## 13. 异常订单处理

当前系统在仿真前会调用 `order_preprocessor.py` 做库存预处理。

处理逻辑：

1. 读取订单波次。
2. 读取日初库存快照。
3. 判断每个订单所需 SKU 是否能被库存满足。
4. 可满足订单进入后续调度和仿真。
5. 不可满足订单进入异常队列，不参与后续 AI 调度和 SimPy 仿真。

因此，如果终端出现：

```text
库存预处理完成：输入 581 单，可执行 522 单，缺料异常 59 单。
```

含义是 522 单会继续仿真，59 单会被记录为异常，不会被处理。

## 14. 模型文件

后端默认从以下目录加载最新的 `.zip` 模型：

```text
output/models/
```

当前主要模型：

```text
output/models/ppo_masking_model_v5.zip
```

如果目录中有多个模型，后端会按文件创建时间选择最新模型。为了避免误加载旧模型，交付时建议只保留需要使用的正式模型，或确保 `ppo_masking_model_v5.zip` 是最新文件。

## 15. 输出文件

常见输出位置：

```text
output/playbooks/weichai_ai_animation_script.json    3D 动画剧本
output/playbooks/weichai_order_manifest.json         订单清单
output/playbooks/weichai_order_report.txt            仿真报告
output/schedule_results/                             纯调度输出
output/models/                                       强化学习模型
```

## 16. 常见问题

### 1. 为什么所有策略都超时

常见原因包括：

1. `Config.DEADLINE_SECONDS` 设置过短。
2. `t_part_master` 中缺少当天 SKU，系统使用默认处理时间导致耗时被放大。
3. 没有重新运行 `backend/sku_avg_time.py`。
4. 用了不匹配的订单日期和库存快照。

### 2. 4 月订单使用 7 月 1 日库存为什么全缺料

这不代表真实仓库 7 月 1 日一定无法完成 4 月订单，而是说明当前代码拿 4 月订单 SKU 去匹配 7 月 1 日库存快照时，匹配结果显示这些订单至少有一个 SKU 不满足。因此更合理的测试方式是：7 月 1 日订单配 7 月 1 日库存。

### 3. `/simulation/start` 返回 task_id 后是否要等终端跑完

不需要。`/simulation/start` 会立即返回 `task_id`，后端在后台运行任务。前端或调用方可以马上轮询：

```http
GET /api/v1/simulation/status/{task_id}
```

但 `/simulation/playbook/{task_id}` 最好等任务完成后再调用。

### 4. `/docs` 页面卡住

如果后台正在执行耗时的仿真或 playbook 生成，浏览器可能看起来卡顿。建议先看终端输出和 `/simulation/status/{task_id}`，等任务完成后再请求 playbook。

### 5. 新增 SKU 后是否必须重新训练模型

不一定。新增 SKU 平均处理时间时，优先重新运行 `backend/sku_avg_time.py` 更新 `t_part_master`。只有当订单结构、处理时间分布或站台约束明显变化时，才建议重新训练强化学习模型。

## 17. 推荐交付方式

如果甲方要求拆成两个仓库：

1. 智能调度策略仓库：保留强化学习训练、模型、数据和核心调度逻辑。
2. 仿真系统仓库：保留当前完整项目，包括后端、前端、数据库、仿真和模型调用。

当前方案下，仿真仓库可以直接包含调度策略仓库的一份代码副本，保证完整系统独立可运行。
