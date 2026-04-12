import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: './',
  
  build: {
    outDir: '../static/bloomerp/js/dist',
    emptyOutDir: true,
    manifest: true,
    sourcemap: true, // Enable source maps for debugging
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'ts/main.ts'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name]-[hash].js',
        assetFileNames: '[name].[ext]',
        // Preserve module structure for better debugging
        preserveModules: false,
      },
    },
    // Target modern browsers (since we're using HTMX anyway)
    target: 'es2020',
    minify: 'esbuild',
  },
  
  resolve: {
    alias: {
      '@': resolve(__dirname, './ts'),
    },
  },
  
  server: {
    port: 5173,
    strictPort: false,
    origin: 'http://localhost:5173',
    // Enable CORS for Django development server
    cors: true,
    // Hot Module Replacement settings
    hmr: {
      host: 'localhost',
      port: 5173,
    },
  },
  
  // Optimize dependencies
  optimizeDeps: {
    include: ['htmx.org'],
  },
  
  // Define global constants
  define: {
    __DEV__: JSON.stringify(process.env.NODE_ENV !== 'production'),
  },
});
