/** Exercise the real composer and shared recipient control against a bounded SDK response. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import type { OutputAsset, OutputChunk } from "rollup";
import { JSDOM, type DOMWindow } from "jsdom";

const root = fileURLToPath(new URL("../../..", import.meta.url)).replace(/\/$/, "");
const entry = `${root}/calendar-composer-test.ts`;
const built = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": `${root}/ts` } },
    plugins: [{
        name: "calendar-composer-test",
        /** Resolve the in-memory test entry. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle production controls and their lifecycle registry together. */
        load(id: string): string | null {
            return id === entry ? `
                import { Modal } from '${root}/ts/components/Modal';
                import CalendarAvailability from '${root}/ts/components/inbox/CalendarAvailability';
                import CalendarEventEditor from '${root}/ts/components/inbox/CalendarEventEditor';
                import { DetailViewCell } from '${root}/ts/components/detail_view_components/DetailViewCell';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('modal', Modal);
                registerComponent('calendar-event-editor', CalendarEventEditor);
                registerComponent('calendar-availability', CalendarAvailability);
                registerComponent('detail-view-value', DetailViewCell);
                export { initComponents, getComponent };
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "ComposerFixture" } },
});
const output = Array.isArray(built) ? built[0] : built;
assert("output" in output);
/** Identify the executable component bundle. */
const chunk = output.output.find((item: OutputAsset | OutputChunk): boolean => item.type === "chunk");
assert(chunk?.type === "chunk");
const code = chunk.code;
interface ComposerWindow extends DOMWindow { ComposerFixture: { initComponents(element: HTMLElement): void; getComponent(element: HTMLElement): { setSelection(selection: { users: string[]; day: string; timezone: string; startTime: string; endTime: string; endDate: string; allDay: boolean }): void } } }
interface Fixture { dom: JSDOM; w: ComposerWindow; requests: URL[]; form: HTMLFormElement }

/** Initialize a composer with real chip controls and a fake network boundary. */
function fixture(noEmail: boolean = false, modal: boolean = false): Fixture {
    const dom = new JSDOM(`<!doctype html><form id="calendar-event-create-form" bloomerp-component="calendar-event-editor" data-recipient-search-url="/recipients/?calendar_users=1">
        <div data-layout-root><div data-layout-row data-row-columns="1"><div data-layout-grid><div bloomerp-component="detail-view-value" data-layout-item-id="attendees" data-colspan="1" data-required="False"><div data-layout-item-body>
        <input name="attendees" value="person@example.com"><input name="attendee_users" value='["u1"]' data-identities='{"person@example.com":"u1"}'>
        <input name="start_date" value="2026-10-15"><input name="end_date" value="2026-10-15">
        <input name="start_time" value="10:00"><input name="end_time" value="11:00">
        <input name="all_day" type="checkbox"><select name="event_timezone"><option>Europe/Brussels</option></select>
        <input type="hidden" name="_permission_token" value="scoped-calendar-token">
        </div></div></div></div></div>
        <div bloomerp-component="calendar-availability" data-url="/components/calendar/availability/"><span data-availability-date></span><div data-availability-grid></div></div>
        <button type="submit" id="object-crud-container-save-button"><i class="fa fa-save"></i><span data-calendar-submit-label>Save</span></button></form>`,
        { runScripts: "outside-only", pretendToBeVisual: true, url: "https://app.example/events/create/" });
    const w = dom.window as ComposerWindow;
    if (modal) {
        const form = w.document.querySelector("form")!;
        const shell = w.document.createElement("div");
        shell.id = "create-object-modal";
        shell.setAttribute("bloomerp-component", "modal");
        shell.dataset.modalPadding = "p-3";
        shell.innerHTML = '<div data-modal-container><div data-modal-body class="p-3"></div></div>';
        form.replaceWith(shell);
        shell.querySelector("[data-modal-body]")!.append(form);
        const style = w.document.createElement("style");
        style.textContent = ".p-3 { padding: 12px; } .p-0 { padding: 0; }";
        w.document.head.append(style);
    }
    const requests: URL[] = [];
    /** Capture requests while returning readable and unavailable attendee calendars. */
    w.fetch = async function fetchFixture(input: RequestInfo | URL): Promise<Response> {
        requests.push(new URL(String(input)));
        return new Response(JSON.stringify({ users: [
            { id: "u1", label: "Person", available: true, busy: [{ start: "2026-10-15T08:00:00Z", end: "2026-10-15T09:00:00Z" }] },
            { id: "u2", label: "Private user", available: false, busy: [] },
        ] }), { headers: { "Content-Type": "application/json" } });
    };
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser default omitted by HTMX but required by JSDOM's XPath implementation. */
    w.XPathExpression.prototype.evaluate = function evaluateWithDefault(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, result);
    };
    if (noEmail) {
        w.document.querySelector<HTMLInputElement>('[name="attendees"]')!.value = "";
        const users = w.document.querySelector<HTMLInputElement>('[name="attendee_users"]')!;
        users.dataset.identities = '{"user:u1":"u1"}';
        users.dataset.labels = '{"user:u1":"Person"}';
    }
    w.eval(code);
    w.ComposerFixture.initComponents(w.document.body);
    return { dom, w, requests, form: w.document.querySelector("form")! };
}

/** Let initialization settle without relying on a network server. */
async function settle(): Promise<void> { await new Promise<void>(function wait(resolve: () => void): void { setTimeout(resolve, 180); }); }

/** Require timezone-aware busy cells and distinguish unavailable information from free time. */
async function availability(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        assert.equal(f.requests[0].searchParams.get("timezone"), "Europe/Brussels");
        assert.deepEqual(f.requests[0].searchParams.getAll("users"), ["u1"]);
        const rows = f.form.querySelectorAll("tbody tr");
        assert.equal(rows.length, 48);
        assert.equal(rows[20].children[1].textContent, "Busy");
        assert.equal(rows[20].children[2].textContent, "?");
        assert.equal(rows[22].children[1].textContent, "");
        assert.match(f.form.textContent!, /person@example.com · User/);
    } finally { f.dom.window.close(); }
}

/** Schedule a one-hour range across midnight from the availability calendar. */
async function midnightSelection(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        f.form.querySelector<HTMLButtonElement>('[data-availability-time="23:30"]')!.click();
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="start_time"]')!.value, "23:30");
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="end_time"]')!.value, "00:30");
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="end_date"]')!.value, "2026-10-16");
    } finally { f.dom.window.close(); }
}

/** Removing an internal account and manually retyping it must produce an external address. */
function manualIdentity(): void {
    const f = fixture();
    try {
        f.form.querySelector<HTMLButtonElement>('[data-recipient-chip] button')!.click();
        const entry = f.form.querySelector<HTMLInputElement>('[role="combobox"]')!;
        entry.value = "person@example.com";
        entry.dispatchEvent(new f.w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="attendee_users"]')!.value, "[]");
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="attendees"]')!.value, "person@example.com");
    } finally { f.dom.window.close(); }
}

test("availability respects the timezone and marks private calendars unknown", availability);
test("selecting a late slot carries its end into the next day", midnightSelection);
test("typed email does not inherit a removed account identity", manualIdentity);

/** Preserve email-free internal identities without putting account tokens into mailbox fields. */
function emailFreeIdentity(): void {
    const f = fixture(true);
    try {
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="attendees"]')!.value, "");
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="attendee_users"]')!.value, '["u1"]');
        assert.match(f.form.textContent!, /Person · User/);
        f.form.querySelector<HTMLButtonElement>('[data-recipient-chip] button')!.click();
        assert.equal(f.form.querySelector<HTMLInputElement>('[name="attendee_users"]')!.value, "[]");
    } finally { f.dom.window.close(); }
}

test("internal accounts without email keep their separate identity", emailFreeIdentity);

/** Keep Save/Send in sync with external mailboxes, internal identities, and unfinished input. */
function submitLabel(): void {
    const f = fixture();
    try {
        const label = f.form.querySelector<HTMLElement>("[data-calendar-submit-label]")!;
        assert.equal(label.textContent, "Send");
        f.form.querySelector<HTMLButtonElement>('[data-recipient-chip] button')!.click();
        assert.equal(label.textContent, "Save");
        const entry = f.form.querySelector<HTMLInputElement>('[role="combobox"]')!;
        entry.value = "new@example.com";
        entry.dispatchEvent(new f.w.Event("input", { bubbles: true }));
        assert.equal(label.textContent, "Send");
        entry.value = "";
        entry.dispatchEvent(new f.w.Event("input", { bubbles: true }));
        assert.equal(label.textContent, "Save");
    } finally { f.dom.window.close(); }
    const internal = fixture(true);
    try {
        assert.equal(internal.form.querySelector("[data-calendar-submit-label]")!.textContent, "Send");
    } finally { internal.dom.window.close(); }
}

/** Reuse CRUD busy feedback and duplicate-submit protection, restoring controls after a failed save. */
function saveFeedback(): void {
    const f = fixture();
    try {
        const button = f.form.querySelector<HTMLButtonElement>("button[type=submit]")!;
        const xhr = { status: 422 };
        const detail = { elt: f.form, xhr, requestConfig: { verb: "post" } };
        f.form.dispatchEvent(new f.w.CustomEvent("htmx:beforeSend", { bubbles: true, detail }));
        assert.equal(button.disabled, true);
        assert.equal(button.getAttribute("aria-busy"), "true");
        assert.match(button.querySelector("i")!.className, /fa-spinner.*fa-spin/);
        const duplicate = new f.w.Event("submit", { bubbles: true, cancelable: true });
        f.form.dispatchEvent(duplicate);
        assert.equal(duplicate.defaultPrevented, true);
        f.form.dispatchEvent(new f.w.CustomEvent("htmx:afterRequest", { bubbles: true, detail }));
        assert.equal(button.disabled, false);
        assert.equal(button.hasAttribute("aria-busy"), false);
        assert.equal(button.querySelector("i")!.className, "fa fa-save");
    } finally { f.dom.window.close(); }
}

/** Refresh selected account IDs after a change and carry the composer token to availability. */
async function participantRefresh(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        f.form.querySelector<HTMLInputElement>('[name="attendee_users"]')!.value = '["u1","u2"]';
        f.form.dispatchEvent(new f.w.Event("change", { bubbles: true }));
        await new Promise<void>(function waitForDebounce(resolve: () => void): void { setTimeout(resolve, 220); });
        const last = f.requests.at(-1)!;
        assert.deepEqual(last.searchParams.getAll("users"), ["u1", "u2"]);
        assert.equal(last.searchParams.get("_permission_token"), "scoped-calendar-token");
        assert.equal(f.form.querySelectorAll("thead th").length, 3);
    } finally { f.dom.window.close(); }
}

test("participant changes select Save or Send", submitLabel);
test("calendar saves reuse CRUD spinner and duplicate-submit protection", saveFeedback);
test("participant changes refresh availability with the scoped token", participantRefresh);

/** Invalid participant input must cancel submission before the shared busy state begins. */
function invalidParticipant(): void {
    const f = fixture();
    try {
        f.form.querySelector<HTMLButtonElement>('[data-recipient-chip] button')!.click();
        f.form.querySelector<HTMLInputElement>('[role="combobox"]')!.value = "invalid-address";
        const event = new f.w.Event("submit", { bubbles: true, cancelable: true });
        f.form.dispatchEvent(event);
        assert.equal(event.defaultPrevented, true);
        assert.equal(f.form.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled, false);
        assert.equal(f.form.querySelector(".fa-spinner"), null);
    } finally { f.dom.window.close(); }
}

test("invalid participants do not lock the submit button", invalidParticipant);

/** The custom event form must never change shared modal padding for subsequent forms. */
function modalPaddingIsolation(): void {
    const f = fixture(false, true);
    try {
        const modal = f.w.document.getElementById("create-object-modal")!;
        const body = modal.querySelector<HTMLElement>("[data-modal-body]")!;
        assert.equal(modal.dataset.modalPadding, "p-3");
        assert.equal(f.w.getComputedStyle(body).paddingTop, "12px");
        f.form.remove();
        const regularForm = f.w.document.createElement("form");
        body.append(regularForm);
        assert.equal(modal.dataset.modalPadding, "p-3");
        assert.equal(f.w.getComputedStyle(body).paddingTop, "12px");
    } finally { f.dom.window.close(); }
}

test("calendar spacing does not leak into a normal add modal", modalPaddingIsolation);

/** The sidebar renders and emits a selected range even when no event form exists. */
async function standaloneAvailability(): Promise<void> {
    const f = fixture();
    try {
        const panel = f.form.querySelector<HTMLElement>('[bloomerp-component="calendar-availability"]')!;
        panel.remove();
        f.form.remove();
        f.w.document.body.append(panel);
        const component = f.w.ComposerFixture.getComponent(panel);
        component.setSelection({ users: ['u1'], day: '2026-10-15', timezone: 'Europe/Brussels', startTime: '10:00', endTime: '11:00', endDate: '2026-10-15', allDay: false });
        await settle();
        assert.equal(panel.querySelectorAll('tbody tr').length, 48);
        let range: unknown;
        /** Capture the standalone component's selected range without supplying form controls. */
        function captureSelection(event: Event): void { range = (event as CustomEvent).detail; }
        panel.addEventListener('bloomerp:availability-time-selected', captureSelection);
        panel.querySelector<HTMLButtonElement>('[data-availability-time="23:30"]')!.click();
        assert.equal(JSON.stringify(range), JSON.stringify({ startTime: '23:30', endTime: '00:30', endDate: '2026-10-16' }));
        assert.equal(f.w.document.querySelector('form'), null);
    } finally { f.dom.window.close(); }
}

test('availability sidebar works independently of an event form', standaloneAvailability);

/** Search through the real SDK and preserve explicitly selected account identities. */
async function userSuggestions(): Promise<void> {
    const f = fixture();
    try {
        f.w.fetch = async function searchUsers(input: RequestInfo | URL): Promise<Response> {
            const url = new URL(String(input));
            f.requests.push(url);
            return new Response(JSON.stringify(url.pathname === "/recipients/" ? {
                suggestions: [{ email: "john@example.com", label: "Users", user_id: "john", display_name: "John Doe" }],
            } : { users: [] }), { headers: { "Content-Type": "application/json" } });
        };
        const entry = f.form.querySelector<HTMLInputElement>('[role="combobox"]')!;
        entry.focus();
        entry.value = "John";
        entry.dispatchEvent(new f.w.InputEvent("input", { bubbles: true }));
        await new Promise<void>(function waitForSearch(resolve: () => void): void { setTimeout(resolve, 250); });
        const request = f.requests.find((url: URL): boolean => url.pathname === "/recipients/");
        assert.ok(request, "Participant search must reach the same-origin recipient endpoint");
        assert.equal(request.origin, "https://app.example");
        assert.equal(request.searchParams.get("q"), "John");
        assert.equal(request.searchParams.get("calendar_users"), "1");
        assert.equal(request.searchParams.get("_permission_token"), "scoped-calendar-token");
        const option = f.form.querySelector<HTMLElement>('[role="option"][data-user-id="john"]');
        assert.ok(option);
        assert.match(option.textContent!, /John Doe/);
        option.click();
        assert.deepEqual(JSON.parse(f.form.querySelector<HTMLInputElement>('[name="attendee_users"]')!.value), ["u1", "john"]);
    } finally { f.dom.window.close(); }
}

test("participant suggestions use a valid SDK URL and retain selected users", userSuggestions);
