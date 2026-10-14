/** Exercise CRUD Save feedback through the real components and HTMX request lifecycle. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';
import type ObjectCRUDViewContainer from './ObjectCRUDViewContainer.ts';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/crud-save-regression-entry.ts`;
const built = await build({
    configFile: false, root, logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    plugins: [{
        name: 'crud-save-regression-entry',
        /** Resolve the in-memory entry without adding a production export. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the real container, toast and HTMX with their shared registry. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                import htmx from 'htmx.org';
                import ObjectCRUDViewContainer from '${root}/ts/components/detail_view_components/ObjectCRUDViewContainer';
                import UiMessage from '${root}/ts/components/UiMessage';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('object-crud-view-container', ObjectCRUDViewContainer);
                registerComponent('ui-message', UiMessage);
                export { htmx, initComponents, getComponent };
            `;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'CrudFixture' } },
});
const bundle = Array.isArray(built) ? built[0] : built;
assert('output' in bundle);
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface Request {
    status: number;
    body: Document | XMLHttpRequestBodyInit | null;
    complete(status: number): void;
    fail(kind: 'error' | 'abort' | 'timeout'): void;
}
interface FixtureWindow extends DOMWindow {
    CrudFixture: {
        htmx: typeof import('htmx.org').default;
        initComponents(element: HTMLElement): void;
        getComponent(element: HTMLElement): ObjectCRUDViewContainer;
    };
}
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    form: HTMLFormElement;
    container: ObjectCRUDViewContainer;
    save: HTMLButtonElement;
    next: HTMLButtonElement;
    requests: Request[];
}

/** Build a real-component form using deterministic, in-memory XHR replies. */
async function fixture(): Promise<Fixture> {
    const dom = new JSDOM(`<!doctype html><body><form hx-post="/save" hx-swap="none">
        <div bloomerp-component="object-crud-view-container">
            <div data-layout-root><div data-layout-row data-row-columns="1"><div data-layout-grid></div></div></div>
            <input name="title" value="Unsaved title" required>
            <div id="object-crud-container-buttons">
                <button type="submit" id="object-crud-container-save-button"><i class="fa fa-save"></i>Save</button>
                <button type="submit" name="next" value="/create" id="object-crud-container-save-and-create-new-button"><i class="fa fa-plus"></i>Save and Create New</button>
            </div>
            <button type="button" id="field" hx-post="/field" hx-swap="none">Field action</button>
        </div></form></body>`, {
        url: 'https://fixture.test', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: new VirtualConsole(),
    });
    const w = dom.window as FixtureWindow;
    const requests: Request[] = [];
    /** Replace only transport, retaining HTMX validation, serialization, queuing and events. */
    class LocalRequest extends w.EventTarget implements Request {
        status = 0;
        response = '';
        responseURL = 'https://fixture.test/save';
        readyState = 1;
        upload = new w.EventTarget();
        body: Document | XMLHttpRequestBodyInit | null = null;
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        onabort: (() => void) | null = null;
        ontimeout: (() => void) | null = null;
        /** Capture the requested URL without opening a socket. */
        open(_method: string, url: string): void { this.responseURL = new URL(url, w.location.href).href; }
        /** Accept headers without transport serialization. */
        setRequestHeader(_name: string, _value: string): void {}
        /** Preserve HTMX's normal content-type setup. */
        overrideMimeType(_type: string): void {}
        /** Supply an empty response-header set. */
        getAllResponseHeaders(): string { return ''; }
        /** Supply no redirect, trigger or swap overrides. */
        getResponseHeader(_name: string): string | null { return null; }
        /** Hold the serialized request until a test releases it. */
        send(body: Document | XMLHttpRequestBodyInit | null): void { this.body = body; requests.push(this); }
        /** Complete a request through HTMX's real response handler. */
        complete(status: number): void { this.status = status; this.readyState = 4; this.onload?.(); }
        /** Invoke the terminal callbacks for transport failure or cancellation. */
        fail(kind: 'error' | 'abort' | 'timeout'): void { this.readyState = 4; this[`on${kind}`]?.(); }
        /** Support HTMX's own abort command. */
        abort(): void { this.fail('abort'); }
    }
    Object.assign(w, { XMLHttpRequest: LocalRequest, structuredClone });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type for JSDOM. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, result?: XPathResult | null): XPathResult {
        return evaluate.call(this, context, type ?? 0, result ?? null);
    };
    w.eval(scriptCode);
    await new Promise<void>(function ready(resolve: () => void): void { w.setTimeout(resolve, 0); });
    const form = w.document.querySelector('form')!;
    const element = form.firstElementChild as HTMLElement;
    w.CrudFixture.initComponents(element);
    w.CrudFixture.htmx.process(form);
    return { dom, w, form, requests, container: w.CrudFixture.getComponent(element),
        save: form.querySelector('#object-crud-container-save-button')!,
        next: form.querySelector('#object-crud-container-save-and-create-new-button')! };
}

/** Assert the visible and accessible pending state of a Save button. */
function assertSaving(button: HTMLButtonElement, saving: boolean): void {
    assert.equal(button.disabled, saving);
    assert.equal(button.getAttribute('aria-busy'), saving ? 'true' : null);
    assert.equal(button.querySelector('.fa-spinner.fa-spin') !== null, saving);
}

/** Close each fixture's timers and document listeners. */
function close(f: Fixture): void { f.container.destroy(); f.dom.window.close(); }

test('both save variants spin and block repeat submits without losing next', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.next.click();
        assert.equal(f.requests.length, 1);
        assert.match(String(f.requests[0].body), /next=%2Fcreate/);
        assertSaving(f.save, true);
        assertSaving(f.next, true);
        assert.equal(f.save.textContent, 'Save');
        f.save.click();
        f.form.requestSubmit();
        f.form.requestSubmit();
        assert.equal(f.requests.length, 1);
        f.requests[0].complete(204);
        assertSaving(f.save, false);
        assertSaving(f.next, false);
        assert.equal(f.requests.length, 1, 'no duplicate submit was queued');
        f.save.click();
        assert.equal(f.requests.length, 2);
        f.requests[1].complete(204);
        assertSaving(f.save, false);
    } finally { close(f); }
});

test('HTTP 500 shows one safe toast, preserves edits and allows a valid retry', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.save.click();
        f.requests[0].complete(500);
        assertSaving(f.save, false);
        assert.equal(f.form.querySelector('input')!.value, 'Unsaved title');
        assert.equal(f.w.document.querySelectorAll('.message-container.alert-danger').length, 1);
        assert.match(f.w.document.querySelector('.message-container')!.textContent!, /Unable to save changes/);
        f.form.dispatchEvent(new f.w.CustomEvent('htmx:afterRequest', { detail: { xhr: f.requests[0] } }));
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 1);
        f.save.click();
        f.requests[1].complete(204);
        assertSaving(f.save, false);
    } finally { close(f); }
});

test('validation and cancelled requests never enter a saving state', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.form.querySelector('input')!.value = '';
        f.save.click();
        assert.equal(f.requests.length, 0);
        assertSaving(f.save, false);
        f.form.querySelector('input')!.value = 'Valid';
        /** Cancel after the component's before-request handler, as other listeners can. */
        function cancel(event: Event): void { event.preventDefault(); }
        f.form.addEventListener('htmx:beforeRequest', cancel);
        f.save.click();
        assert.equal(f.requests.length, 0);
        assertSaving(f.save, false);
        f.form.removeEventListener('htmx:beforeRequest', cancel);
        f.save.click();
        assert.equal(f.requests.length, 1);
    } finally { close(f); }
});

test('nested field requests and stale completions do not change Save feedback', async (): Promise<void> => {
    const f = await fixture();
    try {
        (f.form.querySelector('#field') as HTMLButtonElement).click();
        assert.equal(f.requests.length, 1);
        assertSaving(f.save, false);
        f.save.click();
        assert.equal(f.requests.length, 2);
        f.requests[0].complete(500);
        assertSaving(f.save, true);
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 0);
        f.requests[1].complete(204);
        f.save.click();
        f.form.dispatchEvent(new f.w.CustomEvent('htmx:afterRequest', { detail: { xhr: f.requests[1] } }));
        assertSaving(f.save, true);
        f.requests[2].complete(204);
    } finally { close(f); }
});

for (const kind of ['error', 'abort', 'timeout'] as const) {
    test(`${kind} restores controls and permits retry`, async (): Promise<void> => {
        const f = await fixture();
        try {
            f.save.click();
            f.requests[0].fail(kind);
            assertSaving(f.save, false);
            assert.equal(f.w.document.querySelectorAll('.message-container').length, 0);
            f.save.click();
            assert.equal(f.requests.length, 2);
            f.requests[1].complete(204);
        } finally { close(f); }
    });
}

test('navigation cleanup restores old controls and suppresses late error toasts', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.save.click();
        f.form.dispatchEvent(new f.w.CustomEvent('htmx:beforeCleanupElement', { detail: { elt: f.form } }));
        f.form.remove();
        f.requests[0].complete(500);
        assertSaving(f.save, false);
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 0);
    } finally { close(f); }
});

test('history snapshots exclude pending feedback while the live request stays blocked', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.save.click();
        f.w.document.body.dispatchEvent(new f.w.CustomEvent('htmx:beforeHistorySave'));
        const snapshot = f.form.cloneNode(true) as HTMLFormElement;
        assertSaving(snapshot.querySelector('#object-crud-container-save-button')!, false);
        f.form.requestSubmit();
        assert.equal(f.requests.length, 1);
        await Promise.resolve();
        assertSaving(f.save, true);
        f.requests[0].complete(204);
        assertSaving(f.save, false);
    } finally { close(f); }
});

test('preexisting disabled and accessible button state is restored exactly', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.next.disabled = true;
        f.next.setAttribute('aria-busy', 'false');
        f.save.click();
        f.requests[0].complete(422);
        assertSaving(f.save, false);
        assert.equal(f.next.disabled, true);
        assert.equal(f.next.getAttribute('aria-busy'), 'false');
        assert.equal(f.next.querySelector('i')!.className, 'fa fa-plus');
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 0);
    } finally { close(f); }
});

test('two live CRUD forms keep request state and error feedback independent', async (): Promise<void> => {
    const f = await fixture();
    let otherContainer: ObjectCRUDViewContainer | null = null;
    try {
        const otherForm = f.form.cloneNode(true) as HTMLFormElement;
        f.w.document.body.append(otherForm);
        f.w.CrudFixture.initComponents(otherForm);
        f.w.CrudFixture.htmx.process(otherForm);
        otherContainer = f.w.CrudFixture.getComponent(otherForm.firstElementChild as HTMLElement);
        const otherSave = otherForm.querySelector<HTMLButtonElement>('#object-crud-container-save-button')!;
        f.save.click();
        assertSaving(f.save, true);
        assertSaving(otherSave, false);
        otherSave.click();
        assert.equal(f.requests.length, 2);
        f.requests[0].complete(500);
        assertSaving(f.save, false);
        assertSaving(otherSave, true);
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 1);
        f.requests[1].complete(204);
        assertSaving(otherSave, false);
    } finally { otherContainer?.destroy(); close(f); }
});

test('a detached request cannot notify or unlock the replacement form', async (): Promise<void> => {
    const f = await fixture();
    let replacement: ObjectCRUDViewContainer | null = null;
    try {
        const newForm = f.form.cloneNode(true) as HTMLFormElement;
        f.save.click();
        f.form.replaceWith(newForm);
        f.w.CrudFixture.initComponents(newForm);
        f.w.CrudFixture.htmx.process(newForm);
        replacement = f.w.CrudFixture.getComponent(newForm.firstElementChild as HTMLElement);
        const newSave = newForm.querySelector<HTMLButtonElement>('#object-crud-container-save-button')!;
        newSave.click();
        assert.equal(f.requests.length, 2);
        f.requests[0].complete(500);
        assertSaving(newSave, true);
        assert.equal(f.w.document.querySelectorAll('.message-container').length, 0);
        f.requests[1].complete(204);
        assertSaving(newSave, false);
    } finally { replacement?.destroy(); close(f); }
});

test('successful HTMX form replacement restores detached Save controls', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.form.setAttribute('hx-swap', 'outerHTML');
        f.w.CrudFixture.htmx.process(f.form);
        f.save.click();
        assertSaving(f.save, true);
        f.requests[0].complete(200);
        assert.equal(f.form.isConnected, false);
        assertSaving(f.save, false);
        assertSaving(f.next, false);
    } finally { close(f); }
});

test('HTMX response-handler failure restores controls and permits retry', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.save.click();
        const request = f.requests[0] as Request & { getAllResponseHeaders(): string };
        /** Force HTMX's real onLoadError path during response handling. */
        request.getAllResponseHeaders = function failResponseHeaders(): string {
            throw new Error('simulated response handling failure');
        };
        assert.throws(
            (): void => request.complete(200),
            /simulated response handling failure/,
        );
        assertSaving(f.save, false);
        assertSaving(f.next, false);
        f.save.click();
        assert.equal(f.requests.length, 2);
        f.requests[1].complete(204);
        assertSaving(f.save, false);
    } finally { close(f); }
});
