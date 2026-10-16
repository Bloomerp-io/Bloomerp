/** DOM regressions for calendar creation using the real calendar, modal, and dataview container. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';

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
                import InboxCalendarOverlay from '${root}/ts/components/inbox/InboxCalendarOverlay';
                import { registerComponent, initComponents } from '${root}/ts/components/BaseComponent';
                import htmx from 'htmx.org';
                registerComponent('calendar', Calendar);
                registerComponent('inbox-calendar-overlay', InboxCalendarOverlay);
                registerComponent('calendar-cell', CalendarCell);
                registerComponent('dataview-container', DataViewContainer);
                registerComponent('modal', Modal);
                export { initComponents, htmx };
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
        <div id="data-view-1" bloomerp-component="dataview-container" data-content-type-id="1"
            data-base-url="/components/dataview/1/" data-url="/components/dataview/1/?inboxes=1"
            data-create-url="${create ? '/components/create-object/1/?inboxes=1' : ''}"
            data-modal-id="create-object-modal" data-target="#create-object-modal-body">
            <details bloomerp-component="inbox-calendar-overlay" data-preferred-group="1" open>
                <input type="checkbox" data-overlay-inbox value="1" checked>
                <input type="checkbox" data-overlay-inbox value="2" checked>
                <span data-overlay-error hidden>Select at least one calendar.</span>
                <button type="button" data-apply-overlay>Apply</button>
            </details>
            <div id="data-view-data-section">
                <div bloomerp-component="calendar" data-content-type-id="1" data-view-mode="${mode}"
                    data-calendar-start-field-type="DateTimeField" data-calendar-create-start-field="starts_at"
                    data-calendar-create-end-field="${endField ? 'ends_at' : ''}"
                    data-calendar-create-start-date-field="${datePair ? 'starts_on' : ''}"
                    data-calendar-create-end-date-field="${datePair ? 'ends_on' : ''}">
                    <section data-calendar-unit-section data-calendar-unit="2026-10-15${month ? '' : 'T09'}"
                        data-calendar-create-start="2026-10-15T${month ? '00' : '09'}:00:00+02:00"
                        data-calendar-create-end="2026-10-${month ? '16T00' : '15T10'}:00:00+02:00">
                        <button data-calendar-unit-cell bloomerp-component="calendar-cell">Empty cell</button>
                        <button data-calendar-event bloomerp-component="calendar-cell" data-object-id="event"
                            data-detail-url="/events/event/" data-object-string="Existing event">Existing event</button>
                    </section>
                </div>
            </div>
        </div>
        <div id="create-object-modal" bloomerp-component="modal"></div>`,
        { runScripts: 'outside-only', pretendToBeVisual: true, url: 'https://app.example/inbox/1/calendar/' });
    const w = dom.window as FixtureWindow;
    w.eval(scriptCode);
    const requests: URL[] = [];
    /** Capture real modal/detail requests without making network calls. */
    w.CalendarFixture.htmx.ajax = function capture(method: string, url: string, options: Record<string, unknown>): Promise<HTMLElement> {
        assert.equal(method.toLowerCase(), 'get');
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
        assert.equal(existing.requests[0].pathname, '/events/event/');
        doubleClick(unavailable, unavailable.cell);
        assert.equal(unavailable.requests.length, 0);
    } finally { existing.dom.window.close(); unavailable.dom.window.close(); }
}
test('event double-clicks navigate and unavailable creation does nothing', existingEventsAndUnavailableCreation);

/** Use the actual dataview filter path to overlay inboxes without retaining the old AND constraint. */
function overlayFilters(): void {
    const f = fixture('month');
    try {
        f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!.click();
        assert.equal(f.requests.length, 1);
        const query = f.requests[0].searchParams;
        assert.equal(query.get('inboxes'), null);
        assert.equal(query.get('inboxes__in'), null);
        assert.deepEqual(JSON.parse(query.get('filter')!), [{ connector: 'AND', conditions: [{ field_path: 'inboxes', lookup_id: 'values_in', value: ['1', '2'] }] }]);
        assert.equal(query.get('calendar_color_values'), '1,2');
        assert.equal(query.get('calendar_color_preferred'), '1');
        assert.equal(query.get('calendar_color_field'), 'inboxes');
    } finally { f.dom.window.close(); }
}

/** An empty selection must not remove the scope and accidentally show every event. */
function emptyOverlaySelection(): void {
    const f = fixture('month');
    try {
        for (const checkbox of f.w.document.querySelectorAll<HTMLInputElement>('[data-overlay-inbox]')) checkbox.checked = false;
        f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!.click();
        assert.equal(f.requests.length, 0);
        assert.equal(f.w.document.querySelector<HTMLElement>('[data-overlay-error]')!.hidden, false);
    } finally { f.dom.window.close(); }
}

test('calendar overlays apply a union filter through the shared dataview', overlayFilters);
test('empty calendar overlays do not widen the event scope', emptyOverlaySelection);

/** Retain search and period while replacing only the dropdown's dedicated inbox condition. */
function preserveOverlayConstraints(): void {
    const titleFilter = { connector: 'AND', conditions: [{ field_path: 'title', lookup_id: 'contains', value: 'planning' }] };
    const oldInboxFilter = { connector: 'AND', conditions: [{ field_path: 'inboxes', lookup_id: 'values_in', value: ['1'] }] };
    const f = fixture('month', true, true, true, { filter: JSON.stringify([titleFilter, oldInboxFilter]), q: 'planning', calendar_page: '2' });
    try {
        f.w.document.querySelector<HTMLButtonElement>('[data-apply-overlay]')!.click();
        const query = f.requests[0].searchParams;
        assert.equal(query.get('q'), 'planning');
        assert.equal(query.get('calendar_page'), '2');
        const filters = JSON.parse(query.get('filter')!);
        assert.equal(filters.length, 2);
        assert.deepEqual(filters[0], titleFilter);
        assert.deepEqual(filters[1].conditions[0].value, ['1', '2']);
    } finally { f.dom.window.close(); }
}

test('calendar overlays preserve search, period, and other filter constraints', preserveOverlayConstraints);
