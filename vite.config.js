import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';

const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8610,
    strictPort: false,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: path => path
      }
    }
  }
});
