import assert from 'node:assert/strict';
import { mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

/** Ensure Vite serves the npm facade without resolving the browser-owned runtime. */
async function preservesBrowserRuntimeResolution(): Promise<void> {
    const directory = await mkdtemp(join(tmpdir(), 'bloomerp-runtime-test-'));
    const root = await realpath(directory);
    const packageRoot = fileURLToPath(new URL('../', import.meta.url));
    const facade = fileURLToPath(new URL('../dist/index.js', import.meta.url));
    await writeFile(join(root, 'entry.js'), `import { BaseComponent } from ${JSON.stringify(facade)};\nexport { BaseComponent };\n`);
    const server = await createServer({
        configFile: false,
        root,
        server: { middlewareMode: true, hmr: false, ws: false, fs: { allow: [root, packageRoot] } },
        optimizeDeps: { noDiscovery: true },
    });
    try {
        assert.ok(await server.transformRequest('/entry.js'));
        // A literal runtime import fails here because the runtime is supplied by Django.
        const transformed = await server.transformRequest(`/@fs/${facade}`);
        assert.ok(transformed);
        assert.ok(transformed.code.includes('@bloomerp/runtime'));
        assert.ok(!transformed.code.includes('/@id/@bloomerp/runtime'));
    } finally {
        await server.close();
        await rm(root, { recursive: true, force: true });
    }
}

test('Vite leaves runtime resolution to the browser import map', preservesBrowserRuntimeResolution);
