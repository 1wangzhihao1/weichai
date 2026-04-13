# # 文件路径: core_engine/rules/dispatch_rules.py
# import numpy as np

# class DispatchRules:
#     """
#     【通用规则库：调度与分配大脑】
#     积木特性：纯粹的决策中心。
#     给定当前状态和候选名单，它负责告诉你“下一步该选谁”。
#     无论是传统的老爷车算法，还是最前沿的 AI 大模型，都在此统一调用。
#     """

#     @staticmethod
#     def rule_round_robin(step_counter: int, num_stations: int, valid_masks: np.ndarray = None) -> int:
#         """
#         【传统启发式】：严格轮询 (Round Robin)
#         特点：极度公平，大家轮流干活。
#         高级特性：如果传入了 valid_masks (掩码防弹衣)，遇到满载爆仓的站台会自动跳过，顺延给下一个闲人。
#         """
#         base_idx = step_counter % num_stations
        
#         # 如果没有物理限制，直接返回基础轮询结果
#         if valid_masks is None:
#             return base_idx
        
#         # 如果带了掩码，执行【智能跳过】逻辑
#         for i in range(num_stations):
#             check_idx = (base_idx + i) % num_stations
#             if valid_masks[check_idx]:  # 如果这个站台允许进货
#                 return check_idx
                
#         # 如果所有站台都爆仓了（全为 False），兜底返回原处（理论上外部控制逻辑会先卡住发车）
#         return base_idx

#     @staticmethod
#     def rule_shortest_processing_time(predicted_costs: np.ndarray, valid_masks: np.ndarray = None) -> int:
#         """
#         【传统启发式】：最短处理时间优先 / 贪心算法 (SPT)
#         特点：短视但高效。永远挑当前队列最短、预估完工最早的站台发货。
#         """
#         if valid_masks is None:
#             return int(np.argmin(predicted_costs))
        
#         # 带有物理约束的贪心挑选：把爆仓站台的成本设为无限大
#         masked_costs = np.copy(predicted_costs)
#         masked_costs[~valid_masks] = np.inf 
#         return int(np.argmin(masked_costs))

#     @staticmethod
#     def rule_ai_policy(model, observation: np.ndarray, valid_masks: np.ndarray = None) -> int:
#         """
#         【神级策略】：神经网络降维打击 (RL/PPO)
#         特点：具备上帝视角，能预测未来拥堵。
#         参数：
#             - model: 训练好的 sb3/sb3_contrib 模型
#             - observation: 当前工厂的 67 维全景观察数据
#             - valid_masks: 非法动作安检门
#         """
#         # deterministic=True 确保在交叉验证时，AI 每次面对同样的考卷都给出同样的最优解
#         action, _states = model.predict(observation, action_masks=valid_masks, deterministic=True)
#         return int(action)
# 文件路径: core_engine/rules/dispatch_rules.py

import numpy as np

class DispatchRules:
    """
    复杂动态系统通用调度规则库
    包含：智能AI策略、经典启发式策略、随机策略等。
    """

    # =====================================================================
    # [第一部分] 现有核心策略 (完全保留，未做修改)
    # =====================================================================
    @staticmethod
    def rule_ai_policy(model, obs, valid_masks):
        """智能 AI 统筹策略 (基于 PPO 模型)"""
        # 如果全线爆仓，返回 None 交给上层进行流控等待
        if not np.any(valid_masks):
            return None
            
        action, _ = model.predict(obs, action_masks=valid_masks, deterministic=True)
        return int(action)

    @staticmethod
    def rule_round_robin(step_counter: int, num_stations: int, valid_masks):
        """经典轮询策略 (Round Robin) - 严格遵守物理安检门"""
        if not np.any(valid_masks):
            return None
            
        start_idx = step_counter % num_stations
        for i in range(num_stations):
            idx = (start_idx + i) % num_stations
            if valid_masks[idx]:
                return idx
        return np.where(valid_masks)[0][0]

    # =====================================================================
    # [第二部分] 新增扩充策略 (丰富规则库，增加对比实验维度)
    # =====================================================================
    @staticmethod
    def rule_random(valid_masks):
        """
        【新增】随机发牌策略 (Random Allocation)
        在合法的（未爆仓）的站台中，完全随机选择一个进行派发。
        """
        if not np.any(valid_masks):
            return None
        valid_indices = np.where(valid_masks)[0]
        return np.random.choice(valid_indices)

    @staticmethod
    def rule_least_load(current_loads: list, valid_masks):
        """
        【新增】最少负载优先策略 (Least Load First)
        永远将当前订单派发给“当前物理缓存区最空”的站台，实现最朴素的负载均衡。
        :param current_loads: 长度为 16 的列表，包含各站台当前的物理负载数量。
        """
        if not np.any(valid_masks):
            return None
            
        valid_indices = np.where(valid_masks)[0]
        # 在合法的索引中，找出负载最小的那个
        best_idx = valid_indices[0]
        min_load = current_loads[best_idx]
        
        for idx in valid_indices:
            if current_loads[idx] < min_load:
                min_load = current_loads[idx]
                best_idx = idx
                
        return best_idx

    @staticmethod
    def rule_spt(processing_times: list, valid_masks):
        """
        【新增】最短加工时间优先策略 (Shortest Processing Time, SPT)
        经典运筹学规则：如果多个站台竞争，优先把订单派给处理这批货最快的站台。
        """
        if not np.any(valid_masks):
            return None
            
        valid_indices = np.where(valid_masks)[0]
        best_idx = valid_indices[0]
        min_time = processing_times[best_idx]
        
        for idx in valid_indices:
            if processing_times[idx] < min_time:
                min_time = processing_times[idx]
                best_idx = idx
                
        return best_idx
    # 将此代码追加到 core_engine/rules/dispatch_rules.py 末尾 (在 DispatchRules 类内部)

    @staticmethod
    def rule_fifo(valid_masks):
        """
        【补充】先进先出策略 (FIFO)
        对于本系统的订单派发场景，由于订单是按时间顺序生成的，
        FIFO 在派发层面的体现就是：总是尝试派发给第一个合法的站台。
        """
        if not np.any(valid_masks):
            return None
        # 返回第一个为 True 的索引
        return np.where(valid_masks)[0][0]
    # 将此代码追加到 core_engine/rules/dispatch_rules.py 末尾 (在 DispatchRules 类内部)

    @staticmethod
    def rule_edd(orders: list, valid_masks):
        """
        【扩展预留】最早交货期优先策略 (Earliest Due Date)
        用途：优先处理交期最紧迫的订单。
        前提：需在后续开发中为订单对象增加 due_date 属性。
        """
        if not np.any(valid_masks):
            return None
            
        # 假设 orders 中包含当前待分配的多个订单选项
        # 找到交期最紧迫且有合法站台可接的订单
        # 此处仅为接口预留，实际实现依赖于后续业务对象扩展
        raise NotImplementedError("EDD 策略暂未实装，预留接口用于未来支持交期约束场景。")