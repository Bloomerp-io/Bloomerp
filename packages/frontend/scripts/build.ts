import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import ts from 'typescript';

const source = new URL('../../../bloomerp/django_bloomerp/bloomerp/static_src/ts/components/BaseComponent.ts', import.meta.url);
const output = new URL('../dist/', import.meta.url);
const declarations = ts.transpileDeclaration(readFileSync(source, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
    fileName: 'BaseComponent.ts',
    reportDiagnostics: true,
});
if (declarations.diagnostics?.length) {
    throw new Error(ts.formatDiagnostics(declarations.diagnostics, {
        getCanonicalFileName,
        getCurrentDirectory,
        getNewLine,
    }));
}
mkdirSync(output, { recursive: true });
writeFileSync(new URL('BaseComponent.d.ts', output), declarations.outputText);
writeFileSync(new URL('index.d.ts', output), `export { default as BaseComponent, registerComponent, getComponent, initComponents, componentIdentifier } from './BaseComponent.js';\n`);
// Django maps this runtime-only name to the public entry in the core Vite build.
// Vite must leave the runtime name to the browser import map during development.
writeFileSync(new URL('index.js', output), `const runtimeModule = '@bloomerp/runtime';\nconst runtime = await import(/* @vite-ignore */ runtimeModule);\nexport const { BaseComponent, registerComponent, getComponent, initComponents, componentIdentifier } = runtime;\n`);

/** Preserve diagnostic paths without applying platform-specific normalization. */
function getCanonicalFileName(filename: string): string {
    return filename;
}

/** Resolve diagnostics relative to the package build working directory. */
function getCurrentDirectory(): string {
    return process.cwd();
}

/** Format compiler diagnostics using portable line endings. */
function getNewLine(): string {
    return '\n';
}
