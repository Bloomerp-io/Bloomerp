/** DOM regressions for calendar creation using the real calendar, modal, and dataview container. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type renderDataview from '../../utils/dataview.ts';
import type { Calendar, CalendarCell } from './Calendar.ts';

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
                import { Modal } from '${root}/ts/components/Modal';
                import { Drawer } from '${root}/ts/components/Drawer';
                import InboxCalendarOverlay from '${root}/ts/components/inbox/InboxCalendarOverlay';
                import renderDataview from '${root}/ts/utils/dataview';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                import htmx from 'htmx.org';
                registerComponent('calendar', Calendar);
                registerComponent('inbox-calendar-overlay', InboxCalendarOverlay);
                registerComponent('calendar-cell', CalendarCell);
                registerComponent('dataview-container', DataViewContainer);
                registerComponent('modal', Modal);
                registerComponent('drawer', Drawer);
                export { initComponents, getComponent, htmx, renderDataview };
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
        getComponent(element: HTMLElement): Calendar | CalendarCell | null;
        renderDataview: typeof renderDataview;
        htmx: { ajax(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> };
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
        <section data-calendar-dataview-host><div id="data-view-1" bloomerp-component="dataview-container" data-content-type-id="1"
            data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?inboxes=1"
            data-create-url="${create ? '/components/create-object/1/?inboxes=1' : ''}"
            data-modal-id="create-object-modal" data-target="#create-object-modal-body">
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
            assert(query.get('data_view_create_id'));
            assert(!f.w.document.getElementById('create-object-modal')!.classList.contains('hidden'));
        } finally { f.dom.window.close(); }
    }
}
test('day and week double-clicks open the shared modal with one-hour defaults', hourlyCreation);

/** Cycle overlapping event cards horizontally and keep directly focused cards tied to their own details. */
test('day and week keyboard navigation selects and opens individual events in the same slot', (): void => {
    for (const mode of ['day', 'week']) {
        const f = fixture(mode);
        try {
            /** Provide browser scrolling for selection changes in the DOM fixture. */
            f.w.HTMLElement.prototype.scrollIntoView = function scrollCell(): void {};
            const calendar = f.w.document.querySelector<HTMLElement>('[bloomerp-component="calendar"]')!;
            const first = calendar.querySelector<HTMLElement>('[data-calendar-event]')!;
            const unit = f.cell.dataset.calendarUnit!;
            first.dataset.calendarUnit = unit;
            f.cell.querySelector<HTMLElement>('[data-calendar-unit-cell]')!.dataset.calendarUnit = unit;
            first.insertAdjacentHTML('afterend', `<div role="button" tabindex="0" data-calendar-event data-calendar-unit="${unit}"
                data-object-id="second" data-detail-url="/events/second/update/" bloomerp-component="calendar-cell">Second event</div>`);
            const second = first.nextElementSibling as HTMLElement;
            f.w.CalendarFixture.initComponents(second);
            const component = f.w.CalendarFixture.getComponent(calendar) as Calendar;
            second.focus();
            assert.equal(component.currentCell?.element, second);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
            assert.equal(component.currentCell?.element, first);
            assert.equal(calendar.querySelectorAll('[data-calendar-event].cell-selected').length, 1);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            assert.equal(f.requests[0].pathname, '/events/event/update/');
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            assert.equal(component.currentCell?.element, second);
            calendar.dispatchEvent(new f.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            assert.equal(f.requests[1].pathname, '/events/second/update/');
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
            return Promise.resolve(host);
        };
        await f.w.CalendarFixture.renderDataview(host, 1, undefined, [{ connector: 'AND', conditions: [] }], {
            queryParams: { calendar_page: 3, _permission_token: 'obsolete-token', filter: 'obsolete-filter' },
            args: { hide_filters: true, calendar_inbox: 2 }, hideFilters: false, permissionToken: null, syncUrl: true,
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
        return Promise.resolve(f.w.document.createElement('div'));
    };
    event.dispatchEvent(new f.w.MouseEvent('dblclick', { bubbles: true }));
    assert.equal(target, container.querySelector('[data-drawer-detail-pane]'));
    assert.equal(container.querySelector('[data-dataview-detail-drawer]')!.classList.contains('hidden'), false);
    f.dom.window.close();
});
