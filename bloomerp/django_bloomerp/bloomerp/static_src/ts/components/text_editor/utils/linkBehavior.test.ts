import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import type { LexicalEditor } from "lexical";

const dom = new JSDOM('<!doctype html><html><body></body></html>');
for (const key of ["window", "document", "HTMLElement", "HTMLAnchorElement", "Element", "Node", "Text", "MutationObserver", "DOMParser", "getComputedStyle", "DocumentFragment", "InputEvent", "KeyboardEvent", "HTMLBRElement"]) {
    Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true });
}
/** Supply clipboard data in jsdom, which does not implement ClipboardEvent. */
class TestClipboardEvent extends dom.window.Event {
    clipboardData: DataTransfer;
    /** Build the same clipboard shape the browser paste command receives. */
    constructor(text: string, html: string = "", files: boolean = false, lexical: boolean = false) {
        super("paste", { cancelable: true });
        this.clipboardData = {
            files: files ? [{}] : [], items: files ? [{ kind: "file" }] : [],
            types: lexical ? ["application/x-lexical-editor"] : ["text/plain"],
            /** Return only the requested clipboard representation. */
            getData(type: string): string { return type === "text/plain" ? text : type === "text/html" ? html : ""; },
        } as unknown as DataTransfer;
    }
}
Object.defineProperty(globalThis, "ClipboardEvent", { value: TestClipboardEvent, configurable: true });
const { createEditor, $createParagraphNode, $createTextNode, $getRoot, $getSelection, $isRangeSelection, $isTextNode, PASTE_COMMAND, UNDO_COMMAND, REDO_COMMAND } = await import("lexical");
const { LinkNode } = await import("@lexical/link");
const { $generateHtmlFromNodes, $generateNodesFromDOM } = await import("@lexical/html");
const { registerRichText } = await import("@lexical/rich-text");
const { CodeBlockNode, $createCodeBlockNode } = await import("../nodes/CodeBlockNode.ts");
const { registerHistory, createEmptyHistoryState } = await import("@lexical/history");
const { $insertEditorLink, normalizeLinkHref, registerLinkBehavior } = await import("./linkBehavior.ts");

/** Create a real Lexical document with deterministic synchronous updates. */
function makeEditor(text: string = ""): LexicalEditor {
    const editor = createEditor({ nodes: [LinkNode, CodeBlockNode], theme: { link: "text-blue-600 underline" },
        /** Fail the test on any Lexical invariant error. */
        onError(error: Error): never { throw error; },
    });
    const rootElement = document.createElement("div");
    rootElement.contentEditable = "true";
    document.body.appendChild(rootElement);
    editor.setRootElement(rootElement);
    editor.update((): void => {
        const paragraph = $createParagraphNode();
        if (text) paragraph.append($createTextNode(text));
        $getRoot().append(paragraph);
        paragraph.selectEnd();
    }, { discrete: true });
    return editor;
}
/** Export the persisted HTML representation for assertions. */
function html(editor: LexicalEditor): string {
    return editor.getEditorState().read((): string => $generateHtmlFromNodes(editor));
}
/** Dispatch a paste in a synchronous Lexical transaction. */
function paste(editor: LexicalEditor, text: string, markup: string = "", files: boolean = false, lexical: boolean = false): TestClipboardEvent {
    const event = new TestClipboardEvent(text, markup, files, lexical);
    editor.update((): void => { editor.dispatchCommand(PASTE_COMMAND, event as unknown as ClipboardEvent); }, { discrete: true });
    return event;
}

test("accepts explicit safe URLs and rejects active content, malformed destinations, and prose", (): void => {
    for (const value of ["https://example.com/a?q=one#two", "http://localhost:8000/", "mailto:team@example.com", "tel:+31201234567"]) {
        assert.equal(normalizeLinkHref(value), value);
    }
    assert.equal(normalizeLinkHref("  https://example.com  "), "https://example.com");
    for (const value of ["", "example.com", "relative/path", "//example.com", "javascript:alert(1)", "data:text/html,test", "file:///tmp/file", "https://", "mailto:", "https://example.com with text", "java\nscript:alert(1)", "https://example.com\u0000"]) {
        assert.equal(normalizeLinkHref(value), null, value);
    }
});

test("plain URL paste creates a styled LinkNode and round-trips its name and href", (): void => {
    const editor = makeEditor();
    const unregister = registerLinkBehavior(editor, document.createElement("div"));
    assert.equal(paste(editor, "https://example.com/path").defaultPrevented, true);
    const saved = html(editor);
    assert.match(saved, /<a href="https:\/\/example.com\/path" class="text-blue-600 underline">/);
    assert.match(saved, />https:\/\/example.com\/path<\/span>/);
    const restored = makeEditor();
    restored.update((): void => {
        $getRoot().clear().append(...$generateNodesFromDOM(restored, new DOMParser().parseFromString(saved, "text/html")));
    }, { discrete: true });
    assert.equal(html(restored), saved);
    unregister();
});

test("URL paste over selected text preserves its name and formatting", (): void => {
    const editor = makeEditor("Visit BloomERP");
    editor.update((): void => {
        const text = $getRoot().getFirstDescendant()!;
        assert.ok($isTextNode(text));
        const selection = text.select(6, 14);
        selection.formatText("bold");
    }, { discrete: true });
    registerLinkBehavior(editor, document.createElement("div"));
    paste(editor, "https://bloomerp.io");
    assert.match(html(editor), /<a href="https:\/\/bloomerp.io"[^>]*><b><strong[^>]*>BloomERP<\/strong><\/b><\/a>/);
});

test("named links escape text and repeated insertions never nest anchors", (): void => {
    const editor = makeEditor();
    editor.update((): void => { assert.equal($insertEditorLink("https://example.com", '<img src=x onerror="bad">'), true); }, { discrete: true });
    editor.update((): void => { assert.equal($insertEditorLink("https://other.example", "Second"), true); }, { discrete: true });
    const doc = new DOMParser().parseFromString(html(editor), "text/html");
    assert.equal(doc.querySelectorAll("a").length, 2, html(editor));
    assert.equal(doc.querySelectorAll("a a, img").length, 0);
    assert.equal(doc.querySelector("a")!.textContent, '<img src=x onerror="bad">');
});

test("rich HTML, images, Lexical clipboard, unsafe URLs and prose are not intercepted", (): void => {
    const editor = makeEditor("unchanged");
    registerLinkBehavior(editor, document.createElement("div"));
    for (const event of [
        paste(editor, "https://example.com", "<b>Keep formatting</b>"),
        paste(editor, "https://example.com", "", true),
        paste(editor, "https://example.com", "", false, true),
        paste(editor, "javascript:alert(1)"), paste(editor, "ordinary text"),
    ]) assert.equal(event.defaultPrevented, false);
    assert.match(html(editor), />unchanged<\/span>/);
});

test("read-only editors and disabled widgets do not consume URL paste", (): void => {
    const editor = makeEditor("unchanged");
    const host = document.createElement("div");
    registerLinkBehavior(editor, host);
    host.dataset.disabled = "true";
    assert.equal(paste(editor, "https://example.com").defaultPrevented, false);
    host.dataset.disabled = "false";
    editor.setEditable(false);
    assert.equal(paste(editor, "https://example.com").defaultPrevented, false);
    assert.doesNotMatch(html(editor), /<a /);
});

test("link insertion participates in undo and redo", async (): Promise<void> => {
    const editor = makeEditor("Before ");
    const history = createEmptyHistoryState();
    registerHistory(editor, history, 0);
    registerLinkBehavior(editor, document.createElement("div"));
    editor.update((): void => { $getRoot().getFirstChild()!.selectEnd(); }, { discrete: true, tag: "history-push" });
    const before = html(editor);
    paste(editor, "https://example.com");
    const after = html(editor);
    editor.dispatchCommand(UNDO_COMMAND, undefined);
    await new Promise<void>((resolve): void => { setTimeout(resolve, 0); });
    assert.equal(html(editor), before);
    editor.dispatchCommand(REDO_COMMAND, undefined);
    await new Promise<void>((resolve): void => { setTimeout(resolve, 0); });
    assert.equal(html(editor), after);
});


test("pasting in a code block remains literal", (): void => {
    const editor = makeEditor();
    editor.update((): void => {
        const code = $createCodeBlockNode();
        code.append($createTextNode("source "));
        $getRoot().clear().append(code);
        code.selectEnd();
    }, { discrete: true });
    registerLinkBehavior(editor, document.createElement("div"));
    assert.equal(paste(editor, "https://example.com").defaultPrevented, false);
    assert.doesNotMatch(html(editor), /<a /);
});

test("named insertion inside an existing link never nests anchors", (): void => {
    const editor = makeEditor();
    editor.update((): void => { $insertEditorLink("https://first.example", "First link"); }, { discrete: true });
    editor.update((): void => {
        const text = $getRoot().getFirstDescendant()!;
        assert.ok($isTextNode(text));
        text.select(3, 3);
        $insertEditorLink("https://second.example", "Second");
    }, { discrete: true });
    const doc = new DOMParser().parseFromString(html(editor), "text/html");
    assert.equal(doc.querySelectorAll("a a").length, 0, html(editor));
    assert.equal(doc.querySelector('a[href="https://second.example"]')?.textContent, "Second", html(editor));
});

test("link paste runs before rich-text fallback and rich HTML retains its markup", (): void => {
    Object.defineProperty(globalThis, "DragEvent", { value: class extends dom.window.Event {}, configurable: true });
    const editor = makeEditor();
    registerLinkBehavior(editor, document.createElement("div"));
    registerRichText(editor);
    paste(editor, "https://example.com");
    assert.match(html(editor), /<a href="https:\/\/example.com"/);
    paste(editor, "Bold", "<b>Bold</b>");
    assert.match(html(editor), /<strong[^>]*>Bold<\/strong>/);
});

test("insertion in the middle of text leaves the caret directly after the link", (): void => {
    const editor = makeEditor("before after");
    editor.update((): void => {
        const text = $getRoot().getFirstDescendant()!;
        assert.ok($isTextNode(text));
        text.select(7, 7);
        $insertEditorLink("https://example.com", "Link");
        const selection = $getSelection();
        assert.ok($isRangeSelection(selection));
        selection.insertText("new ");
    }, { discrete: true });
    assert.equal(editor.getEditorState().read((): string => $getRoot().getTextContent()), "before Linknew after");
});
