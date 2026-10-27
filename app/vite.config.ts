import { readFileSync } from 'node:fs'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app's version, package.json's (docs/development.md, "Versions"), for the library screen to show.
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

// Tauri expects a fixed dev port and must not have its own rebuilds watched.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  clearScreen: false,
  server: {
    port: 1421,
    strictPort: true,
    watch: { ignored: ['**/src-tauri/**'] },
  },
})
