/** Exercise SQL query tabs against the real session SDK and Ace editor. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type { Ace } from 'ace-builds';
import type SqlQueryEditor from './SqlQueryEditor';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/sql-query-test-entry.ts`;
const built = await build({
    configFile: false, root, logLevel: 'silent',
    plugins: [{
        name: 'sql-query-test',
        /** Resolve an in-memory entry containing the production editor and SDK. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Preload Ace modules so the fixture needs no script downloads. */
        load(id: string): string | null {
            return id === entry ? `
                import ace from 'ace-builds/src-noconflict/ace';
                import 'ace-builds/src-noconflict/theme-chrome';
                import 'ace-builds/src-noconflict/mode-sql';
                import 'ace-builds/src-noconflict/ext-language_tools';
                export { default as SqlQueryEditor } from '${root}/ts/components/inputs/SqlQueryEditor';
                /** Return the Ace instance owned by the SQL editor. */
                export function sourceEditor(element: HTMLElement): import('ace-builds').Ace.Editor {
                    return ace.edit(element);
                }
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'SqlFixture' } },
});
const output = Array.isArray(built) ? built[0] : built;
assert('output' in output);
/** Select the executable browser bundle. */
const chunk = output.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(chunk?.type === 'chunk');
const code = chunk.code;
const template = readFileSync(`${root}/../templates/cotton/ui/inputs/sql_query_editor.html`, 'utf8')
    .replace("{% url 'api_sql_accessible_tables' %}", '/api/sql/accessible-tables/')
    .replace("{% url 'components_execute_sql_query' %}", '/components/execute_sql_query/')
    .replace(/{% include[^%]*%}/g, '<div data-sql-results-meta></div>')
    .replace(/{{[^}]*}}/g, '');

interface FixtureWindow extends DOMWindow {
    SqlFixture: {
        SqlQueryEditor: typeof SqlQueryEditor;
        sourceEditor(element: HTMLElement): Ace.Editor;
    };
}
interface RequestRecord { url: URL; options: RequestInit; }
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    element: HTMLElement;
    component: SqlQueryEditor;
    editor: Ace.Editor;
    requests: RequestRecord[];
}
type Handler = (request: RequestRecord) => Promise<Response>;

/** Supply the layout-observer API absent from jsdom. */
class FixtureResizeObserver {
    /** Accept the observed editor without simulating browser layout. */
    public observe(_element: Element): void {}
    /** Release the fixture's inert observation. */
    public disconnect(): void {}
}

/** Encode the same JSON response shape used by the generated model API. */
function json(body: unknown, status: number = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** Return paginated saved queries and a small accessible catalog. */
async function defaultHandler(request: RequestRecord): Promise<Response> {
    if (request.url.pathname === '/api/sql/accessible-tables/') {
        return json({ databases: [{ name: 'default', tables: [{ name: 'customer', fields: [{ name: 'id', field_type: 'integer' }] }] }] });
    }
    if (request.url.pathname === '/api/sql_queries/' && !request.options.method?.match(/POST|PATCH/)) {
        const second = request.url.searchParams.has('page');
        return json({ count: 2, previous: null, next: second ? null : 'https://app.example.test/api/sql_queries/?page=2',
            results: [{ id: second ? 'saved-2' : 'saved-1', name: second ? 'Second' : 'First', query: second ? 'SELECT 2;' : 'SELECT 1;' }] });
    }
    if (request.options.method === 'POST' || request.options.method === 'PATCH') {
        return json({ id: 'created-1', ...JSON.parse(String(request.options.body)) });
    }
    throw new Error(`Unexpected request: ${request.url}`);
}

/** Mount the actual Cotton markup with a controllable network boundary. */
function fixture(handler: Handler = defaultHandler): Fixture {
    const dom = new JSDOM(`<!doctype html><form>${template}</form>`, {
        runScripts: 'outside-only', pretendToBeVisual: true, url: 'https://app.example.test/',
    });
    const w = dom.window as FixtureWindow;
    Object.assign(w, { Headers, Request, Response, TextEncoder, TextDecoder, ResizeObserver: FixtureResizeObserver });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Match the browser's default XPath result type for HTMX initialization. */
    w.XPathExpression.prototype.evaluate = function evaluateDefault(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, result);
    };
    const requests: RequestRecord[] = [];
    /** Capture requests issued by the real SDK rather than replacing its methods. */
    w.fetch = async function fetchFixture(input: string | URL | Request, options: RequestInit = {}): Promise<Response> {
        const request = { url: new URL(String(input)), options };
        requests.push(request);
        return handler(request);
    };
    w.document.cookie = 'csrftoken=sql-fixture-csrf; path=/';
    const element = w.document.querySelector<HTMLElement>('[bloomerp-component="sql-query-editor"]')!;
    element.querySelector<HTMLInputElement>('[data-sql-hidden-query-input]')!.value = 'SELECT 99;';
    w.eval(code);
    const component = new w.SqlFixture.SqlQueryEditor(element);
    component.initialize();
    const editor = w.SqlFixture.sourceEditor(element.querySelector('[data-sql-editor]')!);
    return { dom, w, element, component, editor, requests };
}

/** Allow network continuations, Ace changes, and DOM updates to settle. */
async function settle(): Promise<void> {
    await new Promise<void>(function delay(resolve: () => void): void { setTimeout(resolve, 30); });
}

/** Activate a query through the same delegated tab click as the user. */
function activate(f: Fixture, id: string): void {
    f.element.querySelector<HTMLElement>(`[data-sql-tab-id="${id}"]`)!.click();
}

/** Return the query name control used by saves and tab changes. */
function nameInput(f: Fixture): HTMLInputElement {
    return f.element.querySelector<HTMLInputElement>('[data-sql-query-name]')!;
}

/** Close through HTMX cleanup and release the fixture document. */
function close(f: Fixture): void {
    f.element.dispatchEvent(new f.w.CustomEvent('htmx:beforeCleanupElement', { bubbles: true }));
    f.dom.window.close();
}

/** Loading every saved page must preserve the initial SQL and independently edited names. */
async function loadQueries(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        assert.equal(f.element.querySelectorAll('[data-sql-tab-id]').length, 3);
        assert.equal(f.component.getQuery(), 'SELECT 99;');
        nameInput(f).value = 'Initial draft';
        activate(f, 'saved-1');
        assert.equal(f.component.getQuery(), 'SELECT 1;');
        f.editor.setValue('SELECT 11;', -1);
        nameInput(f).value = 'Edited first';
        activate(f, 'saved-2');
        assert.equal(f.component.getQuery(), 'SELECT 2;');
        activate(f, 'saved-1');
        assert.equal(f.component.getQuery(), 'SELECT 11;');
        assert.equal(nameInput(f).value, 'Edited first');
        activate(f, 'unsaved');
        assert.equal(f.component.getQuery(), 'SELECT 99;');
        assert.equal(nameInput(f).value, 'Initial draft');
        assert.equal(f.requests[0].options.credentials, 'include');
    } finally { close(f); }
}

/** Creating and updating use generated model endpoints, session CSRF, and retained drafts. */
async function saveQueries(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        f.element.querySelector<HTMLElement>('[data-sql-tab-add]')!.click();
        f.editor.setValue('SELECT 42;', -1);
        nameInput(f).value = 'Answer';
        f.element.querySelector<HTMLButtonElement>('[data-sql-save]')!.click();
        await settle();
        const created = f.requests.find(function isCreate(request: RequestRecord): boolean {
            /** Identify the model create request among schema and list requests. */
            return request.url.pathname === '/api/sql_queries/' && request.options.method === 'POST';
        })!;
        assert(created);
        assert.deepEqual(JSON.parse(String(created.options.body)), { name: 'Answer', query: 'SELECT 42;' });
        assert.equal(new Headers(created.options.headers).get('X-CSRFToken'), 'sql-fixture-csrf');
        assert.equal(f.element.querySelector<HTMLInputElement>('[data-sql-active-query-id]')!.value, 'created-1');
        f.editor.setValue('SELECT 43;', -1);
        f.element.querySelector<HTMLButtonElement>('[data-sql-save]')!.click();
        await settle();
        const updated = f.requests[f.requests.length - 1];
        assert.equal(updated.url.pathname, '/api/sql_queries/created-1/');
        assert.equal(updated.options.method, 'PATCH');
        assert.equal(JSON.parse(String(updated.options.body)).query, 'SELECT 43;');
        activate(f, 'unsaved');
        assert.equal(f.component.getQuery(), 'SELECT 99;');
        activate(f, 'saved-2');
        assert.equal(f.component.getQuery(), 'SELECT 2;');
    } finally { close(f); }
}

/** A pending save must neither create duplicates nor switch away from a newer draft. */
async function pendingSave(): Promise<void> {
    let finish: (() => void) | undefined;
    /** Delay creation until the user has moved to another draft. */
    async function handler(request: RequestRecord): Promise<Response> {
        if (request.options.method === 'POST') {
            await new Promise<void>(function hold(resolve: () => void): void { finish = resolve; });
        }
        return defaultHandler(request);
    }
    const f = fixture(handler);
    try {
        await settle();
        const save = f.element.querySelector<HTMLButtonElement>('[data-sql-save]')!;
        save.click();
        save.click();
        await settle();
        assert.equal(save.disabled, true);
        f.element.querySelector<HTMLElement>('[data-sql-tab-add]')!.click();
        f.editor.setValue('SELECT 123;', -1);
        finish!();
        await settle();
        assert.equal(save.disabled, false);
        assert.equal(f.component.getQuery(), 'SELECT 123;');
        assert.equal(f.element.querySelector<HTMLInputElement>('[data-sql-active-query-id]')!.value, '');
        /** Count create requests to detect duplicate saves. */
        const saves = f.requests.filter((request: RequestRecord): boolean => request.options.method === 'POST');
        assert.equal(saves.length, 1);
        activate(f, 'created-1');
        assert.equal(f.component.getQuery(), 'SELECT 99;');
    } finally { close(f); }
}

/** Execution uses SDK session transport and preserves server error and pagination fragments. */
async function executeQueries(): Promise<void> {
    /** Return paginated HTML and then the server's validation fragment. */
    async function handler(request: RequestRecord): Promise<Response> {
        if (request.url.pathname !== '/components/execute_sql_query/') return defaultHandler(request);
        const body = new URLSearchParams(String(request.options.body));
        if (body.get('sql_query') === 'invalid') {
            return new Response('<div data-sql-results-meta>Invalid SQL</div>', { status: 400, headers: { 'Content-Type': 'text/html' } });
        }
        return new Response(`<div data-sql-results-meta data-sql-page="${body.get('sql_page')}" data-sql-total-pages="2" data-sql-page-size="25"><table><tbody><tr><td>Result</td></tr></tbody></table></div>`, {
            headers: { 'Content-Type': 'text/html' },
        });
    }
    const f = fixture(handler);
    try {
        await settle();
        await f.component.executeQuery(1);
        assert.equal(f.element.querySelector('[data-sql-page-label]')!.textContent, 'Page 1 of 2');
        f.element.querySelector<HTMLButtonElement>('[data-sql-page-nav="next"]')!.click();
        await settle();
        assert.equal(f.element.querySelector('[data-sql-page-label]')!.textContent, 'Page 2 of 2');
        const request = f.requests[f.requests.length - 1];
        assert.equal(new Headers(request.options.headers).get('X-CSRFToken'), 'sql-fixture-csrf');
        f.editor.setValue('invalid', -1);
        await f.component.executeQuery(1);
        assert.match(f.element.querySelector('[data-sql-results-target]')!.textContent!, /Invalid SQL/);
    } finally { close(f); }
}

/** A rejected save must leave a retryable draft and show feedback. */
async function failedSave(): Promise<void> {
    /** Reject only writes while allowing catalog and query loading. */
    async function handler(request: RequestRecord): Promise<Response> {
        return request.options.method === 'POST' ? json({ detail: 'Permission denied' }, 403) : defaultHandler(request);
    }
    const f = fixture(handler);
    try {
        await settle();
        f.element.querySelector<HTMLButtonElement>('[data-sql-save]')!.click();
        await settle();
        assert.equal(f.component.getQuery(), 'SELECT 99;');
        assert.equal(f.element.querySelector<HTMLInputElement>('[data-sql-active-query-id]')!.value, '');
        assert.equal(f.element.querySelector<HTMLButtonElement>('[data-sql-save]')!.disabled, false);
        assert.match(f.element.querySelector('[data-sql-status]')!.textContent!, /Failed to save/);
    } finally { close(f); }
}

test('saved-query pagination preserves the initial query and independent tab drafts', loadQueries);
test('query create and update use the SDK model API with session CSRF', saveQueries);
test('a pending save retains new drafts and prevents duplicate creation', pendingSave);
test('execution preserves pagination and server error fragments through the SDK', executeQueries);
test('failed saves retain the draft and permit retry', failedSave);
