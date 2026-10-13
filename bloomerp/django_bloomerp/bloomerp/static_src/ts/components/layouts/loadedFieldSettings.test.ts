/** Exercise production layout scheduling and item click handlers with socket-free DOM fixtures. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/loaded-settings-fixture.ts`;
const buildResult = await build({
    configFile: false, root, logLevel: 'silent', resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'loaded-settings-fixture',
        /** Resolve the test adapter without changing production source. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Expose protected user actions and replace only the field transport and modal shell. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import htmx from 'htmx.org';
                import Container from '${root}/ts/components/layouts/BaseSectionedLayoutContainer';
                import Item from '${root}/ts/components/layouts/BaseSectionedLayoutItem';
                import WorkspaceContainer from '${root}/ts/components/workspaces/WorkspaceContainer';
                import { registerComponent, getComponent, initComponents } from '${root}/ts/components/BaseComponent';
                class TestItem extends Item {}
                class TestContainer extends Container {
                    private nextRender: Promise<void> | null = null;
                    private serverLabels = new Map<string, string>();
                    /** Model a successfully saved settings response on the server. */
                    setServerLabel(id: string, label: string): void { this.serverLabels.set(id, label); }
                    /** Hold one server render to reproduce a settings-close race. */
                    delayRender(): (ok?: boolean) => void { let finish: (ok?: boolean) => void; this.nextRender = new Promise<void>((resolve, reject): void => { finish = (ok: boolean = true): void => { if (ok) resolve(); else reject(new Error("Render failed")); }; }); return finish; }
                    getItemSelector(): string { return '[bloomerp-component="test-item"]'; }
                    getItemComponent(element: HTMLElement): TestItem | null { return getComponent(element) as TestItem; }
                    async renderItem(itemId: string, rowIndex: number, position?: number): Promise<void> {
                        const pending = this.nextRender; this.nextRender = null; if (pending) await pending;
                        const grid = this.rowElements[rowIndex].querySelector('[data-layout-grid]');
                        const item = document.createElement('div');
                        item.setAttribute('bloomerp-component', 'test-item');
                        item.dataset.layoutItemId = itemId;
                        item.dataset.layoutItemConfig = JSON.stringify(this.serverLabels.has(itemId) ? {label: this.serverLabels.get(itemId)} : {});
                        item.innerHTML = '<div data-layout-item-controls><button type="button" data-layout-edit-item data-layout-edit-url="/settings/' + itemId + '/">Settings</button></div>';
                        grid.insertBefore(item, grid.children[position ?? grid.children.length] ?? null);
                        initComponents(grid);
                    }
                    select(id: string): void { const item = document.createElement('button'); item.dataset.layoutItemId = id; this.addAvailableItem(item); }
                    drop(id: string): void {
                        const sidebar = this.element.querySelector('[data-layout-available-items-list]');
                        const placeholder = document.createElement('div'); placeholder.dataset.layoutItemId = id;
                        this.onItemSortAdd({from: sidebar, item: placeholder, newIndex: 0}, this.rowElements[0]);
                    }
                    queueSave(): void { this.requestSave(); }
                    /** Remove through the production action and keep indices current. */
                    remove(id: string): void { const item = this.items.find((item: TestItem): boolean => item.getLayoutItemId() === id); if (item) this.removeItem(item); }
                    getItemEditorModal(): any {
                        const element = document.getElementById('field-display-option-modal');
                        return {element, open(): void { element.dataset.open = 'true'; },
                            /** Mirror modal closure so failed loads cannot refresh unsaved editor content. */
                            close(): void { element.dataset.open = 'false'; element.dispatchEvent(new CustomEvent('bloomerp:modal-closed')); }};
                    }
                }
                registerComponent('test-item', TestItem);
                class TestWorkspace extends WorkspaceContainer {
                    /** Expose production workspace save scheduling for regression checks. */
                    queueSave(): void { this.requestSave(); }
                }
                export { TestContainer, TestWorkspace, htmx };
            `;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'LayoutFixture' } },
});
const bundle = Array.isArray(buildResult) ? buildResult[0] : buildResult;
assert('output' in bundle);
const chunk = bundle.output.find((output): boolean => output.type === 'chunk');
assert(chunk?.type === 'chunk');
const code = chunk.code;
interface Container { initialize(): void; destroy(): void; toggleEditMode(): void; select(id: string): void; drop(id: string): void; queueSave(): void; remove(id: string): void; delayRender(): (ok?: boolean) => void; setServerLabel(id: string, label: string): void; }
interface PendingSave { payload: {layout: {rows: Array<{items: Array<{id: string; config: Record<string, unknown>}>}>}}; finish(ok?: boolean): void; }
interface Fixture { dom: JSDOM; w: DOMWindow; container: Container; saves: PendingSave[]; editors: string[]; click(id: string): void; close(): void; }

/** Mount real layout/item classes, retaining manual control over save completion. */
async function fixture(workspace: boolean = false, rejectEditor: boolean = false): Promise<Fixture> {
    const dom = new JSDOM('<!doctype html><body><form><section data-layout-save-url="/save/" data-layout=\'{"rows":[{"columns":2,"items":[]}]}\'><div data-layout-root><div data-layout-row data-row-columns="2"><div data-layout-grid></div></div></div><div data-layout-available-items-list></div></section></form><div id="field-display-option-modal"><div id="field-display-option-modal-body"></div></div></body>', {
        url: 'https://layout.test', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: new VirtualConsole(),
    });
    const w = dom.window;
    const saves: PendingSave[] = [];
    const editors: string[] = [];
    /** Hold the real production fetch promise until the scenario completes it. */
    w.fetch = (_url: URL | RequestInfo, init?: RequestInit): Promise<Response> => new Promise((resolve): void => {
        saves.push({payload: JSON.parse(String(init?.body)), finish(ok: boolean = true): void { resolve(new Response(null, {status: ok ? 200 : 403})); }});
    });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply jsdom's required XPath default. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, result?: XPathResult | null): XPathResult { return evaluate.call(this, context, type ?? 0, result ?? null); };
    w.eval(code);
    const api = (w as DOMWindow & {LayoutFixture: {TestContainer: new (element: HTMLElement) => Container; TestWorkspace: new (element: HTMLElement) => Container; htmx: {ajax(method: string, url: string): Promise<void>}}}).LayoutFixture;
    /** Observe editor requests without a network or a replacement save implementation. */
    api.htmx.ajax = async (_method: string, url: string): Promise<void> => {
        editors.push(url);
        if (rejectEditor) { rejectEditor = false; throw new Error('Settings GET failed'); }
    };
    const ContainerClass = workspace ? api.TestWorkspace : api.TestContainer;
    const container = new ContainerClass(w.document.querySelector('section')!);
    container.initialize(); if (!workspace) container.toggleEditMode();
    await tick();
    return {dom,w,container,saves,editors,
        /** Click the actual production item's edit handler. */
        click(id: string): void { w.document.querySelector<HTMLButtonElement>(`[data-layout-item-id="${id}"] [data-layout-edit-item]`)!.click(); },
        /** Dispose timers and production listeners after the scenario. */
        close(): void { container.destroy(); dom.window.close(); },
    };
}
/** Drain promise continuations without advancing the layout debounce timer. */
async function tick(): Promise<void> { for (let i = 0; i < 20; i += 1) await Promise.resolve(); }

for (const path of ['select', 'drop'] as const) {
    test(`${path}: new settings click waits for persisted layout and does not submit the object form`, async (): Promise<void> => {
        const f = await fixture();
        try {
            let submitted = false;
            f.w.document.querySelector('form')!.addEventListener('submit', (event: Event): void => { submitted = true; event.preventDefault(); });
            f.container[path]('42'); await tick(); f.click('42'); await tick();
            assert.equal(f.saves.length, 1);
            assert.equal(f.editors.length, 0, 'Editor must not race the new layout save');
            assert.equal(f.saves[0].payload.layout.rows[0].items[0].id, '42');
            f.saves[0].finish(); await tick();
            assert.deepEqual(f.editors, ['/settings/42/']); assert.equal(submitted, false);
        } finally { f.close(); }
    });
}

test('failed layout save leaves settings unopened and can be retried', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('42'); await tick(); f.click('42'); await tick();
        assert.equal(f.saves.length, 1); f.saves[0].finish(false); await tick();
        assert.equal(f.editors.length, 0);
        assert.equal(f.w.document.querySelector('[data-message-type="error"]')?.getAttribute('data-message-text'), 'Unable to save the layout. Please try again before editing settings.');
        assert.notEqual(f.w.document.getElementById('field-display-option-modal')!.dataset.open, 'true');
        f.click('42'); await tick(); assert.equal(f.saves.length, 2);
        f.saves[1].finish(); await tick(); assert.deepEqual(f.editors, ['/settings/42/']);
    } finally { f.close(); }
});

test('editor waits for a newer save queued while the first save is in flight', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('41'); await tick(); f.click('41'); await tick();
        assert.equal(f.saves.length, 1);
        f.container.select('42'); await tick(); f.click('42'); await tick();
        f.saves[0].finish(); await tick();
        assert.equal(f.saves.length, 2); assert.equal(f.editors.length, 0);
        assert.equal(f.saves[1].payload.layout.rows[0].items.length, 2);
        f.saves[1].finish(); await tick(); assert.deepEqual(f.editors, ['/settings/42/']);
    } finally { f.close(); }
});

test('removed item never opens a late editor', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('42'); await tick(); f.click('42'); await tick();
        assert.equal(f.saves.length, 1);
        f.w.document.querySelector('[data-layout-item-id="42"]')!.remove();
        f.saves[0].finish(); await tick(); assert.equal(f.editors.length, 0);
    } finally { f.close(); }
});


/** Advance actual debounce timers without replacing the production scheduler. */
async function debounce(f: Fixture): Promise<void> {
    await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 160); });
}

test('closing settings rerenders the item without a stale debounce overwriting its saved config', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('42'); await tick(); f.click('42'); await tick();
        f.saves[0].finish(); await tick();
        f.w.document.getElementById('field-display-option-modal')!.dispatchEvent(new f.w.CustomEvent('bloomerp:modal-closed'));
        await tick(); await debounce(f);
        assert.equal(f.saves.length, 1, 'Closing or canceling settings must not save stale layout data');
        assert.equal(f.w.document.querySelectorAll('[data-layout-item-id="42"] [data-layout-edit-item]').length, 1);
    } finally { f.close(); }
});

test('remove and re-add does not open a stale editor for the previous element', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('42'); await tick(); f.click('42'); await tick();
        const original = f.w.document.querySelector('[data-layout-item-id="42"]')!;
        f.container.remove('42');
        f.container.select('42'); await tick();
        assert.notEqual(f.w.document.querySelector('[data-layout-item-id="42"]'), original);
        f.saves[0].finish(); await tick();
        assert.equal(f.saves.length, 2); f.saves[1].finish(); await tick();
        assert.equal(f.editors.length, 0);
        f.click('42'); await tick(); f.saves[2].finish(); await tick();
        assert.deepEqual(f.editors, ['/settings/42/']);
    } finally { f.close(); }
});

test('destroy cancels debounced work and invalidates in-flight editor requests', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('42'); await tick(); f.click('42'); await tick();
        f.container.destroy(); f.saves[0].finish(); await tick();
        assert.equal(f.editors.length, 0);
        await debounce(f); assert.equal(f.saves.length, 1);
    } finally { f.close(); }
});

test('workspace saves remain serialized and persist a change queued during a slow save', async (): Promise<void> => {
    const f = await fixture(true);
    try {
        f.container.queueSave(); await debounce(f); assert.equal(f.saves.length, 1);
        f.w.document.querySelector('[data-layout-grid]')!.innerHTML = '<div bloomerp-component="workspace-tile" data-layout-item-id="tile-2"></div>';
        f.container.queueSave(); f.saves[0].finish(); await tick();
        assert.equal(f.saves.length, 2);
        assert.equal(f.saves[1].payload.layout.rows[0].items[0].id, 'tile-2');
        f.saves[1].finish(); await tick(); await debounce(f); assert.equal(f.saves.length, 2);
    } finally { f.close(); }
});

test('workspace autosave failures are handled and a later edit retries', async (): Promise<void> => {
    const f = await fixture(true);
    try {
        f.container.queueSave(); await debounce(f); f.saves[0].finish(false); await tick();
        assert.equal(f.w.document.querySelectorAll('[data-message-type="error"]').length, 1);
        f.container.queueSave(); await debounce(f); assert.equal(f.saves.length, 2);
        f.saves[1].finish(); await tick();
    } finally { f.close(); }
});


test('opening another field waits for a slow settings-close refresh before saving either field', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('41'); await tick(); f.container.select('42'); await tick();
        f.click('41'); await tick(); f.saves[0].finish(); await tick();
        const finishRender = f.container.delayRender();
        f.w.document.getElementById('field-display-option-modal')!.dispatchEvent(new f.w.CustomEvent('bloomerp:modal-closed'));
        await tick();
        assert.equal(f.w.document.querySelector('[data-layout-item-id="41"]'), null);
        f.click('42'); await tick(); assert.equal(f.saves.length, 1, 'Do not snapshot a temporarily incomplete DOM');
        finishRender(); await tick(); assert.equal(f.saves.length, 2);
        assert.deepEqual(f.saves[1].payload.layout.rows[0].items.map((item): string => item.id), ['41', '42']);
        f.saves[1].finish(); await tick(); assert.deepEqual(f.editors, ['/settings/41/', '/settings/42/']);
    } finally { f.close(); }
});


for (const clickedId of ['41', '42']) {
test(`a failed refresh recovers before opening settings for ${clickedId} without losing saved config`, async (): Promise<void> => {
    const f = await fixture();
    try {
        f.container.select('41'); await tick(); f.container.select('42'); await tick();
        f.click('41'); await tick(); f.saves[0].finish(); await tick();
        f.container.setServerLabel('41', 'Updated on server');
        const failRender = f.container.delayRender();
        f.w.document.getElementById('field-display-option-modal')!.dispatchEvent(new f.w.CustomEvent('bloomerp:modal-closed'));
        await tick(); failRender(false); await tick();
        assert(f.w.document.querySelector('[data-layout-item-id="41"]'), 'Restore the previous field after a failed GET');
        const finishRetry = f.container.delayRender();
        f.click(clickedId); await tick(); assert.equal(f.saves.length, 1, 'Refresh stale configuration before serializing it');
        finishRetry(); await tick(); assert.equal(f.saves.length, 2);
        assert.equal(f.saves[1].payload.layout.rows[0].items[0].config.label, 'Updated on server');
        f.saves[1].finish(); await tick(); assert.deepEqual(f.editors, ['/settings/41/', `/settings/${clickedId}/`]);
    } finally { f.close(); }
});
}


test('failed settings GET reports a load error after a successful save and preserves retryable progress', async (): Promise<void> => {
    const f = await fixture(false, true);
    try {
        f.container.select('42'); await tick();
        const item = f.w.document.querySelector('[data-layout-item-id="42"]')!;
        item.setAttribute('data-layout-item-config', '{"label":"Keep my label"}');
        f.click('42'); await tick(); f.saves[0].finish(); await tick();
        assert.equal(f.w.document.querySelector('[data-message-type="error"]')?.getAttribute('data-message-text'), 'Unable to load field settings. Please try again.');
        assert.equal(f.w.document.getElementById('field-display-option-modal')!.dataset.open, 'false');
        assert.equal(f.w.document.querySelector('[data-layout-item-id="42"]'), item, 'A failed editor load must not rerender the saved field');
        assert.equal(f.saves[0].payload.layout.rows[0].items[0].config.label, 'Keep my label');
        assert.equal(item.querySelector('[data-layout-edit-item]')!.hasAttribute('aria-busy'), false);
        f.click('42'); await tick(); f.saves[1].finish(); await tick();
        assert.deepEqual(f.editors, ['/settings/42/', '/settings/42/']);
        assert.equal(f.w.document.getElementById('field-display-option-modal')!.dataset.open, 'true');
        assert.equal(f.saves[1].payload.layout.rows[0].items[0].config.label, 'Keep my label');
    } finally { f.close(); }
});
