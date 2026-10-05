import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxies /api/* to the FastAPI backend (uvicorn voice_orchestrator.webapi.app:app
// --reload --port 8000) so the frontend can fetch('/api/...') with no CORS
// configuration needed in dev — same-origin as far as the browser is concerned.
export default defineConfig({
  plugins: [react()],
  build: {
    // D9: the only chunk over Vite's default 500 kB is the lazily loaded
    // voice console (livekit-client alone is ~500 kB minified). Raised just
    // past it so the warning fires again if the *initial* chunk (~260 kB)
    // or anything else grows past that.
    chunkSizeWarningLimit: 560,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
