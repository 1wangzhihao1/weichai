// // 文件路径: src/api/index.js
// import axios from 'axios'

// // 创建一个 Axios 实例，枪口对准你的 FastAPI 后端
// const request = axios.create({
//   baseURL: 'http://localhost:8088/api/v1', 
//   timeout: 30000 // 留足 30 秒超时时间，给 AI 寻优推演留足余地
// })

// // 响应拦截器：自动把包装盒剥掉，只留核心数据
// request.interceptors.response.use(response => {
//   return response.data 
// }, error => {
//   console.error('网络请求炸了:', error)
//   return Promise.reject(error)
// })

// // 暴露 5 大核心接口供咱们的大屏调用
// export default {
//   uploadMasterData(data) {
//     return request.post('/master_data/upload', data)
//   },
//   uploadOrders(data) {
//     return request.post('/orders/upload', data)
//   },
//   startSimulation(batchNo) {
//     return request.post('/simulation/start', { batch_no: batchNo })
//   },
//   getSimulationStatus(taskId) {
//     return request.get(`/simulation/status/${taskId}`)
//   },
//   getSimulationPlaybook(taskId) {
//     return request.get(`/simulation/playbook/${taskId}`)
//   }
// }


// 文件路径: src/api/index.js
import axios from 'axios'

// 创建 Axios 实例
const request = axios.create({
  // 🌟 核心优化：改为相对路径 '/api/v1'。
  // 这样请求会先发给前端所在的域，然后被 vite.config.js 里的 proxy 完美拦截并转发给 8088 端口！
  baseURL: '/api/v1', 
  timeout: 30000 // 留足 30 秒超时时间，给 AI 寻优推演留足缓冲
})

// 响应拦截器：自动把包装盒剥掉，只留核心数据，并做统一报错拦截
request.interceptors.response.use(response => {
  return response.data 
}, error => {
  console.error('🚨 网关请求异常:', error)
  return Promise.reject(error)
})

// ==========================================
// 🌟 纯净极速版 API 接口导出 (已彻底移除物理宕机与插单扰动)
// ==========================================
export default {
  // 1. 同步零件工艺与加工耗时等基础数据
  uploadMasterData(data) {
    return request.post('/master_data/upload', data)
  },
  
  // 2. 上传当天待排产的订单池
  uploadOrders(data) {
    return request.post('/orders/upload', data)
  },
  
  // 3. 呼叫 AI 大脑：开始极速推演最优排产策略
  startSimulation(batchNo, inventorySnapshotId = '2025-07-01-morning', eveningSnapshotId = '2025-07-01-evening') {
    return request.post('/simulation/start', {
      batch_no: batchNo,
      inventory_snapshot_id: inventorySnapshotId,
      evening_snapshot_id: eveningSnapshotId,
      shortage_policy: 'exception_queue'
    })
  },
  
  // 4. 轮询接口：获取后端多目标排产的实时进度条
  getSimulationStatus(taskId) {
    return request.get(`/simulation/status/${taskId}`)
  },
  
  // 5. 战报提取：获取排产完成后的 3D 数字孪生甘特图剧本
  getSimulationPlaybook(taskId) {
    return request.get(`/simulation/playbook/${taskId}`)
  },

  startScheduleDispatch(batchNo, inventorySnapshotId = '2025-07-01-morning', strategy = 'ai', activeStationLimit = 16) {
    return request.post('/schedule/dispatch', {
      batch_no: batchNo,
      inventory_snapshot_id: inventorySnapshotId,
      strategy,
      active_station_limit: activeStationLimit
    })
  },

  getScheduleResult(taskId) {
    return request.get(`/schedule/result/${taskId}`)
  },

  getInventorySnapshots() {
    return request.get('/inventory/snapshots')
  },

  getInventorySummary(snapshotId) {
    return request.get(`/inventory/summary/${snapshotId}`)
  },
  
  // 6. 数据大屏：直连后端 TensorBoard 解析器，获取真实炼丹进化曲线
  getTrainingMetrics() {
    return request.get('/model/training_metrics')
  }
}
