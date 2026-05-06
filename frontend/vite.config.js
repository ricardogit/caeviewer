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
          if (id.includes('react-dom') || id.includes('react-router-dom') || /[/\\]react[/\\]/.test(id)) return 'vendor-react';
          if (id.includes('@react-three') || id.includes('/three/')) return 'vendor-three';
          if (id.includes('@mui/') || id.includes('@emotion/')) return 'vendor-mui';
          if (id.includes('recharts') || id.includes('/d3') || id.includes('d3-')) return 'vendor-charts';
          if (id.includes('axios') || id.includes('zustand') || id.includes('immer') || id.includes('lodash')) return 'vendor-utils';
        },
      }
    }
  }
})
