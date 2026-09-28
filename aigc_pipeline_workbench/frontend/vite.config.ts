import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: "frontend",
  resolve: {
    preserveSymlinks: true,
  },
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
    watch: {
      usePolling: true,
    },
  },
  preview: {
    port: 4173,
    host: "0.0.0.0",
  },
  build: {
    outDir: "../dist/frontend",
    emptyOutDir: true,
  },
});
