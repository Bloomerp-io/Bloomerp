/** Real-component DOM regressions for foreign-key portal restoration and form history. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import type ForeignFieldWidget from './ForeignFieldWidget.ts';
import type InboxCalendarOverlay from '../inbox/InboxCalendarOverlay.ts';
import type { DetailViewCell, DetailViewCellChangeDetail } from '../detail_view_components/DetailViewCell.ts';
import type FormBehaviorRuntime from '../behaviors/FormBehaviorRuntime.ts';
import type { Filter } from '../filters/definition.ts';
import type ObjectCRUDViewContainer from '../detail_view_components/ObjectCRUDViewContainer.ts';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/foreign-field-regression-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'foreign-field-regression-entry',
        /** Resolve an in-memory entry that shares the real component registry. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the unchanged widget, field cell, and form change controller together. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import FormBehaviorRuntime from '${root}/ts/components/behaviors/FormBehaviorRuntime';
                import ForeignFieldWidget from '${root}/ts/components/widgets/ForeignFieldWidget';
                import InboxCalendarOverlay from '${root}/ts/components/inbox/InboxCalendarOverlay';
                import { DetailViewCell } from '${root}/ts/components/detail_view_components/DetailViewCell';
                import ObjectCRUDViewContainer from '${root}/ts/components/detail_view_components/ObjectCRUDViewContainer';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('foreign-field-widget', ForeignFieldWidget);
                registerComponent('detail-view-value', DetailViewCell);
                registerComponent('object-crud-view-container', ObjectCRUDViewContainer);
                export { FormBehaviorRuntime, ForeignFieldWidget, InboxCalendarOverlay, DetailViewCell, ObjectCRUDViewContainer, initComponents, getComponent };
            `;
        },
    }],
    build: { write: false, minify: false, lib: {
        entry, formats: ['iife'], name: 'ForeignFieldFixture',
    } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Locate the executable production bundle among emitted assets. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    ForeignFieldFixture: {
        FormBehaviorRuntime: typeof FormBehaviorRuntime;
        ForeignFieldWidget: typeof ForeignFieldWidget;
        InboxCalendarOverlay: typeof InboxCalendarOverlay;
        DetailViewCell: typeof DetailViewCell;
        ObjectCRUDViewContainer: typeof ObjectCRUDViewContainer;
        initComponents(element: HTMLElement): void;
        getComponent(element: HTMLElement): ForeignFieldWidget | DetailViewCell | ObjectCRUDViewContainer | null;
    };
}
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    panel: HTMLElement;
    widget: HTMLElement;
    input: HTMLInputElement;
    menu: HTMLElement;
    component: ForeignFieldWidget;
    cell: DetailViewCell;
    container: ObjectCRUDViewContainer;
    form: HTMLFormElement;
    buttons: HTMLElement;
    errors: unknown[];
}
interface FixtureOptions { restoreAtEnd?: boolean; initiallySelected?: boolean; isM2M?: boolean; disabled?: boolean; }

/** Flush the mocked search response without opening a browser or a network connection. */
async function flushResults(w: DOMWindow): Promise<void> {
    /** Resolve after the local search promise and rendering microtasks have run. */
    await new Promise<void>(function nextTurn(resolve: () => void): void { w.setTimeout(resolve, 0); });
}

/** Instantiate the production form pipeline with only transport and browser geometry replaced. */
async function fixture(popover: boolean = true, options: FixtureOptions = {}): Promise<Fixture> {
    const errors: unknown[] = [];
    const virtualConsole = new VirtualConsole();
    /** Surface uncaught DOM exceptions and production initialization errors in assertions. */
    function captureError(error: unknown): void { errors.push(error); }
    virtualConsole.on('jsdomError', captureError);
    virtualConsole.on('error', captureError);
    const selectedAttributes = options.initiallySelected
        ? `data-selected-ids='["3"]' data-selected-labels='["Original owner"]'` : '';
    const dom = new JSDOM(`<!doctype html><body><button id="outside">Outside</button>
        <form><div id="container" bloomerp-component="object-crud-view-container">
            <div id="panel" data-dropdown-panel data-layout-row data-row-columns="1"><div data-layout-grid>
                <div id="cell" bloomerp-component="detail-view-value" data-field-name="owner" data-application-field-id="owner">
                    <div data-layout-item-body>
                        <div id="widget" bloomerp-component="foreign-field-widget" data-content-type-id="1" data-field-name="owner" data-is-m2m="${Boolean(options.isM2M)}" data-disabled="${Boolean(options.disabled)}" ${selectedAttributes}>
                            <input type="text"><div class="foreign-field-dropdown hidden"><ul class="foreign-field-results"></ul></div><span id="sibling"></span><div class="foreign-field-selected"></div>
                        </div>
                    </div>
                </div>
            </div></div>
            <div id="object-crud-container-buttons" class="hidden">
                <button type="submit" id="save">Save</button>
                <button type="button" id="object-crud-container-back-button">Undo</button>
                <button type="button" id="object-crud-container-reset-button">Reset</button>
            </div>
        </div></form></body>`, {
        url: 'https://fixture.test', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole,
    });
    const w = dom.window as FixtureWindow;
    const panel = w.document.getElementById('panel')!;
    if (popover) {
        panel.setAttribute('popover', 'manual');
        const matches = panel.matches.bind(panel);
        /** Model an open native popover; jsdom has no top-layer renderer. */
        panel.matches = (selector: string): boolean => selector === ':popover-open' || matches(selector);
    }
    /** Return related objects locally while preserving production search/rendering code. */
    async function fetchObjects(): Promise<unknown> { return { ok: true, json: readObjects }; }
    /** Supply deterministic options for repeated selections and history restoration. */
    async function readObjects(): Promise<unknown> {
        return { objects: [{ id: 7, string_representation: 'Alice' }, { id: 8, string_representation: 'Bob' }] };
    }
    Object.assign(w, { fetch: fetchObjects, structuredClone });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type for jsdom. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, res?: XPathResult | null): XPathResult { return evaluate.call(this, context, type ?? 0, res ?? null); };
    w.eval(scriptCode);
    const widget = w.document.getElementById('widget')!;
    const input = widget.querySelector('input')!;
    const menu = widget.querySelector('.foreign-field-dropdown') as HTMLElement;
    if (options.restoreAtEnd) widget.appendChild(menu);
    /** Represent a half-scale transformed parent with borders and internal scroll. */
    panel.getBoundingClientRect = (): DOMRect => ({left: 100, top: 50, width: 200, height: 150} as DOMRect);
    Object.defineProperties(panel, {offsetWidth:{value:400}, offsetHeight:{value:300}, clientLeft:{value:2}, clientTop:{value:2}, scrollLeft:{value:10}, scrollTop:{value:20}});
    input.getBoundingClientRect = (): DOMRect => ({left: 120, bottom: 90, width: 80} as DOMRect);
    const api = w.ForeignFieldFixture;
    api.initComponents(widget);
    api.initComponents(w.document.getElementById('cell')!);
    api.initComponents(w.document.getElementById('container')!);
    const component = api.getComponent(widget);
    const cell = api.getComponent(w.document.getElementById('cell')!);
    const container = api.getComponent(w.document.getElementById('container')!);
    assert(component instanceof api.ForeignFieldWidget);
    assert(cell instanceof api.DetailViewCell);
    assert(container instanceof api.ObjectCRUDViewContainer);
    input.focus();
    await flushResults(w);
    assert.deepEqual(errors, [], 'production components initialize without errors');
    return {dom,w,panel,widget,input,menu,component,cell,container,errors,
        form: w.document.querySelector('form')!, buttons: w.document.getElementById('object-crud-container-buttons')!};
}

/** Release the real container, cell, and widget listeners and pending DOM tasks. */
function dispose(f: Fixture): void {
    f.container.destroy();
    f.cell.destroy();
    f.component.destroy();
    f.dom.window.close();
}

/** Keep transformed top-layer result placement covered alongside the form pipeline. */
test('foreign-key results remain inside the top-layer filter and use host coordinates', async (): Promise<void> => {
    const f = await fixture();
    try {
        assert.equal(f.menu.parentElement, f.panel);
        assert.equal(f.menu.style.left, '48px');
        assert.equal(f.menu.style.top, '106px');
        assert.equal(f.menu.style.width, '160px');
        assert.equal(f.menu.classList.contains('hidden'), false);
    } finally { dispose(f); }
});

/** Keep calendar alignment open when its body-portalled picker selects and removes a result. */
test('calendar alignment stays open for its FK selection and closes for outside clicks', async (): Promise<void> => {
    const f = await fixture(false);
    const details = f.w.document.createElement('details');
    details.open = true;
    f.widget.before(details);
    details.append(f.widget);
    const overlay = new f.w.ForeignFieldFixture.InboxCalendarOverlay(details);
    overlay.initialize();
    try {
        assert.equal(f.menu.parentElement, f.w.document.body);
        f.menu.querySelector('li[data-id="7"]')!.dispatchEvent(new f.w.MouseEvent('click', { bubbles: true, detail: 1 }));
        assert.equal(f.component.getValue(), '7');
        assert.equal(details.open, true);
        f.w.document.getElementById('outside')!.click();
        assert.equal(details.open, false);
    } finally {
        overlay.destroy();
        dispose(f);
    }
});

/** Preserve ordinary body portal coordinates for forms outside a popover. */
test('ordinary widgets preserve the body portal and viewport-plus-scroll coordinates', async (): Promise<void> => {
    const f = await fixture(false);
    try {
        assert.equal(f.menu.parentElement, f.w.document.body);
        assert.equal(f.menu.style.left, '120px');
        assert.equal(f.menu.style.top, '94px');
        assert.equal(f.menu.style.zIndex, '9999');
    } finally { dispose(f); }
});

/** Keep selection bubbling and sibling restoration independent of dirty tracking. */
test('selection bubbles inside the parent filter and restores the original DOM order', async (): Promise<void> => {
    const f = await fixture();
    try {
        let clicks = 0;
        f.panel.addEventListener('click', (): void => { clicks += 1; });
        f.menu.querySelector<HTMLElement>('li')!.click();
        assert.equal(clicks, 1);
        assert.equal(f.component.getValue(), '7');
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.nextElementSibling!.id, 'sibling');
    } finally { dispose(f); }
});

/** Exercise repeated dismissal through keyboard and outside-pointer interactions. */
test('Escape closes only results and outside clicks restore the portal', async (): Promise<void> => {
    const f = await fixture();
    try {
        const key = new f.w.KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true});
        f.input.dispatchEvent(key);
        assert.equal(key.defaultPrevented, true);
        assert.equal(f.menu.parentElement, f.widget);
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        assert.equal(f.menu.parentElement, f.panel);
        f.w.document.getElementById('outside')!.click();
        assert.equal(f.menu.parentElement, f.widget);
    } finally { dispose(f); }
});

/** Clean up nested results before their top-layer parent is dismissed. */
test('closing the parent popover and destroying the widget leave no detached results', async (): Promise<void> => {
    const f = await fixture();
    try {
        const event = new f.w.Event('beforetoggle');
        Object.defineProperty(event, 'newState', {value:'closed'});
        f.panel.dispatchEvent(event);
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.classList.contains('hidden'), true);
        assert.equal(f.menu.style.left, '');
    } finally { dispose(f); }
});


/** Reposition an existing portal and release listeners when its widget is destroyed. */
test('repeated results retain restoration state and respond to resize and transition completion', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        f.input.getBoundingClientRect = (): DOMRect => ({left:140, bottom:110, width:100} as DOMRect);
        f.w.dispatchEvent(new f.w.Event('resize'));
        assert.equal(f.menu.style.left, '88px');
        assert.equal(f.menu.style.top, '146px');
        assert.equal(f.menu.style.width, '200px');
        f.input.getBoundingClientRect = (): DOMRect => ({left:150, bottom:120, width:100} as DOMRect);
        f.panel.dispatchEvent(new f.w.Event('transitionend'));
        assert.equal(f.menu.style.left, '108px');
        f.component.destroy();
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.nextElementSibling?.id, 'sibling');
        f.w.dispatchEvent(new f.w.Event('resize'));
        assert.equal(f.menu.style.left, '');
    } finally { dispose(f); }
});

/** Preserve focus-return and focus-leave behavior for keyboard-accessible results. */
test('focused result Escape returns focus and focus leaving results closes the menu', async (): Promise<void> => {
    const f = await fixture();
    try {
        const option = f.menu.querySelector<HTMLElement>('li')!;
        option.focus();
        const key = new f.w.KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true});
        option.dispatchEvent(key);
        assert.equal(key.defaultPrevented, true);
        assert.equal(f.w.document.activeElement, f.input);
        assert.equal(f.menu.parentElement, f.widget);
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        f.menu.querySelector<HTMLElement>('li')!.focus();
        f.w.document.getElementById('outside')!.focus();
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.classList.contains('hidden'), true);
    } finally { dispose(f); }
});

interface RestoreProbe {
    moves: Array<'insertBefore' | 'appendChild'>;
    focusouts: number;
    restore(): void;
}

/**
 * Model synchronous browser focus loss inside a native DOM reparent operation.
 * jsdom does not emit these events itself. If a focus handler moves the node
 * again, reject the now-stale outer move, as browser pre-insertion can do.
 * The production focusout handlers and complete selection/change path stay real.
 */
function interruptRestorationWithFocusout(f: Fixture): RestoreProbe {
    const insertBefore = f.widget.insertBefore;
    const appendChild = f.widget.appendChild;
    let dispatchingFocusout = false;
    const probe: RestoreProbe = {
        moves: [],
        focusouts: 0,
        /** Remove only this fixture's DOM-operation instrumentation. */
        restore(): void {
            f.widget.insertBefore = insertBefore;
            f.widget.appendChild = appendChild;
        },
    };
    /** Dispatch the focus events while the outer native insertion is still pending. */
    function beforeMove(node: Node, method: 'insertBefore' | 'appendChild'): void {
        if (node !== f.menu) return;
        probe.moves.push(method);
        const focused = f.w.document.activeElement;
        if (dispatchingFocusout || !focused || !f.menu.contains(focused)) return;
        const sourceParent = node.parentNode;
        dispatchingFocusout = true;
        probe.focusouts += 1;
        try {
            focused.dispatchEvent(new f.w.FocusEvent('blur', { relatedTarget: null }));
            focused.dispatchEvent(new f.w.FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
        } finally {
            dispatchingFocusout = false;
        }
        if (node.parentNode !== sourceParent) {
            throw new f.w.DOMException('The node was moved by a synchronous focusout handler', 'NotFoundError');
        }
    }
    /** Intercept restoration before an existing sibling, retaining native DOM behavior. */
    f.widget.insertBefore = function<T extends Node>(node: T, sibling: Node | null): T {
        beforeMove(node, 'insertBefore');
        return insertBefore.call(this, node, sibling) as T;
    };
    /** Intercept restoration with no surviving sibling, retaining native DOM behavior. */
    f.widget.appendChild = function<T extends Node>(node: T): T {
        beforeMove(node, 'appendChild');
        return appendChild.call(this, node) as T;
    };
    return probe;
}

/** Open production search again after a selection or history action. */
async function reopen(f: Fixture): Promise<void> {
    f.input.dispatchEvent(new f.w.FocusEvent('focus'));
    await flushResults(f.w);
    assert.equal(f.menu.classList.contains('hidden'), false);
    assert.equal(f.menu.parentElement, f.panel.hasAttribute('popover') ? f.panel : f.w.document.body);
}

/** Select a focused result through the actual bubbling pointer event handler. */
function selectResult(f: Fixture, id: string): void {
    const result = f.menu.querySelector<HTMLElement>(`li[data-id="${id}"]`);
    assert(result, `search returned option ${id}`);
    result.focus();
    assert.equal(f.w.document.activeElement, result);
    result.dispatchEvent(new f.w.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
}

/** Assert submitted value, cell value, rendered label, and the real Save controls agree. */
function assertFormState(f: Fixture, value: string, label: string, dirty: boolean): void {
    assert.deepEqual(f.errors, [], 'selection and its change events must not throw');
    assert.equal(f.component.getValue(), value);
    assert.equal(f.cell.value, value, 'the real cell receives the widget change');
    assert.equal(f.input.value, '', 'labels are tokens rather than editable query text');
    assert.equal(f.widget.querySelector('.foreign-field-badge span, .foreign-field-badge a')?.textContent || '', label);
    assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), value ? [value] : []);
    assert.equal(f.buttons.classList.contains('hidden'), !dirty, 'form history controls reflect the change');
    assert.equal(f.w.document.getElementById('save')!.closest('.hidden') === null, dirty, 'Save is visible exactly while form history is dirty');
}

for (const popover of [false, true]) {
    for (const restoreAtEnd of [false, true]) {
        const host = popover ? 'popover' : 'body';
        const method = restoreAtEnd ? 'appendChild' : 'insertBefore';
        /** Verify reentrant focus loss cannot interrupt a real field change or form history. */
        test(`${host} ${method}: synchronous focusout preserves selection, Save, Undo, and reopening`, async (): Promise<void> => {
            const f = await fixture(popover, { restoreAtEnd });
            const probe = interruptRestorationWithFocusout(f);
            const widgetValues: string[] = [];
            const cellChanges: DetailViewCellChangeDetail[] = [];
            /** Record the genuine widget notification, without synthesizing change events. */
            function recordWidgetChange(event: Event): void {
                widgetValues.push((event as CustomEvent<{ value: string }>).detail.value);
            }
            /** Record the genuine cell transition consumed by the form controller. */
            function recordCellChange(event: Event): void {
                cellChanges.push((event as CustomEvent<DetailViewCellChangeDetail>).detail);
            }
            f.form.addEventListener('bloomerp:widget-change', recordWidgetChange);
            f.form.addEventListener('bloomerp:detail-view-cell-change', recordCellChange);
            try {
                assertFormState(f, '', '', false);
                selectResult(f, '7');
                assertFormState(f, '7', 'Alice', true);
                assert.deepEqual(probe.moves, [method], 'restoration is claimed before synchronous reentry');
                assert.equal(probe.focusouts, 1, 'the regression actually exercised synchronous focusout');
                assert.deepEqual(widgetValues, ['7']);
                assert.equal(cellChanges.length, 1);
                assert.equal(cellChanges[0].cell, f.cell);
                assert.equal(cellChanges[0].previousValue, '');
                assert.equal(cellChanges[0].value, '7');
                assert.equal(cellChanges[0].previousSnapshot.kind, 'widget');
                assert.equal(cellChanges[0].snapshot.kind, 'widget');
                assert.equal(f.menu.parentElement, f.widget);
                assert.equal(f.menu.classList.contains('hidden'), true);
                assert.equal(f.menu.style.position, '');
                assert.equal(f.menu.style.left, '');
                if (!restoreAtEnd) assert.equal(f.menu.nextElementSibling?.id, 'sibling');

                f.w.document.getElementById('object-crud-container-back-button')!.click();
                assertFormState(f, '', '', false);
                assert.equal(cellChanges.length, 1, 'Undo restores silently rather than recording another edit');
                await reopen(f);
                selectResult(f, '8');
                assertFormState(f, '8', 'Bob', true);
                assert.deepEqual(widgetValues, ['7', '8']);
                assert.equal(cellChanges.length, 2);
                assert.deepEqual(probe.moves, [method, method]);
                assert.equal(probe.focusouts, 2);

                f.w.document.getElementById('object-crud-container-reset-button')!.click();
                assertFormState(f, '', '', false);
                assert.equal(cellChanges.length, 2);
                assert.equal(f.widget.querySelectorAll('.foreign-field-dropdown').length, 1);
                assert.equal(f.w.document.querySelectorAll('.foreign-field-dropdown').length, 1);
            } finally {
                probe.restore();
                dispose(f);
            }
        });
    }
}

/** Verify clearing a relation keeps its empty submission and supports real Undo/reset snapshots. */
test('cleared selection submits an empty value, Undo restores it, and Reset returns to the original owner', async (): Promise<void> => {
    const f = await fixture(false, { initiallySelected: true });
    const probe = interruptRestorationWithFocusout(f);
    try {
        assertFormState(f, '3', 'Original owner', false);
        selectResult(f, '7');
        assertFormState(f, '7', 'Alice', true);
        f.widget.querySelector<HTMLButtonElement>('.foreign-field-selected button')!.click();
        assert.equal(f.component.getValue(), '');
        assert.equal(f.cell.value, '');
        assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), ['']);
        assert.equal(f.widget.querySelectorAll('[data-empty-value="true"]').length, 1);
        assert.equal(f.buttons.classList.contains('hidden'), false);

        f.w.document.getElementById('object-crud-container-back-button')!.click();
        assertFormState(f, '7', 'Alice', true);
        assert.equal(f.widget.querySelectorAll('[data-empty-value="true"]').length, 0);
        await reopen(f);
        selectResult(f, '8');
        assertFormState(f, '8', 'Bob', true);
        f.w.document.getElementById('object-crud-container-reset-button')!.click();
        assertFormState(f, '3', 'Original owner', false);
        assert.equal(f.widget.querySelectorAll('[data-empty-value="true"]').length, 0);
        assert.equal(probe.focusouts, 2);
        assert.deepEqual(probe.moves, ['insertBefore', 'insertBefore']);
    } finally {
        probe.restore();
        dispose(f);
    }
});

/** Keep the input's ArrowDown/Enter path connected to the genuine Save and Undo controls. */
test('keyboard selection updates Save and Ctrl+Z restores the previous foreign key', async (): Promise<void> => {
    const f = await fixture(false);
    try {
        assert.equal(f.w.document.activeElement, f.input);
        f.input.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
        const enter = new f.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        f.input.dispatchEvent(enter);
        assert.equal(enter.defaultPrevented, true);
        assertFormState(f, '7', 'Alice', true);
        assert.equal(f.menu.parentElement, f.widget);
        const undo = new f.w.KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
        f.input.dispatchEvent(undo);
        assert.equal(undo.defaultPrevented, true);
        assertFormState(f, '', '', false);
    } finally { dispose(f); }
});

/** Model fragment cleanup/replacement with real registration, fresh instances, and stale HTML markers. */
test('replacing and reinitializing a form fragment preserves selection events and leaves no old portal', async (): Promise<void> => {
    const f = await fixture(false);
    let probe: RestoreProbe | null = null;
    try {
        f.input.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        const freshForm = f.form.cloneNode(true) as HTMLFormElement;
        const previousWidget = f.widget;
        const previousMenu = f.menu;
        const previousComponent = f.component;
        const previousContainer = f.container;
        await reopen(f);
        selectResult(f, '7');
        assertFormState(f, '7', 'Alice', true);
        await reopen(f);
        assert.equal(previousMenu.parentElement, f.w.document.body);

        f.container.destroy();
        f.cell.destroy();
        f.component.destroy();
        assert.equal(previousMenu.parentElement, previousWidget, 'fragment cleanup recalls its open portal');
        f.form.replaceWith(freshForm);
        const api = f.w.ForeignFieldFixture;
        api.initComponents(freshForm);
        f.form = freshForm;
        f.panel = freshForm.querySelector<HTMLElement>('#panel')!;
        f.widget = freshForm.querySelector<HTMLElement>('#widget')!;
        f.input = f.widget.querySelector<HTMLInputElement>('input[type="text"]')!;
        f.menu = f.w.document.querySelector<HTMLElement>('.foreign-field-dropdown')!;
        f.buttons = freshForm.querySelector<HTMLElement>('#object-crud-container-buttons')!;
        const component = api.getComponent(f.widget);
        const cell = api.getComponent(freshForm.querySelector<HTMLElement>('#cell')!);
        const container = api.getComponent(freshForm.querySelector<HTMLElement>('#container')!);
        assert(component instanceof api.ForeignFieldWidget);
        assert(cell instanceof api.DetailViewCell);
        assert(container instanceof api.ObjectCRUDViewContainer);
        f.component = component;
        f.cell = cell;
        f.container = container;
        assert.notEqual(component, previousComponent);
        assert.notEqual(container, previousContainer);
        assert.equal(previousMenu.isConnected, false);
        await flushResults(f.w);
        assertFormState(f, '', '', false);
        assert.equal(f.w.document.querySelectorAll('.foreign-field-dropdown').length, 1);
        assert.equal(f.menu.parentElement, f.w.document.body);

        probe = interruptRestorationWithFocusout(f);
        selectResult(f, '8');
        assertFormState(f, '8', 'Bob', true);
        assert.equal(probe.focusouts, 1);
        assert.deepEqual(probe.moves, ['insertBefore']);
        f.w.document.getElementById('object-crud-container-back-button')!.click();
        assertFormState(f, '', '', false);
        assert.equal(f.menu.parentElement, f.widget);
    } finally {
        probe?.restore();
        dispose(f);
    }
});

/** Type a query and commit the first search result without moving the cursor. */
async function enterResult(f: Fixture, query: string): Promise<void> {
    f.input.value = query;
    f.input.dispatchEvent(new f.w.Event('input', { bubbles: true }));
    /** Wait for the production search debounce and its local response. */
    await new Promise<void>(function afterSearch(resolve: () => void): void { f.w.setTimeout(resolve, 275); });
    const enter = new f.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    f.input.dispatchEvent(enter);
    assert.equal(enter.defaultPrevented, true);
    assert.equal(f.w.document.activeElement, f.input);
    assert.equal(f.input.value, '');
}

/** Exercise both cardinalities through real input events and the form history pipeline. */
for (const isM2M of [false, true]) {
    test(`Enter ${isM2M ? 'appends' : 'replaces'} selected tokens and deletion retains the cursor`, async (): Promise<void> => {
        const f = await fixture(false, { initiallySelected: true, isM2M });
        try {
            await enterResult(f, 'Alice');
            const expected = isM2M ? ['3', '7'] : ['7'];
            assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), expected);
            assert.equal(f.widget.querySelectorAll('.foreign-field-badge').length, expected.length);
            if (isM2M) {
                await enterResult(f, 'Alice');
                assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), expected, 'duplicate entries are ignored');
            }
            f.input.value = 'uncommitted query';
            const editing = new f.w.KeyboardEvent('keydown', { key: 'Backspace', bubbles: true, cancelable: true });
            f.input.dispatchEvent(editing);
            assert.equal(editing.defaultPrevented, false, 'query text can be edited without removing tokens');
            assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), expected);
            f.input.value = '';
            const backspace = new f.w.KeyboardEvent('keydown', { key: 'Backspace', bubbles: true, cancelable: true });
            f.input.dispatchEvent(backspace);
            assert.equal(backspace.defaultPrevented, true);
            assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), isM2M ? ['3'] : ['']);
            assert.equal(f.w.document.activeElement, f.input);
            if (isM2M) {
                f.input.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true }));
                assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), ['']);
                assert.equal(f.w.document.activeElement, f.input);
            }
            assert.deepEqual(f.errors, []);
        } finally { dispose(f); }
    });
}

/** Preserve the cursor for the initial selection, pointer changes, and remove buttons. */
test('empty and pointer selections keep the input focused and deletions work with a closed dropdown', async (): Promise<void> => {
    const f = await fixture(false);
    try {
        await enterResult(f, 'Alice');
        assertFormState(f, '7', 'Alice', true);
        await reopen(f);
        selectResult(f, '8');
        assert.equal(f.w.document.activeElement, f.input);
        assertFormState(f, '8', 'Bob', true);
        f.widget.querySelector<HTMLButtonElement>('.foreign-field-selected button')!.click();
        assert.equal(f.w.document.activeElement, f.input);
        assert.equal(f.component.getValue(), '');
        f.component.setSerializableState({ value: '7', inputValue: '', selections: [{ id: '7', label: 'Alice', url: '' }] } as ReturnType<ForeignFieldWidget['getSerializableState']>);
        f.input.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true }));
        assert.equal(f.component.getValue(), '');
        assert.deepEqual(Array.from(new f.w.FormData(f.form).getAll('owner')), ['']);
        assert.equal(f.w.document.activeElement, f.input);
    } finally { dispose(f); }
});

/** Protect selected values while the user composes text or the widget is disabled. */
for (const disabled of [false, true]) {
    test(`${disabled ? 'disabled' : 'composing'} input does not remove selected tokens`, async (): Promise<void> => {
        const f = await fixture(false, { initiallySelected: true, disabled });
        try {
            const event = new f.w.KeyboardEvent('keydown', { key: 'Backspace', isComposing: !disabled, bubbles: true, cancelable: true });
            f.input.dispatchEvent(event);
            assert.equal(f.component.getValue(), '3');
            assert.equal(event.defaultPrevented, false);
        } finally { dispose(f); }
    });
}

/** Build a relation filter without sharing mutable condition objects. */
function choiceFilter(value: string): Filter[] {
    return [{ connector: 'AND', conditions: [{ field_path: 'id', lookup_id: 'equals', value }] }];
}

/** Keep static limits, replace dynamic limits, and suppress obsolete asynchronous results. */
test('behavior choice changes abort old searches and retain static limits and selected values', async (): Promise<void> => {
    const f = await fixture(false, { initiallySelected: true });
    const requests: Array<{ url: string; signal: AbortSignal; resolve: (response: unknown) => void }> = [];
    /** Hold transport responses so an obsolete request can complete after a new filter. */
    function holdSearch(url: string, options: RequestInit): Promise<unknown> {
        return new Promise<unknown>(function hold(resolve: (response: unknown) => void): void {
            requests.push({ url, signal: options.signal as AbortSignal, resolve });
        });
    }
    try {
        f.widget.dataset.choicesFilter = JSON.stringify(choiceFilter('static'));
        Object.assign(f.w, { fetch: holdSearch });
        f.component.setBehaviorChoicesFilter(choiceFilter('7'));
        f.component.setBehaviorChoicesFilter(choiceFilter('8'));
        assert.equal(requests.length, 2);
        assert.equal(requests[0].signal.aborted, true);
        assert.deepEqual(JSON.parse(new URL(requests[1].url, 'https://fixture.test').searchParams.get('filter')!), [...choiceFilter('static'), ...choiceFilter('8')]);
        /** Return an obsolete result even though the simulated server ignored cancellation. */
        function obsoleteObjects(): { objects: Array<{ id: number; string_representation: string }> } {
            return { objects: [{ id: 7, string_representation: 'Obsolete' }] };
        }
        requests[0].resolve({ ok: true, json: obsoleteObjects });
        await flushResults(f.w);
        assert.equal(f.menu.querySelector('li[data-id="7"]'), null);
        assert.equal(f.component.getValue(), '3');
        f.component.setBehaviorChoicesFilter([]);
        assert.equal(JSON.stringify(f.component.getChoicesFilter()), JSON.stringify(choiceFilter('static')));
        assert.equal(requests[1].signal.aborted, true);
        assert.deepEqual(f.errors, []);
    } finally { dispose(f); }
});

/** Exercise server-response adaptation and Reset with the real behavior runtime and widget. */
test('initial and change behavior responses filter choices and Reset restores the initial restriction', async (): Promise<void> => {
    const f = await fixture(false);
    const root = f.w.document.getElementById('container')!;
    const runtime = new f.w.ForeignFieldFixture.FormBehaviorRuntime(root);
    let evaluations = 0;
    /** Serve behavior responses while leaving object transport deterministic. */
    async function transport(url: string, options?: RequestInit): Promise<unknown> {
        if (url === '/behaviors') {
            const payload = JSON.parse(options!.body as string);
            evaluations += 1;
            const filters = choiceFilter(payload.event === 'initial' ? '7' : '8');
            /** Supply the exact backend state-update response contract. */
            function response(): unknown {
                return { revision: payload.revision, values: [], messages: [], states: [{ field: 'owner', visible: null, disabled: null, choices_filter: filters }] };
            }
            return { ok: true, json: response };
        }
        /** Return a selectable object for the user's field-change event. */
        function objects(): unknown { return { objects: [{ id: 7, string_representation: 'Alice' }] }; }
        return { ok: true, json: objects };
    }
    try {
        root.dataset.behaviorUrl = '/behaviors';
        root.dataset.behaviorOwnerId = 'layout';
        root.dataset.behaviorOwnerKey = 'preference_id';
        f.w.document.getElementById('cell')!.dataset.layoutItemConfig = JSON.stringify({ behaviors: { version: 1, behaviors: [{ events: ['initial', 'change'] }] } });
        Object.assign(f.w, { fetch: transport });
        runtime.initialize();
        await flushResults(f.w);
        assert.equal(evaluations, 1);
        assert.deepEqual(f.component.getBehaviorChoicesFilter(), choiceFilter('7'));
        selectResult(f, '7');
        await flushResults(f.w);
        assert.equal(evaluations, 2);
        assert.deepEqual(f.component.getBehaviorChoicesFilter(), choiceFilter('8'));
        runtime.reset();
        assert.deepEqual(f.component.getBehaviorChoicesFilter(), choiceFilter('7'));
        assert.equal(f.component.getValue(), '7', 'state updates do not silently change the chosen relation');
        assert.deepEqual(f.errors, []);
    } finally { runtime.destroy(); dispose(f); }
});
