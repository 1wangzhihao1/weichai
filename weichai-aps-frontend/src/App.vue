<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import api from './api/index' 
import Factory3D from './components/Factory3D.vue' 
import AlgorithmResults from './components/AlgorithmResults.vue' 

const activeTab = ref('sim') // 默认显示 3D 仿真模块 ('sim' 或 'algo')

// 🌟 核心修改 1：将准星对准真实大盘波次，一键启动不迷路！
const batchNo = ref('ORDER_WAVE_2026-04-11')
const inventorySnapshotId = ref('2025-07-01-morning')
const eveningSnapshotId = ref('2025-07-01-evening')
const inventorySnapshots = ref([])

const isSimulating = ref(false)
const progress = ref(0)
const statusMessage = ref('等待下发云端推演指令...')
const simResult = ref(null)
const factoryRef = ref(null) 

// 16 宫格状态数据源
const stationStatus = ref(Array(16).fill().map(() => ({ active: false, orderCount: 0, maxOrders: 2, isPoweredOff: false })))

// 接收 3D 沙盘实时传回的 KPI 数据
const kpiData = reactive({
  ordersDone: 0,
  ordersTotal: 0,
  boxesDone: 0,
  boxesActive: 0,
  boxesTotal: 0,
  progressPct: 0,
  currentTime: 0,
  maxTime: 0
})

let pollTimer = null

const handleStart = async () => {
  isSimulating.value = true
  progress.value = 0
  simResult.value = null
  statusMessage.value = '正在呼叫后台 AI 调度大脑...'
  
  // 自动切回 3D 界面观看
  activeTab.value = 'sim'

  try {
    const res = await api.startSimulation(batchNo.value, inventorySnapshotId.value, eveningSnapshotId.value)
    if (res.code === 200) {
      startPolling(res.task_id)
    }
  } catch (error) {
    statusMessage.value = '呼叫失败！请检查 FastAPI 后端 8088 端口是否运行！'
    isSimulating.value = false
  }
}

const loadInventorySnapshots = async () => {
  try {
    const res = await api.getInventorySnapshots()
    if (res.code === 200 && Array.isArray(res.data)) {
      inventorySnapshots.value = res.data
    }
  } catch (error) {
    inventorySnapshots.value = [
      { snapshot_id: '2025-07-01-morning', summary: {} },
      { snapshot_id: '2025-07-01-evening', summary: {} }
    ]
  }
}

const startPolling = (taskId) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await api.getSimulationStatus(taskId)
      if (res.code === 200) {
        // 🌟 核心修改 2：完美解析后端推过来的百分比字符串
        progress.value = parseInt(res.data.progress.replace('%', ''))
        statusMessage.value = res.data.message || '推演中...'

        // 如果后端传回 failed，立刻停止并报错
        if (res.data.status === 'failed') {
          clearInterval(pollTimer)
          isSimulating.value = false
          return
        }

        if (res.data.status === 'completed' || progress.value === 100) {
          clearInterval(pollTimer)
          isSimulating.value = false
          simResult.value = res.data
          statusMessage.value = '宏观排产完成！正在解析 3D 微观时空剧本...'
          
          await nextTick()
          fetchPlaybookAndPlay(taskId)
        }
      }
    } catch (error) {
      clearInterval(pollTimer)
    }
  }, 1000) // 每秒心跳轮询一次
}

const fetchPlaybookAndPlay = async (taskId) => {
  try {
    const res = await api.getSimulationPlaybook(taskId)
    if (res.code === 200) {
      statusMessage.value = '数据链加载完毕，物理引擎接管！'
      factoryRef.value.loadAndPlay(res.data)
    }
  } catch (error) {
    statusMessage.value = '获取 3D 剧本失败！'
  }
}

const onUpdateStations = (statusArray) => {
  stationStatus.value = statusArray
}

const onUpdateKpi = (data) => {
  Object.assign(kpiData, data)
}

onMounted(() => {
  loadInventorySnapshots()
})
</script>

<template>
  <div class="app-container">
    
    <div class="header">
      <div class="logo-area">🚀 潍柴 APS 智能排产数字孪生大屏 <span class="version-tag">V5.1</span></div>
      
      <div class="tab-switch">
        <div :class="['tab-btn', activeTab === 'algo' ? 'active' : '']" @click="activeTab = 'algo'">
          📊 智能算法对比
        </div>
        <div :class="['tab-btn', activeTab === 'sim' ? 'active' : '']" @click="activeTab = 'sim'">
          🏭 3D 数字孪生
        </div>
      </div>
    </div>

    <div class="layout-main">
      
      <div class="left-panel" v-show="activeTab === 'sim'">
        
        <div class="control-box">
          <div class="panel-title">🎛️ 孪生排产控制中枢</div>
          <div style="display: flex; gap: 10px;">
            <input type="text" class="custom-input" v-model="batchNo" placeholder="请输入要推演的订单批次号" />
            <button class="primary-btn" :disabled="isSimulating" @click="handleStart">
              {{ isSimulating ? '计算中...' : '⚡ 启动' }}
            </button>
          </div>
          
          <div class="inventory-selectors">
            <label>
              <span>日初库存快照</span>
              <select class="custom-select" v-model="inventorySnapshotId">
                <option v-for="item in inventorySnapshots" :key="item.snapshot_id" :value="item.snapshot_id">
                  {{ item.snapshot_id }}
                </option>
              </select>
            </label>
            <label>
              <span>日末校验快照</span>
              <select class="custom-select" v-model="eveningSnapshotId">
                <option v-for="item in inventorySnapshots" :key="item.snapshot_id" :value="item.snapshot_id">
                  {{ item.snapshot_id }}
                </option>
              </select>
            </label>
          </div>

          <div v-if="isSimulating || progress > 0" class="progress-box">
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: progress + '%' }"></div>
            </div>
            <p class="status-msg">{{ statusMessage }}</p>
          </div>
        </div>

        <div class="kpi-monitor" v-if="simResult">
          <div class="panel-title">📊 订单履约总进度</div>
          <div class="progress-track" style="margin-bottom: 15px; height: 12px; border-radius: 6px;">
            <div class="progress-fill" :style="{ width: kpiData.progressPct + '%' }"></div>
          </div>
          
          <div class="kpi-row highlight">
            <span>主订单完工进度:</span> 
            <span class="kpi-val">{{ kpiData.ordersDone }} / {{ kpiData.ordersTotal }}</span>
          </div>
          <div class="kpi-row">
            <span>总计投放实体箱:</span> 
            <span class="kpi-val">{{ kpiData.boxesTotal }}</span>
          </div>
          <div class="kpi-row">
            <span>传送/排队中 (在途):</span> 
            <span class="kpi-val text-warning">{{ kpiData.boxesActive }}</span>
          </div>
          <div class="kpi-row">
            <span>已下线 (完成):</span> 
            <span class="kpi-val text-success">{{ kpiData.boxesDone }}</span>
          </div>
          
          <div class="kpi-divider"></div>
          <div class="kpi-row sub">
            <span>包含回库在内的总耗时:</span> 
            <span class="kpi-val">{{ kpiData.maxTime.toFixed(1) }} s</span>
          </div>
          <div class="kpi-divider"></div>
          <div class="kpi-row sub">
            <span>库存预处理订单:</span>
            <span class="kpi-val">{{ simResult.inventory_result?.preprocess_stats?.processable_order_count || 0 }} / {{ simResult.inventory_result?.preprocess_stats?.input_order_count || 0 }}</span>
          </div>
          <div class="kpi-row sub">
            <span>缺料异常订单:</span>
            <span class="kpi-val text-warning">{{ simResult.inventory_result?.exception_order_count || 0 }}</span>
          </div>
          <div class="kpi-row sub">
            <span>稀缺SKU数量:</span>
            <span class="kpi-val">{{ simResult.inventory_result?.preprocess_stats?.scarce_sku_count || 0 }}</span>
          </div>
          <div class="kpi-row sub">
            <span>预处理重排订单:</span>
            <span class="kpi-val">{{ simResult.inventory_result?.preprocess_stats?.reordered_count || 0 }}</span>
          </div>
        </div>

        <div class="station-monitor">
          <div class="panel-title">📡 产线 16 站台实时状态矩阵</div>
          <div class="st-grid">
            <div v-for="(item, idx) in stationStatus" :key="idx" 
                 :class="['st-card', item.isPoweredOff ? 'off' : (item.active ? 'busy' : 'idle')]">
              <div class="st-header">
                <span class="st-id">S{{ (idx+1).toString().padStart(2, '0') }}</span>
                <span class="st-buffer" v-if="!item.isPoweredOff">订单: {{ item.orderCount }}/{{ item.maxOrders }}</span>
              </div>
              <div class="st-status-text">
                <span class="st-dot"></span>
                {{ item.isPoweredOff ? 'AI 节能休眠' : (item.active ? '组装中' : '待命中') }}
              </div>
            </div>
          </div>
        </div>

      </div>

      <div class="right-panel">
        <AlgorithmResults v-if="activeTab === 'algo'" :simResult="simResult" />
        
        <Factory3D 
          v-show="activeTab === 'sim'" 
          ref="factoryRef" 
          @update-stations="onUpdateStations" 
          @update-kpi="onUpdateKpi" 
        />
      </div>

    </div>
  </div>
</template>

<style scoped>
.app-container { width: 100vw; height: 100vh; background-color: #08121C; color: #ffffff; display: flex; flex-direction: column; overflow: hidden; font-family: 'Helvetica Neue', Arial, sans-serif; }

/* 炫酷的 Header 样式 */
.header { 
  display: flex; justify-content: space-between; align-items: center;
  padding: 15px 30px; background: rgba(15, 25, 40, 0.9); border-bottom: 2px solid #1E3A5F; z-index: 10; 
}
.logo-area { font-size: 20px; font-weight: 900; text-shadow: 0 0 10px rgba(0, 229, 255, 0.5); letter-spacing: 1px; color: #fff; display: flex; align-items: center; gap: 10px;}
.version-tag { font-size: 11px; background: #00E5FF; color: #000; padding: 2px 6px; border-radius: 4px; font-weight: bold;}

/* 切换按钮样式 */
.tab-switch { display: flex; background: rgba(0, 0, 0, 0.5); border-radius: 8px; border: 1px solid #1E3A5F; overflow: hidden; }
.tab-btn { padding: 8px 20px; font-size: 15px; font-weight: bold; cursor: pointer; color: #A0B2C6; transition: all 0.3s; }
.tab-btn:hover { color: #00E5FF; background: rgba(0, 229, 255, 0.1); }
.tab-btn.active { background: #00E5FF; color: #08121C; box-shadow: 0 0 15px rgba(0, 229, 255, 0.5); }

.layout-main { display: flex; flex: 1; padding: 15px; gap: 15px; height: calc(100vh - 65px); box-sizing: border-box; }

.left-panel { flex: 0 0 400px; display: flex; flex-direction: column; gap: 15px; overflow-y: auto; padding-right: 5px; }
.left-panel::-webkit-scrollbar { width: 6px; }
.left-panel::-webkit-scrollbar-thumb { background: #1E3A5F; border-radius: 3px; }

.right-panel { flex: 1; position: relative; border-radius: 12px; overflow: hidden; box-shadow: 0 0 30px rgba(0, 0, 0, 0.5);}

.control-box, .station-monitor, .kpi-monitor { background: rgba(15, 25, 40, 0.7); padding: 20px; border-radius: 10px; border: 1px solid #1E3A5F; box-shadow: 0 4px 15px rgba(0,0,0,0.3); backdrop-filter: blur(10px); }

.panel-title { font-size: 15px; color: #00E5FF; font-weight: bold; margin-bottom: 15px; border-bottom: 1px dashed #1E3A5F; padding-bottom: 8px; }

/* 自定义原生 Input 和 Button */
.custom-input { flex: 1; padding: 8px 12px; background: rgba(0, 0, 0, 0.4); border: 1px solid #1E3A5F; color: #FFF; font-size: 13px; border-radius: 6px; outline: none; transition: 0.3s; }
.custom-input:focus { border-color: #00E5FF; }
.inventory-selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.inventory-selectors label { display: flex; flex-direction: column; gap: 6px; color: #A0B2C6; font-size: 12px; font-weight: bold; }
.custom-select { width: 100%; padding: 8px 10px; background: rgba(0, 0, 0, 0.4); border: 1px solid #1E3A5F; color: #FFF; font-size: 12px; border-radius: 6px; outline: none; }
.custom-select:focus { border-color: #00E5FF; }
.primary-btn { background: linear-gradient(135deg, #00E5FF, #0077FF); border: none; padding: 8px 20px; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; transition: 0.3s; }
.primary-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 10px rgba(0, 229, 255, 0.4); }
.primary-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 进度条 */
.progress-box { margin-top: 15px; }
.progress-track { width: 100%; height: 16px; background: #0A1525; border-radius: 8px; border: 1px solid #1E3A5F; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #0077FF, #00E5FF); transition: width 0.3s ease; }
.status-msg { margin-top: 8px; color: #A0B2C6; font-size: 12px; text-align: center; }

/* 实时大盘 KPI */
.kpi-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; color: #A0B2C6; }
.kpi-row.highlight { color: #fff; font-size: 14px; font-weight: bold; margin-bottom: 12px; }
.kpi-val { font-family: monospace; font-size: 16px; font-weight: bold; color: #fff; }
.text-warning { color: #FFB800; }
.text-success { color: #52C41A; }
.kpi-divider { height: 1px; border-top: 1px dashed #1E3A5F; margin: 12px 0; }
.kpi-row.sub { font-size: 12px; }

/* 16宫格监控网格样式 */
.st-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.st-card { background: rgba(0,0,0,0.4); border: 1px solid #1E3A5F; border-radius: 6px; padding: 8px; display: flex; flex-direction: column; transition: all 0.2s; }
.st-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.st-id { color: #A0B2C6; font-weight: bold; font-size: 14px; }
.st-buffer { font-size: 10px; color: #fff; background: rgba(255,255,255,0.1); padding: 2px 4px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); }
.st-status-text { font-size: 12px; font-weight: bold; display: flex; align-items: center; gap: 5px; }
.st-dot { width: 8px; height: 8px; border-radius: 50%; }

/* 🌟 核心美化：科幻青色满载运行 (替换以前的报错红) */
.st-card.busy { border-color: #00E5FF; background: rgba(0, 229, 255, 0.1); box-shadow: inset 0 0 10px rgba(0, 229, 255, 0.1); }
.st-card.busy .st-status-text { color: #00E5FF; }
.st-card.busy .st-dot { background: #00E5FF; box-shadow: 0 0 8px #00E5FF; }
.st-card.busy .st-id { color: #00E5FF; }
.st-card.busy .st-buffer { background: rgba(0, 229, 255, 0.2); border-color: #00E5FF; color: #fff; }

.st-card.idle { border-color: #52C41A; background: rgba(82, 196, 26, 0.05); }
.st-card.idle .st-status-text { color: #52C41A; }
.st-card.idle .st-dot { background: #52C41A; box-shadow: 0 0 8px #52C41A; }

.st-card.off { border-color: #334155; background: rgba(15, 23, 42, 0.8); opacity: 0.5; }
.st-card.off .st-status-text { color: #64748B; }
.st-card.off .st-dot { background: #475569; }
.st-card.off .st-id { text-decoration: line-through; color: #475569; }
</style>
