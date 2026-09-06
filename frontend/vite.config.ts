/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 开发服务器配置:前端 5173 端口,把 /api 代理到后端 8000,
// 浏览器侧无跨域问题,axios 只需写相对路径
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  // Vitest 配置:纯逻辑测试用 node 环境(SSE 解析/状态运算不依赖 DOM)
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
