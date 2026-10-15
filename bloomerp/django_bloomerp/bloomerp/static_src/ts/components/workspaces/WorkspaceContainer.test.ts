/** Exercise real workspace/HTMX request scheduling without a browser or network socket. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';
import type htmx from 'htmx.org';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/workspace-request-test.ts`;
const bundle = await build({
    configFile: false,
    root,
    logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'workspace-test-entry',
        /** Resolve the synthetic entry while importing the unchanged production modules. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Export the real registration and HTMX APIs into the isolated DOM. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import htmx from 'htmx.org';
                import WorkspaceContainer from '${root}/ts/components/workspaces/WorkspaceContainer';
                import { Modal } from '${root}/ts/components/Modal';
                import WorkspaceTile from '${root}/ts/components/workspaces/WorkspaceTile';
                import { registerComponent, setupComponentAutoInit } from '${root}/ts/components/BaseComponent';
                registerComponent('workspace-container', WorkspaceContainer);
                registerComponent('workspace-tile', WorkspaceTile);
                registerComponent('modal', Modal);
                export { htmx, setupComponentAutoInit };
            `;
        },
    }],
    build: {
        write: false,
        minify: false,
        lib: { entry, formats: ['iife'], name: 'WorkspaceFixture' },
    },
});
const outputBundle = Array.isArray(bundle) ? bundle[0] : bundle;
assert('output' in outputBundle);
const script = outputBundle.output.find((output): boolean => output.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface PendingRequest {
    url: string;
    onload: (() => void) | null;
    onerror: (() => void) | null;
    onabort: (() => void) | null;
    complete(status?: number): void;
}
interface FixtureWindow extends DOMWindow {
    WorkspaceFixture: { htmx: typeof htmx; setupComponentAutoInit(): void };
}

class WorkspaceFixture {
    readonly dom = new JSDOM('<!doctype html><body><main id="main-content"></main></body>', {
        url: 'https://workspace.test/', runScripts: 'outside-only', pretendToBeVisual: true,
        virtualConsole: new VirtualConsole(),
    });
    readonly window = this.dom.window as FixtureWindow;
    readonly pending: PendingRequest[] = [];
    readonly sent: string[] = [];

    /** Install an XHR transport that can only return local HTML fixtures. */
    constructor() {
        const fixture = this;
        const window = this.window;
        class ControlledRequest extends window.EventTarget implements PendingRequest {
            upload = new window.EventTarget();
            status = 200;
            response = '';
            responseText = '';
            responseURL = '';
            url = '';
            onload: (() => void) | null = null;
            onerror: (() => void) | null = null;
            onabort: (() => void) | null = null;
            /** Capture request metadata without opening a socket. */
            open(_method: string, url: string): void {
                this.url = url;
                this.responseURL = new URL(url, window.location.href).href;
            }
            /** Accept headers for this local, non-network transport. */
            setRequestHeader(_name: string, _value: string): void {}
            /** Keep the HTML transport interface used by HTMX. */
            overrideMimeType(_type: string): void {}
            /** Return a standard HTML response with no HX overrides. */
            getAllResponseHeaders(): string { return 'Content-Type: text/html\r\n'; }
            /** Return only the local response's content type. */
            getResponseHeader(name: string): string | null {
                return name.toLowerCase() === 'content-type' ? 'text/html' : null;
            }
            /** Defer completion so tests control the order of outstanding requests. */
            send(_body: unknown): void { fixture.pending.push(this); fixture.sent.push(this.url); }
            /** Deliver cancellation through HTMX's own error handling. */
            abort(): void { this.onabort?.(); }
            /** Swap a tile response through the real HTMX onload callback. */
            complete(status: number = 200): void {
                this.status = status;
                const id = new URL(this.url, window.location.href).searchParams.get('tile_id');
                this.response = this.responseText = tileMarkup(id!, true);
                this.onload?.();
            }
        }
        Object.assign(window, { XMLHttpRequest: ControlledRequest });
        const evaluate = window.XPathExpression.prototype.evaluate;
        /** Supply the browser default required explicitly by jsdom's XPath implementation. */
        window.XPathExpression.prototype.evaluate = function (
            context: Node, type?: number, result?: XPathResult | null,
        ): XPathResult { return evaluate.call(this, context, type ?? 0, result ?? null); };
        window.eval(scriptCode);
        window.WorkspaceFixture.setupComponentAutoInit();
    }

    /** Let HTMX initialize the document before any controlled request is started. */
    async ready(): Promise<void> {
        await new Promise<void>((resolve: () => void): void => { this.window.setTimeout(resolve, 0); });
    }

    /** Replace the main content using HTMX's real swap and component lifecycle events. */
    async navigate(name: string): Promise<void> {
        const layout = JSON.stringify({ rows: [{ columns: 2, items: [{ id: `${name}1` }, { id: `${name}2` }] }] });
        const markup = `<section bloomerp-component="workspace-container" data-workspace-id="${name}"
            data-layout-render-item-url="/render/" data-layout='${layout}'><div data-layout-root>
            <div data-layout-row><div data-layout-grid>${tileMarkup(`${name}1`)}${tileMarkup(`${name}2`)}</div></div>
            </div></section>`;
        this.window.WorkspaceFixture.htmx.swap(this.window.document.querySelector('main')!, markup, {
            swapStyle: 'innerHTML', swapDelay: 0, settleDelay: 0,
        });
        await flushPromises();
    }

    /** Retrieve a specific already-sent request without allowing a real network fallback. */
    take(tileId: string): PendingRequest {
        const index = this.pending.findIndex((request: PendingRequest): boolean =>
            new URL(request.url, this.window.location.href).searchParams.get('tile_id') === tileId);
        assert(index >= 0, `Expected an outstanding request for ${tileId}; sent: ${this.sent.join(', ')}`);
        return this.pending.splice(index, 1)[0];
    }

    /** Complete exactly one tile and drain its sequential-load continuation. */
    async complete(tileId: string, status: number = 200): Promise<void> {
        this.take(tileId).complete(status);
        await flushPromises();
    }

    /** Assert that both current tiles contain their response and no loading placeholders. */
    assertLoaded(name: string): void {
        const main = this.window.document.querySelector('main')!;
        assert.equal(main.querySelectorAll('.skeleton-loader').length, 0);
        for (const id of [`${name}1`, `${name}2`]) {
            assert.equal(main.querySelector(`[data-layout-item-id="${id}"] [data-layout-item-body]`)?.textContent, `Loaded ${id}`);
        }
    }

    /** Release the DOM's animation timers after each isolated test scenario. */
    close(): void { this.dom.window.close(); }
}

/** Render the minimum production tile structure required by the layout component. */
function tileMarkup(id: string, loaded: boolean = false): string {
    return `<div bloomerp-component="workspace-tile" data-layout-item-id="${id}"><div data-layout-item-header><span data-detail-label>Tile</span><button type="button" data-tile-expand>Expand tile</button></div><div data-layout-item-body>${loaded ? `Loaded ${id}` : 'Placeholder'}</div></div>`;
}

/** Drain bounded sequential promise continuations without changing response ordering. */
async function flushPromises(): Promise<void> {
    for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
}

/** Verify the original sequential load remains intact with tile-owned requests. */
async function sequentialLoad(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('current');
        assert.equal(fixture.sent.length, 1);
        await fixture.complete('current1');
        assert.equal(fixture.sent.length, 2);
        await fixture.complete('current2');
        fixture.assertLoaded('current');
    } finally { fixture.close(); }
}
test('a workspace loads all tiles sequentially', sequentialLoad);

/** Prove the latest workspace completes even if an older tile never responds. */
async function unresolvedPreviousWorkspace(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('old');
        await fixture.navigate('new');
        await fixture.complete('new1');
        await fixture.complete('new2');
        fixture.assertLoaded('new');
        assert.equal(fixture.pending.length, 1, 'The old request remains intentionally unresolved');
    } finally { fixture.close(); }
}
test('rapid replacement does not put current tiles behind an unresolved old request', unresolvedPreviousWorkspace);

/** Ensure late stale completion cannot overwrite or queue-block the current workspace. */
async function staleCompletion(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('old');
        await fixture.navigate('middle');
        await fixture.navigate('new');
        await fixture.complete('new1');
        await fixture.complete('old1');
        await fixture.complete('middle1');
        await fixture.complete('new2');
        fixture.assertLoaded('new');
        assert.equal(fixture.sent.length, 4, 'Detached workspaces must not send their remaining tile requests');
        assert.equal(fixture.pending.length, 0);
    } finally { fixture.close(); }
}
test('three rapid replacements ignore stale completion and finish every current tile', staleCompletion);

/** Keep the existing HTTP-error presentation and allow the next tile to load. */
async function currentHttpError(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('current');
        await fixture.complete('current1', 500);
        await fixture.complete('current2');
        const main = fixture.window.document.querySelector('main')!;
        assert.equal(main.querySelectorAll('.skeleton-loader').length, 0);
        assert.match(main.querySelector('[data-layout-item-id="current1"]')!.textContent!, /Unable to load tile/);
        assert.match(main.querySelector('[data-layout-item-id="current2"]')!.textContent!, /Loaded current2/);
    } finally { fixture.close(); }
}
test('a failed current tile shows an error and does not stop the following tile', currentHttpError);

/** Keep workspace filters serialized while preserving the latest requested filter values. */
async function repeatedFilters(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('current');
        const root = fixture.window.document.querySelector('[data-workspace-id]')!;
        for (const value of ['first', 'latest']) {
            root.dispatchEvent(new fixture.window.CustomEvent('bloomerp:filters-apply', {
                bubbles: true, detail: { scope: 'workspace', id: 'current', filters: [{ field: 'name', operator: 'exact', value }] },
            }));
        }
        await fixture.complete('current1');
        await fixture.complete('current2');
        assert.equal(fixture.pending.length, 1, 'Repeated filters request one serialized reload');
        await fixture.complete('current1');
        await fixture.complete('current2');
        fixture.assertLoaded('current');
        assert.equal(fixture.sent.length, 4);
        const params = new URL(fixture.sent.at(-1)!, fixture.window.location.href).searchParams;
        assert.match(params.get('filter')!, /latest/);
        assert.equal(params.get('workspace_id'), 'current');
    } finally { fixture.close(); }
}
test('repeated filter changes remain coalesced and retain the latest workspace values', repeatedFilters);

/** Cover repeated Home navigation when both generations use the same workspace and tile IDs. */
async function repeatedSameWorkspace(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('home');
        const oldRequest = fixture.take('home1');
        await fixture.navigate('home');
        await fixture.complete('home1');
        await fixture.complete('home2');
        fixture.assertLoaded('home');
        oldRequest.complete();
        await flushPromises();
        fixture.assertLoaded('home');
        assert.equal(fixture.sent.length, 3, 'The detached Home generation must not reload remaining tiles');
    } finally { fixture.close(); }
}
test('repeated Home navigation with identical IDs survives a late old response', repeatedSameWorkspace);

/** Keep a previous navigation's network failure isolated from the latest tile sequence. */
async function previousNetworkError(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('old');
        const oldRequest = fixture.take('old1');
        await fixture.navigate('new');
        oldRequest.onerror?.();
        await flushPromises();
        await fixture.complete('new1');
        await fixture.complete('new2');
        fixture.assertLoaded('new');
        assert.equal(fixture.pending.length, 0);
        assert.equal(fixture.sent.length, 3);
    } finally { fixture.close(); }
}
test('a stale network error does not prevent the latest workspace finishing', previousNetworkError);

/** Verify that exhausting every response leaves no silently dropped tile behind a skeleton. */
async function allResponsesSettled(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('old');
        await fixture.navigate('new');
        for (let response = 0; response < 10 && fixture.pending.length > 0; response += 1) {
            fixture.pending.shift()!.complete();
            await flushPromises();
        }
        assert.equal(fixture.pending.length, 0, 'All locally captured requests have completed');
        fixture.assertLoaded('new');
    } finally { fixture.close(); }
}
test('all current tiles render after every outstanding response has settled', allResponsesSettled);

/** Exercise expansion using the real modal and HTMX lifecycle without new requests. */
async function fullscreenTileLifecycle(): Promise<void> {
    const fixture = new WorkspaceFixture();
    try {
        await fixture.ready();
        await fixture.navigate('current');
        await fixture.complete('current1');
        await fixture.complete('current2');
        const { document } = fixture.window;
        const declaration = document.createElement('div');
        declaration.id = 'bloomerp-general-use-modal';
        document.body.append(declaration);
        const tile = document.querySelector<HTMLElement>('[data-layout-item-id="current1"]')!;
        const originalParent = tile.parentElement;
        const body = tile.querySelector<HTMLElement>('[data-layout-item-body]')!;
        const input = document.createElement('input');
        input.value = 'Unsaved tile state';
        body.append(input);
        const expand = tile.querySelector<HTMLButtonElement>('[data-tile-expand]')!;
        for (const closeWith of ['button', 'escape', 'history']) {
            expand.click();
            expand.click();
            assert.equal(document.querySelectorAll('[data-modal-disposable]').length, 1);
            const modal = tile.closest<HTMLElement>('[data-modal-disposable]')!;
            assert(modal.querySelector('[data-modal-container]')?.classList.contains('h-full'));
            const toggle = modal.querySelector<HTMLButtonElement>('[bloomerp-full-screen-modal]')!;
            toggle.click();
            assert(modal.querySelector('[data-modal-container]')?.classList.contains('max-w-4xl'));
            toggle.click();
            assert(modal.querySelector('[data-modal-container]')?.classList.contains('h-full'));
            assert.equal(tile.querySelector('input'), input);
            if (closeWith === 'button') modal.querySelector<HTMLButtonElement>('[bloomerp-close-modal]')!.click();
            else if (closeWith === 'escape') document.dispatchEvent(new fixture.window.KeyboardEvent('keydown', { key: 'Escape' }));
            else document.body.dispatchEvent(new fixture.window.CustomEvent('htmx:beforeHistorySave'));
            await new Promise<void>((resolve: () => void): void => { fixture.window.setTimeout(resolve, 220); });
            assert.equal(tile.parentElement, originalParent);
            assert.equal(input.value, 'Unsaved tile state');
            assert.equal(document.activeElement, expand);
            assert.equal(document.querySelectorAll('[data-modal-disposable]').length, 0);
            assert.equal(document.body.style.overflow, '');
        }
        assert.equal(fixture.sent.length, 2, 'Expansion must not fetch or duplicate the rendered tile');
        expand.click();
        await fixture.navigate('new');
        assert.equal(document.querySelectorAll('[data-modal-disposable]').length, 0);
        assert.equal(tile.isConnected, false);
        await fixture.complete('new1');
        await fixture.complete('new2');
        fixture.assertLoaded('new');
    } finally { fixture.close(); }
}
test('fullscreen tile preserves live state across close, Escape, history and workspace replacement', fullscreenTileLifecycle);

/** Keep the live tile in owner bookkeeping when its own or a sibling response finishes. */
async function fullscreenPendingTileResponse(): Promise<void> {
    for (const pending of ['current1', 'current2']) {
        const fixture = new WorkspaceFixture();
        try {
            await fixture.ready();
            await fixture.navigate('current');
            if (pending === 'current2') await fixture.complete('current1');
            const { document } = fixture.window;
            const declaration = document.createElement('div');
            declaration.id = 'bloomerp-general-use-modal';
            document.body.append(declaration);
            document.querySelector<HTMLButtonElement>('[data-tile-expand]')!.click();
            if (pending === 'current1') await fixture.complete('current1');
            await fixture.complete('current2');
            fixture.assertLoaded('current');
            assert.equal(document.querySelectorAll('[data-modal-disposable]').length, 0);
            assert.equal(document.body.style.overflow, '');
            const workspace = document.querySelector('[data-workspace-id]') as Element & {
                __bloomerp_component: { items: Array<{ getLayoutItemId(): string; setColspan(value: number): void }> };
            };
            const items = workspace.__bloomerp_component.items;
            assert.deepEqual(Array.from(items, (item): string => item.getLayoutItemId()), ['current1', 'current2']);
            items[0].setColspan(2);
            assert.equal(workspace.querySelector<HTMLElement>('[data-layout-item-id="current1"]')!.dataset.colspan, '2');
        } finally { fixture.close(); }
    }
}
test('pending own and sibling tile responses preserve expanded tile bookkeeping', fullscreenPendingTileResponse);
