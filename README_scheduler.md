# 订单分拣智能调度策略训练说明

## 本次训练改动

当前强化学习训练代码做了三类调整，用于改善反复重启训练导致的抽样重复，并让奖励函数重新对齐整批订单的完工时间。

## 1. 训练步数

训练入口：

```text
scenarios/order_picking/train_agent_v1.py
```

当前推荐一次性训练：

```text
3,000,000 steps
```

不建议继续采用：

```text
1,000,000 + 1,000,000 + 1,000,000
```

因为反复重启训练脚本时，如果随机种子固定，每一轮训练抽到的 1000 单片段序列可能重复。

## 2. 学习率与更新频率

训练脚本已从固定学习率改为线性衰减：

```text
3e-4 -> 3e-5
```

前期保持较快学习速度，后期减小更新步长，降低训练末期的大幅波动。

rollout 参数调整为：

```text
n_steps = 4000
batch_size = 1000
ent_coef = 0.005
```

相比原来的 `n_steps=1000`，现在每次更新会收集更多 episode 片段，曲线通常会更稳。

## 3. 订单片段随机抽样

环境文件：

```text
scenarios/order_picking/rl_environment.py
```

订单片段抽样已从全局随机数：

```python
np.random.randint(...)
```

改为环境自身随机源：

```python
self.np_random.integers(...)
```

这样可以减少每次重启训练后抽样序列重复的问题。

训练脚本默认会按当前时间生成新的训练种子，并在启动时打印出来。如果需要复现实验，可以手动指定：

```powershell
$env:PICKING_TRAIN_SEED = "42"
python scenarios\order_picking\train_agent_v1.py
```

## 4. 奖励函数

当前奖励函数保留原有局部奖励：

```text
jam_delay 惩罚
出口距离惩罚
```

同时在 episode 结束时加入整批订单的 makespan 终结奖励：

```text
如果最终 makespan 小于目标 makespan：给正奖励
如果最终 makespan 超过目标 makespan：按超出时长惩罚
```

这样模型不只学习“每一步少堵一点”，也会学习“整批 1000 单最终完工时间更短”。

## 5. 推荐运行命令

```powershell
cd D:\weichai\weichai_model_rules_malfunction
.\venv\Scripts\activate
python scenarios\order_picking\train_agent_v1.py
```

训练结果保存到：

```text
output/models/ppo_masking_model_v6.zip
```

默认情况下，脚本会从头初始化一个新模型，训练完成后保存到上面的 v6 路径。原来的 `output/models/ppo_masking_model_v5.zip` 不会被覆盖，这样可以避免“旧奖励函数训练出来的模型”和“新奖励函数”混在一起。

如果确实需要在已有 v6 模型基础上续训，可以运行：

```powershell
$env:PICKING_RESUME = "1"
python scenarios\order_picking\train_agent_v1.py
```

建议正式对比新奖励效果时，不开启 `PICKING_RESUME`。

## 6. 训练结果判断

TensorBoard 中的 `rollout/ep_rew_mean` 会因为不同 1000 单片段难度不同而波动。判断模型是否更好，不能只看最后一个点。

建议训练后继续使用：

```powershell
python scenarios\order_picking\compare.py
```

在固定测试集上比较 AI、随机、轮询策略的完工时间。
