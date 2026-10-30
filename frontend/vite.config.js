import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    hmr: {
      // Run Vite HMR on a separate port so it never conflicts
      // with the /ws proxy that forwards sensor WebSocket traffic.
      port: 0,
    },
    proxy: {
      // Proxy REST API calls to FastAPI
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Proxy WebSocket sensor stream to FastAPI
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path,
      },
    },
  },
})