/** Exercise real Lexical actions, serialization, and history without network or renderer mocks. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { JSDOM, type DOMWindow } from "jsdom";
import type * as Lexical from "lexical";
import type * as Lists from "@lexical/list";
import type * as RichText from "@lexical/rich-text";
import type * as HTML from "@lexical/html";
import type * as History from "@lexical/history";
import type * as Links from "@lexical/link";
import type { EditorActionRegistry, ActionPayload, ActionSurface } from "./actionRegistry";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type * as References from "./nodes/ReferenceNode";
import type { CodeBlockNode } from "./nodes/CodeBlockNode";

const root = fileURLToPath(new URL("../../..", import.meta.url)).replace(/\/$/, "");
const entry = root + "/editor-actions-fixture.ts";
const result = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": root + "/ts" } },
    plugins: [{
        name: "editor-actions-fixture",
        /** Resolve the test entry without writing generated source into the repository. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle the same Lexical module instance for actions, serialization, and assertions. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `
                export * from 'lexical';
                export * from '@lexical/list';
                export * from '@lexical/rich-text';
                export * from '@lexical/html';
                export * from '@lexical/history';
                export * from '@lexical/link';
                export * from '${root}/ts/components/text_editor/actionRegistry';
                export * from '${root}/ts/components/text_editor/actions';
                export * from '${root}/ts/components/text_editor/serialization';
                export * from '${root}/ts/components/text_editor/nodes/CodeBlockNode';
                export * from '${root}/ts/components/text_editor/nodes/ReferenceNode';
            `;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "EditorActionsFixture" } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert("output" in bundle);
/** Find the executable test bundle among any emitted assets. */
function isScript(item: import("rollup").OutputAsset | import("rollup").OutputChunk): item is import("rollup").OutputChunk { return item.type === "chunk"; }
const script = bundle.output.find(isScript)!;

type API = typeof Lexical & typeof Lists & typeof RichText & typeof HTML & typeof History & typeof Links & typeof References & {
    EditorActionRegistry: typeof EditorActionRegistry;
    ACTIONS: Readonly<Record<string, import("./actionRegistry").Action>>;
    CodeBlockNode: typeof CodeBlockNode;
    createEditorHTMLConfig(): Lexical.HTMLConfig;
};
type Fixture = { dom: JSDOM; window: DOMWindow; api: API; editor: Lexical.LexicalEditor; registry: EditorActionRegistry; host: BloomerpTextEditor };

/** Create a real editor with the production capabilities and HTML import/export rules. */
function fixture(markup: string = "<p>Alpha Beta Gamma</p>"): Fixture {
    const dom = new JSDOM("<!doctype html><html><body><div id='host'><div id='editor' contenteditable='true'></div></div></body></html>", {
        url: "http://fixture.test", runScripts: "outside-only", pretendToBeVisual: true,
    });
    // Mermaid's browser dependencies use these modern APIs absent from jsdom.
    Object.assign(dom.window, { TextEncoder, TextDecoder, structuredClone });
    const evaluate = dom.window.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type, which jsdom requires explicitly. */
    dom.window.XPathExpression.prototype.evaluate = function evaluateXPath(context: Node, type: number = 0, result: XPathResult | null = null): XPathResult {
        return evaluate.call(this, context, type, result);
    };
    /** Provide range geometry only; Lexical selection and document operations remain real. */
    function rangeRect(): DOMRect { return new dom.window.DOMRect(0, 0, 100, 20); }
    /** Supply the DOM geometry collection absent from jsdom. */
    function rangeRects(): DOMRectList { return [rangeRect()] as unknown as DOMRectList; }
    dom.window.Range.prototype.getBoundingClientRect = rangeRect;
    dom.window.Range.prototype.getClientRects = rangeRects;
    dom.window.eval(script.code);
    const api = (dom.window as unknown as { EditorActionsFixture: API }).EditorActionsFixture;
    const editor = api.createEditor({ namespace: "Action tests", html: api.createEditorHTMLConfig(),
        nodes: [api.HeadingNode, api.QuoteNode, api.ListNode, api.ListItemNode, api.LinkNode, api.CodeBlockNode, api.ReferenceNode],
        /** Surface every Lexical structural failure as a failed assertion. */
        onError(error: Error): never { throw error; },
    });
    editor.setRootElement(dom.window.document.getElementById("editor")!);
    const host = { editor, element: dom.window.document.getElementById("host")! } as BloomerpTextEditor;
    const registry = new api.EditorActionRegistry(host, api.ACTIONS);
    Object.assign(host, { actionRegistry: registry });
    registry.initialize();
    api.registerRichText(editor);
    api.registerList(editor);
    /** Populate and select an ordinary paragraph from actual saved HTML. */
    function populate(): void {
        const document = new dom.window.DOMParser().parseFromString(markup, "text/html");
        api.$getRoot().append(...api.$generateNodesFromDOM(editor, document));
        api.$getRoot().getFirstChild()!.selectEnd();
    }
    editor.update(populate, { discrete: true });
    return { dom, window: dom.window, api, editor, registry, host };
}

/** Select exact offsets inside one text leaf before invoking a capability. */
function select(f: Fixture, start: number, end: number, block: number = 0): void {
    /** Update the real Lexical range rather than mocking action context. */
    function setRange(): void {
        const node = f.api.$getRoot().getChildAtIndex<Lexical.ElementNode>(block)!.getFirstDescendant()!;
        assert(f.api.$isTextNode(node));
        node.select(start, end);
    }
    f.editor.update(setRange, { discrete: true });
}

/** Execute the production registry command and synchronously commit its result. */
function run(f: Fixture, id: string, source: ActionSurface = "selection", payload: ActionPayload = {}): boolean {
    let handled = false;
    const selection = f.registry.captureSelection();
    /** Preserve the same command transaction while making assertions deterministic. */
    function dispatch(): void { handled = f.registry.execute(id, source, selection, payload); }
    f.editor.update(dispatch, { discrete: true });
    return handled;
}

/** Export the same HTML stored by Bloomerp forms and document templates. */
function html(f: Fixture): string {
    /** Read the current immutable editor state for serialization. */
    function exportHTML(): string { return f.api.$generateHtmlFromNodes(f.editor); }
    return f.editor.getEditorState().read(exportHTML);
}

/** Read exported structure without depending on Lexical's incidental wrapper tags. */
function document(f: Fixture): Document { return new f.window.DOMParser().parseFromString(html(f), "text/html"); }

/** Opening diagram confirmation must preserve the slash query until content is applied. */
test("diagram confirmation leaves slash text untouched before content is applied", function deferredDiagram(): void {
    const f = fixture("<p>/mermaid</p>");
    let sourceAtOpen = "";
    /** Observe the document handed to the source dialog without confirming an insertion. */
    function openSource(_host: BloomerpTextEditor, _context: import("./actionRegistry").ActionContext): void {
        sourceAtOpen = f.api.$getRoot().getTextContent();
    }
    f.registry.register("diagram_confirmation", { ...f.api.ACTIONS.mermaid, handler: openSource });
    assert(f.registry.list("toolbar").some(function isDiagram(entry: import("./actionRegistry").RegisteredAction): boolean {
        /** Verify that diagram insertion is exposed in the toolbar. */
        return entry.id === "mermaid";
    }));
    assert(f.registry.list("slash").some(function isDiagram(entry: import("./actionRegistry").RegisteredAction): boolean {
        /** Verify that diagram insertion is exposed in the slash menu. */
        return entry.id === "mermaid";
    }));
    assert.equal(run(f, "diagram_confirmation", "slash"), true);
    assert.equal(sourceAtOpen, "/mermaid");
    assert.equal(document(f).body.textContent, "/mermaid");
    f.registry.destroy();
    f.dom.window.close();
});

/** Partial inline operations must not format text outside the range. */
test("inline formats apply to selected characters and report mixed state", function selectedCharacters(): void {
    const f = fixture();
    select(f, 6, 10);
    assert.equal(run(f, "bold"), true);
    assert.equal(document(f).querySelector("strong")?.textContent, "Beta");
    assert.equal(document(f).body.textContent, "Alpha Beta Gamma");
    /** Extend selection across formatted and ordinary text. */
    function selectAll(): void { f.api.$getRoot().select(0, 1); }
    f.editor.update(selectAll, { discrete: true });
    assert.equal(f.registry.list("selection").find(isBold)!.state.mixed, true);
    run(f, "bold");
    assert.equal(f.registry.list("selection").find(isBold)!.state.active, true);
    f.dom.window.close();
});

/** Match the bold command without depending on its translated label. */
function isBold(entry: import("./actionRegistry").RegisteredAction): boolean { return entry.id === "bold"; }

/** Clear-at-caret changes subsequent typing, and restored highlights can be switched off. */
test("clearing a caret preserves existing text and highlight toggles after reload", function caretAndHighlight(): void {
    const f = fixture("<p><strong>Keep this</strong></p>");
    const before = html(f);
    select(f, 4, 4);
    run(f, "clear_formatting");
    assert.equal(html(f), before);
    select(f, 0, 9);
    run(f, "highlight");
    const restored = fixture(html(f));
    select(restored, 0, 9);
    run(restored, "highlight");
    assert.equal(document(restored).querySelectorAll("mark").length, 0);
    assert.doesNotMatch(html(restored), /background-color/);
    assert.equal(run(restored, "font_size", "selection", { value: "1000px" }), false);
    f.window.close(); restored.window.close();
});

/** All formatting and layout must survive the editor's HTML persistence boundary. */
test("highlight, color, size, alignment and indentation round-trip through HTML", function roundTrip(): void {
    const f = fixture();
    select(f, 6, 10);
    run(f, "highlight");
    run(f, "text_color", "selection", { value: "#dc2626" });
    assert.equal(run(f, "font_size", "selection", { value: "24px" }), true);
    assert.match(JSON.stringify(f.editor.getEditorState().toJSON()), /24px/);
    run(f, "align_center");
    run(f, "indent");
    const saved = html(f);
    const restored = fixture(saved);
    const result = document(restored);
    assert.equal(result.querySelector("p")!.style.textAlign, "center");
    assert.equal(result.querySelector("p")!.style.paddingInlineStart, "40px");
    assert.equal(result.querySelector("mark")!.textContent, "Beta");
    assert.match(html(restored), /font-size: 24px/);
    assert.match(html(restored), /color: rgb\(220, 38, 38\)/);
    assert.equal(result.body.textContent, "Alpha Beta Gamma");
    f.window.close(); restored.window.close();
});

/** Node conversions must preserve words and existing block alignment. */
test("slash and selection actions share semantic block transformations", function blockTransformations(): void {
    const f = fixture("<p style='text-align: right'>Existing words /h2</p>");
    run(f, "h2", "slash");
    assert.equal(document(f).querySelector("h2")!.textContent, "Existing words ");
    assert.equal(document(f).querySelector("h2")!.style.textAlign, "right");
    run(f, "quote");
    assert.equal(document(f).querySelector("blockquote")!.textContent, "Existing words ");
    run(f, "paragraph");
    assert.equal(document(f).querySelector("p")!.style.textAlign, "right");
    run(f, "code_block");
    assert.equal(document(f).querySelector("pre code")!.textContent, "Existing words ");
    run(f, "paragraph");
    assert.equal(document(f).querySelector("p")!.textContent, "Existing words ");
    f.window.close();
});

/** Converting a selected item must not replace or discard its untouched siblings. */
test("list conversions create valid items and partial unlisting retains sibling content", function listStructure(): void {
    const f = fixture("<p>One</p><p>Two</p><p>Three</p>");
    /** Select all source blocks for list conversion. */
    function all(): void { f.api.$getRoot().select(0, 3); }
    f.editor.update(all, { discrete: true });
    run(f, "unordered_list");
    assert.equal(document(f).querySelectorAll("ul > li").length, 3);
    /** Select one item while leaving adjacent items outside the conversion range. */
    function middle(): void {
        const text = f.api.$getRoot().getFirstChild<Lexical.ElementNode>()!.getChildAtIndex<Lexical.ElementNode>(1)!.getFirstDescendant()!;
        assert(f.api.$isTextNode(text)); text.select(0, 3);
    }
    f.editor.update(middle, { discrete: true });
    run(f, "h1");
    assert.equal(document(f).querySelector("h1")!.textContent, "Two");
    assert.deepEqual([...document(f).querySelectorAll("li")].map(textContent), ["One", "Three"]);
    assert.equal(document(f).body.textContent, "OneTwoThree");
    f.window.close();
});

/** Read text content for semantic list assertions. */
function textContent(element: Element): string { return element.textContent ?? ""; }

/** Inline operations must keep atomic identities and reject destructive code conversion. */
test("references remain atomic across formatting and clear formatting", function atomicReferences(): void {
    const f = fixture("<p>Before <span data-reference-kind='user' data-target-id='7' data-occurrence-id='known'>David</span> after</p>");
    /** Select the paragraph, including its reference, using the real node range. */
    function all(): void { f.api.$getRoot().select(0, 1); }
    f.editor.update(all, { discrete: true });
    run(f, "bold");
    assert.equal(document(f).querySelector("[data-occurrence-id='known']")!.textContent, "David");
    assert.equal(run(f, "code_block"), false);
    run(f, "clear_formatting");
    assert.equal(document(f).querySelectorAll("strong").length, 0);
    assert.equal(document(f).querySelector("[data-target-id='7']")!.textContent, "David");
    f.window.close();
});

/** Keyboard entry points must pass the same state and read-only guards as visible controls. */
test("shortcuts use the registry and disabled editors cannot execute formatting", function shortcutAndReadonly(): void {
    const f = fixture();
    select(f, 6, 10);
    const event = new f.window.KeyboardEvent("keydown", { key: "b", ctrlKey: true, cancelable: true });
    /** Send a genuine keyboard command through Lexical's command propagation. */
    function key(): void { f.editor.dispatchCommand(f.api.KEY_DOWN_COMMAND, event as KeyboardEvent); }
    f.editor.update(key, { discrete: true });
    assert.equal(event.defaultPrevented, true);
    assert.equal(document(f).querySelector("strong")!.textContent, "Beta");
    f.editor.setEditable(false);
    assert.equal(run(f, "italic"), false);
    assert.equal(f.registry.list("selection").find(isBold)!.state.disabled, true);
    f.editor.setEditable(true); f.host.element.dataset.disabled = "true";
    assert.equal(run(f, "italic"), false);
    f.window.close();
});

/** Registering builder capabilities must not alter other editors or shared built-ins. */
test("extension capabilities remain scoped to their editor", function isolatedRegistries(): void {
    const first = fixture(); const second = fixture();
    let invoked = 0;
    /** Count execution of this one editor's extension capability. */
    function extension(): void { invoked++; }
    first.registry.register("builder_only", { label: "Builder only", icon: "", handler: extension, surfaces: ["selection", "slash"] });
    assert.equal(run(first, "builder_only"), true);
    assert.equal(invoked, 1);
    assert.equal(second.registry.get("builder_only"), undefined);
    assert.equal(first.api.ACTIONS["builder_only"], undefined);
    first.registry.destroy(); second.registry.destroy(); first.window.close(); second.window.close();
});

/** Formatting operations must be independently reversible rather than merged into typing. */
test("formatting and block conversion participate in undo and redo", async function history(): Promise<void> {
    const f = fixture();
    f.api.registerHistory(f.editor, f.api.createEmptyHistoryState(), 300);
    select(f, 6, 10);
    const before = html(f);
    run(f, "bold");
    const bold = html(f);
    run(f, "h2");
    f.editor.dispatchCommand(f.api.UNDO_COMMAND, undefined);
    await tick(f);
    assert.equal(html(f), bold);
    f.editor.dispatchCommand(f.api.UNDO_COMMAND, undefined);
    await tick(f);
    assert.equal(html(f), before);
    const redo = new f.window.KeyboardEvent("keydown", { key: "z", ctrlKey: true, shiftKey: true, cancelable: true });
    f.editor.dispatchCommand(f.api.KEY_DOWN_COMMAND, redo as KeyboardEvent);
    await tick(f);
    assert.equal(redo.defaultPrevented, true);
    assert.equal(html(f), bold);
    f.window.close();
});

/** Flush asynchronous history command reconciliation without artificial rendering delays. */
async function tick(f: Fixture): Promise<void> {
    /** Resolve after pending Lexical command updates have committed. */
    function next(resolve: () => void): void { f.window.setTimeout(resolve, 0); }
    await new Promise<void>(next);
}
