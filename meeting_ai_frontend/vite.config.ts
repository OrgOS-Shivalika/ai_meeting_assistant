import { defineConfig, loadEnv } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

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
