# 文件路径: scenarios/order_picking/train_agent_v2.py
import os
import sys

# 🌟 寻路雷达：强制将项目根目录加入 Python 的搜索视野
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import CheckpointCallback

# 导入咱们的 84 维完美平滑奖励环境
from rl_environment import PickingEnv

def mask_fn(env):
    """
    【动作掩码提取器】
    保留高级防护接口：为第三阶段“宕机强行隔离机器”打好提前量！
    """
    return env.action_masks()

def main():
    print("="*80)
    print("🚀 启动 [第二阶段：极限压榨与接力训练] 工业级 AI 训练炉...")
    print("="*80)

    # 1. 实例化咱们用积木拼出来的物理环境
    raw_env = PickingEnv()
    
    # 2. 穿上“防弹衣”：接入动作掩码拦截器
    env = ActionMasker(raw_env, mask_fn)

    # 3. 存盘点设置
    os.makedirs("./checkpoints_v2", exist_ok=True)
    checkpoint_callback = CheckpointCallback(
        save_freq=50000,
        save_path='./checkpoints_v2/',
        name_prefix='ppo_weichai_v2_cost'
    )

    # 4. 初始化或加载大脑 (🌟 继承已有极品底子继续深造)
    model_name = "ppo_masking_model_v2_cost_saving"
    # 注意这里去 output/models/ 目录下找你的模型
    model_dir = os.path.join(project_root, "output/models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, model_name + ".zip")
    
    if os.path.exists(model_path):
        print(f"📥 发现绝世好丹！正在加载已有模型: {model_path}")
        print("📈 站在巨人的肩膀上继续修炼...")
        # 加载模型，并且一定要把 env 传进去
        model = MaskablePPO.load(
            model_path, 
            env=env, 
            tensorboard_log="./ppo_tensorboard_logs_v2/"
        )
    else:
        print("🌱 未找到旧模型，正在从零开始初始化新脑子...")
        model = MaskablePPO(
            "MlpPolicy", 
            env, 
            verbose=1, 
            learning_rate=0.0003,      
            n_steps=2048,              
            batch_size=256,            
            ent_coef=0.01,             # 保持适度探索，稳扎稳打
            seed=42,                   
            tensorboard_log="./ppo_tensorboard_logs_v2/" 
        )

    # 5. 点火开炉与优雅中断
    try:
        print("💡 正在进行极限压榨训练！随时可以按 Ctrl+C 提前收网。")
        print("💡 提示：如果加载了旧模型，TensorBoard 的步数会接着之前的记录继续画！")
        
        # 🌟 加大药量：再给它 200 万步的时间！
        # reset_num_timesteps=False 保证 TensorBoard 曲线不折断，连续绘制
        model.learn(total_timesteps=2000000, callback=checkpoint_callback, reset_num_timesteps=False)
        print("\n✅ 极限训练自然完成！")
        
    except KeyboardInterrupt:
        print("\n🛑 接收到中断信号 (Ctrl+C)！正在执行紧急闭炉，保存当前最强大脑...")
        
    finally:
        # 覆盖保存这个进化后的终极大脑
        # sb3 保存时会自动加上 .zip 后缀，所以传路径时去掉 .zip
        save_path_no_ext = model_path.replace('.zip', '')
        model.save(save_path_no_ext)
        print(f"💾 终极脑已覆盖保存至: {model_path}")
        print("="*80)

if __name__ == "__main__":
    main()