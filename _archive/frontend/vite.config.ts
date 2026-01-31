import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Detect Docker and pick backend target
const isDocker = process.env.DOCKER_ENV === 'true'
const backendTarget = isDocker
  ? 'http://sentient-backend:8000'   // docker-compose service name + port
  : 'http://localhost:8000'          // local dev

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,   // 👈 match Dockerfile + docker-compose
    host: true,
    allowedHosts: [
      'localhost',
      '.ngrok-free.app',
      '.ngrok.io',
      '.ngrok.app'
    ],
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/socket.io': {
        target: backendTarget,
        changeOrigin: true,
        ws: true,
      }
    }
  },
})
