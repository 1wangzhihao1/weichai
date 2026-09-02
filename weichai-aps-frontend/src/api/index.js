import axios from 'axios'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 300000
})

request.interceptors.response.use(response => {
  return response.data
}, error => {
  console.error('API request failed:', error)
  return Promise.reject(error)
})

export default {
  uploadMasterData(data) {
    return request.post('/master_data/upload', data)
  },

  uploadOrders(data) {
    return request.post('/orders/upload', data)
  },

  startSimulation(batchNo, inventorySnapshotId, eveningSnapshotId, options = {}) {
    return request.post('/simulation/start', {
      batch_no: batchNo,
      inventory_snapshot_id: inventorySnapshotId,
      evening_snapshot_id: eveningSnapshotId,
      shortage_policy: 'exception_queue',
      strategy: options.strategy || 'ai',
      active_station_limit: options.activeStationLimit || 16,
      history_date: options.historyDate || null,
      process_time_source: options.processTimeSource || 'sku_average',
      operation_gap_seconds: options.operationGapSeconds ?? null
    })
  },

  getSimulationStatus(taskId) {
    return request.get(`/simulation/status/${taskId}`)
  },

  getSimulationPlaybook(taskId) {
    return request.get(`/simulation/playbook/${taskId}`)
  },

  startScheduleDispatch(batchNo, inventorySnapshotId, strategy = 'ai', activeStationLimit = 16) {
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

  getOrderBatches() {
    return request.get('/orders/batches')
  },

  getAppConfig() {
    return request.get('/app/config')
  },

  rebuildSkuTime() {
    return request.post('/sku-time/rebuild')
  },

  getInventorySummary(snapshotId) {
    return request.get(`/inventory/summary/${snapshotId}`)
  },

  getTrainingMetrics() {
    return request.get('/model/training_metrics')
  }
}
