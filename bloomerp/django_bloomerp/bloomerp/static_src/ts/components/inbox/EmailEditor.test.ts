/** Real-component email attachment, clipboard and lifecycle regressions with only network responses mocked. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import type { OutputAsset, OutputChunk } from "rollup";
import { JSDOM, VirtualConsole, type DOMWindow } from "jsdom";
import type { EmailEditor } from "./EmailEditor.ts";
import type { BloomerpTextEditor } from "../text_editor/BloomerpTextEditor.ts";
import type ReferenceAttachments from "../detail_view_components/ReferenceAttachments.ts";

const root = fileURLToPath(new URL("../../..", import.meta.url)).replace(/\/$/, "");
const entry = `${root}/email-test-entry.ts`;
const built = await build({ configFile: false, root, logLevel: "silent", resolve: { alias: { "@": `${root}/ts` } },
    plugins: [{ name: "email-test-entry",
        /** Resolve the virtual test entry. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the production registry and all email component boundaries together. */
        load(id: string): string | null { return id === entry ? `
            import { EmailEditor } from '${root}/ts/components/inbox/EmailEditor';
            import ReferenceAttachments from '${root}/ts/components/detail_view_components/ReferenceAttachments';
            import { BloomerpTextEditor } from '${root}/ts/components/text_editor/BloomerpTextEditor';
            import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
            import { PASTE_COMMAND, $getRoot } from 'lexical';
            registerComponent('email-editor', EmailEditor);
            registerComponent('reference-attachments', ReferenceAttachments);
            registerComponent('bloomerp-text-editor', BloomerpTextEditor);
            export { initComponents, getComponent, PASTE_COMMAND, $getRoot };
        ` : null; },
    }], build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "EmailFixture" } } });
const result = Array.isArray(built) ? built[0] : built;
assert("output" in result);
/** Select the executable browser bundle. */
const chunk = result.output.find((item: OutputAsset | OutputChunk): boolean => item.type === "chunk");
assert(chunk?.type === "chunk");
const code = chunk.code;
const existing = "44842d0a-22ac-4b60-b370-594155e2b99f";
const uploaded = "bd566adf-338d-4d15-b798-a9b162191bb8";
interface Browser extends DOMWindow { EmailFixture: { initComponents(element: HTMLElement): void; getComponent(element: HTMLElement): EmailEditor | BloomerpTextEditor | ReferenceAttachments; PASTE_COMMAND: unknown; $getRoot(): { selectEnd(): void } } }
interface Request { path: string; init: RequestInit; resolve(response: Response): void }
interface Fixture { dom: JSDOM; w: Browser; host: HTMLElement; form: HTMLFormElement; rich: BloomerpTextEditor; requests: Request[]; files: HTMLInputElement[]; alerts: string[]; errors: unknown[] }

/** Return a minimal JSON response at the network boundary. */
function response(data: unknown, status: number = 200): Response { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
/** Allow queued DOM and promise reactions to complete. */
async function settle(delay: number = 30): Promise<void> { await new Promise<void>((resolve: () => void): void => { setTimeout(resolve, delay); }); }

/** Initialize the actual editor, picker and composer with independently controllable requests. */
function fixture(reply: boolean = false, childFirst: boolean = false, holdDrafts: boolean = false): Fixture {
    const errors: unknown[] = [];
    const virtualConsole = new VirtualConsole();
    virtualConsole.on("jsdomError", (error: unknown): void => { errors.push(error); });
    virtualConsole.on("error", (...values: unknown[]): void => { errors.push(values); });
    const dom = new JSDOM(`<!doctype html><div bloomerp-component="email-editor" data-send-url="/send" ${reply ? "" : 'data-draft-user-id="4" data-template-url="/prepare-template"'}>
      <form><input name="csrfmiddlewaretoken" value="csrf"><input name="draft_id"><input name="to" value="recipient@example.com"><input name="subject" value="Original subject"><input name="email_account_id" value="account">
      <div bloomerp-component="bloomerp-text-editor" data-editor-id="body" data-include-toolbar="false" data-reference-upload-url="/upload" data-reference-serve-url="/api/files/serve/" data-reference-search-url="/references" data-template-search-url="/templates">
        <input name="body" data-text-editor-input="true" value="&lt;p&gt;Before&lt;/p&gt;&lt;p&gt;After&lt;/p&gt;"><div id="editor-body" contenteditable="true"></div>
      </div><div data-template-arguments></div><div data-email-preview hidden></div>
      <div bloomerp-component="reference-attachments" data-can-change="true" data-reference-upload-url="/upload" data-reference-search-url="/references" data-reference-preview-url="/preview/__file_id__">
        <input name="object_references" value="{}"><div data-reference-chips></div><div data-reference-files-group><span data-reference-files-count></span><div data-reference-file-list></div></div>
      </div><div data-reference-search-panel><input data-reference-search="file"><div data-reference-results></div><button type="button" data-reference-upload>Upload</button></div>
      <p data-email-status></p><button type="submit">Send</button></form></div><div id="bloomerp-general-use-drawer-body"></div>`, { url: "https://app.example.test/", pretendToBeVisual: true, runScripts: "outside-only", virtualConsole });
    const w = dom.window as Browser;
    Object.assign(w, { Headers, Response, Request, TextEncoder, TextDecoder, structuredClone, CSS: { escape: (value: string): string => value } });
    const original = w.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type to HTMX. */
    w.XPathExpression.prototype.evaluate = function evaluate(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult { return original.call(this, context, type, result); };
    w.Range.prototype.getBoundingClientRect = (): DOMRect => new w.DOMRect(0, 0, 20, 20);
    w.Range.prototype.getClientRects = (): DOMRectList => [] as unknown as DOMRectList;
    let preview = 0;
    w.URL.createObjectURL = (): string => `blob:https://app.example.test/${++preview}`;
    w.URL.revokeObjectURL = (_url: string): void => {};
    /** Model clipboard data without substituting any editor implementation. */
    class Clipboard extends w.Event {
        clipboardData: DataTransfer;
        constructor(html: string, files: File[]) {
            super("paste", { cancelable: true, bubbles: true });
            this.clipboardData = { files, items: files.map((file: File): object => ({ kind: "file", type: file.type })), types: ["text/html"], getData(type: string): string { return type === "text/html" ? html : ""; } } as unknown as DataTransfer;
        }
    }
    Object.defineProperty(w, "ClipboardEvent", { value: Clipboard });
    /** Supply the drag-event constructor used by Lexical's normal paste fallback. */
    class Drag extends w.Event {}
    Object.defineProperty(w, "DragEvent", { value: Drag });
    const requests: Request[] = [];
    /** Delay delivery and upload replies while completing ordinary searches and autosaves. */
    w.fetch = (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
        const path = new URL(String(input), w.location.href).pathname;
        return new Promise<Response>((resolve: (value: Response) => void): void => {
            requests.push({ path, init, resolve });
            if (path === "/references") resolve(response({ items: [{ kind: "file", target_id: existing, label: "Stored report.pdf" }] }));
            else if (path.includes("email_draft") && !holdDrafts) resolve(response({ id: "draft-one" }));
            else if (path === "/prepare-template") resolve(response({ body: "<p>Prepared</p>", form_html: "" }));
        });
    };
    const files: HTMLInputElement[] = [];
    const click = w.HTMLInputElement.prototype.click;
    /** Capture native file chooser inputs while leaving all other controls real. */
    w.HTMLInputElement.prototype.click = function clickInput(): void { if (this.type === "file") files.push(this); else click.call(this); };
    const alerts: string[] = [];
    w.alert = (message?: unknown): void => { alerts.push(String(message)); };
    w.eval(code);
    const host = w.document.querySelector<HTMLElement>('[bloomerp-component="email-editor"]')!;
    const richHost = host.querySelector<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]')!;
    if (childFirst) w.EmailFixture.initComponents(host.querySelector("form")!);
    w.EmailFixture.initComponents(host);
    return { dom, w, host, form: host.querySelector("form")!, rich: w.EmailFixture.getComponent(richHost) as BloomerpTextEditor, requests, files, alerts, errors };
}

/** Submit through the real event path, including duplicate-submit protection. */
function submit(f: Fixture): void { f.form.dispatchEvent(new f.w.Event("submit", { bubbles: true, cancelable: true })); }
/** Start an ordinary attachment upload through its actual picker button. */
function upload(f: Fixture): void {
    f.form.querySelector<HTMLButtonElement>("[data-reference-upload]")!.click();
    const input = f.files.at(-1)!;
    Object.defineProperty(input, "files", { configurable: true, value: [new f.w.File(["new"], "new.txt", { type: "text/plain" })] });
    input.dispatchEvent(new f.w.Event("change"));
}
/** Dispatch an actual Lexical clipboard command using the email-owned handler. */
function paste(f: Fixture, html: string = "", files: File[] = []): Event {
    const event = new f.w.ClipboardEvent(html, files);
    f.rich.editor!.update((): void => { f.w.EmailFixture.$getRoot().selectEnd(); f.rich.editor!.dispatchCommand(f.w.EmailFixture.PASTE_COMMAND as never, event as never); }, { discrete: true });
    return event;
}
/** Tear down through the real HTMX path and release the fixture browser. */
function close(f: Fixture): void { f.host.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.host } })); f.host.remove(); f.dom.window.close(); }

/** Exercise addition, deduplication, removal and attachment-only draft autosave. */
async function pickerDraft(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        const input = f.form.querySelector<HTMLInputElement>("[data-reference-search]")!;
        input.dispatchEvent(new f.w.FocusEvent("focusin", { bubbles: true })); await settle();
        f.form.querySelector<HTMLButtonElement>('[data-reference-results] [role="menuitem"]')!.click();
        input.dispatchEvent(new f.w.FocusEvent("focusin", { bubbles: true })); await settle();
        f.form.querySelector<HTMLButtonElement>('[data-reference-results] [role="menuitem"]')!.click(); await settle(750);
        const selection = JSON.parse((f.form.elements.namedItem("object_references") as HTMLInputElement).value);
        assert.equal(selection.manual.length, 1);
        const draft = f.requests.find((request: Request): boolean => request.path.includes("email_draft"))!;
        assert.equal(JSON.parse(JSON.parse(String(draft.init.body)).payload.object_references).manual[0].target_id, existing);
        f.form.querySelector<HTMLButtonElement>("[data-reference-remove]")!.click(); await settle(750);
        assert.equal(JSON.parse((f.form.elements.namedItem("object_references") as HTMLInputElement).value).manual.length, 0);
        assert.equal(f.requests.filter((request: Request): boolean => request.init.method === "DELETE").length, 0);
        assert.deepEqual(f.errors, []);
    } finally { close(f); }
}
test("shared picker deduplicates selections, preserves removal and saves attachment-only edits", pickerDraft);

/** Keep Send disabled until every inline and ordinary upload is included in the form. */
async function concurrentUploads(): Promise<void> {
    const f = fixture();
    try {
        await settle(); upload(f);
        paste(f, "", [new f.w.File(["png"], "clipboard.png", { type: "image/png" })]);
        const pending = f.requests.filter((request: Request): boolean => request.path === "/upload");
        assert.equal(pending.length, 2); submit(f); assert.equal(f.requests.some((request: Request): boolean => request.path === "/send"), false);
        pending[0].resolve(response({ file_id: existing, name: "new.txt" })); await settle();
        assert.equal(f.form.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled, true);
        pending[1].resolve(response({ file_id: uploaded, name: "clipboard.png" })); await settle();
        assert.equal(f.form.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled, false);
        submit(f); await settle();
        const send = f.requests.find((request: Request): boolean => request.path === "/send")!;
        const data = send.init.body as FormData;
        assert.match(String(data.get("body")), new RegExp(uploaded));
        assert.equal(JSON.parse(String(data.get("object_references"))).manual[0].target_id, existing);
        assert.deepEqual(f.errors, []);
        send.resolve(response({ message: "Sent" })); await settle();
    } finally { close(f); }
}
test("concurrent pasted-image and attachment uploads all finish before sending", concurrentUploads);

/** Preserve all user input on provider failure and send once on retry. */
async function failedSend(): Promise<void> {
    const f = fixture(true);
    try {
        await settle(); submit(f); submit(f); await settle();
        const sent = f.requests.filter((request: Request): boolean => request.path === "/send"); assert.equal(sent.length, 1);
        sent[0].resolve(response({ errors: ["Try again"] }, 400)); await settle();
        assert.equal(f.form.hidden, false); assert.equal((f.form.elements.namedItem("subject") as HTMLInputElement).value, "Original subject");
        assert.match(f.rich.getValue(), /Before/); assert.match(f.host.textContent!, /Try again/);
        submit(f); await settle(); assert.equal(f.requests.filter((request: Request): boolean => request.path === "/send").length, 2);
        assert.equal(f.requests.some((request: Request): boolean => request.path.includes("email_draft")), false);
        f.requests.at(-1)!.resolve(response({ message: "Sent" })); await settle(); assert.equal(f.form.hidden, true);
    } finally { close(f); }
}
test("reply JSON send retains inputs on failure, blocks duplicates and permits retry", failedSend);

/** Preserve paragraphs and sizing around pasted embedded HTML images. */
async function embeddedHtml(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        paste(f, '<p>Left</p><img src="data:image/png;base64,cG5n" alt="Important chart" style="width:130px"><p>Right</p>');
        const pending = f.requests.find((request: Request): boolean => request.path === "/upload")!; assert(pending);
        pending.resolve(response({ file_id: uploaded, name: "pasted-image.png" })); await settle();
        const body = f.rich.getValue(); assert(body.indexOf("Left") < body.indexOf(uploaded)); assert(body.indexOf(uploaded) < body.indexOf("Right")); assert.match(body, /width:130px/); assert.match(body, /Important chart/);
        assert.equal(f.requests.every((request: Request): boolean => request.path === "/upload" || request.path.includes("email_draft")), true);
    } finally { close(f); }
}
test("pasted data-image HTML is stored and retains its position between paragraphs", embeddedHtml);

for (const childFirst of [false, true]) {
    for (const failed of [false, true]) {
        test(`HTMX cleanup aborts ${failed ? "failed" : "successful"} late uploads (${childFirst ? "child" : "root"}-first)`, async (): Promise<void> => {
            const f = fixture(false, childFirst); await settle(); upload(f);
            const pending = f.requests.find((request: Request): boolean => request.path === "/upload")!;
            f.host.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.host } })); f.host.remove();
            const snapshot = f.host.innerHTML;
            assert.equal(pending.init.signal?.aborted, true);
            pending.resolve(response(failed ? {} : { file_id: uploaded, name: "late.txt" }, failed ? 400 : 200)); await settle();
            assert.equal(f.host.innerHTML, snapshot); assert.deepEqual(f.alerts, []); assert.equal(f.requests.length, 1); f.dom.window.close();
        });
    }
}

for (const reply of [false, true]) {
    test(`${reply ? "reply" : "enhanced"} template selection retains its existing event ownership`, async (): Promise<void> => {
        const f = fixture(reply);
        try {
            await settle(); let inserted = "";
            const event = new f.w.CustomEvent("bloomerp:template-selected", { bubbles: true, cancelable: true, detail: { template: { id: "t", name: "Template", body: "raw" }, insert(body: string): void { inserted = body; } } });
            f.form.dispatchEvent(event); await settle();
            assert.equal(event.defaultPrevented, !reply);
            assert.equal(f.requests.some((request: Request): boolean => request.path === "/prepare-template"), !reply);
            assert.equal(inserted, reply ? "" : "<p>Prepared</p>");
        } finally { close(f); }
    });
}

/** Preserve rich HTML when clipboard file/image counts cannot be matched safely. */
async function mixedClipboard(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        paste(f, '<p>Keep this pasted text</p><img src="https://external.example/one.png"><img src="https://external.example/two.png"><p>Keep this too</p>', [new f.w.File(["png"], "clipboard.png", { type: "image/png" })]);
        await settle();
        const body = f.rich.getValue(); assert.match(body, /Keep this pasted text/); assert.match(body, /Keep this too/);
        assert.match(body, /external.example\/one.png/); assert.match(body, /external.example\/two.png/);
        assert.equal(f.requests.some((request: Request): boolean => request.path === "/upload"), false);
    } finally { close(f); }
}
test("mismatched clipboard representations preserve all pasted text and HTML", mixedClipboard);

/** Keep a failed image visible and allow removal before a later upload resolves. */
async function imageUploadFailuresAndRemoval(): Promise<void> {
    const f = fixture(true);
    try {
        await settle(); paste(f, "", [new f.w.File(["png"], "failed.png", { type: "image/png" })]);
        f.requests.at(-1)!.resolve(response({ errors: ["Upload failed"] }, 400)); await settle();
        assert.match(f.rich.getValue(), /blob:/);
        assert.match(f.host.textContent!, /Email operation failed/);
        assert.equal(f.form.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled, false);
        paste(f, "", [new f.w.File(["png"], "removed.png", { type: "image/png" })]);
        const pending = f.requests.at(-1)!;
        f.rich.setValue("<p>Keep my replacement text</p>", true); await settle();
        pending.resolve(response({ file_id: uploaded, name: "removed.png" })); await settle();
        assert.match(f.rich.getValue(), /Keep my replacement text/);
        assert.doesNotMatch(f.rich.getValue(), /<img|blob:|data-target-id/);
        assert.deepEqual(f.errors, []);
    } finally { close(f); }
}
test("failed pasted uploads retain an editable placeholder and removed images never reappear", imageUploadFailuresAndRemoval);

/** Abort email-owned image work before a detached editor receives its result. */
async function pastedImageCleanup(): Promise<void> {
    const f = fixture(true); await settle();
    paste(f, "", [new f.w.File(["png"], "clipboard.png", { type: "image/png" })]);
    const pending = f.requests.at(-1)!;
    f.host.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.host } })); f.host.remove();
    const snapshot = f.host.innerHTML;
    assert.equal(pending.init.signal?.aborted, true);
    pending.resolve(response({ file_id: uploaded, name: "late.png" })); await settle();
    assert.equal(f.host.innerHTML, snapshot); assert.deepEqual(f.errors, []); f.dom.window.close();
}
test("HTMX cleanup cancels pasted-image uploads before late replacement", pastedImageCleanup);

/** Reject unsupported or malformed clipboard data without losing existing editor content. */
async function invalidClipboardImages(): Promise<void> {
    const f = fixture(true);
    try {
        await settle();
        paste(f, '<p>Invalid</p><img src="data:image/svg+xml;base64,PHN2Zz4=">');
        assert.match(f.host.textContent!, /supported image/);
        assert.match(f.rich.getValue(), /Before/);
        assert.equal(f.requests.length, 0);
        paste(f, "", [new f.w.File(["avif"], "unsupported.avif", { type: "image/avif" })]);
        assert.match(f.host.textContent!, /PNG, JPEG, GIF or WebP/);
        assert.equal(f.requests.length, 0); assert.deepEqual(f.errors, []);
    } finally { close(f); }
}
test("invalid clipboard images do not upload or discard existing content", invalidClipboardImages);

/** Save the latest body even when an earlier autosave outlives HTMX cleanup. */
async function pendingAutosaveCleanup(): Promise<void> {
    const f = fixture(false, false, true); await settle();
    const subject = f.form.elements.namedItem("subject") as HTMLInputElement;
    subject.value = "First snapshot"; subject.dispatchEvent(new f.w.Event("input", { bubbles: true })); await settle(750);
    const first = f.requests.find((request: Request): boolean => request.path.includes("email_draft"))!; assert(first);
    f.rich.setValue("<p>Latest edited body</p>", true); await settle();
    f.host.dispatchEvent(new f.w.CustomEvent("htmx:beforeCleanupElement", { bubbles: true, detail: { elt: f.host } })); f.host.remove();
    first.resolve(response({ id: "draft-one" })); await settle();
    const drafts = f.requests.filter((request: Request): boolean => request.path.includes("email_draft"));
    assert.equal(drafts.length, 2);
    assert.match(JSON.parse(String(drafts[1].init.body)).payload.body, /Latest edited body/);
    drafts[1].resolve(response({ id: "draft-one" })); await settle(); assert.deepEqual(f.errors, []); f.dom.window.close();
}
test("cleanup preserves queued edits behind an in-flight draft save", pendingAutosaveCleanup);
