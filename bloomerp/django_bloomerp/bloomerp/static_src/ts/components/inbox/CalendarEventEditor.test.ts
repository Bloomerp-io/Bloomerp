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
                import CalendarEventEditor from '${root}/ts/components/inbox/CalendarEventEditor';
                import { registerComponent, initComponents } from '${root}/ts/components/BaseComponent';
                registerComponent('calendar-event-editor', CalendarEventEditor);
                export { initComponents };
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
interface ComposerWindow extends DOMWindow { ComposerFixture: { initComponents(element: HTMLElement): void } }
interface Fixture { dom: JSDOM; w: ComposerWindow; requests: URL[]; form: HTMLFormElement }

/** Initialize a composer with real chip controls and a fake network boundary. */
function fixture(noEmail: boolean = false): Fixture {
    const dom = new JSDOM(`<!doctype html><form bloomerp-component="calendar-event-editor" data-availability-url="/events/create/" data-recipient-search-url="/recipients/?calendar_users=1">
        <input name="attendees" value="person@example.com"><input name="attendee_users" value='["u1"]' data-identities='{"person@example.com":"u1"}'>
        <input name="start_date" value="2026-10-15"><input name="end_date" value="2026-10-15">
        <input name="start_time" value="10:00"><input name="end_time" value="11:00">
        <input name="all_day" type="checkbox"><select name="event_timezone"><option>Europe/Brussels</option></select>
        <span data-availability-date></span><div data-availability-grid></div></form>`,
        { runScripts: "outside-only", pretendToBeVisual: true, url: "https://app.example/events/create/" });
    const w = dom.window as ComposerWindow;
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
async function settle(): Promise<void> { await new Promise<void>(function wait(resolve: () => void): void { setTimeout(resolve, 20); }); }

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
