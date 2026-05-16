// 文件路径: src/main.js
import { createApp } from 'vue'
import App from './App.vue'

// 🌟 引入 Element Plus 和它的样式文件
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

const app = createApp(App)

// 告诉 Vue 实例使用 Element Plus
app.use(ElementPlus)
app.mount('#app')