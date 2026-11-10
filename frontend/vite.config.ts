import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-режим: прокси на api (этап 1: 8000 занят сторонним процессом → compose мапит api на 8001;
// prod — nginx, HLD §3.1)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
