import { defineConfig, loadEnv } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import type { IncomingMessage } from 'http'
import path from 'path'

// In dev, every API path gets proxied to the FastAPI server. The frontend
// continues to call relative paths (no host hardcoded) and the browser sees
// everything as same-origin — so CORS never runs.
//
// Production keeps working unchanged: FastAPI serves the SPA from `/` and
// the API from the same host, so same-origin holds there too.
//
// VITE_API_URL overrides the proxy target if you point dev at a different
// backend (e.g. a deployed staging server).
//
// Important: some proxy prefixes (notably `/meeting-types` and
// `/auth/google/callback`) overlap with SPA routes. If a user is on
// `/meeting-types?type=4` and hits refresh, the browser sends a GET with
// `Accept: text/html` and NO Authorization header — proxying that to
// FastAPI returns a 401 JSON page (`{"detail":"Not authenticated"}`)
// which the browser then renders as the full page content. To avoid
// that, the proxy `bypass` hook below short-circuits HTML navigations
// to the SPA's index.html, and only forwards real XHR/fetch traffic
// (which carries `Accept: application/json` plus the bearer token) to
// FastAPI.
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
  // Phase 2D + 3D — semantic search + graph read API.
  '/search',
  '/entities',
  '/webhook',
  '/ws',
  '/health',
  '/docs',
  '/openapi.json',
  '/redoc',
  // Phase 4E — document chunks inspection endpoint.
  '/documents',
  // Phase 5D — RAG ask + conversations + runs.
  '/rag',
  // Phase 6D — merge suggestions + rehydrate.
  '/consolidation',
  // Agents v2 admin API (control-panel page).
  '/agents_v2',
  // Continuum Core — client boards + stage kanban.
  '/continuum',
]

const isHtmlNavigation = (req: IncomingMessage): boolean => {
  if (req.method !== 'GET') return false
  const accept = (req.headers.accept || '') as string
  // A browser navigation explicitly asks for HTML; an XHR/fetch asks for
  // JSON (our apiClient never sets Accept manually but `fetch` defaults
  // to `*/*` while the browser address-bar GET defaults to
  // `text/html,application/xhtml+xml,...`).
  return accept.includes('text/html')
}

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
      // Return `/index.html` for top-level HTML navigations so the SPA
      // hydrates instead of dumping the JSON 401 from FastAPI's
      // OAuth2PasswordBearer. WebSocket upgrades and JSON XHR pass
      // through unchanged.
      bypass: (req: IncomingMessage) => {
        if (prefix === '/ws') return undefined
        if (isHtmlNavigation(req)) {
          return '/index.html'
        }
        return undefined
      },
    }
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
