<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
// 🌟 引入咱们刚刚在 index.js 里封装的 API 接口
import api from '../api/index' 

const props = defineProps({
  simResult: {
    type: Object,
    default: () => null
  }
})

const compareChartRef = ref(null)
const curveChartRef = ref(null)

let compareChartInstance = null
let curveChartInstance = null

// 🌟 将曲线渲染逻辑单独抽离成异步函数
const renderCurveChart = async () => {
  if (!curveChartRef.value) return
  
  if (!curveChartInstance) {
    curveChartInstance = echarts.init(curveChartRef.value)
  }
  
  // 🌟 显示极客风加载动画
  curveChartInstance.showLoading({ 
    text: '正在扫描硬盘读取最新 TensorBoard 日志...', 
    color: '#00E5FF', 
    textColor: '#A0B2C6', 
    maskColor: 'rgba(10, 21, 37, 0.8)' 
  })

  try {
    // 🌟 核心：发起真实的后端请求
    const res = await api.getTrainingMetrics()
    
    // 情况 A：完美拿到数据
    if (res && res.code === 200 && res.data) {
      const steps = res.data.steps
      const rewards = res.data.rewards

      const option2 = {
        backgroundColor: 'transparent',
        title: { text: 'AI 调度大脑 (PPO) 真实训练收敛曲线', textStyle: { color: '#00E5FF', fontSize: 16 }, left: 'center', top: 10 },
        tooltip: { trigger: 'axis', formatter: '{b}<br/>Reward 分数: {c}' },
        grid: { left: '10%', right: '5%', bottom: '15%', top: '25%' },
        xAxis: { type: 'category', boundaryGap: false, data: steps, axisLabel: { color: '#fff' } },
        yAxis: { type: 'value', min: 'dataMin', name: 'Reward 奖励值', axisLabel: { color: '#fff' }, nameTextStyle: { color: '#A0B2C6' }, splitLine: { lineStyle: { color: '#1E3A5F' } } },
        series: [
          {
            name: 'Reward',
            type: 'line',
            smooth: 0.2, // 保留真实震荡感
            data: rewards,
            itemStyle: { color: '#67C23A' },
            lineStyle: { width: 3 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(103, 194, 58, 0.5)' },
                { offset: 1, color: 'rgba(103, 194, 58, 0)' }
              ])
            }
          }
        ]
      }
      curveChartInstance.hideLoading()
      curveChartInstance.setOption(option2, true) 
    } 
    // 情况 B：后端通了，但没找到日志文件 (假 200，真 404)
    else {
      curveChartInstance.hideLoading()
      curveChartInstance.setOption({
        backgroundColor: 'transparent',
        title: {
          text: `⚠️ 曲线渲染中止\n\n原因: ${res?.message || '未找到训练日志'}\n\n系统已开启自动寻址，请确保场景目录下存在 ppo_tensorboard_logs 文件夹`,
          textStyle: { color: '#FFB800', fontSize: 14, fontWeight: 'normal', lineHeight: 24 },
          left: 'center',
          top: 'center'
        }
      }, true)
      console.warn("未能获取到完整的训练数据: ", res)
    }
  } catch (error) {
    // 情况 C：后端彻底炸了，或者接口写错了 (网络级报错)
    curveChartInstance.hideLoading()
    curveChartInstance.setOption({
      backgroundColor: 'transparent',
      title: {
        text: `❌ 接口请求失败\n\n请检查 FastAPI 服务 (8088端口) 是否正常运行`,
        textStyle: { color: '#FF4D4F', fontSize: 14, fontWeight: 'normal', lineHeight: 24 },
        left: 'center',
        top: 'center'
      }
    }, true)
    console.error("获取训练日志彻底失败: ", error)
  }
}

const renderCharts = () => {
  if (!props.simResult) return

  // ==========================================
  // 1. 三大策略降维打击对比图 (柱状+折线双轴)
  // ==========================================
  if (compareChartRef.value) {
    if (!compareChartInstance) {
      compareChartInstance = echarts.init(compareChartRef.value)
    }
    const data = props.simResult
    const option1 = {
      backgroundColor: 'transparent',
      title: { text: '三大排产策略效能对比', textStyle: { color: '#00E5FF', fontSize: 16 }, left: 'center', top: 10 },
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#fff' }, top: 40 },
      grid: { left: '10%', right: '10%', bottom: '15%', top: '25%' },
      xAxis: { data: ['AI 强化学习', '传统轮询', '随机乱派'], axisLabel: { color: '#fff', fontSize: 14 } },
      yAxis: [
        { type: 'value', name: '总完工耗时(s)', axisLabel: { color: '#fff' }, nameTextStyle: { color: '#A0B2C6' }, splitLine: { lineStyle: { color: '#1E3A5F' } } },
        { type: 'value', name: '启用机床数(台)', min: 0, max: 16, axisLabel: { color: '#fff' }, nameTextStyle: { color: '#A0B2C6' }, splitLine: { show: false } }
      ],
      series: [
        { 
          name: '总耗时', 
          type: 'bar', 
          barWidth: '30%', 
          data: [data.ai_result?.total_makespan || 0, data.trad_result?.total_makespan || 0, data.rand_result?.total_makespan || 0], 
          itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: '#00E5FF'}, {offset: 1, color: '#0077FF'}]), borderRadius: [6, 6, 0, 0] } 
        },
        { 
          name: '所需机床', 
          type: 'line', 
          yAxisIndex: 1, 
          data: [data.ai_result?.active_stations || 0, data.trad_result?.active_stations || 0, data.rand_result?.active_stations || 0], 
          itemStyle: { color: '#FFB800' }, 
          lineStyle: { width: 4, shadowColor: 'rgba(255, 184, 0, 0.5)', shadowBlur: 10 }, 
          symbolSize: 10 
        }
      ]
    }
    compareChartInstance.setOption(option1, true)
  }

  // ==========================================
  // 2. 调用真实的 PPO 训练收敛曲线渲染逻辑
  // ==========================================
  renderCurveChart()
}

// 监听推演结果，有数据就刷新图表
watch(() => props.simResult, async (newVal) => {
  if (newVal) {
    await nextTick()
    renderCharts()
  }
}, { immediate: true })

// 窗口尺寸变化时的自适应处理
const handleResize = () => {
  compareChartInstance?.resize()
  curveChartInstance?.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  // 如果初次挂载时后端没有推演数据，依然可以尝试拉取一次 TensorBoard 曲线给用户看
  if (!props.simResult) {
    renderCurveChart()
  }
})

// 🌟 企业级规范：组件销毁时释放实例，防止内存泄漏
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  compareChartInstance?.dispose()
  curveChartInstance?.dispose()
})
</script>

<template>
  <div class="algo-container">
    <div v-if="!simResult" class="empty-state">
      <h2>📊 等待后台 AI 推演数据...</h2>
      <p>请在【3D 仿真车间】面板点击“启动推演”按钮下发云端指令。</p>
      <div style="height: 300px; width: 600px; margin-top: 30px;" ref="curveChartRef"></div>
    </div>
    
    <div v-else class="charts-wrapper">
      <div class="summary-cards">
        <div class="card">
          <div class="card-title">AI 极限完工耗时</div>
          <div class="card-value ai-color">{{ simResult.ai_result?.total_makespan || 0 }} <span class="unit">秒</span></div>
        </div>
        <div class="card">
          <div class="card-title">为您节省机床</div>
          <div class="card-value highlight">{{ 16 - (simResult.ai_result?.active_stations || 16) }} <span class="unit">台</span></div>
        </div>
        <div class="card">
          <div class="card-title">综合效率提升</div>
          <div class="card-value highlight">{{ simResult.efficiency_up || '0%' }}</div>
        </div>
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
.empty-state { text-align: center; color: #A0B2C6; display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; height: 100%;}
.empty-state h2 { color: #00E5FF; text-shadow: 0 0 10px rgba(0,229,255,0.3); margin-bottom: 10px; }

.charts-wrapper { width: 100%; height: 100%; padding: 20px; display: flex; flex-direction: column; box-sizing: border-box;}
.summary-cards { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 20px; height: 100px; }
.card { flex: 1; background: rgba(15, 25, 40, 0.8); border: 1px solid #1E3A5F; border-radius: 8px; display: flex; flex-direction: column; justify-content: center; align-items: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
.card-title { color: #A0B2C6; font-size: 14px; margin-bottom: 5px; }
.card-value { font-size: 32px; font-weight: 900; }
.unit { font-size: 14px; font-weight: normal; }
.ai-color { color: #00E5FF; }
.highlight { color: #67C23A; }

.charts-grid { display: flex; gap: 20px; flex: 1; min-height: 0; }
.chart-box { flex: 1; background: rgba(15, 25, 40, 0.5); border: 1px solid #1E3A5F; border-radius: 8px; }
</style>