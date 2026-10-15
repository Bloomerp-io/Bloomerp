/** Real tooltip and foreign-field DOM regressions with local transport and deterministic hover timers. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';
import type { attachObjectPreviewTooltip, hideObjectPreviewTooltip } from './objectPreviewTooltip.ts';

const root = fileURLToPath(new URL('../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/object-preview-regression-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'object-preview-regression-entry',
        /** Resolve an in-memory entry without adding production exports for tests. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Exercise the shipped manager alongside the real document-level widget handlers. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import ForeignFieldWidget from '${root}/ts/components/widgets/ForeignFieldWidget';
                import { DataTable, DataTableCell } from '${root}/ts/components/data_view_components/DataTable';
                import { KanbanBoard, KanbanCard } from '${root}/ts/components/data_view_components/KanbanBoard';
                import { CardView, CardViewCard } from '${root}/ts/components/data_view_components/CardView';
                import { Calendar, CalendarCell } from '${root}/ts/components/data_view_components/Calendar';
                import { registerComponent, initComponents, getComponent, setupComponentAutoInit } from '${root}/ts/components/BaseComponent';
                registerComponent('datatable', DataTable);
                registerComponent('datatable-cell', DataTableCell);
                registerComponent('kanban-board', KanbanBoard);
                registerComponent('kanban-card', KanbanCard);
                registerComponent('card-view', CardView);
                registerComponent('card-view-card', CardViewCard);
                registerComponent('calendar', Calendar);
                registerComponent('calendar-cell', CalendarCell);
                export { initComponents, getComponent, setupComponentAutoInit };
                export { attachObjectPreviewTooltip, hideObjectPreviewTooltip } from '${root}/ts/utils/objectPreviewTooltip';
                export { ForeignFieldWidget };
            `;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'PreviewFixture' } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Identify the executable bundle among emitted assets. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    PreviewFixture: {
        attachObjectPreviewTooltip: typeof attachObjectPreviewTooltip;
        hideObjectPreviewTooltip: typeof hideObjectPreviewTooltip;
        ForeignFieldWidget: new(element: HTMLElement) => { initialize(): void; destroy(): void };
        initComponents(element: HTMLElement): void;
        setupComponentAutoInit(): void;
        getComponent(element: HTMLElement): { destroy(): void; currentCell?: { element: HTMLElement } } | null;
    };
}
interface Fixture {
    w: FixtureWindow;
    anchor: HTMLElement;
    copied: string[];
    requests: string[];
    errors: unknown[];
    advance(milliseconds: number): Promise<void>;
    close(): void;
}
const markup = `<div data-preview-field="10"><div><span data-preview-label>Description</span>
    <button type="button" data-preview-copy aria-label="Copy Description"><i>Copy</i></button></div>
    <div data-preview-value>Preview <strong>description</strong> &amp; details</div>
    <span data-preview-copy-status aria-live="polite"></span></div>
    <a id="preview-link" href="/objects/42/">Related object</a>`;

/** Create isolated browser-like state; replace only timers, network and clipboard. */
function fixture(options: { rejectCopy?: boolean; rejectFetch?: boolean; pendingFetch?: Promise<Response>; responseFor?: (url: string) => Promise<Response> } = {}): Fixture {
    const errors: unknown[] = [];
    const virtualConsole = new VirtualConsole();
    /** Record uncaught DOM failures separately from handled preview fetch failures. */
    function captureError(error: unknown): void { errors.push(error); }
    virtualConsole.on('jsdomError', captureError);
    const dom = new JSDOM(`<!doctype html><body><button id="anchor">Preview</button><button id="outside">Outside</button>
        <div id="widget" data-content-type-id="1" data-field-name="owner"><input type="text">
        <div class="foreign-field-dropdown hidden"><ul class="foreign-field-results"></ul></div>
        <div class="foreign-field-selected"></div></div></body>`, {
        url: 'https://fixture.test', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole,
    });
    const w = dom.window as FixtureWindow;
    /** Model browser scrolling, which jsdom intentionally does not implement. */
    w.HTMLElement.prototype.scrollIntoView = function(_options?: boolean | ScrollIntoViewOptions): void {};
    let now = 0;
    let nextId = 0;
    const timers = new Map<number, { due: number; handler: () => void }>();
    /** Schedule deterministic timers while retaining the manager's actual delay choices. */
    w.setTimeout = (handler: TimerHandler, delay: number = 0): number => {
        assert.equal(typeof handler, 'function');
        const id = ++nextId;
        timers.set(id, { due: now + delay, handler: handler as () => void });
        return id;
    };
    /** Cancel only the requested timer as the browser would. */
    w.clearTimeout = (id: number): void => { timers.delete(id); };
    const requests: string[] = [];
    /** Return rendered preview HTML locally without patching any tooltip logic. */
    async function fetchPreview(input: RequestInfo | URL): Promise<Response> {
        requests.push(String(input));
        if (options.responseFor) return options.responseFor(String(input));
        if (options.pendingFetch) return options.pendingFetch;
        if (options.rejectFetch) throw new Error('Preview unavailable');
        return new Response(markup);
    }
    const copied: string[] = [];
    /** Capture clipboard values and model a denied clipboard permission. */
    async function writeText(value: string): Promise<void> {
        if (options.rejectCopy) throw new Error('Clipboard denied');
        copied.push(value);
    }
    Object.assign(w, { fetch: fetchPreview });
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText } });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type, which jsdom requires explicitly. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, res?: XPathResult | null): XPathResult {
        return evaluate.call(this, context, type ?? 0, res ?? null);
    };
    w.eval(scriptCode);
    const widget = new w.PreviewFixture.ForeignFieldWidget(w.document.getElementById('widget')!);
    widget.initialize();
    const anchor = w.document.getElementById('anchor')!;
    const cleanup = w.PreviewFixture.attachObjectPreviewTooltip({ element: anchor, objectId: '42', contentTypeId: '1' });
    /** Run due timers and flush transport, DOM and clipboard promise continuations. */
    async function advance(milliseconds: number): Promise<void> {
        now += milliseconds;
        for (const [id, timer] of timers) {
            if (timer.due <= now) { timers.delete(id); timer.handler(); }
        }
        for (let index = 0; index < 12; index++) await Promise.resolve();
    }
    /** Release production handlers and the isolated DOM after every regression. */
    function close(): void { cleanup(); widget.destroy(); w.PreviewFixture.hideObjectPreviewTooltip(); dom.window.close(); }
    return { w, anchor, copied, requests, errors, advance, close };
}

/** Trigger the same non-bubbling enter/leave events used by production hover handlers. */
function hover(w: DOMWindow, element: HTMLElement, type: 'mouseenter' | 'mouseleave'): void {
    element.dispatchEvent(new w.MouseEvent(type));
}

/** Show a preview after the intentional hover delay and return its portal. */
async function open(f: Fixture): Promise<HTMLElement> {
    hover(f.w, f.anchor, 'mouseenter');
    await f.advance(999);
    assert.equal(f.w.document.querySelector('.foreign-field-preview-tooltip'), null);
    await f.advance(1);
    const tooltip = f.w.document.querySelector<HTMLElement>('.foreign-field-preview-tooltip')!;
    assert(tooltip && !tooltip.classList.contains('hidden'));
    assert(tooltip.querySelector('[data-preview-value]'));
    return tooltip;
}

/** Reproduce the reported click-away bug and check hover ownership through repeated copies and links. */
async function keepPreviewInteractive(): Promise<void> {
    const f = fixture();
    try {
        const tooltip = await open(f);
        hover(f.w, f.anchor, 'mouseleave');
        hover(f.w, tooltip, 'mouseenter');
        await f.advance(200);
        const button = tooltip.querySelector<HTMLButtonElement>('[data-preview-copy]')!;
        tooltip.querySelector<HTMLElement>('i')!.click();
        await f.advance(0);
        assert.deepEqual(f.copied, ['Preview description & details']);
        assert.equal(tooltip.querySelector('[data-preview-copy-status]')!.textContent, 'Copied');
        assert.equal(button.disabled, false);
        button.click();
        await f.advance(0);
        assert.equal(f.copied.length, 2);
        assert.equal(tooltip.classList.contains('hidden'), false);
        let followedLink = false;
        /** Capture native link delivery without navigating jsdom's document. */
        function linkClick(event: Event): void { followedLink = true; event.preventDefault(); }
        tooltip.querySelector('a')!.addEventListener('click', linkClick);
        tooltip.querySelector('a')!.click();
        assert.equal(followedLink, true);
        assert.equal(tooltip.classList.contains('hidden'), false);
        hover(f.w, tooltip, 'mouseleave');
        await f.advance(151);
        assert.equal(tooltip.classList.contains('hidden'), true);
        assert.deepEqual(f.errors, []);
    } finally { f.close(); }
}
test('preview survives nested copy and link clicks until hover leaves', keepPreviewInteractive);

/** Clipboard permission failure is visible, recoverable and does not dismiss the preview. */
async function clipboardFailure(): Promise<void> {
    const f = fixture({ rejectCopy: true });
    try {
        const tooltip = await open(f);
        const button = tooltip.querySelector<HTMLButtonElement>('[data-preview-copy]')!;
        button.click();
        await f.advance(0);
        assert.match(tooltip.querySelector('[data-preview-copy-status]')!.textContent!, /Could not copy/);
        assert.equal(button.disabled, false);
        assert.equal(tooltip.classList.contains('hidden'), false);
        assert.deepEqual(f.errors, []);
    } finally { f.close(); }
}
test('clipboard rejection leaves a usable preview with feedback', clipboardFailure);

/** Outside clicks still dismiss the portal and a subsequent hover reopens it. */
async function outsideClickAndReopen(): Promise<void> {
    const f = fixture();
    try {
        const tooltip = await open(f);
        f.w.document.getElementById('outside')!.click();
        assert.equal(tooltip.classList.contains('hidden'), true);
        hover(f.w, f.anchor, 'mouseenter');
        await f.advance(1000);
        assert.equal(tooltip.classList.contains('hidden'), false);
        assert(tooltip.querySelector('[data-preview-copy]'));
    } finally { f.close(); }
}
test('outside dismissal and repeat hover remain functional', outsideClickAndReopen);

/** Cancelling a hover before the delay never flashes an unwanted tooltip. */
async function interruptedHover(): Promise<void> {
    const f = fixture();
    try {
        hover(f.w, f.anchor, 'mouseenter');
        await f.advance(500);
        hover(f.w, f.anchor, 'mouseleave');
        await f.advance(1000);
        assert.equal(f.w.document.querySelector('.foreign-field-preview-tooltip'), null);
    } finally { f.close(); }
}
test('leaving before the preview delay cancels opening', interruptedHover);

/** A dismissed pending response cannot resurrect a preview after navigation or cleanup. */
async function staleResponse(): Promise<void> {
    let resolveFetch: (value: Response) => void;
    const pendingFetch = new Promise<Response>(function captureResolve(resolve: (value: Response) => void): void { resolveFetch = resolve; });
    const f = fixture({ pendingFetch });
    try {
        hover(f.w, f.anchor, 'mouseenter');
        await f.advance(1000);
        const tooltip = f.w.document.querySelector<HTMLElement>('.foreign-field-preview-tooltip')!;
        f.w.PreviewFixture.hideObjectPreviewTooltip();
        resolveFetch!(new Response(markup));
        await f.advance(0);
        assert.equal(tooltip.classList.contains('hidden'), true);
        assert.equal(tooltip.querySelector('[data-preview-copy]'), null);
    } finally { f.close(); }
}
test('late responses cannot revive a dismissed preview', staleResponse);

/** A failed preview fetch stays bounded to the panel and a later hover can retry. */
async function failedPreviewRetry(): Promise<void> {
    const options = { rejectFetch: true };
    const f = fixture(options);
    try {
        hover(f.w, f.anchor, 'mouseenter');
        await f.advance(1000);
        const tooltip = f.w.document.querySelector<HTMLElement>('.foreign-field-preview-tooltip')!;
        assert.match(tooltip.textContent!, /Preview unavailable/);
        assert.equal(tooltip.querySelector('[data-preview-copy]'), null);
        hover(f.w, f.anchor, 'mouseleave');
        await f.advance(151);
        assert.equal(tooltip.classList.contains('hidden'), true);
        options.rejectFetch = false;
        hover(f.w, f.anchor, 'mouseenter');
        await f.advance(1000);
        assert(tooltip.querySelector('[data-preview-copy]'));
        assert.equal(tooltip.classList.contains('hidden'), false);
    } finally { f.close(); }
}
test('failed preview requests can be retried on a later hover', failedPreviewRetry);


/** Reproduce valid nested field markup without adding a nested component identity. */
function foreignValue(objectId: string = '42'): string {
    return `<span data-foreign-preview-object-id="${objectId}" data-foreign-preview-content-type-id="2"><a href="/related/${objectId}/">Related value</a></span>`;
}

/** Mount an actual production dataview and its actual cell class around a foreign value. */
function mountView(f: Fixture, view: string): HTMLElement {
    const cellComponent = { table: 'datatable-cell', kanban: 'kanban-card', card: 'card-view-card', calendar: 'calendar-cell' }[view];
    const viewComponent = { table: 'datatable', kanban: 'kanban-board', card: 'card-view', calendar: 'calendar' }[view];
    const tag = view === 'table' ? 'td' : 'div';
    const cell = `<${tag} id="view-cell" bloomerp-component="${cellComponent}" data-detail-url="/owners/99/" data-object-id="99" data-object-string="Owner" data-column-index="0" data-row-index="0">${foreignValue()}</${tag}>`;
    const content = view === 'table' ? `<table><tbody><tr>${cell}</tr></tbody></table>` : cell;
    const root = f.w.document.createElement('div');
    root.setAttribute('bloomerp-component', viewComponent!);
    root.dataset.contentTypeId = '1';
    root.innerHTML = content;
    f.w.document.body.append(root);
    f.w.PreviewFixture.initComponents(root);
    return root;
}

/** Check hover and navigation through every shipped view's shared initialization path. */
function viewContract(view: string): () => Promise<void> {
    /** Validate one view without mocking its container, cell, binding helper or tooltip manager. */
    return async function checkView(): Promise<void> {
        const f = fixture();
        const root = mountView(f, view);
        try {
            const link = root.querySelector<HTMLAnchorElement>('a')!;
            f.w.PreviewFixture.setupComponentAutoInit();
            for (let index = 0; index < 3; index++) {
                f.w.document.body.dispatchEvent(new f.w.CustomEvent('htmx:afterSwap', { detail: { target: root } }));
            }
            hover(f.w, link, 'mouseenter');
            await f.advance(1000);
            assert.deepEqual(f.requests, ['/components/object-preview/2/42/']);
            assert(f.w.document.querySelector('[data-preview-copy]'));
            let delivered = false;
            /** Observe unchanged native click delivery while suppressing jsdom navigation only. */
            function inspectClick(event: MouseEvent): void {
                assert.equal(event.defaultPrevented, false);
                delivered = true;
                event.preventDefault();
            }
            link.addEventListener('click', inspectClick);
            link.click();
            assert.equal(delivered, true);
            assert.equal(link.getAttribute('href'), '/related/42/');
            const menuEvent = new f.w.MouseEvent('contextmenu', { bubbles: true, cancelable: true });
            link.dispatchEvent(menuEvent);
            assert.equal(menuEvent.defaultPrevented, true, 'the existing cell context menu still owns the event');
            assert.equal(f.w.PreviewFixture.getComponent(root)!.currentCell?.element, root.querySelector('#view-cell'));
            assert.deepEqual(f.errors, []);
        } finally { f.w.PreviewFixture.getComponent(root)?.destroy(); f.close(); }
    };
}
for (const view of ['table', 'kanban', 'card', 'calendar']) {
    test(`${view} foreign values preview once and preserve link and cell navigation`, viewContract(view));
}

/** Reconcile replacement fragments and metadata changes without retaining old listeners. */
async function replacedForeignValues(): Promise<void> {
    const f = fixture();
    const root = mountView(f, 'card');
    try {
        const old = root.querySelector<HTMLElement>('[data-foreign-preview-object-id]')!;
        const oldLink = old.querySelector('a')!;
        hover(f.w, oldLink, 'mouseenter');
        old.dispatchEvent(new f.w.CustomEvent('htmx:beforeCleanupElement', { bubbles: true, detail: { elt: old } }));
        old.outerHTML = foreignValue('43');
        await f.advance(1000);
        assert.deepEqual(f.requests, [], 'removed values never finish their scheduled hover');
        hover(f.w, oldLink, 'mouseenter');
        await f.advance(1000);
        assert.deepEqual(f.requests, [], 'removed values have no remaining hover listeners');
        const next = root.querySelector<HTMLElement>('[data-foreign-preview-object-id]')!;
        hover(f.w, next.querySelector('a')!, 'mouseenter');
        await f.advance(1000);
        assert.deepEqual(f.requests, ['/components/object-preview/2/43/']);
        next.dataset.foreignPreviewObjectId = '';
        await f.advance(0);
        hover(f.w, next.querySelector('a')!, 'mouseenter');
        await f.advance(1000);
        assert.equal(f.requests.length, 1, 'blank identity never creates a preview request');
        root.dispatchEvent(new f.w.CustomEvent('htmx:beforeCleanupElement', { bubbles: true, detail: { elt: root } }));
        next.dataset.foreignPreviewObjectId = '44';
        await f.advance(0);
        hover(f.w, next.querySelector('a')!, 'mouseenter');
        await f.advance(1000);
        assert.equal(f.requests.length, 1, 'a cleaned dataview no longer observes new values');
    } finally { f.w.PreviewFixture.getComponent(root)?.destroy(); f.close(); }
}
test('HTMX replacements and removed identities release foreign preview listeners', replacedForeignValues);

/** Keep same-record hover ownership separate from the content cache when a prior row disappears. */
async function pendingSameRecordMovesToNewAnchor(): Promise<void> {
    let resolveFetch: (value: Response) => void;
    const pendingFetch = new Promise<Response>(function captureResolve(resolve: (value: Response) => void): void { resolveFetch = resolve; });
    const f = fixture({ pendingFetch });
    const root = mountView(f, 'card');
    try {
        const first = root.querySelector<HTMLAnchorElement>('a')!;
        root.querySelector('#view-cell')!.insertAdjacentHTML('beforeend', foreignValue());
        await f.advance(0);
        const second = root.querySelectorAll<HTMLAnchorElement>('a')[1];
        /** Distinguish the newer anchor's geometry from the removed one. */
        second.getBoundingClientRect = (): DOMRect => ({ left: 350, top: 300, width: 20, bottom: 320 } as DOMRect);
        hover(f.w, first, 'mouseenter');
        await f.advance(1000);
        hover(f.w, first, 'mouseleave');
        hover(f.w, second, 'mouseenter');
        first.parentElement!.dispatchEvent(new f.w.CustomEvent('htmx:beforeCleanupElement', { bubbles: true, detail: { elt: first.parentElement } }));
        first.parentElement!.remove();
        await f.advance(200);
        resolveFetch!(new Response(markup));
        await f.advance(0);
        const tooltip = f.w.document.querySelector<HTMLElement>('.foreign-field-preview-tooltip')!;
        assert.equal(tooltip.classList.contains('hidden'), false);
        assert(tooltip.querySelector('[data-preview-copy]'));
        assert.equal(tooltip.style.left, '360px');
        assert.deepEqual(f.requests, ['/components/object-preview/2/42/']);
    } finally { f.w.PreviewFixture.getComponent(root)?.destroy(); f.close(); }
}
test('pending same-record preview follows the surviving anchor after row replacement', pendingSameRecordMovesToNewAnchor);


/** Returning to an earlier record must not mistake a loading panel for cached preview content. */
async function returnWhileOtherRecordLoads(): Promise<void> {
    let resolveOther: (value: Response) => void;
    const otherResponse = new Promise<Response>(function captureResolve(resolve: (value: Response) => void): void { resolveOther = resolve; });
    /** Delay only the second record while serving the first one's real HTML immediately. */
    async function responseFor(url: string): Promise<Response> {
        return url.endsWith('/43/') ? otherResponse : new Response(markup);
    }
    const f = fixture({ responseFor });
    const root = mountView(f, 'table');
    try {
        root.querySelector('#view-cell')!.insertAdjacentHTML('beforeend', foreignValue('43'));
        await f.advance(0);
        const [first, second] = root.querySelectorAll<HTMLAnchorElement>('a');
        hover(f.w, first, 'mouseenter');
        await f.advance(1000);
        assert(f.w.document.querySelector('[data-preview-copy]'));
        hover(f.w, first, 'mouseleave');
        hover(f.w, second, 'mouseenter');
        await f.advance(1000);
        assert.equal(f.w.document.querySelector('[data-preview-copy]'), null);
        hover(f.w, second, 'mouseleave');
        hover(f.w, first, 'mouseenter');
        await f.advance(1000);
        assert(f.w.document.querySelector('[data-preview-copy]'), 'returning to A restores A content instead of keeping B spinner');
        resolveOther!(new Response('<p>Stale second record</p>'));
        await f.advance(0);
        const tooltip = f.w.document.querySelector<HTMLElement>('.foreign-field-preview-tooltip')!;
        assert.doesNotMatch(tooltip.textContent!, /Stale second record/);
        assert.deepEqual(f.requests, ['/components/object-preview/2/42/', '/components/object-preview/2/43/', '/components/object-preview/2/42/']);
    } finally { f.w.PreviewFixture.getComponent(root)?.destroy(); f.close(); }
}
test('returning to an earlier foreign value during another fetch restores its preview', returnWhileOtherRecordLoads);
