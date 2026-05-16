import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // 监听的本地端口 (默认 5173)
    port: 5173,
    // 🌟 核心：配置本地代理，彻底解决 CORS 跨域问题
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8088', // 你的 FastAPI 后端地址
        changeOrigin: true, // 允许改变源
        // rewrite: (path) => path.replace(/^\/api/, '') // 如果后端本身就有 /api 前缀，则不需要 rewrite
      }
    }
  }
})