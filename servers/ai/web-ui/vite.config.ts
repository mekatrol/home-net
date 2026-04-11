import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  base: '/',
  build: {
    assetsDir: 'assets',
    emptyOutDir: true,
    outDir: '../app/web',
  },
  define: {
    __API_BASE_URL__: JSON.stringify(command === 'serve' ? 'http://email.lan:8080' : ''),
  },
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
}))
