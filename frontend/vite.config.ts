import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-режим: прокси на api (этап 1: 8000 занят чужим процессом, compose
// публикует api на 8001; prod - nginx, HLD §3.1)
// При сборке: VITE_APP_BASE (например '/know/') - приложение под подпутём
// (merch-vibe.ru/know); по умолчанию - корень (локальный стенд). В зависимости от base
// dist собирается в подпапку (nginx отдаёт /know/ alias'ом на dist/know/).
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
  // Vitest (реорганизация frontend): jsdom + setup с jest-dom
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
