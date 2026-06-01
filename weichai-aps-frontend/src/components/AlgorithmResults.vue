<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import api from '../api/index' 

const props = defineProps({
  simResult: { type: Object, default: () => null }
})

const compareChartRef = ref(null)
const curveChartRef = ref(null)

let compareChartInstance = null
let curveChartInstance = null

const renderHolographicFallback = (msg, color) => {
  const mockData = Array.from({length: 50}, () => Math.random() * 10 + 20)
  curveChartInstance.setOption({
    backgroundColor: 'transparent',
    title: { text: msg, textStyle: { color: color, fontSize: 14, fontWeight: 'normal', lineHeight: 24 }, left: 'center', top: 'center', z: 10 },
    xAxis: { show: false, data: Array.from({length: 50}, (_, i) => i) },
    yAxis: { show: false, min: 0, max: 40 },
    series: [{ type: 'line', data: mockData, smooth: true, lineStyle: { color: color, width: 1, type: 'dashed', opacity: 0.3 }, areaStyle: { color: color, opacity: 0.05 }, symbol: 'none' }]
  }, true)
}

const renderCurveChart = async () => {
  if (!curveChartRef.value) return
  if (!curveChartInstance) curveChartInstance = echarts.init(curveChartRef.value)
  
  curveChartInstance.showLoading({ text: '正在扫描硬盘读取最新 TensorBoard 日志...', color: '#00E5FF', textColor: '#A0B2C6', maskColor: 'rgba(10, 21, 37, 0.8)' })

  try {
    const res = await api.getTrainingMetrics()
    if (res && res.code === 200 && res.data) {
      const steps = res.data.steps
      const rewards = res.data.rewards

      // 🌟 核心极限修复：彻底解决 Y 轴刻度过大、曲线被压扁成直线的问题！
      // 强化学习前 20%~30% 属于“盲人摸象”期，常伴有几万到几十万的极其离谱负分惩罚。
      // 【解决办法】：只取后 75% 的稳态数据来推算 Y 轴范围，将早期的天文数字强行“沉入海底”。
      const stableRewards = rewards.slice(Math.floor(rewards.length * 0.25))
      const minStable = Math.min(...stableRewards)
      const maxStable = Math.max(...stableRewards)
      const yRange = maxStable - minStable || 100
      
      const calcMin = Math.floor(minStable - yRange * 0.15) // 底部留 15% 喘息空间

      const option2 = {
        backgroundColor: 'transparent',
        title: { text: 'AI 调度大脑 (PPO) 真实训练收敛曲线', textStyle: { color: '#00E5FF', fontSize: 16 }, left: 'center', top: 10 },
        tooltip: { trigger: 'axis', formatter: '{b}<br/>Reward 分数: {c}' },
        dataZoom: [
          { type: 'inside', xAxisIndex: 0, filterMode: 'filter' },
          { type: 'slider', xAxisIndex: 0, bottom: 5, height: 15, textStyle: { color: '#A0B2C6' } },
          { type: 'slider', yAxisIndex: 0, right: 5, width: 15, textStyle: { color: '#A0B2C6' } }
        ],
        grid: { left: '12%', right: '8%', bottom: '20%', top: '25%' },
        xAxis: { type: 'category', boundaryGap: false, data: steps, axisLabel: { color: '#fff' } },
        yAxis: { 
          type: 'value', 
          name: 'Reward (稳态缩放)', 
          axisLabel: { color: '#fff' }, 
          nameTextStyle: { color: '#A0B2C6' }, 
          splitLine: { lineStyle: { color: '#1E3A5F', type: 'dashed' } },
          // 🌟 强行锁定底线：早期的极端点将被画在屏幕外（被裁剪掉），主体趋势彻底释放！
          min: calcMin,
          scale: true
        },
        series: [
          {
            name: 'Reward', 
            type: 'line', 
            smooth: 0.3, 
            data: rewards,
            clip: true, // 🌟 必须开启裁剪，不让超出网格的烂分画出界外
            itemStyle: { color: '#67C23A' },
            lineStyle: { width: 3, shadowColor: 'rgba(103, 194, 58, 0.5)', shadowBlur: 10 },
            areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(103, 194, 58, 0.4)' }, { offset: 1, color: 'rgba(103, 194, 58, 0)' }]) }
          }
        ]
      }
      curveChartInstance.hideLoading()
      curveChartInstance.setOption(option2, true) 
    } else {
      curveChartInstance.hideLoading()
      renderHolographicFallback(`⚠️ 曲线渲染中止: 训练日志未挂载`, '#FFB800')
    }
  } catch (error) {
    curveChartInstance.hideLoading()
    renderHolographicFallback(`❌ 接口通信失败: 无法连接至后端获取日志`, '#FF4D4F')
  }
}

const renderCharts = () => {
  if (!props.simResult) return
  if (compareChartRef.value) {
    if (!compareChartInstance) compareChartInstance = echarts.init(compareChartRef.value)
    const data = props.simResult
    const option1 = {
      backgroundColor: 'transparent',
      title: { text: '多算法极限压榨比对测试', textStyle: { color: '#00E5FF', fontSize: 16 }, left: 'center', top: 10 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { textStyle: { color: '#fff' }, top: 40 },
      grid: { left: '12%', right: '12%', bottom: '15%', top: '25%' },
      xAxis: { data: ['AI 强化学习', '传统轮询', '随机乱派'], axisLabel: { color: '#fff', fontSize: 14 } },
      yAxis: [
        { type: 'value', name: '总完工耗时(s)', axisLabel: { color: '#fff' }, nameTextStyle: { color: '#A0B2C6' }, splitLine: { lineStyle: { color: '#1E3A5F', type: 'dashed' } } },
        { type: 'value', name: '必需开机数(台)', min: 0, max: 16, axisLabel: { color: '#fff' }, nameTextStyle: { color: '#A0B2C6' }, splitLine: { show: false } }
      ],
      series: [
        { 
          name: '总耗时', type: 'bar', barWidth: '35%', 
          data: [
            { value: data.ai_result?.total_makespan || 0, itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: '#00E5FF'}, {offset: 1, color: '#0077FF'}]) } },
            { value: data.trad_result?.total_makespan || 0, itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: '#4A90E2'}, {offset: 1, color: '#003366'}]) } },
            { value: data.rand_result?.total_makespan || 0, itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: '#9CA3AF'}, {offset: 1, color: '#4B5563'}]) } }
          ], 
          itemStyle: { borderRadius: [6, 6, 0, 0] } 
        },
        { 
          name: '所需机床', type: 'line', yAxisIndex: 1, 
          data: [data.ai_result?.active_stations || 0, data.trad_result?.active_stations || 0, data.rand_result?.active_stations || 0], 
          itemStyle: { color: '#FFB800' }, lineStyle: { width: 4, shadowColor: 'rgba(255, 184, 0, 0.5)', shadowBlur: 10 }, symbol: 'diamond', symbolSize: 12
        }
      ]
    }
    compareChartInstance.setOption(option1, true)
  }
  renderCurveChart()
}

watch(() => props.simResult, async (newVal) => {
  if (newVal) { await nextTick(); renderCharts() }
}, { immediate: true })

const handleResize = () => { compareChartInstance?.resize(); curveChartInstance?.resize() }
onMounted(() => { window.addEventListener('resize', handleResize); if (!props.simResult) renderCurveChart() })
onUnmounted(() => { window.removeEventListener('resize', handleResize); compareChartInstance?.dispose(); curveChartInstance?.dispose() })
</script>

<template>
  <div class="algo-container">
    <div v-if="!simResult" class="empty-state">
      <h2>📊 等待后台 AI 推演战报...</h2>
      <p>请在【3D 数字孪生】面板点击“启动”按钮，获取极限压榨数据。</p>
      <div style="height: 300px; width: 100%; margin-top: 30px;" ref="curveChartRef"></div>
    </div>
    <div v-else class="charts-wrapper">
      <div class="summary-cards">
        <div class="card"><div class="card-title">AI 极限完工耗时</div><div class="card-value ai-color">{{ simResult.ai_result?.total_makespan || 0 }} <span class="unit">秒</span></div></div>
        <div class="card"><div class="card-title">为您节省实体机床</div><div class="card-value highlight">{{ Math.max(0, (simResult.trad_result?.active_stations || 16) - (simResult.ai_result?.active_stations || 16)) }} <span class="unit">台</span></div></div>
        <div class="card"><div class="card-title">综合效率提升</div><div class="card-value highlight">{{ simResult.efficiency_up || '0%' }}</div></div>
      </div>
      <div class="charts-grid">
        <div ref="compareChartRef" class="chart-box"></div>
        <div ref="curveChartRef" class="chart-box"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.algo-container { width: 100%; height: 100%; background: #0A1525; border-radius: 12px; border: 1px solid #1E3A5F; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.empty-state { text-align: center; color: #A0B2C6; display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; height: 100%; padding: 0 40px;}
.empty-state h2 { color: #00E5FF; text-shadow: 0 0 10px rgba(0,229,255,0.3); margin-bottom: 10px; }
.charts-wrapper { width: 100%; height: 100%; padding: 20px; display: flex; flex-direction: column; box-sizing: border-box;}
.summary-cards { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 20px; height: 110px; }
.card { flex: 1; background: rgba(15, 25, 40, 0.8); border: 1px solid #1E3A5F; border-radius: 8px; display: flex; flex-direction: column; justify-content: center; align-items: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); position: relative; overflow: hidden;}
.card::before { content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: #00E5FF; }
.card:nth-child(2)::before { background: #67C23A; }
.card:nth-child(3)::before { background: #67C23A; }
.card-title { color: #A0B2C6; font-size: 14px; margin-bottom: 8px; font-weight: bold; letter-spacing: 1px;}
.card-value { font-size: 36px; font-weight: 900; text-shadow: 0 0 20px rgba(255,255,255,0.1);}
.unit { font-size: 14px; font-weight: normal; color: #A0B2C6; margin-left: 4px;}
.ai-color { color: #00E5FF; text-shadow: 0 0 15px rgba(0,229,255,0.4);}
.highlight { color: #67C23A; text-shadow: 0 0 15px rgba(103,194,58,0.4);}
.charts-grid { display: flex; gap: 20px; flex: 1; min-height: 0; }
.chart-box { flex: 1; background: rgba(15, 25, 40, 0.5); border: 1px solid #1E3A5F; border-radius: 8px; box-shadow: inset 0 0 30px rgba(0,0,0,0.2); }
</style>