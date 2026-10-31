/** Exercise recipient-dependent delivery and rich-text hints with production components. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import type { OutputAsset, OutputChunk } from "rollup";
import { JSDOM, type DOMWindow } from "jsdom";
import type { BloomerpTextEditor } from "../text_editor/BloomerpTextEditor.ts";

const root = fileURLToPath(new URL("../../..", import.meta.url)).replace(/\/$/, "");
const entry = `${root}/signature-request-test-entry.ts`;
const built = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": `${root}/ts` } },
    plugins: [{
        name: "signature-request-test",
        /** Resolve the virtual entry without generating a production file. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the real recipient picker, composer, editor, and shared registry. */
        load(id: string): string | null {
            return id === entry ? `
                import SendSignatureRequest from '${root}/ts/components/document_signing/SendSignatureRequest';
                import { BloomerpTextEditor } from '${root}/ts/components/text_editor/BloomerpTextEditor';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('bloomerp:send-signature-request', SendSignatureRequest);
                registerComponent('bloomerp-text-editor', BloomerpTextEditor);
                export { initComponents, getComponent };
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "SigningFixture" } },
});
const output = Array.isArray(built) ? built[0] : built;
assert("output" in output);
/** Select the executable browser bundle. */
const chunk = output.output.find((item: OutputAsset | OutputChunk): boolean => item.type === "chunk");
assert(chunk?.type === "chunk");
const code = chunk.code;

interface SigningWindow extends DOMWindow {
    SigningFixture: { initComponents(element: HTMLElement): void; getComponent(element: HTMLElement): BloomerpTextEditor };
}
interface Fixture {
    dom: JSDOM;
    w: SigningWindow;
    form: HTMLFormElement;
    checkbox: HTMLInputElement;
    rows: HTMLElement[];
    rich: BloomerpTextEditor;
}

/** Mount independent role pickers with one explicitly selected internal account. */
function fixture(): Fixture {
    const dom = new JSDOM(`<!doctype html><form id="send-signature" bloomerp-component="bloomerp:send-signature-request" data-recipient-search-url="/recipients?calendar_users=1">
        <div data-signature-recipient><label for="role-one">First role</label>
          <input id="role-one" data-recipient-input name="recipient_one" value="person@example.com">
          <input type="hidden" data-recipient-users name="recipient_users_one" value='["u1"]' data-identities='{"person@example.com":"u1"}'>
        </div>
        <div data-signature-recipient><input id="role-two" data-recipient-input name="recipient_two">
          <input type="hidden" data-recipient-users name="recipient_users_two" value="[]"></div>
        <input type="checkbox" data-send-email name="send_email" checked>
        <input type="hidden" data-send-email-value name="send_email" value="on" disabled>
        <p data-email-required hidden>Required for external recipients</p>
        <div data-email-options><select data-email-sender name="sender"><option value="">Choose</option><option value="sender">Sender</option></select></div>
        <input name="valid_until">
        <div data-email-content><span id="send-signature-content-label">Email content</span>
          <div bloomerp-component="bloomerp-text-editor" data-editor-id="message" data-include-toolbar="false" data-placeholder="Write a message…">
            <input name="content" data-text-editor-input="true" value=""><div id="editor-message" contenteditable="true"></div>
          </div>
        </div></form>`, { runScripts: "outside-only", pretendToBeVisual: true, url: "https://app.example.test/" });
    const w = dom.window as SigningWindow;
    Object.assign(w, { Headers, Request, Response, TextEncoder, TextDecoder, structuredClone, CSS: { escape: String } });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Match the default XPath result type used by browsers and HTMX. */
    w.XPathExpression.prototype.evaluate = function evaluateDefault(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, result);
    };
    /** Return an explicit internal-user suggestion at the network boundary. */
    w.fetch = async function suggestions(): Promise<Response> {
        return new Response(JSON.stringify({ suggestions: [{ email: "colleague@example.com", user_id: "u2", label: "Users", display_name: "Colleague" }] }), { headers: { "Content-Type": "application/json" } });
    };
    w.eval(code);
    w.SigningFixture.initComponents(w.document.body);
    return {
        dom, w, form: w.document.querySelector("form")!, checkbox: w.document.querySelector("[data-send-email]")!,
        rows: Array.from(w.document.querySelectorAll("[data-signature-recipient]")),
        rich: w.SigningFixture.getComponent(w.document.querySelector('[bloomerp-component="bloomerp-text-editor"]')!),
    };
}

/** Allow the production recipient debounce and pending browser updates to complete. */
async function settle(delay: number = 30): Promise<void> {
    await new Promise<void>(function wait(resolve: () => void): void { setTimeout(resolve, delay); });
}

/** Tear down through the same HTMX event used when closing the modal. */
function close(f: Fixture): void {
    f.form.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.form } }));
    f.rich.destroy();
    f.dom.window.close();
}

/** Type through the shared picker so unfinished external addresses affect delivery immediately. */
function typeRecipient(f: Fixture, row: number, value: string): HTMLInputElement {
    const entry = f.rows[row].querySelector<HTMLInputElement>('[role="combobox"]')!;
    entry.value = value;
    entry.dispatchEvent(new f.w.Event("input", { bubbles: true }));
    return entry;
}

/** Mixed recipients force email and retain the internal-only choice when the external one is removed. */
function mixedRecipients(): void {
    const f = fixture();
    try {
        assert.equal(f.checkbox.disabled, false);
        f.checkbox.click();
        assert.equal(f.checkbox.checked, false);
        const content = f.form.querySelector<HTMLElement>("[data-email-content]")!;
        assert.equal(content.hidden, true);
        const entry = typeRecipient(f, 1, "external@example.com");
        assert.equal(f.checkbox.checked, true);
        assert.equal(f.checkbox.disabled, true);
        assert.equal(content.hidden, false);
        assert.deepEqual(new f.w.FormData(f.form).getAll("send_email"), ["on"]);
        entry.dispatchEvent(new f.w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
        f.rows[1].querySelector<HTMLButtonElement>("[data-recipient-chip] button")!.click();
        assert.equal(f.checkbox.disabled, false);
        assert.equal(f.checkbox.checked, false);
        assert.equal(content.hidden, true);
        assert.equal(f.form.querySelector<HTMLSelectElement>("[data-email-sender]")!.required, false);
        assert.equal(new f.w.FormData(f.form).has("send_email"), false);
    } finally { close(f); }
}

/** Explicit internal selection stays optional; retyping its mailbox does not inherit that identity. */
async function explicitInternalSelection(): Promise<void> {
    const f = fixture();
    try {
        f.checkbox.click();
        const entry = typeRecipient(f, 1, "colleague");
        entry.focus();
        await settle(260);
        f.rows[1].querySelector<HTMLElement>('[role="option"]')!.click();
        assert.equal(f.checkbox.disabled, false);
        assert.equal(f.checkbox.checked, false);
        assert.equal(f.rows[1].querySelector<HTMLInputElement>("[data-recipient-users]")!.value, '["u2"]');
        f.rows[1].querySelector<HTMLButtonElement>("[data-recipient-chip] button")!.click();
        typeRecipient(f, 1, "colleague@example.com");
        entry.dispatchEvent(new f.w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
        assert.equal(f.checkbox.disabled, true);
        assert.equal(f.checkbox.checked, true);
        assert.equal(f.rows[1].querySelector<HTMLInputElement>("[data-recipient-users]")!.value, "[]");
    } finally { close(f); }
}

/** Email hints follow document content without becoming saved HTML or covering media-only messages. */
async function editorPlaceholder(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        const root = f.rich.editor!.getRootElement()!;
        assert.equal(root.dataset.empty, "true");
        assert.equal(root.getAttribute("aria-placeholder"), "Write a message…");
        assert.doesNotMatch(f.rich.getValue(), /Write a message/);
        f.rich.setValue("<p>Hello</p>", true);
        await settle();
        assert.equal(root.dataset.empty, "false");
        f.rich.setValue('<p><img src="https://app.example.test/image.png" alt="Attachment"></p>', true);
        await settle();
        assert.equal(root.dataset.empty, "false");
        f.rich.setValue("", true);
        await settle();
        assert.equal(root.dataset.empty, "true");
        assert.doesNotMatch(f.rich.getValue(), /data-placeholder|Write a message/);
    } finally { close(f); }
}

/** Modal cleanup removes preference listeners and permits an independent replacement composer. */
function cleanup(): void {
    const f = fixture();
    try {
        f.form.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.form } }));
        f.checkbox.click();
        assert.equal(f.form.querySelector<HTMLElement>("[data-email-content]")!.hidden, false);
    } finally { close(f); }
}

test("mixed recipients require email and preserve the internal-only preference", mixedRecipients);
test("only an explicit user selection makes a recipient internal", explicitInternalSelection);
test("the empty editor hint never covers content or leaks into saved HTML", editorPlaceholder);
test("HTMX cleanup releases recipient and delivery listeners", cleanup);
