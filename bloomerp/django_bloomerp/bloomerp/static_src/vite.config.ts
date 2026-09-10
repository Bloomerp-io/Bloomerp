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
        main: resolve(__dirname, 'ts/entry.ts'),
      },
      output: {
        // Keep application startup in one hashed module. The template versions
        // main.js with a query string; lazy chunks must not import that entry
        // without the query and execute startup a second time.
        manualChunks: {
          app: [resolve(__dirname, 'ts/main.ts')],
        },
        entryFileNames: '[name].js',
        chunkFileNames: '[name]-[hash].js',
        // The Django head template loads the application's CSS at this path.
        assetFileNames: asset => asset.names.includes('app.css') ? 'main.css' : '[name].[ext]',
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
    watch: {
      // Prevent backend SQLite writes from triggering frontend reloads.
      ignored: ['**/*.sqlite3', '**/*.sqlite3-*', '**/db.sqlite3', '**/db.sqlite3-*'],
    },
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
