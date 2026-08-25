/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  // Relative asset URLs: the app is served from a generated Ingress
  // prefix that is unknown at build time, so nothing may be absolute.
  base: './',
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    // In development the UI runs on Vite and the API on uvicorn; this proxy
    // keeps the frontend calling same-origin `/api` paths in both modes.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8099', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8099', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
  },
});
