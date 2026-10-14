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
    };
}
interface Fixture {
    w: FixtureWindow;
    anchor: HTMLElement;
    copied: string[];
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
function fixture(options: { rejectCopy?: boolean; rejectFetch?: boolean; pendingFetch?: Promise<Response> } = {}): Fixture {
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
    /** Return rendered preview HTML locally without patching any tooltip logic. */
    async function fetchPreview(): Promise<Response> {
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
    return { w, anchor, copied, errors, advance, close };
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
