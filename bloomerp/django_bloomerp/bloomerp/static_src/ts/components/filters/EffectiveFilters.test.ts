/** Real-component DOM regressions for server-recovered dataview filter state. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';
import type BaseComponent from '../BaseComponent.ts';
import type { DataViewContainer } from '../data_view_components/DataViewContainer.ts';
import type FilterContainer from './FilterContainer.ts';
import type RenderedFilter from './RenderedFilter.ts';
import type { Filter, FilterCondition, SavedFilter } from './definition.ts';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/effective-filters-regression-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'effective-filters-regression-entry',
        /** Resolve an in-memory harness without replacing any production component. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the actual badge, editor, container, modal, and component lifecycle. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import htmx from 'htmx.org';
                import { DataViewContainer } from '${root}/ts/components/data_view_components/DataViewContainer';
                import RenderedFilter from '${root}/ts/components/filters/RenderedFilter';
                import FilterContainer from '${root}/ts/components/filters/FilterContainer';
                import { Modal } from '${root}/ts/components/Modal';
                import { registerComponent, initComponents, getComponent, setupComponentAutoInit } from '${root}/ts/components/BaseComponent';
                registerComponent('data-view-container', DataViewContainer);
                registerComponent('rendered-filter', RenderedFilter);
                registerComponent('unified-filter-container', FilterContainer);
                registerComponent('modal', Modal);
                export { htmx, DataViewContainer, RenderedFilter, FilterContainer, initComponents, getComponent, setupComponentAutoInit };
            `;
        },
    }],
    build: { write: false, minify: false, lib: {
        entry, formats: ['iife'], name: 'EffectiveFiltersFixture',
    } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Find the executable bundle rather than a CSS asset emitted by the real editor. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    EffectiveFiltersFixture: {
        DataViewContainer: typeof DataViewContainer;
        RenderedFilter: typeof RenderedFilter;
        FilterContainer: typeof FilterContainer;
        htmx: { ajax(method: string, url: string, options?: unknown): Promise<void> };
        initComponents(element: HTMLElement): void;
        setupComponentAutoInit(): void;
        getComponent(element: HTMLElement): BaseComponent | null;
    };
}
interface RequestRecord { path: string; method: string; data: Record<string, unknown>; }
interface FixtureOptions { rawFilter: string; effective: Filter[]; defaults?: SavedFilter[]; mainEditor?: boolean; }
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    container: HTMLElement;
    component: DataViewContainer;
    rendered: HTMLElement;
    section: HTMLElement;
    requests: RequestRecord[];
    navigations: string[];
    errors: unknown[];
}

/** Build one well-formed condition while keeping raw URL and effective fixtures distinct. */
function condition(field: string, value: unknown): FilterCondition {
    return { field_path: field, lookup_id: 'exact', value };
}

/** Construct a conjunction of conditions accepted or rejected by the server fixture. */
function group(...conditions: FilterCondition[]): Filter {
    return { connector: 'AND', conditions };
}

/** Construct the server's configured saved-default metadata. */
function savedDefault(id: string, name: string, filters: Filter[]): SavedFilter {
    return { id, name, scope: 'model', identifier: '42', filters };
}

/** Let production label and condition-editor promise chains finish against local transport. */
async function flush(w: DOMWindow): Promise<void> {
    /** Resolve after pending promise continuations have rendered their DOM. */
    await new Promise<void>(function nextTurn(resolve: () => void): void { w.setTimeout(resolve, 0); });
}

/** Instantiate real components with only fetch and HTMX request transport mocked. */
async function fixture(options: FixtureOptions): Promise<Fixture> {
    const errors: unknown[] = [];
    const requests: RequestRecord[] = [];
    const navigations: string[] = [];
    const virtualConsole = new VirtualConsole();
    /** Preserve initialization and uncaught DOM errors for explicit assertions. */
    function captureError(error: unknown): void { errors.push(error); }
    virtualConsole.on('jsdomError', captureError);
    virtualConsole.on('error', captureError);
    const url = new URL('https://fixture.test/objects/');
    url.searchParams.set('filter', options.rawFilter);
    const dom = new JSDOM(`<!doctype html><body>
        <div id="container" bloomerp-component="data-view-container" data-content-type-id="42" data-base-url="/objects/">
            <div data-rendered-filters data-scope="model" data-scope-id="42" data-host-id="7"
                 data-defaults-url="/filters/defaults" data-value-editor-url="/filters/value-editor" data-can-manage-defaults="true">
                <div data-rendered-filter-list></div>
                <template data-rendered-filter-template>
                    <span bloomerp-component="rendered-filter"><button type="button" data-rendered-filter-label></button></span>
                </template>
                <template data-rendered-filter-modal>
                    <div id="rendered-filter-editor" bloomerp-component="modal" data-modal-title="Edit filter">
                        <div data-modal-content>
                        <div bloomerp-component="unified-filter-container" data-include-controls="true"
                             data-fields-url="/filters/fields" data-lookups-url="/filters/lookups"
                             data-value-editor-url="/filters/value-editor" data-presets-url="/filters/presets"
                             data-save-preset-url="/filters/save"></div>
                        </div>
                    </div>
                </template>
            </div>
            <div id="data-view-data-section"><span hidden data-effective-json-filters></span></div>
        </div></body>`, {
        url: url.toString(), runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole,
    });
    const w = dom.window as FixtureWindow;
    const container = w.document.getElementById('container')!;
    const rendered = container.querySelector<HTMLElement>('[data-rendered-filters]')!;
    const section = w.document.getElementById('data-view-data-section')!;
    container.dataset.url = url.toString();
    rendered.dataset.defaultFilters = JSON.stringify(options.defaults ?? []);
    section.querySelector<HTMLElement>('[data-effective-json-filters]')!.dataset.effectiveJsonFilters = JSON.stringify(options.effective);
    if (options.mainEditor) {
        const host = w.document.createElement('div');
        host.dataset.filterHostEditor = '';
        const modal = rendered.querySelector<HTMLTemplateElement>('[data-rendered-filter-modal]')!;
        const editor = modal.content.querySelector('[bloomerp-component="unified-filter-container"]')!.cloneNode(true) as HTMLElement;
        Object.assign(editor.dataset, {
            scope: 'model', scopeId: '42', allowEmpty: 'true', initialFilters: JSON.stringify(options.effective),
        });
        host.append(editor);
        container.prepend(host);
    }
    /** Capture every discovery/editor request while responding like the existing endpoints. */
    async function fetchFilter(input: string | URL, init: RequestInit = {}): Promise<unknown> {
        const requestUrl = new URL(String(input), url);
        const data: Record<string, unknown> = init.body
            ? JSON.parse(String(init.body)) : Object.fromEntries(requestUrl.searchParams);
        requests.push({ path: requestUrl.pathname, method: init.method ?? 'GET', data });
        let payload: unknown;
        if (requestUrl.pathname === '/filters/fields') {
            payload = [{ name: 'Fields', fields: [
                { field: 'owner', label: 'Owner' }, { field: 'title', label: 'Title' },
                { field: 'active', label: 'Active' }, { field: 'region', label: 'Region' },
            ] }];
        } else if (requestUrl.pathname === '/filters/lookups') {
            payload = [{ id: 'exact', label: 'Equals', nested: false }];
        } else if (requestUrl.pathname === '/filters/value-editor') {
            const widget = w.document.createElement('div');
            const inputElement = w.document.createElement('input');
            inputElement.name = 'value';
            inputElement.value = String(data.value ?? '');
            inputElement.setAttribute('value', inputElement.value);
            if (data.field_path === 'owner') widget.dataset.selectedLabels = JSON.stringify(['Alice']);
            widget.append(inputElement);
            payload = { widget: widget.outerHTML };
        } else {
            throw new Error(`Unexpected filter request: ${requestUrl.pathname}`);
        }
        /** Return fixture endpoint data without stubbing any filter behavior. */
        async function json(): Promise<unknown> { return payload; }
        return { ok: true, json };
    }
    Object.assign(w, { fetch: fetchFilter, structuredClone });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Match the browser's optional XPath result type for HTMX's jsdom startup. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, result?: XPathResult | null): XPathResult {
        return evaluate.call(this, context, type ?? 0, result ?? null);
    };
    w.eval(scriptCode);
    const api = w.EffectiveFiltersFixture;
    /** Capture outgoing dataview refreshes while leaving URL construction and events real. */
    api.htmx.ajax = async function requestData(_method: string, requestUrl: string, _options?: unknown): Promise<void> {
        navigations.push(requestUrl);
    };
    api.setupComponentAutoInit();
    api.initComponents(container);
    const component = api.getComponent(container);
    assert(component instanceof api.DataViewContainer);
    await flush(w);
    assert.deepEqual(errors, [], 'production filter components initialize cleanly');
    return { dom, w, container, component, rendered, section, requests, navigations, errors };
}

/** Return only live badges, excluding their inert template. */
function badges(f: Fixture): HTMLElement[] {
    return Array.from(f.rendered.querySelectorAll<HTMLElement>('[data-rendered-filter-list] > [bloomerp-component="rendered-filter"]'));
}

/** Read live badge labels as displayed to the user. */
function labels(f: Fixture): string[] {
    /** Extract the real RenderedFilter component's label button text. */
    return badges(f).map(function label(badge: HTMLElement): string {
        return badge.querySelector('[data-rendered-filter-label]')!.textContent!;
    });
}

/** Verify that neither labels nor editor discovery sent a rejected condition downstream. */
function assertNoRejectedRequests(f: Fixture): void {
    assert.doesNotMatch(JSON.stringify(f.requests), /secret_field|forbidden_value|malformed_value/);
    assert.deepEqual(f.errors, []);
}

/** Resolve the retained toolbar editor through the real component registry. */
function mainEditor(f: Fixture): FilterContainer {
    const root = f.container.querySelector<HTMLElement>('[data-filter-host-editor] [bloomerp-component="unified-filter-container"]');
    assert(root);
    const component = f.w.EffectiveFiltersFixture.getComponent(root);
    assert(component instanceof f.w.EffectiveFiltersFixture.FilterContainer);
    return component;
}

/** Apply the toolbar's current conditions using its production button and bubbling event. */
async function applyMainEditor(f: Fixture): Promise<void> {
    /** Locate the toolbar Apply control without selecting a badge modal's button. */
    const button = Array.from(f.container.querySelectorAll<HTMLButtonElement>('[data-filter-host-editor] button'))
        .find((control: HTMLButtonElement): boolean => control.textContent === 'Apply');
    assert(button);
    button.click();
    await flush(f.w);
}

/** Exercise the actual badge action menu and filter modal, including asynchronous editors. */
async function openEditor(f: Fixture, badge: HTMLElement): Promise<FilterContainer> {
    const label = badge.querySelector<HTMLButtonElement>('[data-rendered-filter-label]')!;
    /** Supply layout visibility; jsdom has no browser geometry engine. */
    label.getClientRects = (): DOMRectList => [label.getBoundingClientRect()] as unknown as DOMRectList;
    label.click();
    /** Find the visible Edit action generated by the production badge menu. */
    const edit = Array.from(f.w.document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
        .find((button: HTMLButtonElement): boolean => button.textContent === 'Edit');
    assert(edit, 'the real badge offers an Edit action');
    edit.click();
    await flush(f.w);
    const editorRoot = f.w.document.querySelector<HTMLElement>('body > [bloomerp-component="modal"] [bloomerp-component="unified-filter-container"]');
    assert(editorRoot, 'the real edit modal opens');
    const editor = f.w.EffectiveFiltersFixture.getComponent(editorRoot);
    assert(editor instanceof f.w.EffectiveFiltersFixture.FilterContainer);
    return editor;
}

/** Simulate a server fragment replacement and dispatch HTMX's normal bubbling swap event. */
async function swapEffective(f: Fixture, effective: Filter[], rawFilter: string): Promise<void> {
    const marker = f.w.document.createElement('span');
    marker.hidden = true;
    marker.dataset.effectiveJsonFilters = JSON.stringify(effective);
    f.section.replaceChildren(marker);
    const responseUrl = new URL('/objects/', f.w.location.href);
    responseUrl.searchParams.set('filter', rawFilter);
    f.section.dispatchEvent(new f.w.CustomEvent('htmx:afterSwap', {
        bubbles: true, detail: { target: f.section, xhr: { responseURL: responseUrl.toString() } },
    }));
    await flush(f.w);
}

/** Release real component listeners, modal instances, and jsdom timers. */
function dispose(f: Fixture): void {
    f.component.destroy();
    f.dom.window.close();
}

/** Invalid raw JSON and a completely recovered-away condition are both harmless. */
for (const rawFilter of ['{malformed_value', JSON.stringify([group(condition('secret_field', 'forbidden_value'))])]) {
    /** Treat an explicit empty effective payload as authoritative even with configured defaults. */
    test(`empty effective filters ignore raw input ${rawFilter}`, async (): Promise<void> => {
        const f = await fixture({ rawFilter, effective: [], defaults: [
            savedDefault('rejected', 'Rejected default', [group(condition('secret_field', 'forbidden_value'))]),
        ] });
        try {
            assert.deepEqual(labels(f), []);
            assert.deepEqual(f.requests, []);
            await swapEffective(f, [], rawFilter);
            await swapEffective(f, [], rawFilter);
            assert.deepEqual(labels(f), []);
            assert.deepEqual(f.requests, []);
            assertNoRejectedRequests(f);
        } finally { dispose(f); }
    });
}

/** Only server-accepted conditions may populate badges or their actual edit modal. */
test('surviving effective condition drives labels and editor requests instead of raw URL filters', async (): Promise<void> => {
    const effective = [group(condition('owner', '7'))];
    const rawFilter = JSON.stringify([group(
        condition('secret_field', 'forbidden_value'), condition('owner', '7'),
    ), { connector: 'BROKEN', conditions: [condition('title', 'malformed_value')] }]);
    const f = await fixture({ rawFilter, effective });
    try {
        assert.deepEqual(labels(f), ['owner exact Alice']);
        assert.equal(badges(f)[0].dataset.filters, JSON.stringify(effective));
        const editor = await openEditor(f, badges(f)[0]);
        assert.equal(JSON.stringify(editor.getFilters()), JSON.stringify(effective));
        assert.equal(f.w.document.querySelectorAll('body > [bloomerp-component="modal"] [data-filter-condition]').length, 1);
        assert.equal(f.requests.filter((request: RequestRecord): boolean => request.path === '/filters/value-editor').length, 2);
        assertNoRejectedRequests(f);
    } finally { dispose(f); }
});

/** Matching defaults preserve both their saved identity and named badge across recovery. */
test('a valid default keeps its identity even when effective JSON object keys are reordered', async (): Promise<void> => {
    const filters = [group(condition('owner', '7'))];
    const effective: Filter[] = [{ conditions: [{ value: '7', lookup_id: 'exact', field_path: 'owner' }], connector: 'AND' }];
    const f = await fixture({ rawFilter: '{malformed_value', effective, defaults: [savedDefault('valid-default', 'My owners', filters)] });
    try {
        assert.deepEqual(labels(f), ['My owners']);
        assert.equal(badges(f)[0].dataset.defaultFilterId, 'valid-default');
        assert.equal(badges(f)[0].dataset.savedFilterId, 'valid-default');
        assert.equal(f.requests.length, 0, 'named defaults do not need label-resolution requests');
        const editor = await openEditor(f, badges(f)[0]);
        assert.equal(JSON.stringify(editor.getFilters()), JSON.stringify(filters));
        const name = f.w.document.querySelector<HTMLInputElement>('body > [bloomerp-component="modal"] input[aria-label="Filter name"]');
        assert.equal(name?.value, 'My owners');
        const firstBadge = badges(f)[0];
        await swapEffective(f, effective, '{malformed_value');
        await swapEffective(f, effective, '{malformed_value');
        assert.equal(badges(f)[0], firstBadge, 'equivalent restoration does not recreate or duplicate badges');
        assert.deepEqual(labels(f), ['My owners']);
        assertNoRejectedRequests(f);
    } finally { dispose(f); }
});

/** Default metadata must never resurrect a rejected condition in a recovered group. */
for (const defaults of [
    [savedDefault('rejected', 'Rejected default', [group(condition('secret_field', 'forbidden_value'))])],
    [savedDefault('partial-group', 'Partially rejected group', [group(condition('owner', '7'), condition('secret_field', 'forbidden_value'))])],
    [savedDefault('partial-collection', 'Partially rejected collection', [group(condition('owner', '7')), group(condition('secret_field', 'forbidden_value'))])],
]) {
    /** Keep recovered remnants as regular filters and use only those remnants on edit. */
    test(`${defaults[0].name} is not reintroduced when a valid condition survives`, async (): Promise<void> => {
        const effective = [group(condition('owner', '7'))];
        const f = await fixture({ rawFilter: JSON.stringify(defaults[0].filters), effective, defaults });
        try {
            assert.deepEqual(labels(f), ['owner exact Alice']);
            assert.equal(badges(f)[0].dataset.defaultFilterId, undefined);
            assert.equal(badges(f)[0].dataset.savedFilterId, undefined);
            const editor = await openEditor(f, badges(f)[0]);
            assert.equal(JSON.stringify(editor.getFilters()), JSON.stringify(effective));
            const component = f.w.EffectiveFiltersFixture.getComponent(badges(f)[0]);
            assert(component instanceof f.w.EffectiveFiltersFixture.RenderedFilter);
            component.confirmEdit(effective);
            await flush(f.w);
            assert.deepEqual(labels(f), ['owner exact Alice']);
            assert.equal(f.navigations.length, 1);
            assert.deepEqual(JSON.parse(new URL(f.navigations[0]).searchParams.get('filter')!), effective);
            await swapEffective(f, effective, JSON.stringify(defaults[0].filters));
            assert.deepEqual(labels(f), ['owner exact Alice']);
            assertNoRejectedRequests(f);
        } finally { dispose(f); }
    });
}

/** Data-section swaps refresh the retained toolbar using each new authoritative payload. */
test('partial swaps retain the container, replace stale badges, and clear to empty without duplication', async (): Promise<void> => {
    const initial = [group(condition('title', 'Old'))];
    const validDefault = savedDefault('valid-default', 'Current owner', [group(condition('owner', '7'))]);
    const f = await fixture({ rawFilter: JSON.stringify(initial), effective: initial, defaults: [validDefault] });
    try {
        assert.deepEqual(labels(f), ['title exact Old']);
        const retainedComponent = f.component;
        const retainedControls = f.rendered;
        const next = [...validDefault.filters, group(condition('title', 'New'))];
        const rejectedRaw = JSON.stringify([group(condition('secret_field', 'forbidden_value'))]);
        await swapEffective(f, next, rejectedRaw);
        assert.equal(f.w.EffectiveFiltersFixture.getComponent(f.container), retainedComponent);
        assert.equal(f.container.querySelector('[data-rendered-filters]'), retainedControls);
        assert.deepEqual(labels(f), ['Current owner', 'title exact New']);
        assert.equal(badges(f)[0].dataset.defaultFilterId, 'valid-default');
        const retainedBadges = badges(f);
        const requestCount = f.requests.length;
        await swapEffective(f, next, rejectedRaw);
        assert.deepEqual(badges(f), retainedBadges, 'repeated swap retains the same two badges');
        assert.equal(f.requests.length, requestCount, 'repeated restoration adds no label requests');
        await swapEffective(f, [], rejectedRaw);
        await swapEffective(f, [], rejectedRaw);
        assert.deepEqual(labels(f), []);
        assert.equal(f.w.EffectiveFiltersFixture.getComponent(f.container), retainedComponent);
        assert.equal(f.requests.length, requestCount);
        assertNoRejectedRequests(f);
    } finally { dispose(f); }
});

/** Applying a valid toolbar filter must not revive server-rejected defaults locally. */
test('user Apply keeps rejected defaults suppressed through repeated applications', async (): Promise<void> => {
    const effective = [group(condition('owner', '7'))];
    const defaults = [
        savedDefault('rejected', 'Rejected default', [group(condition('secret_field', 'forbidden_value'))]),
        savedDefault('partial', 'Partial default', [group(condition('owner', '7'), condition('secret_field', 'forbidden_value'))]),
    ];
    const f = await fixture({ rawFilter: JSON.stringify(defaults[0].filters), effective, defaults, mainEditor: true });
    try {
        assert.deepEqual(labels(f), ['owner exact Alice']);
        await applyMainEditor(f);
        await applyMainEditor(f);
        assert.deepEqual(labels(f), ['owner exact Alice']);
        assert.equal(badges(f)[0].dataset.defaultFilterId, undefined);
        assert.equal(f.navigations.length, 2);
        for (const url of f.navigations) {
            assert.deepEqual(JSON.parse(new URL(url).searchParams.get('filter')!), effective);
        }
        assertNoRejectedRequests(f);
    } finally { dispose(f); }
});

/** A retained toolbar must edit the latest response rather than its original filter payload. */
test('partial swap refreshes the same toolbar editor and permits defaults accepted by a later response', async (): Promise<void> => {
    const initial = [group(condition('title', 'Old'))];
    const defaults = [savedDefault('later-default', 'European rows', [group(condition('region', 'EU'))])];
    const f = await fixture({ rawFilter: JSON.stringify(initial), effective: initial, defaults, mainEditor: true });
    try {
        const retainedEditor = mainEditor(f);
        const next = [...defaults[0].filters, group(condition('owner', '7'))];
        const rejectedRaw = JSON.stringify([group(condition('secret_field', 'forbidden_value'))]);
        await swapEffective(f, next, rejectedRaw);
        assert.equal(mainEditor(f), retainedEditor);
        assert.equal(JSON.stringify(retainedEditor.getFilters()), JSON.stringify(next));
        assert.deepEqual(labels(f), ['European rows', 'owner exact Alice']);
        assert.equal(badges(f)[0].dataset.defaultFilterId, 'later-default');
        await applyMainEditor(f);
        assert.deepEqual(labels(f), ['European rows', 'owner exact Alice']);
        assert.deepEqual(JSON.parse(new URL(f.navigations[0]).searchParams.get('filter')!), next);
        await swapEffective(f, [], rejectedRaw);
        assert.equal(mainEditor(f), retainedEditor);
        assert.equal(JSON.stringify(retainedEditor.getFilters()), '[]');
        assert.deepEqual(labels(f), []);
        await applyMainEditor(f);
        assert.deepEqual(labels(f), []);
        assert.deepEqual(JSON.parse(new URL(f.navigations.at(-1)!).searchParams.get('filter')!), []);
        assertNoRejectedRequests(f);
    } finally { dispose(f); }
});
