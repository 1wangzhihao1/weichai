


# # 文件路径: scenarios/order_picking/compare.py

# import os
# import sys
# import numpy as np
# import glob
# import matplotlib.pyplot as plt

# # 强制将项目根目录加入搜索视野
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
# if project_root not in sys.path:
#     sys.path.append(project_root)

# from sb3_contrib import MaskablePPO
# from scenarios.order_picking.rl_environment import PickingEnv
# from scenarios.order_picking.config import Config

# # 设置 Matplotlib 支持中文显示
# plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'sans-serif']
# plt.rcParams['axes.unicode_minus'] = False

# def run_simulation(env, strategy, max_stations, model=None):
#     """
#     运行单次仿真推演
#     :param strategy: 'round_robin', 'random', 'ai'
#     :param max_stations: 当前允许开启的最大站台数 (模拟资源受限)
#     """
#     obs, _ = env.reset(seed=888) # 使用固定的种子保证考卷绝对公平
#     done = False
#     step_count = 0
    
#     while not done:
#         # 1. 传统工厂轮询法：1,2,3... 极其均匀，无脑死板
#         if strategy == "round_robin":
#             action = step_count % max_stations
            
#         # 2. 随机瞎蒙法
#         elif strategy == "random":
#             action = np.random.randint(0, max_stations)
            
#         # 3. 咱们的强化学习高维上帝视角
#         elif strategy == "ai":
#             # 结界 1：降本掩码 (关停后几台，强制只允许选前 max_stations 个)
#             energy_saving_mask = np.array([True] * max_stations + [False] * (Config.NUM_STATIONS - max_stations))
            
#             # 结界 2：物理安检门 (获取环境真实的防爆仓掩码)
#             try:
#                 env_internal_mask = env.unwrapped.action_masks()
#             except AttributeError:
#                 env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

#             # 🌟 核心修复：双重结界大一统！既不能发给已关机的，也不能发给已爆仓的！
#             combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
            
#             # 🚨 极限兜底：如果允许开机的那几台【全部爆仓】了怎么办？
#             if not np.any(combined_masks):
#                 combined_masks = energy_saving_mask
            
#             # AI 进行思考 (结合了双重掩码，既降本又防爆)
#             action, _ = model.predict(obs, action_masks=combined_masks, deterministic=True)
#             action = int(action)
            
#         obs, reward, done, _, _ = env.step(action)
#         step_count += 1
        
#     # 🌟 完美适配 V6 物理引擎：直接读取推进后的系统绝对时间！
#     makespan = float(env.unwrapped.global_time)
#     return makespan

# def main():
#     print("="*80)
#     print("📊 启动 [资源受限降维打击] 多算法横向对比实验 (测试集闭卷考试)")
#     print("="*80)

#     # 1. 🌟 挂载 测试集(Test Set)！绝不让 AI 看见平时练的题！
#     env = PickingEnv(dataset_type='test')

#     # 2. 🌟 动态雷达：自动抓取最新炼出来的脑子
#     model_dir = os.path.join(project_root, "output/models")
#     zip_files = glob.glob(os.path.join(model_dir, '*.zip'))
    
#     model = None
#     if zip_files:
#         latest_model_path = max(zip_files, key=os.path.getctime)
#         try:
#             model = MaskablePPO.load(latest_model_path, env=env)
#             print(f"✅ 成功装载最新 AI 大脑: {os.path.basename(latest_model_path)}")
#         except Exception as e:
#             print(f"⚠️ 模型加载失败: {e}")
#     else:
#         print("⚠️ 警告: 尚未找到任何 .zip 模型文件。请确保已经跑过 train_agent 炼丹。")

#     # 3. 设置实验变量 (X轴)：可用站台数从 16 一路卡死到 4
#     station_limits = list(range(4, 17))
    
#     results_rr = []
#     results_rand = []
#     results_ai = []

#     print("\n⏳ 正在使用【后30天未见数据】进行高强度扫掠演算，请稍候...")
    
#     for limit in station_limits:
#         # 跑轮询
#         ms_rr = run_simulation(env, "round_robin", limit)
#         results_rr.append(ms_rr)
        
#         # 跑随机
#         ms_rand = run_simulation(env, "random", limit)
#         results_rand.append(ms_rand)
        
#         # 跑 AI (如果模型存在)
#         if model:
#             ms_ai = run_simulation(env, "ai", limit, model)
#             results_ai.append(ms_ai)
#             print(f"可用站台: {limit:2d} | 完工耗时 -> AI: {ms_ai:6.1f}s | 轮询: {ms_rr:6.1f}s | 随机: {ms_rand:6.1f}s")
#         else:
#             print(f"可用站台: {limit:2d} | 完工耗时 -> 轮询: {ms_rr:6.1f}s | 随机: {ms_rand:6.1f}s")

#     # ==========================================
#     # 🎨 4. 使用 Matplotlib 绘制震撼的降维打击图表
#     # ==========================================
#     plt.figure(figsize=(10, 6))
    
#     plt.plot(station_limits, results_rand, marker='x', linestyle=':', color='gray', label='Random (受限随机)', linewidth=2)
#     plt.plot(station_limits, results_rr, marker='o', linestyle='--', color='blue', label='Round-Robin (受限轮询)', linewidth=2)
    
#     if model:
#         plt.plot(station_limits, results_ai, marker='D', linestyle='-', color='red', label='RL-Agent (强化学习智能排程)', linewidth=3)
    
#     plt.axhline(y=Config.DEADLINE_SECONDS, color='darkred', linestyle='-.', linewidth=2, label=f'Deadline 交期死线 ({Config.DEADLINE_SECONDS}s)')

#     plt.title("多目标排程降维打击测试：未见数据泛化能力评估 (V6 引擎版)", fontsize=16, pad=15)
#     plt.xlabel("允许启用的最大站台数量 (个)", fontsize=12)
#     plt.ylabel("总完工耗时 Makespan (秒)", fontsize=12)
#     plt.xticks(station_limits)
#     plt.grid(True, alpha=0.3)
#     plt.legend(fontsize=11)
    
#     output_img = os.path.join(project_root, "output/performance_comparison.png")
#     os.makedirs(os.path.dirname(output_img), exist_ok=True)
#     plt.savefig(output_img, dpi=300, bbox_inches='tight')
    
#     print("\n" + "="*80)
#     print(f"🎉 实验报告已生成！请前往查看图表: {output_img}")
#     print("="*80)
    
#     # 弹出图表窗口 (如果环境支持)
#     # plt.show()

# if __name__ == "__main__":
#     main()



# 文件路径: scenarios/order_picking/compare.py

import os
import sys
import numpy as np
import glob
import matplotlib.pyplot as plt
from collections import defaultdict

# 强制将项目根目录加入搜索视野
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from scenarios.order_picking.rl_environment import PickingEnv
from scenarios.order_picking.config import Config

# 设置 Matplotlib 支持中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

def run_simulation(env, strategy, max_stations, model=None):
    """运行单次仿真推演"""
    obs, _ = env.reset(seed=888) 
    done = False
    step_count = 0
    
    while not done:
        if strategy == "round_robin":
            action = step_count % max_stations
        elif strategy == "random":
            action = np.random.randint(0, max_stations)
        elif strategy == "ai":
            # 结界 1：降本掩码
            energy_saving_mask = np.array([True] * max_stations + [False] * (Config.NUM_STATIONS - max_stations))
            
            # 结界 2：环境防爆掩码
            try:
                env_internal_mask = env.unwrapped.action_masks()
            except AttributeError:
                env_internal_mask = np.ones(Config.NUM_STATIONS, dtype=bool)

            combined_masks = np.logical_and(energy_saving_mask, env_internal_mask)
            
            # 兜底：如果允许开机的全爆仓了，强制放行给最闲的一台（V8环境会自动处理）
            if not np.any(combined_masks):
                combined_masks = energy_saving_mask
            
            action, _ = model.predict(obs, action_masks=combined_masks, deterministic=True)
            action = int(action)
            
        obs, reward, done, _, _ = env.step(action)
        step_count += 1
        
    # V8 环境中 global_time 就是最终完工时间
    makespan = float(env.unwrapped.global_time)
    return makespan

def main():
    print("="*80)
    print("📊 启动 [真实单日压力测试] 多算法横向对比实验 (V10 终极版)")
    print("="*80)

    # 1. 挂载测试集数据 (后 30 天未见数据)
    print("🔄 正在加载测试集数据，准备切分时空档案...")
    env = PickingEnv(dataset_type='test')
    test_orders = env.unwrapped.real_world_orders
    
    if not test_orders:
        print("❌ 致命错误：测试集为空，请检查数据文件路径！")
        return

    # ========================================================
    # 🌟 核心引擎：真实单日流量嗅探器
    # ========================================================
    orders_by_date = defaultdict(list)
    for order in test_orders:
        # 提取真实物理时间戳的日期部分
        date_str = order['start_time'].date().isoformat()
        orders_by_date[date_str].append(order)

    # 找出测试集中，单量最大、最繁忙的一天作为“期末考试压力卷”
    busiest_date = max(orders_by_date, key=lambda k: len(orders_by_date[k]))
    daily_orders = orders_by_date[busiest_date]
    actual_test_orders = len(daily_orders)

    print(f"\n📅 成功锁定测试集中最繁忙的一天: 【{busiest_date}】")
    print(f"📦 该日真实独立订单量: {actual_test_orders} 单")
    
    # 强行将环境的数据池替换为这一天的真实数据
    env.unwrapped.real_world_orders = daily_orders
    env.unwrapped.total_orders = actual_test_orders
    env.unwrapped.episode_length = actual_test_orders
    # ========================================================

    # 2. 动态雷达：自动抓取最新炼出来的脑子
    model_dir = os.path.join(project_root, "output/models")
    zip_files = glob.glob(os.path.join(model_dir, '*.zip'))
    
    model = None
    if zip_files:
        latest_model_path = max(zip_files, key=os.path.getctime)
        try:
            model = MaskablePPO.load(latest_model_path, env=env)
            print(f"\n✅ 成功装载最新 AI 大脑: {os.path.basename(latest_model_path)}")
        except Exception as e:
            print(f"\n⚠️ 模型加载失败: {e}")
    else:
        print("\n⚠️ 警告: 尚未找到任何 .zip 模型文件。请确保已经跑过 train_agent 炼丹。")

    # 3. 设置实验变量 (X轴)：1台 到 16台 全量扫掠
    station_limits = list(range(1, 17))
    
    results_rr = []
    results_rand = []
    results_ai = []

    print(f"\n⏳ 正在对 {busiest_date} 的流量进行 1-16 台站台极限压榨...")
    print(f"📌 甲方硬性交期死线: {Config.DEADLINE_SECONDS} 秒")
    print("-" * 70)
    
    for limit in station_limits:
        ms_rr = run_simulation(env, "round_robin", limit)
        results_rr.append(ms_rr)
        
        ms_rand = run_simulation(env, "random", limit)
        results_rand.append(ms_rand)
        
        if model:
            ms_ai = run_simulation(env, "ai", limit, model)
            results_ai.append(ms_ai)
            print(f"可用站台: {limit:2d} | AI最优耗时: {ms_ai:7.1f}s | 传统轮询: {ms_rr:7.1f}s | 随机发车: {ms_rand:7.1f}s")
        else:
            print(f"可用站台: {limit:2d} | 传统轮询: {ms_rr:7.1f}s | 随机发车: {ms_rand:7.1f}s")

    # ==========================================
    # 🎨 4. 图表刻录：自动开启 Y 轴高空视距保护
    # ==========================================
    plt.figure(figsize=(10, 6))
    
    plt.plot(station_limits, results_rand, marker='x', linestyle=':', color='gray', label='Random (受限随机)', linewidth=2)
    plt.plot(station_limits, results_rr, marker='o', linestyle='--', color='blue', label='Round-Robin (受限轮询)', linewidth=2)
    
    if model:
        plt.plot(station_limits, results_ai, marker='D', linestyle='-', color='red', label='RL-Agent (强化学习智能排程)', linewidth=3)
    
    # 绝对死线！(基于 Config.py 自动读取，确保不会错位)
    plt.axhline(y=Config.DEADLINE_SECONDS, color='darkred', linestyle='-.', linewidth=2, label=f'Deadline ({Config.DEADLINE_SECONDS}s)')

    plt.title(f"真实单日压力测试 ({busiest_date} | {actual_test_orders}单) 完工时间 vs 站台启用数", fontsize=15, pad=15)
    plt.xlabel("允许启用的最大站台数量 (个)", fontsize=12)
    plt.ylabel("总完工耗时 Makespan (秒)", fontsize=12)
    plt.xticks(station_limits)
    
    # 🌟 Y轴保护机制：1~3 台机器的耗时绝对会超过 10 万秒。
    # 为了保证图表的美观度，强行将画幅顶部限制在 Deadline 的 1.6 倍高度。
    plt.ylim(0, Config.DEADLINE_SECONDS * 1.6)
    
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=11)
    
    output_img = os.path.join(project_root, "output/performance_comparison.png")
    os.makedirs(os.path.dirname(output_img), exist_ok=True)
    plt.savefig(output_img, dpi=300, bbox_inches='tight')
    
    print("\n" + "="*80)
    print(f"🎉 实验报告已生成！请前往查看高清图表: \n📂 {output_img}")
    print("="*80)

if __name__ == "__main__":
    main()