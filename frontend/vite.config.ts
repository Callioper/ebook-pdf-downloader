import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

function readVersion(): string {
  try {
    const versionFile = path.join(__dirname, '..', 'backend', 'version.py')
    const content = fs.readFileSync(versionFile, 'utf-8')
    const match = content.match(/VERSION\s*=\s*"([^"]+)"/)
    return match ? match[1] : '0.0.0'
  } catch {
    return '0.0.0'
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    APP_VERSION: JSON.stringify(readVersion()),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
