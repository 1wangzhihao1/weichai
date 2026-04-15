# 文件路径: scenarios/order_picking/rl_environment.py

import gymnasium as gym
from gymnasium import spaces
import numpy as np

# 🌟 规范引用
from config import Config
from core_engine.models.entity_model import DataLoader, LogicalOrder, PhysicalEntity
from core_engine.models.resource_model import LogicalStation

class PickingEnv(gym.Env):
    def __init__(self, total_orders_to_process=None):
        super().__init__()
        
        print("🧠 AI 大脑正在加载真实车间数据档案...")
        self.real_world_orders = DataLoader.load_history_orders()
        self.total_orders = total_orders_to_process or len(self.real_world_orders)
        
        # ========================================================
        # 🌟 第二阶段大换血：观察空间维度升维
        # 50(零件种类) + 1(当前单耗时) + 16(预测完成时间) + 1(死线紧迫度) + 16(开机状态) = 84维
        # ========================================================
        self.obs_dim = Config.NUM_PART_TYPES + 1 + Config.NUM_STATIONS + 1 + Config.NUM_STATIONS
        self.action_space = spaces.Discrete(Config.NUM_STATIONS)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(self.obs_dim,), dtype=np.float32)

        # 🌟 第三阶段新增：记录当前发生物理宕机的站台集合，用于动作掩码动态切断路由
        self.broken_stations = set()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.np_random, seed = gym.utils.seeding.np_random(seed)
        else:
            self.np_random = np.random.default_rng()

        # 每次重置环境时，清空故障记录
        self.broken_stations = set()

        self.logical_orders = self.real_world_orders[:self.total_orders]
        
        self.order_process_times = []
        self.order_box_p_times = [] 
        
        for order in self.logical_orders:
            box_p_times = [entity.p_time for entity in order.entities]
            self.order_process_times.append(order.total_process_time)
            self.order_box_p_times.append(box_p_times)
            
        self.current_step = 0
        self.global_time = 0.0
        self.last_dispatch_time = 0.0 
        
        self.station_workloads = np.zeros(Config.NUM_STATIONS, dtype=np.float32) 
        self.station_buffers = [[] for _ in range(Config.NUM_STATIONS)] 
        
        # 🌟 第二阶段新增：记录 16 个站台的开机状态 (0: 休眠黑屏, 1: 已通电亮起)
        self.station_active_status = np.zeros(Config.NUM_STATIONS, dtype=np.float32)
        
        self.stations = [LogicalStation(i, Config.BUFFER_CAPACITY) for i in range(Config.NUM_STATIONS)]
        
        return self._get_obs(), {}

    def _calculate_hypothetical_finishes(self, box_p_times):
        hypothetical = np.zeros(Config.NUM_STATIONS)
        num_boxes = len(box_p_times)

        for i in range(Config.NUM_STATIONS):
            # 🌟 回归真实物理法则：调用接口获取主线距离与支线真实耗时
            d_main = Config.get_station_main_distance(i)
            branch_info = Config.get_branch_info(i)
            t_trans = (d_main / Config.BELT_SPEED) + branch_info["transit_time_s"]
            
            buffer_q = list(self.station_buffers[i]) 
            curr_dispatch = self.last_dispatch_time
            worker_free_time = self.station_workloads[i]
            
            for b_idx in range(num_boxes):
                if len(buffer_q) >= Config.BUFFER_CAPACITY:
                    free_time = buffer_q.pop(0)
                    curr_dispatch = max(curr_dispatch + Config.DISPATCH_INTERVAL, free_time - t_trans)
                else:
                    curr_dispatch += Config.DISPATCH_INTERVAL
                    
                arr_time = curr_dispatch + t_trans
                start_p = max(arr_time, worker_free_time)
                finish_p = start_p + box_p_times[b_idx]
                
                worker_free_time = finish_p
                buffer_q.append(finish_p)
                
            hypothetical[i] = worker_free_time
            
        return hypothetical

    def _get_obs(self):
        obs = np.zeros(self.obs_dim, dtype=np.float32)
        if self.current_step < self.total_orders:
            current_order = self.logical_orders[self.current_step]
            
            parts_array = np.zeros(Config.NUM_PART_TYPES, dtype=np.float32)
            for entity in current_order.entities:
                idx = entity.entity_type - 1 
                if 0 <= idx < Config.NUM_PART_TYPES:
                    parts_array[idx] += entity.qty
                    
            obs[0:Config.NUM_PART_TYPES] = parts_array / 50.0 
            # 防止数据溢出：
            obs[Config.NUM_PART_TYPES] = self.order_process_times[self.current_step] / 30000.0
            
            box_p_times = self.order_box_p_times[self.current_step]
            hypothetical = self._calculate_hypothetical_finishes(box_p_times)
            
            obs[Config.NUM_PART_TYPES + 1 : Config.NUM_PART_TYPES + 1 + Config.NUM_STATIONS] = \
                (hypothetical - np.min(hypothetical)) / (np.max(hypothetical) - np.min(hypothetical) + 1e-6)
            
            # ========================================================
            # 🌟 第二阶段新增：给 AI 植入“时间观”和“成本观”
            # ========================================================
            base_idx = Config.NUM_PART_TYPES + 1 + Config.NUM_STATIONS
            
            # 特征A：Deadline 紧迫度 (当前时间/死线时间)
            obs[base_idx] = min(self.global_time / Config.DEADLINE_SECONDS, 1.0)
            # 特征B：当前哪些机器是免费(已开启)的，哪些是要扣分(待开启)的
            obs[base_idx + 1 :] = self.station_active_status
            
        return obs

    def step(self, action):
        box_p_times = self.order_box_p_times[self.current_step]
        costs = self._calculate_hypothetical_finishes(box_p_times)
        
        actual_cost = costs[action]
        
        # 🌟 真实物理沙盘更新
        d_main = Config.get_station_main_distance(action)
        branch_info = Config.get_branch_info(action)
        t_trans = (d_main / Config.BELT_SPEED) + branch_info["transit_time_s"]
        
        buffer_q = self.station_buffers[action]
        for b_idx in range(len(box_p_times)):
            if len(buffer_q) >= Config.BUFFER_CAPACITY:
                free_time = buffer_q.pop(0)
                self.last_dispatch_time = max(self.last_dispatch_time + Config.DISPATCH_INTERVAL, free_time - t_trans)
            else:
                self.last_dispatch_time += Config.DISPATCH_INTERVAL
                
            arr_time = self.last_dispatch_time + t_trans
            start_p = max(arr_time, self.station_workloads[action])
            finish_p = start_p + box_p_times[b_idx]
            
            self.station_workloads[action] = finish_p
            buffer_q.append(finish_p)
            
        self.global_time = self.last_dispatch_time
        self.stations[action].free_at = self.station_workloads[action]

        # ========================================================
        # 🌟 平滑奖励体系
        # ========================================================
        is_new_machine = False
        if self.station_active_status[action] == 0.0:
            is_new_machine = True
            self.station_active_status[action] = 1.0 
            
        reward = 0.0
        
        # 1. 局部引导：只在“已开机”的机器里做负载均衡
        active_indices = np.where(self.station_active_status == 1.0)[0]
        if len(active_indices) > 0 and not is_new_machine:
            active_costs = costs[active_indices]
            if actual_cost == np.min(active_costs):
                reward += 1.0  
            else:
                reward -= 0.5  
                
        # 2. 温和的开机阻力
        if is_new_machine:
            reward -= 2.0  

        self.current_step += 1
        done = self.current_step >= self.total_orders
        
        # 3. 终局结算
        if done:
            makespan = np.max(self.station_workloads)
            active_machines = int(np.sum(self.station_active_status))
            
            makespan_score = (80000.0 - makespan) / 100.0
            saved_machines = Config.NUM_STATIONS - active_machines
            machine_score = saved_machines * 20.0
            
            reward += (makespan_score + machine_score)

        return self._get_obs(), float(reward), done, False, {}

    # ========================================================
    # 🌟 第三阶段终极重构：面向对象的外部合法控制接口 (Hooks)
    # 仅供外部 API 网关或调度主引擎按需调用，绝不自作主张！
    # ========================================================
    
    def action_masks(self):
        """
        基于当前宕机名单，动态生成合法动作掩码矩阵。
        """
        masks = np.ones(Config.NUM_STATIONS, dtype=bool)
        for sid in self.broken_stations:
            masks[sid] = False
            
        # 安全兜底：如果遭遇极端情况所有机器都坏了，强行解开0号机器避免程序死锁报错
        if not np.any(masks):
            print("⚠️ [RL Env] 致命警告：所有站台均处于宕机状态，为防止系统死锁，强制保留 0 号站台路由！")
            masks[0] = True
            
        return masks

    def trigger_breakdown(self, station_ids: list):
        """
        【合法接口】接收外部指令，将指定站台加入宕机黑名单，触发动作掩码屏蔽。
        """
        for sid in station_ids:
            self.broken_stations.add(sid)
        print(f"💥 [RL Env 接收到外部中断] 动作掩码动态切流！已切断通往故障站台 {station_ids} 的派发路由。")

    def trigger_fixed(self, station_ids: list):
        """
        【合法接口】接收外部指令，将指定站台从宕机黑名单移除，恢复路由。
        """
        for sid in station_ids:
            if sid in self.broken_stations:
                self.broken_stations.remove(sid)
        print(f"🔧 [RL Env 接收到外部恢复] 路由恢复！站台 {station_ids} 已修复，AI 可重新向其派发订单。")

    def trigger_vip_order(self, vip_order):
        """
        【合法接口】接收外部 API 传来的加急订单实体，安全地将其插入排程队列队首。
        彻底消除以前在外部文件强行篡改内部数据的恶性耦合。
        """
        # 将订单实体安全推入逻辑队列
        self.logical_orders.insert(self.current_step, vip_order)
        
        # 安全同步更新特征数组（保证长度与逻辑队列一致）
        box_p_times = [entity.p_time for entity in vip_order.entities]
        self.order_process_times.insert(self.current_step, vip_order.total_process_time)
        self.order_box_p_times.insert(self.current_step, box_p_times)
        
        # 总任务数扩容
        self.total_orders += 1
        print(f"🚨 [RL Env 接收到外部插单] 成功完成队首插单封装！AI 将在下个 Step 立刻处理加急订单。")