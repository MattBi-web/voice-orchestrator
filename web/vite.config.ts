import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxies /api/* to the FastAPI backend (uvicorn voice_orchestrator.webapi.app:app
// --reload --port 8000) so the frontend can fetch('/api/...') with no CORS
// configuration needed in dev — same-origin as far as the browser is concerned.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
