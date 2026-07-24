import { defineConfig, loadEnv } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// In dev, the API prefixes get proxied to the FastAPI server. The frontend
// calls relative paths (no host hardcoded) and the browser sees everything as
// same-origin — so CORS never runs. Production keeps working unchanged:
// FastAPI serves the SPA from `/` and the API from the same host.
//
// VITE_API_URL overrides the proxy target if you point dev at a different
// backend. VITE_API_PREFIX / VITE_PUBLIC_PREFIX must match the backend's
// API_PREFIX / PUBLIC_PREFIX (defaults /api and /public). Because every API
// route now lives under one of these prefixes, SPA routes (e.g.
// `/meeting-types`, `/auth/google/callback`) never collide with the API and
// are served the SPA shell by Vite's own fallback — no bypass hack needed.
const normalizePrefix = (p: string): string => {
  const t = (p || '').replace(/^\/+|\/+$/g, '')
  return t ? `/${t}` : ''
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_URL || 'http://localhost:8000'
  const apiPrefix = normalizePrefix(env.VITE_API_PREFIX ?? '/api') || '/api'
  const publicPrefix = normalizePrefix(env.VITE_PUBLIC_PREFIX ?? '/public') || '/public'

  const proxy: Record<string, any> = {
    // Authenticated API + the viewer WebSocket (under API_PREFIX/ws).
    [apiPrefix]: { target, changeOrigin: true, ws: true },
    // Unauthenticated login/register.
    [publicPrefix]: { target, changeOrigin: true },
    // Infra / API docs.
    '/docs': { target, changeOrigin: true },
    '/openapi.json': { target, changeOrigin: true },
    '/redoc': { target, changeOrigin: true },
    '/health': { target, changeOrigin: true },
  }

  return {
    plugins: [
      tailwindcss(),
      react(),
      babel({ presets: [reactCompilerPreset()] })
    ],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      allowedHosts: [
        'viral-salami-thimble.ngrok-free.dev',
      ],
      proxy,
    },
  }
})
