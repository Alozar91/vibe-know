import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-режим: прокси на api (этап 1: 8000 занят сторонним процессом → compose мапит api на 8001;
// prod — nginx, HLD §3.1)
// База сборки: VITE_APP_BASE (например '/know/') — приложение по подпути
// (merch-vibe.ru/know); не задана — корень (локальный стенд). При base
// dist кладётся в подкаталог (nginx отдаёт /know/ alias'ом на dist/know/).
const APP_BASE = process.env.VITE_APP_BASE
  ? process.env.VITE_APP_BASE.replace(/\/?$/, '/')
  : '/'
export default defineConfig({
  plugins: [react()],
  base: APP_BASE,
  build: APP_BASE === '/' ? {} : { outDir: `dist${APP_BASE.replace(/\/$/, '')}`, emptyOutDir: false },
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
