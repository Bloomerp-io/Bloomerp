import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: './',
  // Resolve emitted fonts and other assets relative to the deployed bundle.
  base: './',
  
  build: {
    outDir: '../static/bloomerp/js/dist',
    emptyOutDir: true,
    // Keep the manifest visible to Django's staticfiles finder and collectstatic.
    manifest: 'manifest.json',
    sourcemap: true, // Enable source maps for debugging
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'ts/entry.ts'),
      },
      output: {
        // Keep application startup in one hashed module. Every module, including
        // the entry, has a build-specific URL so lazy imports cannot load an
        // entry cached from an earlier release.
        manualChunks: {
          app: [resolve(__dirname, 'ts/main.ts')],
        },
        entryFileNames: '[name]-[hash].js',
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
