import { defineConfig, loadEnv } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'

// In dev, every API path gets proxied to the FastAPI server. The frontend
// continues to call relative paths (no host hardcoded) and the browser sees
// everything as same-origin — so CORS never runs.
//
// Production keeps working unchanged: FastAPI serves the SPA from `/` and
// the API from the same host, so same-origin holds there too.
//
// VITE_API_URL overrides the proxy target if you point dev at a different
// backend (e.g. a deployed staging server).
const API_PATH_PREFIXES = [
  '/auth',
  '/categories',
  '/teams',
  '/meeting-types',
  '/meetings',
  '/allmeetings',
  '/inject-bot',
  '/transcriptions',
  '/tasks',
  '/webhook',
  '/ws',
  '/health',
  '/docs',
  '/openapi.json',
  '/redoc',
]

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_URL || 'http://localhost:8000'

  const proxy: Record<string, any> = {}
  for (const prefix of API_PATH_PREFIXES) {
    proxy[prefix] = {
      target,
      changeOrigin: true,
      // /ws upgrades to a websocket — vite handles that when ws: true.
      ws: prefix === '/ws',
    }
  }

  return {
    plugins: [
      tailwindcss(),
      react(),
      babel({ presets: [reactCompilerPreset()] })
    ],
    server: {
      proxy,
    },
  }
})
