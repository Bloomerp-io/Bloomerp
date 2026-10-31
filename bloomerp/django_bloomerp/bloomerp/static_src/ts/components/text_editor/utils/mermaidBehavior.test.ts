/** Exercise Mermaid dialogs with the production code widget, Ace, and Lexical lifecycle. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { JSDOM, type DOMWindow } from "jsdom";
import type { Ace } from "ace-builds";
import type { LexicalEditor } from "lexical";
import type CodeEditorWidget from "../../widgets/CodeEditorWidget";
import type BaseComponent from "../../BaseComponent";

const root = fileURLToPath(new URL("../../../..", import.meta.url)).replace(/\/$/, "");
const entry = `${root}/mermaid-widget-fixture.ts`;
const result = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": `${root}/ts` } },
    plugins: [{
        name: "mermaid-widget-fixture",
        /** Resolve the in-memory entry without creating production files. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Keep editor and dialog behavior real while avoiding SVG layout in jsdom. */
        load(id: string): string | null {
            if (id === `${root}/ts/utils/mermaid.ts`) return `
                /** Return a deterministic preview without requiring browser SVG geometry. */
                export async function renderMermaid(source: string): Promise<string> {
                    if (source === 'invalid') throw new Error('Invalid Mermaid source');
                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.textContent = source;
                    svg.append(text);
                    return svg.outerHTML;
                }
            `;
            return id === entry ? `
                import ace from 'ace-builds/src-noconflict/ace';
                import CodeEditorWidget from '${root}/ts/components/widgets/CodeEditorWidget';
                import { Modal } from '${root}/ts/components/Modal';
                import { registerComponent, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('code-editor-widget', CodeEditorWidget);
                registerComponent('modal', Modal);
                /** Expose the same Ace instance owned by the production code widget. */
                export function sourceEditor(container: HTMLElement): import('ace-builds').Ace.Editor {
                    return ace.edit(container);
                }
                export { getComponent };
                export * from 'lexical';
                export * from '@lexical/html';
                export * from '${root}/ts/components/text_editor/nodes/MermaidNode';
                export * from '${root}/ts/components/text_editor/utils/mermaidBehavior';
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "MermaidWidgetFixture" } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert("output" in bundle);
/** Select the executable containing the actual code editor and modal. */
function isScript(item: import("rollup").OutputAsset | import("rollup").OutputChunk): item is import("rollup").OutputChunk {
    return item.type === "chunk";
}
const script = bundle.output.find(isScript)!;
type API = typeof import("lexical") & typeof import("@lexical/html") & typeof import("../nodes/MermaidNode")
    & typeof import("./mermaidBehavior") & {
        sourceEditor(container: HTMLElement): Ace.Editor;
        getComponent(element: HTMLElement): BaseComponent;
    };
interface FixtureWindow extends DOMWindow { MermaidWidgetFixture: API; }
type Fixture = { dom: JSDOM; w: FixtureWindow; api: API; editor: LexicalEditor; host: HTMLElement; cleanup: () => void };

/** Mount a real editable document and open its diagram source dialog. */
function fixture(): Fixture {
    const dom = new JSDOM(`<!doctype html><html><body>
        <div id="bloomerp-general-use-modal" bloomerp-component="modal" class="hidden"></div>
        <div id="host"><div id="editor" contenteditable="true"></div></div>
        </body></html>`, { runScripts: "outside-only", url: "https://app.example/", pretendToBeVisual: true });
    const w = dom.window as FixtureWindow;
    Object.assign(w, { TextEncoder, TextDecoder, structuredClone });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the default XPath result type expected by HTMX. */
    w.XPathExpression.prototype.evaluate = function evaluateXPath(context: Node, type: number = 0, previous: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, previous);
    };
    w.eval(script.code);
    const api = w.MermaidWidgetFixture;
    const editor = api.createEditor({ nodes: [api.MermaidNode],
        /** Surface structural editor errors as failed tests. */
        onError(error: Error): never { throw error; },
    });
    editor.setRootElement(w.document.getElementById("editor")!);
    /** Preserve a real slash insertion range while the code input takes focus. */
    function populate(): void {
        const paragraph = api.$createParagraphNode().append(api.$createTextNode("/mermaid"));
        api.$getRoot().append(paragraph);
        paragraph.selectEnd();
    }
    editor.update(populate, { discrete: true });
    const host = w.document.getElementById("host")!;
    const cleanup = api.registerMermaidBehavior(editor, host);
    api.promptMermaidInsert(editor, host);
    return { dom, w, api, editor, host, cleanup };
}

/** Wait for widget changes, the source-preview debounce, and queued Lexical updates. */
async function settle(): Promise<void> {
    /** Resume after the dialog's 250ms preview debounce. */
    function delay(resolve: () => void): void { setTimeout(resolve, 300); }
    await new Promise<void>(delay);
}

/** Export the same inert HTML persisted by the rich-text widget. */
function savedHTML(f: Fixture): string {
    /** Serialize immutable editor state without affecting its selection. */
    function serialize(): string { return f.api.$generateHtmlFromNodes(f.editor); }
    return f.editor.getEditorState().read(serialize);
}

/** Release dialogs, owned Ace instances, and the fixture document. */
function dispose(f: Fixture): void {
    f.cleanup();
    f.editor.setRootElement(null);
    f.dom.window.close();
}

test("Mermaid code edits update the preview, reject invalid source, and insert the validated value", async function editSource(): Promise<void> {
    const f = fixture();
    try {
        await settle();
        const codeHost = f.w.document.querySelector<HTMLElement>('[bloomerp-component="code-editor-widget"]')!;
        const container = codeHost.querySelector<HTMLElement>("[data-code-editor-container]")!;
        const aceEditor = f.api.sourceEditor(container);
        assert.equal(codeHost.dataset.language, "mermaid");
        assert.equal((aceEditor.session.getMode() as Ace.SyntaxMode & { $id: string }).$id, "ace/mode/mermaid");
        assert(aceEditor.session.getTokens(0).some(function isDeclaration(token: Ace.Token): boolean {
            /** Verify Mermaid declarations receive syntax highlighting. */
            return token.type === "keyword.control" && token.value === "flowchart";
        }));
        assert(codeHost.contains(f.w.document.activeElement));
        const form = codeHost.closest("form")!;
        const apply = form.querySelector<HTMLButtonElement>('button[type="submit"]')!;
        aceEditor.setValue("invalid", -1);
        assert.equal(apply.disabled, true);
        await settle();
        assert.equal(apply.disabled, true);
        assert.match(form.querySelector('[role="alert"]')!.textContent!, /Invalid Mermaid/);
        assert.match(savedHTML(f), /\/mermaid/);
        const value = "sequenceDiagram\n    Alice->>Bob: Hello";
        aceEditor.setValue(value, -1);
        await settle();
        assert.equal(codeHost.querySelector<HTMLTextAreaElement>("[data-code-editor-input]")!.value, value);
        assert.equal(form.querySelector("[data-mermaid-preview] text")!.textContent, value);
        assert.equal(apply.disabled, false);
        form.dispatchEvent(new f.w.Event("submit", { bubbles: true, cancelable: true }));
        await settle();
        assert.match(savedHTML(f), /<pre data-text-editor-mermaid="true"><code>sequenceDiagram/);
        assert.doesNotMatch(savedHTML(f), /\/mermaid/);
        assert.equal(container.textContent, "");
        assert.equal(codeHost.isConnected, false);
        const diagram = f.host.querySelector<HTMLElement>("[data-mermaid-node-key]")!;
        diagram.dispatchEvent(new f.w.MouseEvent("click", { bubbles: true, detail: 2 }));
        const reopened = f.w.document.querySelector<HTMLElement>('[bloomerp-component="code-editor-widget"]')!;
        assert.equal((f.api.getComponent(reopened) as CodeEditorWidget).getValue(), value);
    } finally { dispose(f); }
});

test("cancelling and destroying a diagram dialog release its code widget without editing the document", async function cancelSource(): Promise<void> {
    const f = fixture();
    try {
        const original = savedHTML(f);
        const codeHost = f.w.document.querySelector<HTMLElement>('[bloomerp-component="code-editor-widget"]')!;
        const container = codeHost.querySelector<HTMLElement>("[data-code-editor-container]")!;
        f.api.sourceEditor(container).setValue("flowchart LR\nA --> C", -1);
        codeHost.closest("form")!.querySelector<HTMLButtonElement>('button[type="button"]')!.click();
        await settle();
        assert.equal(savedHTML(f), original);
        assert.equal(container.textContent, "");
        assert.equal(codeHost.isConnected, false);
        f.api.promptMermaidInsert(f.editor, f.host);
        const reopened = f.w.document.querySelector<HTMLElement>('[bloomerp-component="code-editor-widget"]')!;
        f.cleanup();
        assert.equal(reopened.isConnected, false);
        assert.equal(savedHTML(f), original);
    } finally { dispose(f); }
});
