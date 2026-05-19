import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import compression from 'vite-plugin-compression'

export default defineConfig({
  base: '/step-view/',
  plugins: [
    react(),
    compression({ algorithm: 'gzip', ext: '.gz' }),
  ],

  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
        proxyTimeout: 600000,
        timeout: 600000,
      }
    }
  },

  resolve: {
    alias: {
      '@kitware/vtk.js': '@kitware/vtk.js'
    }
  },

  optimizeDeps: {
    include: ['@kitware/vtk.js'],
  },

  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('@kitware/vtk.js')) return 'vendor-vtk';
          if (id.includes('@react-three') || id.includes('/three/')) return 'vendor-three';
          if (id.includes('recharts') || id.includes('/d3') || id.includes('d3-')) return 'vendor-charts';
          if (id.includes('axios') || id.includes('zustand') || id.includes('immer') || id.includes('lodash')) return 'vendor-utils';
          // react / emotion / MUI: NOT manually chunked.
          // Rollup's auto-chunk algorithm resolves their circular-ESM deps in the
          // correct init order; forcing them into named chunks breaks that ordering
          // and causes "Cannot access 'x' before initialization" TDZ errors.
        },
      }
    }
  }
})
