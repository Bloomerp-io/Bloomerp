/** DOM regressions for calendar creation using the real calendar, modal, and dataview container. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type renderDataview from '../../utils/dataview.ts';
import type { Calendar, CalendarCell } from './Calendar.ts';
import type { DataViewContainer } from './DataViewContainer.ts';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/calendar-regression-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent', resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'calendar-regression-entry',
        /** Resolve the in-memory production-component test entry. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Share the real component registry and HTMX request boundary. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import { Calendar, CalendarCell } from '${root}/ts/components/data_view_components/Calendar';
                import { DataViewContainer } from '${root}/ts/components/data_view_components/DataViewContainer';
                import { DataviewActionList } from '${root}/ts/components/data_view_components/DataviewActionList';
                import { DataviewCreate } from '${root}/ts/components/data_view_components/DataviewCreate';
                import { Modal } from '${root}/ts/components/Modal';
                import { Drawer } from '${root}/ts/components/Drawer';
                import InboxCalendarOverlay from '${root}/ts/components/inbox/InboxCalendarOverlay';
                import renderDataview from '${root}/ts/utils/dataview';
                import { registerComponent, initComponents, getComponent, setupComponentAutoInit } from '${root}/ts/components/BaseComponent';
                import htmx from 'htmx.org';
                registerComponent('calendar', Calendar);
                registerComponent('inbox-calendar-overlay', InboxCalendarOverlay);
                registerComponent('calendar-cell', CalendarCell);
                registerComponent('dataview-container', DataViewContainer);
                registerComponent('dataview-action-list', DataviewActionList);
                registerComponent('dataview-create', DataviewCreate);
                registerComponent('modal', Modal);
                registerComponent('drawer', Drawer);
                export { initComponents, getComponent, htmx, renderDataview, setupComponentAutoInit };
            `;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'CalendarFixture' } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Find the executable test bundle. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    CalendarFixture: {
        initComponents(element: HTMLElement): void;
        getComponent(element: HTMLElement): Calendar | CalendarCell | DataViewContainer | null;
        renderDataview: typeof renderDataview;
        setupComponentAutoInit(): void;
        htmx: {
            ajax(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement>;
            swap(target: HTMLElement, html: string, options: Record<string, unknown>): void;
        };
    };
}
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    cell: HTMLElement;
    requests: URL[];
}

/** Initialize an empty cell and an event with optional create availability and date-only fields. */
function fixture(mode: string, create: boolean = true, datePair: boolean = true, endField: boolean = true, query: Record<string, string> = {}): Fixture {
    const month = mode === 'month';
    const dom = new JSDOM(`<!doctype html>
        <section data-calendar-dataview-host><div id="data-view-1" bloomerp-component="dataview-container" data-content-type-id="1" data-dataview-selection-enabled
            data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?inboxes=1">
            ${create ? '<div bloomerp-component="dataview-create" data-create-url="/components/create-object/1/?inboxes=1" hidden></div>' : ''}
            <details bloomerp-component="inbox-calendar-overlay" data-preferred-group="1" data-save-url="/components/communication/calendar/1/align/" open>
                <input type="checkbox" data-overlay-inbox value="1" checked>
                <input type="checkbox" data-overlay-inbox value="2" checked>
                <span data-overlay-error hidden>Select at least one calendar.</span>
                <button type="button" data-apply-overlay>Apply</button>
            </details>
            <div id="data-view-data-section">
                <div bloomerp-component="calendar" data-content-type-id="1" data-calendar-view-mode="${mode}"
                    data-calendar-start-field-type="DateTimeField" data-calendar-create-start-field="starts_at"
                    data-calendar-create-end-field="${endField ? 'ends_at' : ''}"
                    data-calendar-create-start-date-field="${datePair ? 'starts_on' : ''}"
                    data-calendar-create-end-date-field="${datePair ? 'ends_on' : ''}">
                    <div data-calendar-grid>
                    <section data-calendar-unit-section data-calendar-unit="2026-10-15${month ? '' : 'T09'}"
                        data-calendar-create-start="2026-10-15T${month ? '00' : '09'}:00:00+02:00"
                        data-calendar-create-end="2026-10-${month ? '16T00' : '15T10'}:00:00+02:00">
                        <button data-calendar-unit-cell bloomerp-component="calendar-cell">Empty cell</button>
                        <div role="button" tabindex="0" data-calendar-event bloomerp-component="calendar-cell" data-object-id="event"
                            data-detail-url="/events/event/update/" data-object-string="Existing event">Existing event</div>
                    </section>
                    </div>
                </div>
            </div>
        </div>
        </section><div id="create-object-modal" bloomerp-component="modal"></div>`,
        { runScripts: 'outside-only', pretendToBeVisual: true, url: 'https://app.example/inbox/1/calendar/' });
    const w = dom.window as FixtureWindow;
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Match browser XPath defaults when asynchronous SDK requests let HTMX initialize. */
    w.XPathExpression.prototype.evaluate = function evaluateWithDefault(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, result);
    };
    w.eval(scriptCode);
    const requests: URL[] = [];
    /** Capture real modal/detail requests without making network calls. */
    w.CalendarFixture.htmx.ajax = function capture(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {

        requests.push(new URL(url, w.location.origin));
        return Promise.resolve(w.document.createElement('div'));
    };
    const container = w.document.querySelector<HTMLElement>('[bloomerp-component="dataview-container"]')!;
    const url = new URL(container.dataset.url!, w.location.origin);
    for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
    container.dataset.url = url.toString();
    w.CalendarFixture.initComponents(w.document.body);
    return { dom, w, cell: w.document.querySelector<HTMLElement>('[data-calendar-unit-section]')!, requests };
}

/** Dispatch a bubbling double-click as the browser would on a cell or event. */
function doubleClick(f: Fixture, element: HTMLElement): void {
    element.dispatchEvent(new f.w.MouseEvent('dblclick', { bubbles: true, cancelable: true }));
}

/** Supply viewport and application content bounds for calendar sizing tests. */
function calendarLayoutFixture(mode: string): Fixture {
    const f = fixture(mode);
    const calendar = f.w.document.querySelector<HTMLElement>('[bloomerp-component="calendar"]')!;
    const component = f.w.CalendarFixture.getComponent(calendar) as Calendar;
    component.destroy();
    calendar.dataset.calendarTimezone = 'Pacific/Kiritimati';
    Object.defineProperty(f.w, 'innerHeight', { value: 988, configurable: true });
    f.w.document.body.style.overflowY = 'auto';
    Object.defineProperty(f.w.document.body, 'clientHeight', { value: 964, configurable: true });
    /** Represent the bounded application content area. */
    f.w.document.body.getBoundingClientRect = function contentBounds(): DOMRect {
        return new f.w.DOMRect(0, 12, 1000, 964);
    };
    calendar.parentElement!.style.paddingBottom = '16px';
    /** Position the calendar below its navigation and toolbar. */
    calendar.getBoundingClientRect = function calendarBounds(): DOMRect {
        return new f.w.DOMRect(0, 180 - f.w.document.body.scrollTop, 1000, Number.parseFloat(calendar.style.height) || 0);
    };
    return f;
}

/** Keep the month grid below its toolbar and within the visible content area after resizing. */
function monthFitsContentArea(): void {
    const f = calendarLayoutFixture('month');
    try {
        const calendar = f.w.document.querySelector<HTMLElement>('[bloomerp-component="calendar"]')!;
        const component = f.w.CalendarFixture.getComponent(calendar) as Calendar;
        component.initialize();
        assert.equal(calendar.style.height, '780px');

        f.w.document.body.scrollTop = 100;
        Object.defineProperty(f.w.document.body, 'clientHeight', { value: 764 });
        f.w.dispatchEvent(new f.w.Event('resize'));
        assert.equal(calendar.style.height, '580px');
    } finally {
        f.dom.window.close();
    }
}
test('month calendar fits the visible content area on resize', monthFitsContentArea);

/** Verify hour defaults, inherited filters, modal opening, and the shared create correlation ID. */
function hourlyCreation(): void {
    for (const mode of ['day', 'week']) {
        const f = fixture(mode);
        try {
            doubleClick(f, f.cell);
            assert.equal(f.requests.length, 1);
            const query = f.requests[0].searchParams;
            assert.equal(query.get('starts_at'), '2026-10-15T09:00:00+02:00');
            assert.equal(query.get('ends_at'), '2026-10-15T10:00:00+02:00');
            assert.equal(query.get('inboxes'), '1');
            assert.equal(query.has('data_view_create_id'), false);
            const modal = f.w.document.querySelector<HTMLElement>('[data-modal-instance-of="create-object-modal"]')!;
            assert(modal.classList.contains('flex'));
            assert.match(modal.getAttribute('hx-headers') ?? '', /"X-Bloomerp-Modal-Create":"true"/);
        } finally { f.dom.window.close(); }
    }
}
test('day and week double-clicks open the shared modal with one-hour defaults', hourlyCreation);

/** Cycle overlapping events, toggle record selection with Space, and open the active event with Enter. */
test('Space selects calendar records and Enter opens the active record', (): void => {
    for (const mode of ['day', 'week']) {
        const f = fixture(mode);
        try {
            /** Provide browser scrolling for selection changes in the DOM fixture. */
            f.w.HTMLElement.prototype.scrollIntoView = function scrollCell(): void {};
            const calendar = f.w.document.querySelector<HTMLElement>('[bloomerp-component="calendar"]')!;
            const first = calendar.querySelector<HTMLElement>('[data-calendar-event]')!;
            first.setAttribute('data-dataview-record', '');
            first.insertAdjacentHTML('afterbegin', '<input type="checkbox" data-bulk-checkbox data-object-id="event">');
            const unit = f.cell.dataset.calendarUnit!;
            first.dataset.calendarUnit = unit;
            f.cell.querySelector<HTMLElement>('[data-calendar-unit-cell]')!.dataset.calendarUnit = unit;
            first.insertAdjacentHTML('afterend', `<div role="button" tabindex="0" data-dataview-record data-calendar-event data-calendar-unit="${unit}"
                data-object-id="second" data-detail-url="/events/second/update/" bloomerp-component="calendar-cell">
                <input type="checkbox" data-bulk-checkbox data-object-id="second">Second event</div>`);
            const second = first.nextElementSibling as HTMLElement;
            f.w.CalendarFixture.initComponents(second);
            const component = f.w.CalendarFixture.getComponent(calendar) as Calendar;
            second.focus();
            assert.equal(component.currentCell?.element, second);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
            assert.equal(component.currentCell?.element, first);
            assert.equal(calendar.querySelectorAll('[data-calendar-event].cell-selected').length, 1);
            const space = new f.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
            calendar.dispatchEvent(space);
            assert.equal(space.defaultPrevented, true);
            assert.equal(first.querySelector('input')?.checked, true);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: ' ', repeat: true, bubbles: true }));
            assert.equal(first.querySelector('input')?.checked, true);
            assert.equal(f.requests.length, 0);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            assert.equal(component.currentCell?.element, second);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: ' ', bubbles: true }));
            assert.equal(second.querySelector('input')?.checked, true);
            assert.equal(first.querySelector('input')?.checked, true);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: ' ', bubbles: true }));
            assert.equal(second.querySelector('input')?.checked, false);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            assert.equal(f.requests[0].pathname, '/events/second/update/');
            assert.equal(second.querySelector('input')?.checked, false);
        } finally { f.dom.window.close(); }
    }
});

/** Embedded action controls must retain focus and avoid the calendar's event gestures. */
test('object action controls do not navigate, focus the event, or begin a calendar drag', (): void => {
    const f = fixture('week');
    try {
        const event = f.w.document.querySelector<HTMLElement>('[data-calendar-event]')!;
        event.insertAdjacentHTML('beforeend', '<div data-calendar-object-actions data-no-row-click><button type="button">Action</button></div>');
        const button = event.querySelector('button')!;
        button.focus();
        button.dispatchEvent(new f.w.MouseEvent('pointerdown', { bubbles: true, button: 0 }));
        assert.equal(f.w.document.activeElement, button);
        button.dispatchEvent(new f.w.MouseEvent('dblclick', { bubbles: true }));
        assert.equal(f.requests.length, 0);
        const drag = new f.w.Event('dragstart', { bubbles: true, cancelable: true });
        button.dispatchEvent(drag);
        assert.equal(drag.defaultPrevented, true);
    } finally { f.dom.window.close(); }
});

/** Prefer the explicit date pair in month view, with an exclusive end on the following day. */
function monthlyCreation(): void {
    const f = fixture('month');
    try {
        doubleClick(f, f.cell.querySelector<HTMLElement>('[data-calendar-unit-cell]')!);
        const query = f.requests[0].searchParams;
        assert.equal(query.get('starts_on'), '2026-10-15');
        assert.equal(query.get('ends_on'), '2026-10-16');
        assert.equal(query.has('starts_at'), false);
    } finally { f.dom.window.close(); }
}
test('month double-clicks use the configured date-only pair', monthlyCreation);

/** Retain datetime-only calendars and omit an unconfigured end field. */
function optionalDateFields(): void {
    const month = fixture('month', true, false);
    const day = fixture('day', true, false, false);
    try {
        doubleClick(month, month.cell);
        assert.equal(month.requests[0].searchParams.get('starts_at'), '2026-10-15T00:00:00+02:00');
        assert.equal(month.requests[0].searchParams.get('ends_at'), '2026-10-16T00:00:00+02:00');
        doubleClick(day, day.cell);
        assert.equal(day.requests[0].searchParams.has('ends_at'), false);
    } finally { month.dom.window.close(); day.dom.window.close(); }
}
test('datetime-only month calendars and optional end fields remain supported', optionalDateFields);

/** Leave existing event navigation intact and avoid creation where no create view is available. */
function existingEventsAndUnavailableCreation(): void {
    const existing = fixture('week');
    const unavailable = fixture('week', false);
    try {
        doubleClick(existing, existing.cell.querySelector<HTMLElement>('[data-calendar-event]')!);
        assert.equal(existing.requests.length, 1);
        assert.equal(existing.requests[0].pathname, '/events/event/update/');
        doubleClick(unavailable, unavailable.cell);
        assert.equal(unavailable.requests.length, 0);
    } finally { existing.dom.window.close(); unavailable.dom.window.close(); }
}
test('event double-clicks navigate and unavailable creation does nothing', existingEventsAndUnavailableCreation);

/** Save alignment through the shared preference utility and swap in the server's dataview loader. */
async function saveAlignment(): Promise<void> {
    const f = fixture('month', true, true, true, { q: 'meeting', calendar_page: '2', _permission_token: 'old-token' });
    try {
        let posted: Record<string, unknown> | null = null;
        let requested: URL | null = null;
        f.w.document.cookie = 'csrftoken=preference-test';
        const overlay = f.w.document.querySelector<HTMLElement>('[bloomerp-component="inbox-calendar-overlay"]')!;
        const container = f.w.document.querySelector<HTMLElement>('[bloomerp-component="dataview-container"]')!;
        /** Inspect the real preference utility request without replacing its POST or CSRF handling. */
        f.w.CalendarFixture.htmx.ajax = function captureSave(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            assert.equal(method, 'post');
            assert.equal(options.source, overlay);
            assert.equal(options.target, container);
            assert.equal(options.swap, 'outerHTML');
            assert.equal((options.headers as Record<string, string>)['X-CSRFToken'], 'preference-test');
            assert.equal((options.headers as Record<string, string>)['X-Bloomerp-Sync-Url'], 'false');
            requested = new URL(url, f.w.location.origin);
            posted = options.values as Record<string, unknown>;
            return Promise.resolve(container);
        };
        f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!.click();
        /** Flush the preference utility's completed HTMX request. */
        await new Promise<void>(function nextTurn(resolve: () => void): void { f.w.setTimeout(resolve, 0); });
        assert.deepEqual(JSON.parse(String(posted!.selection)), { inboxes: ['1', '2'], users: [] });
        assert.deepEqual(Object.keys(posted!), ['selection']);
        assert(requested);
        const url = requested as URL;
        assert.equal(url.pathname, '/components/communication/calendar/1/align/');
        assert.equal(url.searchParams.get('q'), 'meeting');
        assert.equal(url.searchParams.get('calendar_page'), '2');
        assert.equal(url.searchParams.has('_permission_token'), false);
        assert.equal(url.searchParams.has('filter'), false);
        assert.equal(f.requests.length, 0);
    } finally { f.dom.window.close(); }
}

/** A failed preference save should remain visible and allow another attempt. */
test('calendar preference save errors are shown and the apply button permits retry', async (): Promise<void> => {
    const f = fixture('month');
    try {
        let attempts = 0;
        /** Fail only the first transport request to exercise the real utility rejection path. */
        f.w.CalendarFixture.htmx.ajax = function rejectFirstSave(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            attempts += 1;
            return attempts === 1 ? Promise.reject(new Error('Save failed')) : Promise.resolve(f.cell);
        };
        const button = f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!;
        button.click();
        /** Flush the rejected save and the component's error feedback. */
        await new Promise<void>(function failedTurn(resolve: () => void): void { f.w.setTimeout(resolve, 0); });
        assert.equal(f.w.document.querySelector<HTMLElement>('[data-overlay-error]')!.hidden, false);
        assert.equal(button.disabled, false);
        button.click();
        /** Flush the successful retry. */
        await new Promise<void>(function retryTurn(resolve: () => void): void { f.w.setTimeout(resolve, 0); });
        assert.equal(attempts, 2);
        assert.equal(f.w.document.querySelector<HTMLElement>('[data-overlay-error]')!.hidden, true);
    } finally { f.dom.window.close(); }
});

/** Empty selection cannot accidentally widen the calendar membership filter. */
function emptyAlignment(): void {
    const f = fixture('month');
    try {
        for (const checkbox of f.w.document.querySelectorAll<HTMLInputElement>('[data-overlay-inbox]')) checkbox.checked = false;
        f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!.click();
        assert.equal(f.requests.length, 0);
        assert.equal(f.w.document.querySelector<HTMLElement>('[data-overlay-error]')!.hidden, false);
    } finally { f.dom.window.close(); }
}

test('align calendars only saves the preference and reloads the dataview', saveAlignment);
test('empty calendar alignment does not widen access', emptyAlignment);

/** Explicit utility options override inherited arguments without retaining an obsolete capability. */
test('renderDataview accepts optional shell arguments, filters, and synchronization', async (): Promise<void> => {
    const f = fixture('month');
    try {
        const host = f.w.document.querySelector<HTMLElement>('[data-calendar-dataview-host]')!;
        /** Check the helper's serialized options and return the initialized dataview fixture. */
        f.w.CalendarFixture.htmx.ajax = function captureRender(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            const query = new URL(url, f.w.location.origin).searchParams;
            assert.equal(method, 'get');
            assert.equal(query.get('_arg_hide_filters'), 'false');
            assert.equal(query.get('_arg_calendar_inbox'), '2');
            assert.equal(query.get('calendar_page'), '3');
            assert.equal(query.has('_permission_token'), false);
            assert.deepEqual(JSON.parse(query.get('filter')!), [{ connector: 'AND', conditions: [] }]);
            assert.equal((options.headers as Record<string, string>)['X-Bloomerp-Sync-Url'], 'true');
            assert.equal((options.headers as Record<string, string>)['X-Bloomerp-Context'], 'view-context');
            return Promise.resolve(host);
        };
        await f.w.CalendarFixture.renderDataview(host, 1, undefined, [{ connector: 'AND', conditions: [] }], {
            queryParams: { calendar_page: 3, filter: 'obsolete-filter' },
            args: { hide_filters: true, calendar_inbox: 2 }, hideFilters: false, contextId: 'view-context', syncUrl: true,
        });
    } finally { f.dom.window.close(); }
});

/** Calendar periods must not shadow the shared dataview's detail-navigation mode. */
test('double-clicking an event opens its update URL inside the shared drawer', (): void => {
    const f = fixture('month');
    const container = f.w.document.getElementById('data-view-1')!;
    container.dataset.viewMode = 'drawer';
    container.insertAdjacentHTML('beforeend', `<div id="calendar-detail-drawer" class="hidden" bloomerp-component="drawer" data-dataview-detail-drawer><div data-drawer-panel><div data-drawer-detail-pane></div></div></div>`);
    const event = container.querySelector<HTMLElement>('[data-calendar-event]')!;
    let target: unknown;
    f.w.CalendarFixture.htmx.ajax = function captureUpdate(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
        target = options.target;
        assert.equal(url, '/events/event/update/');
        assert.equal(options.push, 'false');
        assert.equal(options.source, event);
        return Promise.resolve(f.w.document.createElement('div'));
    };
    event.dispatchEvent(new f.w.MouseEvent('dblclick', { bubbles: true }));
    assert.equal(target, container.querySelector('[data-drawer-detail-pane]'));
    assert.equal(container.querySelector('[data-dataview-detail-drawer]')!.classList.contains('hidden'), false);
    f.dom.window.close();
});

/** Row requests and filter resets retain a source within the same dataview context. */
test('row details and filter resets inherit the dataview context with clean URLs', (): void => {
    const f = fixture('month');
    try {
        const container = f.w.document.getElementById('data-view-1')!;
        container.dataset.requestContextId = 'view-context';
        const dataview = f.w.CalendarFixture.getComponent(container) as DataViewContainer;
        const event = container.querySelector<HTMLElement>('[data-calendar-event]')!;
        const urls: URL[] = [];
        const contexts: Array<string | undefined> = [];
        /** Record the URL and nearest context the shared HTMX source will inherit. */
        f.w.CalendarFixture.htmx.ajax = function captureRequest(_method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            const source = options.source as HTMLElement;
            urls.push(new URL(url, f.w.location.origin));
            contexts.push(source.closest<HTMLElement>('[data-request-context-id]')?.dataset.requestContextId);
            return Promise.resolve(container);
        };
        doubleClick(f, event);
        dataview.filter({}, true);
        assert.equal(urls[0].pathname, '/events/event/update/');
        assert.equal(urls[0].search, '');
        assert.equal(urls[1].search, '');
        assert.deepEqual(contexts, ['view-context', 'view-context']);
    } finally {
        f.dom.window.close();
    }
});


/** Check width and body class overrides when several actions reuse the same drawer. */
function drawerPresentation(): void {
    const f = fixture('month');
    try {
        const { document } = f.w;
        document.body.insertAdjacentHTML('beforeend', `
            <button id="wide" bloomerp-open-drawer="preview" bloomerp-set-drawer-title-for="preview"
                bloomerp-set-drawer-title-to="Bookings" bloomerp-set-drawer-size-to="4xl"
                bloomerp-set-drawer-body-class-to="p-4 overflow-auto">Bookings</button>
            <button id="full" bloomerp-open-drawer="preview" bloomerp-set-drawer-title-for="preview"
                bloomerp-set-drawer-size-to="full" bloomerp-set-drawer-body-class-to="p-6">All bookings</button>
            <button id="object-large" bloomerp-open-drawer="preview" bloomerp-set-drawer-title-for="preview"
                bloomerp-set-drawer-size-to="lg">File</button>
            <button id="plain" bloomerp-open-drawer="preview">Plain opener</button>
            <div id="preview" class="hidden" bloomerp-component="drawer" data-drawer-size="xl">
                <div id="preview-panel" class="max-w-xl w-full" data-drawer-panel>
                    <h2 data-drawer-title></h2>
                    <div id="preview-body" class="overflow-auto"></div>
                </div>
            </div>`);
        f.w.CalendarFixture.getComponent(document.getElementById('preview')!);
        const panel = document.getElementById('preview-panel')!;
        const body = document.getElementById('preview-body')!;

        document.getElementById('wide')!.click();
        assert.ok(panel.classList.contains('max-w-4xl'));
        assert.ok(!panel.classList.contains('max-w-xl'));
        assert.ok(body.classList.contains('p-4'));
        assert.equal(panel.querySelector('[data-drawer-title]')?.textContent, 'Bookings');

        document.getElementById('full')!.click();
        assert.ok(panel.classList.contains('max-w-full'));
        assert.ok(!panel.classList.contains('max-w-4xl'));
        assert.ok(body.classList.contains('p-6'));
        assert.ok(!body.classList.contains('p-4'));

        document.getElementById('object-large')!.click();
        assert.ok(panel.classList.contains('max-w-lg'));
        assert.ok(!panel.classList.contains('max-w-full'));
        assert.ok(!body.classList.contains('p-6'));
        assert.ok(body.classList.contains('overflow-auto'));

        document.getElementById('plain')!.click();
        assert.ok(panel.classList.contains('max-w-xl'));
        assert.ok(!panel.classList.contains('max-w-lg'));
        assert.equal(body.className, 'overflow-auto');
    } finally {
        f.dom.window.close();
    }
}
test('drawer openers set body classes and width independently', drawerPresentation);

/** Check that a modal opener owns its body classes for one opening. */
function modalPresentation(): void {
    const f = fixture('month');
    try {
        const { document } = f.w;
        document.body.insertAdjacentHTML('beforeend', `
            <button id="compact-modal" bloomerp-open-modal="preview-modal"
                bloomerp-set-modal-body-class-to="p-2 text-sm bg-base">Compact</button>
            <button id="styled-modal" bloomerp-open-modal="preview-modal"
                bloomerp-set-modal-body-class-to="rounded-lg">Styled</button>
            <button id="plain-modal" bloomerp-open-modal="preview-modal">Plain</button>
            <div id="preview-modal" bloomerp-component="modal" data-modal-padding="p-4"
                data-modal-body-class="text-sm"></div>`);
        f.w.CalendarFixture.getComponent(document.getElementById('preview-modal')!);
        const body = document.getElementById('preview-modal-body')!;

        document.getElementById('compact-modal')!.click();
        assert.ok(body.classList.contains('p-2'));
        assert.ok(body.classList.contains('bg-base'));
        assert.ok(!body.classList.contains('p-4'));

        document.getElementById('styled-modal')!.click();
        assert.ok(body.classList.contains('rounded-lg'));
        assert.ok(body.classList.contains('p-4'));
        assert.ok(!body.classList.contains('p-2'));
        assert.ok(!body.classList.contains('bg-base'));

        document.getElementById('plain-modal')!.click();
        assert.ok(body.classList.contains('text-sm'));
        assert.ok(body.classList.contains('p-4'));
        assert.ok(body.classList.contains('overflow-y-auto'));
        assert.ok(!body.classList.contains('rounded-lg'));
    } finally {
        f.dom.window.close();
    }
}
test('modal openers replace their body classes and restore the default padding', modalPresentation);

/** Forward the live selection and filters while preserving the action header. */
function toolbarSelection(): void {
    const f = fixture('month', true, true, true, {
        filter: 'old-filter',
    });
    try {
        const container = f.w.document.getElementById('data-view-1')!;
        container.insertAdjacentHTML('beforeend', `
            <input type="checkbox" data-bulk-checkbox data-object-id="first">
            <input type="checkbox" data-bulk-checkbox data-object-id="second">
            <div bloomerp-component="dataview-action-list">
                <div data-data-view-button="reconcile" data-dataview-action="true"><button id="reconcile">Reconcile</button></div>
                <div data-data-view-button="export"><button id="export">Export</button></div>
                <button type="button" data-dataview-create-button>Add</button>
                <div data-base-url="/nested/" data-content-type-id="2">
                    <div data-data-view-button="nested" data-dataview-action="true"><button id="nested">Nested</button></div>
                </div>
            </div>`);
        const actions = container.querySelector<HTMLElement>('[bloomerp-component="dataview-action-list"]')!;
        const actionList = f.w.CalendarFixture.getComponent(actions)!;
        const checkbox = container.querySelector<HTMLInputElement>('[data-object-id="first"]')!;
        checkbox.checked = true;
        checkbox.dispatchEvent(new f.w.Event('change', { bubbles: true }));

        /** Emit HTMX's request configuration boundary and inspect its parameters. */
        function parameters(id: string): Record<string, unknown> {
            const button = f.w.document.getElementById(id)!;
            const detail = {
                elt: button,
                path: '/action/?filter=old-filter',
                headers: { 'X-Bloomerp-Context': 'action-context' },
                parameters: {} as Record<string, unknown>,
            };
            button.dispatchEvent(new f.w.CustomEvent('htmx:configRequest', { bubbles: true, detail }));
            return { ...detail.parameters, path: detail.path, context: detail.headers['X-Bloomerp-Context'] };
        }
        assert.equal(JSON.stringify(parameters('reconcile').selected_ids), '["first"]');
        assert.equal(parameters('nested').selected_ids, undefined);
        assert.equal(parameters('export').selected_ids, undefined);
        const dataSection = f.w.document.getElementById('data-view-data-section')!;
        dataSection.dispatchEvent(new f.w.CustomEvent('htmx:afterSwap', {
            bubbles: true,
            detail: {
                target: dataSection,
                xhr: { responseURL: 'https://app.example/dataview/?filter=current-filter&q=search' },
            },
        }));
        const updated = new URL(parameters('reconcile').path as string, f.w.location.origin);
        assert.equal(updated.searchParams.get('filter'), 'current-filter');
        assert.equal(updated.searchParams.get('q'), 'search');
        assert.equal(updated.searchParams.has('_permission_token'), false);
        assert.equal(updated.searchParams.has('_dataview_detail_view_token'), false);
        assert.equal(parameters('reconcile').context, 'action-context');
        dataSection.dispatchEvent(new f.w.CustomEvent('htmx:afterSwap', {
            bubbles: true, detail: { target: dataSection, xhr: { responseURL: 'https://app.example/dataview/' } },
        }));
        assert.equal(new URL(parameters('reconcile').path as string, f.w.location.origin).searchParams.has('filter'), false);
        checkbox.checked = false;
        checkbox.dispatchEvent(new f.w.Event('change', { bubbles: true }));
        assert.equal(JSON.stringify(parameters('reconcile').selected_ids), '[]');

        actions.querySelector<HTMLButtonElement>('[data-dataview-create-button]')?.click();
        assert.equal(f.requests[0].pathname, '/components/create-object/1/');
        assert.equal(f.requests[0].searchParams.has('data_view_create_id'), false);
        assert(f.w.document.querySelector('[data-modal-instance-of="create-object-modal"].flex'));

        // Teardown releases the listener even if the old DOM still exists.
        actionList.destroy();
        assert.equal(parameters('reconcile').selected_ids, undefined);
    } finally { f.dom.window.close(); }
}
test('toolbar requests carry the current checkbox selection and stay scoped to their container', toolbarSelection);

/** Exercise record selection across duplicate items, renderer swaps, and collection changes. */
function sharedRecordSelection(): void {
    const f = fixture('month', true, true, true, { q: 'test' });
    try {
        const container = f.w.document.getElementById('data-view-1')!;
        const component = f.w.CalendarFixture.getComponent(container)!;
        const section = container.querySelector<HTMLElement>('#data-view-data-section')!;
        container.insertAdjacentHTML('afterbegin', `
            <div data-dataview-selection-bar hidden>
                <span data-selection-count data-label="%(count)s selected"></span>
                <div data-dataview-selection-actions bloomerp-component="dataview-action-list" hidden>
                    <div data-dataview-action><button type="button" data-test-action>Action</button></div>
                </div>
            </div>`);
        const bar = container.querySelector<HTMLElement>('[data-dataview-selection-bar]')!;
        const actions = container.querySelector<HTMLElement>('[data-dataview-selection-actions]')!;
        f.w.CalendarFixture.getComponent(actions);
        const status = container.querySelector<HTMLElement>('[data-selection-count]')!;
        const action = container.querySelector<HTMLButtonElement>('[data-test-action]')!;
        container.dataset.renderId = 'original-view';

        /** Render a selectable record using the same contract as the production checkbox template. */
        function record(id: string): string {
            return `<div data-dataview-record><input type="checkbox" data-bulk-checkbox data-object-id="${id}"></div>`;
        }

        /** Read the selection passed to an action on the host model. */
        function selectedIds(): string[] {
            const parameters = {} as { selected_ids: string[] };
            action.dispatchEvent(new f.w.CustomEvent('htmx:configRequest', { bubbles: true, detail: { elt: action, parameters } }));
            return Array.from(parameters.selected_ids);
        }

        /** Report a data section swap while preserving the fixture's original request path. */
        function swapResults(query: string): void {
            const url = new URL(container.dataset.url!);
            url.search = query;
            section.dispatchEvent(new f.w.CustomEvent('htmx:afterSwap', {
                bubbles: true, detail: { target: section, xhr: { responseURL: url.toString() } },
            }));
        }

        section.innerHTML = record('same') + record('same') + record('different')
            + `<div data-base-url="/nested/" data-content-type-id="1">${record('nested')}</div>`;
        component.onAfterSwap();
        const duplicates = section.querySelectorAll<HTMLInputElement>('[data-object-id="same"]');
        assert.equal(duplicates[0].hidden, false);
        assert.equal(bar.hidden, true);
        assert.equal(actions.hidden, true);
        duplicates[0].click();
        assert.equal(duplicates[1].checked, true);
        assert.equal(duplicates[1].parentElement?.hasAttribute('data-dataview-record-selected'), true);
        assert.equal(status.textContent, '1 selected');
        assert.equal(bar.hidden, false);
        assert.equal(actions.hidden, false);
        f.w.CalendarFixture.setupComponentAutoInit();
        const card = duplicates[0].parentElement!;
        f.w.CalendarFixture.htmx.swap(card, '<input type="checkbox" data-bulk-checkbox data-object-id="same">', {
            swapStyle: 'innerHTML', swapDelay: 0, settleDelay: 0,
        });
        assert.equal(card.querySelector<HTMLInputElement>('input')?.checked, true);
        section.querySelector<HTMLInputElement>('[data-object-id="different"]')?.click();
        assert.deepEqual(selectedIds(), ['same', 'different']);
        assert.equal(status.textContent, '2 selected');

        section.innerHTML = '<input type="checkbox" data-bulk-checkbox data-all="true">' + record('same') + record('new')
            + `<div data-base-url="/nested/" data-content-type-id="1">${record('nested')}</div>`;
        swapResults('inboxes=1&q=test&page=2');
        assert.equal(section.querySelector<HTMLInputElement>('[data-object-id="same"]')?.checked, true);
        const master = section.querySelector<HTMLInputElement>('[data-all]')!;
        assert.equal(master.indeterminate, true);
        assert.equal(status.textContent, '2 selected');
        master.click();
        assert.deepEqual(selectedIds(), ['same', 'different', 'new']);
        master.click();
        assert.deepEqual(selectedIds(), ['different']);
        section.querySelector<HTMLInputElement>('[data-object-id="same"]')?.click();
        swapResults('inboxes=1&q=different&page=2');
        assert.deepEqual(selectedIds(), []);
        assert.equal(bar.hidden, true);
        assert.equal(section.querySelector<HTMLInputElement>('[data-object-id="same"]')?.checked, false);

        section.querySelector<HTMLInputElement>('[data-object-id="same"]')?.click();
        f.w.document.body.dispatchEvent(new f.w.CustomEvent('bloomerp:dataview-refresh', { detail: { renderId: 'another-view' } }));
        assert.deepEqual(selectedIds(), ['same']);
        assert.equal(f.requests.length, 0);
        f.w.document.body.dispatchEvent(new f.w.CustomEvent('bloomerp:dataview-refresh', { detail: { renderId: 'original-view' } }));
        assert.deepEqual(selectedIds(), []);
        assert.equal(f.requests.length, 1);

        section.innerHTML = `<div data-dataview-record-type="2">${record('file')}</div>`;
        component.onAfterSwap();
        const file = section.querySelector<HTMLInputElement>('[data-object-id="file"]')!;
        assert.equal(file.hidden, true);
        file.click();
        assert.equal(status.textContent, '');
        assert.equal(bar.hidden, true);
        assert.equal(actions.hidden, true);
        assert.deepEqual(selectedIds(), []);

        section.innerHTML = record('same');
        container.removeAttribute('data-dataview-selection-enabled');
        component.onAfterSwap();
        const unavailable = section.querySelector<HTMLInputElement>('[data-object-id="same"]')!;
        assert.equal(unavailable.hidden, true);
        unavailable.click();
        assert.deepEqual(selectedIds(), []);
        assert.equal(bar.hidden, true);
    } finally {
        f.dom.window.close();
    }
}
test('record selection follows the filtered collection across renderer swaps and stays scoped to its model', sharedRecordSelection);

/** A save from a portaled drawer reloads matching views with their own filters. */
function contentTypeRefresh(): void {
    const f = fixture('week', false, true, true, { q: 'first' });
    try {
        const sources: string[] = [];
        const capture = f.w.CalendarFixture.htmx.ajax;
        /** Verify that each view owns its request and that a background reload leaves history alone. */
        f.w.CalendarFixture.htmx.ajax = function captureRefresh(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            const source = options.source as HTMLElement;
            sources.push(source.id);
            assert.equal(options.target, source.querySelector('#data-view-data-section'));
            assert.equal(options.push, 'false');
            assert.equal(options.replace, 'false');
            return capture(method, url, options);
        };
        f.w.document.body.insertAdjacentHTML('beforeend', `
            <div id="second-view" bloomerp-component="dataview-container" data-content-type-id="1"
                 data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?q=second" data-sync-url="true">
                <div id="data-view-data-section"></div>
            </div>
            <div id="other-view" bloomerp-component="dataview-container" data-content-type-id="2"
                 data-base-url="/components/dataview/2/" data-url="/components/dataview/2/?q=other">
                <div id="data-view-data-section"></div>
            </div>
            <div id="file-view" bloomerp-component="dataview-container" data-content-type-id="3"
                 data-base-url="/components/dataview/3/" data-url="/components/dataview/3/?q=files">
                <div id="data-view-data-section"><div data-dataview-record-type="1"></div></div>
            </div>
            <div data-dataview-detail-drawer><form></form></div>`);
        f.w.CalendarFixture.initComponents(f.w.document.body);
        const drawerForm = f.w.document.querySelector('[data-dataview-detail-drawer] form')!;
        drawerForm.dispatchEvent(new f.w.CustomEvent('bloomerp:dataview-refresh', {
            bubbles: true, detail: { contentTypeId: 1 },
        }));
        assert.deepEqual(f.requests.map((url: URL): string | null => url.searchParams.get('q')), [
            'first', 'second', 'files',
        ]);
        assert.deepEqual(sources, ['data-view-1', 'second-view', 'file-view']);
    } finally {
        f.dom.window.close();
    }
}
test('a drawer save refreshes DataViews displaying the same content type', contentTypeRefresh);

/** Replace the action's row while leaving a second view of the same record intact. */
function scopedItemRefresh(): void {
    const f = fixture('week');
    try {
        const first = f.w.document.getElementById('data-view-1')!;
        const recordMarkup = '<tr data-dataview-record data-dataview-item-index="4" data-object-id="22"'
            + ' data-dataview-item-url="/components/dataview/1/item/22/?q=first">'
            + '<td><button type="button">Complete</button></td></tr>';
        first.querySelector('#data-view-data-section')!.innerHTML = `<table><tbody>${recordMarkup}</tbody></table>`;
        first.insertAdjacentHTML('afterend', `
            <div id="second-view" bloomerp-component="dataview-container" data-content-type-id="1"
                 data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?q=second">
                <div id="data-view-data-section"><table><tbody>${recordMarkup.replace('q=first', 'q=second')}</tbody></table></div>
            </div>`);
        const second = f.w.document.getElementById('second-view')!;
        f.w.CalendarFixture.initComponents(second);
        const firstRow = first.querySelector('tr')!;
        /** Capture the request and exercise HTMX's actual row replacement. */
        f.w.CalendarFixture.htmx.ajax = function loadRow(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            f.requests.push(new URL(url, f.w.location.origin));
            assert.equal(method, 'get');
            assert.equal(options.source, firstRow);
            assert.equal(options.target, firstRow);
            assert.equal(options.swap, 'outerHTML');
            assert.equal((options.headers as Record<string, string>)['X-Bloomerp-Dataview-Item-Index'], '4');
            f.w.CalendarFixture.htmx.swap(firstRow, '<tr><td>Completed</td></tr>', {
                swapStyle: 'outerHTML', swapDelay: 0, settleDelay: 0,
            });
            return Promise.resolve(first.querySelector('tr')!);
        };
        firstRow.querySelector('button')!.dispatchEvent(new f.w.CustomEvent('bloomerp:dataview-record-refresh', {
            bubbles: true,
            detail: { contentTypeId: 1, objectId: '22', originOnly: true },
        }));
        assert.equal(f.requests.length, 1);
        assert.equal(f.requests[0].searchParams.get('q'), 'first');
        assert.equal(first.querySelector('tr')?.textContent, 'Completed');
        assert.equal(second.querySelector('tr')?.textContent, 'Complete');
    } finally {
        f.dom.window.close();
    }
}
test('an object action replaces only its originating record', scopedItemRefresh);

/** Resolve each occurrence of an embedded record through its host's item URL. */
function embeddedItemRefresh(): void {
    const f = fixture('week');
    try {
        const view = f.w.document.getElementById('data-view-1')!;
        const section = view.querySelector('#data-view-data-section')!;
        section.innerHTML = `
            <div data-dataview-record data-object-id="60" data-dataview-record-content-type-id="2"
                 data-dataview-item-url="/components/dataview/1/item/60/?folder_id=4" data-dataview-item-placement="first"></div>
            <div data-dataview-record data-object-id="60" data-dataview-record-content-type-id="2"
                 data-dataview-item-url="/components/dataview/1/item/60/?folder_id=7" data-dataview-item-placement="second"></div>
            <div data-dataview-record data-object-id="60" data-dataview-record-content-type-id="1"
                 data-dataview-item-url="/components/dataview/1/item/60/?folder_id=9"></div>`;
        const placements: string[] = [];
        /** Capture the row-specific request and its renderer placement. */
        f.w.CalendarFixture.htmx.ajax = function loadRow(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
            f.requests.push(new URL(url, f.w.location.origin));
            assert.equal(method, 'get');
            assert.equal(options.source, options.target);
            placements.push((options.headers as Record<string, string>)['X-Bloomerp-Dataview-Item-Placement']);
            return Promise.resolve(options.target as HTMLElement);
        };
        f.w.document.body.dispatchEvent(new f.w.CustomEvent('bloomerp:dataview-record-refresh', {
            detail: { contentTypeId: 2, objectId: '60' },
        }));
        assert.deepEqual(f.requests.map((url: URL): string => url.pathname), [
            '/components/dataview/1/item/60/', '/components/dataview/1/item/60/',
        ]);
        assert.deepEqual(f.requests.map((url: URL): string | null => url.searchParams.get('folder_id')), ['4', '7']);
        assert.deepEqual(placements, ['first', 'second']);
    } finally {
        f.dom.window.close();
    }
}
test('a record refresh uses the matching host rows and their own placement', embeddedItemRefresh);

/** Ensure save, dismissal, and draft reuse stay scoped to the Dataview that opened each modal. */
async function scopedCreateModal(): Promise<void> {
    const f = fixture('week', true, true, true, { q: 'first' });
    try {
        const first = f.w.document.getElementById('data-view-1')!;
        first.insertAdjacentHTML('afterbegin', '<button type="button" data-dataview-create-button>Add first</button>');
        const firstAdd = first.querySelector<HTMLButtonElement>('[data-dataview-create-button]')!;
        first.insertAdjacentHTML('beforeend', `
            <div id="second-view" bloomerp-component="dataview-container" data-content-type-id="1" data-dataview-selection-enabled
                 data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?q=second">
                <div bloomerp-component="dataview-create" data-create-url="/components/create-object/1/" hidden></div>
                <button type="button" data-dataview-create-button>Add second</button>
                <div id="data-view-data-section"><input type="checkbox" data-bulk-checkbox data-object-id="checked"></div>
            </div>`);
        const second = f.w.document.getElementById('second-view')!;
        f.w.CalendarFixture.initComponents(second);
        const secondAdd = second.querySelector<HTMLButtonElement>('[data-dataview-create-button]')!;
        const checked = second.querySelector<HTMLInputElement>('[data-bulk-checkbox]')!;
        checked.click();

        firstAdd.click();
        const firstModal = f.w.document.querySelector<HTMLElement>('[data-modal-instance-of="create-object-modal"]')!;
        const firstBody = firstModal.querySelector<HTMLElement>('[data-modal-body]')!;
        firstBody.innerHTML = '<form><input value="Retained draft"></form>';
        secondAdd.click();
        const secondModal = f.w.document.querySelectorAll<HTMLElement>('[data-modal-instance-of="create-object-modal"]').item(1);
        assert.notEqual(firstModal.id, secondModal.id);
        const secondBody = secondModal.querySelector<HTMLElement>('[data-modal-body]')!;
        secondBody.innerHTML = '<form></form>';
        secondAdd.remove();
        secondBody.querySelector('form')!.dispatchEvent(new f.w.CustomEvent('bloomerp:close-modal', {
            bubbles: true, detail: { result: 'saved' },
        }));

        /** Wait for the modal's configured exit animation to finish. */
        function afterClose(): Promise<void> {
            return new Promise<void>(function wait(resolve: () => void): void {
                f.w.setTimeout(resolve, 240);
            });
        }

        await afterClose();
        assert(firstModal.classList.contains('flex'));
        assert(secondModal.classList.contains('hidden'));
        assert.equal(f.requests.length, 3);
        assert.equal(f.requests[2].searchParams.get('q'), 'second');
        assert.equal(checked.checked, true);

        firstModal.querySelector<HTMLButtonElement>('[bloomerp-close-modal]')!.click();
        await afterClose();
        assert.equal(f.requests.length, 3);
        firstAdd.click();
        assert.equal(firstBody.querySelector<HTMLInputElement>('input')?.value, 'Retained draft');
        assert.equal(f.requests.length, 3);
        firstBody.querySelector('form')!.dispatchEvent(new f.w.CustomEvent('bloomerp:close-modal', {
            bubbles: true, detail: { result: 'saved' },
        }));
        await afterClose();
        assert.equal(f.requests.length, 4);
        assert.equal(f.requests[3].searchParams.get('q'), 'first');
        firstAdd.click();
        assert.equal(f.requests.length, 5);
    } finally {
        f.dom.window.close();
    }
}
test('create modals refresh only their originating Dataview and preserve dismissed drafts', scopedCreateModal);
