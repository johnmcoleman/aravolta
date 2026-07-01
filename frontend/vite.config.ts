import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev server proxies /api -> the FastAPI backend, so the browser talks to the
// real API (no hardcoded data) on a single origin (no CORS needed locally).
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true, // listen on 0.0.0.0 so VS Code can forward the port
    allowedHosts: true, // accept VS Code's forwarded/tunnel host header
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
