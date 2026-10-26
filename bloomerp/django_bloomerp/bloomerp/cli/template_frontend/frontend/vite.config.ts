import { defineConfig } from 'vite';

export default defineConfig({
    base: './',
    optimizeDeps: { exclude: ['@bloomerp/frontend', '@bloomerp/runtime'] },
    build: {
        outDir: '../static/__APP_LABEL__/frontend',
        emptyOutDir: true,
        manifest: 'manifest.json',
        target: 'es2020',
        rollupOptions: {
            input: 'ts/main.ts',
            external: ['@bloomerp/frontend', '@bloomerp/runtime'],
        },
    },
    server: { port: 5174, strictPort: true, cors: true, origin: 'http://localhost:5174' },
});
