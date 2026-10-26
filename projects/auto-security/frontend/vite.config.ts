import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // 从仓库根目录 .env 读取后端地址，避免与本机其他服务抢占 8000
  const env = loadEnv(mode, '..', '')
  const apiTarget = env.ASE_API_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    envDir: '..',
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
