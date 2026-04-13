# 文件路径: scenarios/order_picking/compare.py

import os
import sys
import numpy as np
import matplotlib.pyplot as plt

# 强制将项目根目录加入搜索视野
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from rl_environment import PickingEnv
from config import Config

# 设置 Matplotlib 支持中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

def run_simulation(env, strategy, max_stations, model=None):
    """
    运行单次仿真推演
    :param strategy: 'round_robin', 'random', 'ai'
    :param max_stations: 当前允许开启的最大站台数 (模拟资源受限)
    """
    obs, _ = env.reset(seed=888) # 使用固定的种子保证考卷绝对公平
    done = False
    step_count = 0
    
    while not done:
        # 1. 传统工厂轮询法：1,2,3... 极其均匀，无脑死板
        if strategy == "round_robin":
            action = step_count % max_stations
            
        # 2. 随机瞎蒙法
        elif strategy == "random":
            action = np.random.randint(0, max_stations)
            
        # 3. 咱们的强化学习高维上帝视角
        elif strategy == "ai":
            # 制造资源限制结界 (Action Mask)：只允许选前 max_stations 个站台
            action_mask = np.array([True] * max_stations + [False] * (Config.NUM_STATIONS - max_stations))
            
            # AI 进行思考 (deterministic=True 代表不探索，直接输出最高置信度的动作)
            action, _ = model.predict(obs, action_masks=action_mask, deterministic=True)
            action = int(action)
            
        obs, reward, done, _, _ = env.step(action)
        step_count += 1
        
    # 获取真实完工时间
    makespan = np.max(env.unwrapped.station_workloads)
    return makespan

def main():
    print("="*80)
    print("📊 启动 [资源受限降维打击] 多算法横向对比实验")
    print("="*80)

    # 1. 加载刚刚换血的物理沙盘环境
    env = PickingEnv()

    # 2. 尝试加载咱们正在训练/已训练好的 AI 模型
    model_path = os.path.join(project_root, "output/models/ppo_masking_model_v2_cost_saving.zip")
    try:
        model = MaskablePPO.load(model_path, env=env)
        print("✅ 成功装载 AI 大脑！")
    except Exception as e:
        print(f"⚠️ 警告: 尚未找到训练好的 AI 模型 ({model_path})。")
        print("请确保 train_agent_v2.py 至少跑出过一个 .zip 文件。现在仅展示传统算法图表。")
        model = None

    # 3. 设置实验变量 (X轴)：可用站台数从 16 一路卡死到 4
    station_limits = list(range(4, 17))
    
    # 存储 Y轴 结果 (完工总耗时)
    results_rr = []
    results_rand = []
    results_ai = []

    print("\n⏳ 正在进行高强度扫掠演算，请稍候...")
    
    for limit in station_limits:
        # 跑轮询
        ms_rr = run_simulation(env, "round_robin", limit)
        results_rr.append(ms_rr)
        
        # 跑随机
        ms_rand = run_simulation(env, "random", limit)
        results_rand.append(ms_rand)
        
        # 跑 AI (如果模型存在)
        if model:
            ms_ai = run_simulation(env, "ai", limit, model)
            results_ai.append(ms_ai)
            print(f"可用站台: {limit:2d} | 完工耗时 -> AI: {ms_ai:6.1f}s | 轮询: {ms_rr:6.1f}s | 随机: {ms_rand:6.1f}s")
        else:
            print(f"可用站台: {limit:2d} | 完工耗时 -> 轮询: {ms_rr:6.1f}s | 随机: {ms_rand:6.1f}s")

    # ==========================================
    # 🎨 4. 使用 Matplotlib 绘制震撼的降维打击图表
    # ==========================================
    plt.figure(figsize=(10, 6))
    
    # 画传统算法线
    plt.plot(station_limits, results_rand, marker='x', linestyle=':', color='gray', label='Random (受限随机)', linewidth=2)
    plt.plot(station_limits, results_rr, marker='o', linestyle='--', color='blue', label='Round-Robin (受限轮询)', linewidth=2)
    
    # 画 AI 线 (加粗爆红)
    if model:
        plt.plot(station_limits, results_ai, marker='D', linestyle='-', color='red', label='RL-Agent (强化学习智能排程)', linewidth=3)
    
    # 画出 Deadline 死亡红线
    plt.axhline(y=Config.DEADLINE_SECONDS, color='darkred', linestyle='-.', linewidth=2, label=f'Deadline 交期死线 ({Config.DEADLINE_SECONDS}s)')

    # 图表装饰
    plt.title("多目标排程降维打击测试：完工时间 vs 站台启用数", fontsize=16, pad=15)
    plt.xlabel("允许启用的最大站台数量 (个)", fontsize=12)
    plt.ylabel("总完工耗时 Makespan (秒)", fontsize=12)
    plt.xticks(station_limits)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=11)
    
    # 将图表保存为高清图片
    output_img = os.path.join(project_root, "output/performance_comparison.png")
    os.makedirs(os.path.dirname(output_img), exist_ok=True)
    plt.savefig(output_img, dpi=300, bbox_inches='tight')
    
    print("\n" + "="*80)
    print(f"🎉 实验报告已生成！请前往查看图表: {output_img}")
    print("="*80)
    
    # 弹出图表窗口 (如果环境支持)
    plt.show()

if __name__ == "__main__":
    main()