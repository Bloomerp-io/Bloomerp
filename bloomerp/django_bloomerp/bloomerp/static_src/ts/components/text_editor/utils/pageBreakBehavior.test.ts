/** Exercise real Lexical page-break editing and persistence without a browser server. */
import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import type { LexicalEditor } from "lexical";

const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true });
for (const key of ["window", "document", "HTMLElement", "HTMLAnchorElement", "Element", "Node", "Text", "MutationObserver", "DOMParser", "getComputedStyle", "DocumentFragment", "InputEvent", "KeyboardEvent", "HTMLBRElement"]) {
    Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true });
}
Object.defineProperty(globalThis, "DragEvent", { value: class extends dom.window.Event {}, configurable: true });
const { createEditor, $createParagraphNode, $createTextNode, $getRoot, $getSelection, $isRangeSelection, $isTextNode, UNDO_COMMAND, REDO_COMMAND, DELETE_CHARACTER_COMMAND, CONTROLLED_TEXT_INSERTION_COMMAND } = await import("lexical");
const { $generateHtmlFromNodes, $generateNodesFromDOM } = await import("@lexical/html");
const { registerRichText } = await import("@lexical/rich-text");
const { registerHistory, createEmptyHistoryState } = await import("@lexical/history");
const { PageBreakNode, PAGE_BREAK_ATTRIBUTE } = await import("../nodes/PageBreakNode.ts");
const { documentTemplateNodes, insertPageBreak } = await import("./pageBreakBehavior.ts");
const marker = `<div ${PAGE_BREAK_ATTRIBUTE}="true"></div>`;

/** Create an editor with the same context-specific nodes as the production widget. */
function makeEditor(text: string = "", context: string | undefined = "document-template"): LexicalEditor {
    const editor = createEditor({ nodes: documentTemplateNodes(context),
        /** Surface invariant violations as test failures. */
        onError(error: Error): never { throw error; },
    });
    const root = document.createElement("div");
    root.contentEditable = "true";
    document.body.appendChild(root);
    editor.setRootElement(root);
    registerRichText(editor);
    /** Seed one editable paragraph and its initial caret. */
    function seed(): void {
        const paragraph = $createParagraphNode();
        if (text) paragraph.append($createTextNode(text));
        $getRoot().append(paragraph);
        paragraph.selectEnd();
    }
    editor.update(seed, { discrete: true });
    return editor;
}

/** Wait for queued editor mutations and focus updates to settle. */
async function tick(): Promise<void> {
    await new Promise<void>(function schedule(resolve: () => void): void {
        /** Resolve after the next event-loop turn. */
        setTimeout(resolve, 0);
    });
}

/** Export only the HTML persisted by the editor. */
function html(editor: LexicalEditor): string {
    return editor.getEditorState().read(function exportHtml(): string {
        /** Use the production Lexical HTML serializer. */
        return $generateHtmlFromNodes(editor);
    });
}

/** Replace the editor document using its registered HTML converters. */
function restore(editor: LexicalEditor, value: string): void {
    editor.update(function importHtml(): void {
        /** Import a saved document and select its trailing content. */
        $getRoot().clear().append(...$generateNodesFromDOM(editor, new DOMParser().parseFromString(value, "text/html")));
        $getRoot().selectEnd();
    }, { discrete: true });
}

/** Count semantic markers in the saved document rather than editor decoration. */
function count(editor: LexicalEditor): number {
    return new DOMParser().parseFromString(html(editor), "text/html").querySelectorAll(`[${PAGE_BREAK_ATTRIBUTE}]`).length;
}

test("inserts at the caret, preserves following text, and exports no editor controls", async function insertInText(): Promise<void> {
    /** Splitting a paragraph must not replace its following text. */
    const editor = makeEditor("BeforeAfter");
    editor.update(function selectMiddle(): void {
        /** Place the caret between both halves of the paragraph. */
        const text = $getRoot().getFirstDescendant()!;
        assert.ok($isTextNode(text));
        text.select(6, 6);
    }, { discrete: true });
    insertPageBreak(editor);
    await tick();
    const saved = html(editor);
    assert.equal(count(editor), 1);
    assert.ok(saved.indexOf("Before") < saved.indexOf(marker));
    assert.ok(saved.indexOf("After") > saved.indexOf(marker));
    assert.doesNotMatch(saved, /Page break|Remove|button|contenteditable|dashed/);
    assert.equal(editor.getRootElement()!.querySelector(`[${PAGE_BREAK_ATTRIBUTE}] span`)!.textContent, "Page break");
    assert.ok(editor.getRootElement()!.querySelector('[aria-label="Remove page break"]'));
    editor.setRootElement(null);
});

test("round-trips HTML and JSON without importing visible controls", function persistMarker(): void {
    /** Both serializers retain one atomic marker between document paragraphs. */
    const editor = makeEditor();
    restore(editor, `<p>First</p>${marker}<p>Second</p>`);
    const saved = html(editor);
    const restored = makeEditor();
    restore(restored, saved);
    assert.equal(html(restored), saved);
    const serialized = JSON.stringify(editor.getEditorState().toJSON());
    restored.setEditorState(restored.parseEditorState(serialized));
    assert.equal(html(restored), saved);
    restore(restored, '<div data-document-template-page-break="true"><span>Page break</span><button>Remove</button></div><p>After</p>');
    assert.equal(count(restored), 1);
    assert.doesNotMatch(html(restored), /Page break|Remove|button/);
    editor.setRootElement(null);
    restored.setRootElement(null);
});

test("slash insertion removes its trigger and repeated markers remain independent", async function repeatInsertion(): Promise<void> {
    /** Removing one marker must leave the second boundary intact. */
    const editor = makeEditor("First /page");
    insertPageBreak(editor, true);
    await tick();
    insertPageBreak(editor);
    await tick();
    assert.equal(count(editor), 2);
    assert.doesNotMatch(html(editor), /\/page/);
    editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!.click();
    await tick();
    assert.equal(count(editor), 1);
    assert.match(html(editor), /First/);
    editor.setRootElement(null);
});

test("marker removal can be undone and redone", async function undoRemoval(): Promise<void> {
    /** Removing the marker uses an ordinary undoable editor transaction. */
    const editor = makeEditor();
    restore(editor, `<p>First</p>${marker}<p>Second</p>`);
    const unregister = registerHistory(editor, createEmptyHistoryState(), 0);
    editor.update(function seedHistory(): void {
        /** Establish the pre-removal history state. */
        $getRoot().selectEnd();
    }, { discrete: true, tag: "history-push" });
    const before = html(editor);
    editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!.click();
    await tick();
    assert.equal(count(editor), 0);
    editor.dispatchCommand(UNDO_COMMAND, undefined);
    await tick();
    assert.equal(html(editor), before);
    editor.dispatchCommand(REDO_COMMAND, undefined);
    await tick();
    assert.equal(count(editor), 0);
    unregister();
    editor.setRootElement(null);
});

test("ordinary and header editors do not register or insert page breaks", async function scopeNodes(): Promise<void> {
    /** Context opt-in must not affect other rich-text editor instances. */
    for (const context of ["", "email", "document-template-header", "ordinary"]) {
        const editor = makeEditor("Unchanged", context);
        const before = html(editor);
        assert.equal(editor.hasNodes([PageBreakNode]), false);
        insertPageBreak(editor);
        await tick();
        assert.equal(html(editor), before);
        editor.setRootElement(null);
    }
    assert.deepEqual(documentTemplateNodes(undefined), []);
});

test("empty documents and removal of a sole marker stay editable", async function removeSoleMarker(): Promise<void> {
    /** The last marker must not leave a broken root selection. */
    const editor = makeEditor();
    insertPageBreak(editor);
    await tick();
    assert.equal(count(editor), 1);
    restore(editor, marker);
    editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!.click();
    await tick();
    editor.dispatchCommand(CONTROLLED_TEXT_INSERTION_COMMAND, "After removal");
    await tick();
    assert.equal(count(editor), 0);
    assert.match(html(editor), /After removal/);
    editor.setRootElement(null);
});

test("read-only editors reject insertion and marker removal", async function readOnlyMarker(): Promise<void> {
    /** Visible controls must respect the editor's editability state. */
    const editor = makeEditor();
    restore(editor, `<p>Before</p>${marker}<p>After</p>`);
    editor.setEditable(false);
    const before = html(editor);
    insertPageBreak(editor);
    editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!.click();
    await tick();
    assert.equal(html(editor), before);
    editor.setRootElement(null);
});

test("typing after removing the first adjacent marker preserves the second marker", async function adjacentRemoval(): Promise<void> {
    /** Atomic decorators prevent text from being inserted into a page-break element. */
    const editor = makeEditor();
    restore(editor, `<p>Before</p>${marker}${marker}<p>After</p>`);
    editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!.click();
    await tick();
    editor.dispatchCommand(CONTROLLED_TEXT_INSERTION_COMMAND, "Typed");
    await tick();
    assert.equal(count(editor), 1);
    assert.match(html(editor), /Typed/);
    assert.match(html(editor), /After/);
    editor.setRootElement(null);
});

test("forward delete at a page-break boundary leaves subsequent typing valid", async function deleteBoundary(): Promise<void> {
    /** Delete must not leave a node selection that silently discards typed text. */
    const editor = makeEditor();
    restore(editor, `<p></p>${marker}<p>After</p>`);
    editor.update(function selectBeforeMarker(): void {
        /** Position forward delete immediately before the marker. */
        $getRoot().getFirstChild()!.selectEnd();
    }, { discrete: true });
    editor.dispatchCommand(DELETE_CHARACTER_COMMAND, false);
    await tick();
    editor.dispatchCommand(CONTROLLED_TEXT_INSERTION_COMMAND, "Typed");
    await tick();
    assert.equal(count(editor), 0);
    assert.match(html(editor), /Typed/);
    assert.match(html(editor), /After/);
    editor.getEditorState().read(function validSelection(): void {
        /** Ensure the caret stays in an editable range. */
        assert.ok($isRangeSelection($getSelection()));
    });
    editor.setRootElement(null);
});

test("remove-button keyboard activation and tab navigation remain native", function keyboardControl(): void {
    /** Enter, Space and Tab must not be consumed by Lexical or edit document text. */
    const editor = makeEditor();
    restore(editor, `<p>Before</p>${marker}<p>After</p>`);
    const button = editor.getRootElement()!.querySelector<HTMLButtonElement>('button')!;
    button.focus();
    const before = html(editor);
    for (const key of ["Enter", " ", "Tab"]) {
        const event = new dom.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
        button.dispatchEvent(event);
        assert.equal(event.defaultPrevented, false, key);
        assert.equal(html(editor), before);
    }
    editor.setRootElement(null);
});


test("inserting a page break can be undone and redone without losing following text", async function undoInsertion(): Promise<void> {
    /** Insertion belongs to the same editor history as ordinary document edits. */
    const editor = makeEditor("BeforeAfter");
    const unregister = registerHistory(editor, createEmptyHistoryState(), 0);
    editor.update(function seedHistory(): void {
        /** Select the insertion position and capture the previous state. */
        const text = $getRoot().getFirstDescendant()!;
        assert.ok($isTextNode(text));
        text.select(6, 6);
    }, { discrete: true, tag: "history-push" });
    const before = html(editor);
    insertPageBreak(editor);
    await tick();
    const after = html(editor);
    assert.equal(count(editor), 1);
    editor.dispatchCommand(UNDO_COMMAND, undefined);
    await tick();
    assert.equal(html(editor), before);
    editor.dispatchCommand(REDO_COMMAND, undefined);
    await tick();
    assert.equal(html(editor), after);
    unregister();
    editor.setRootElement(null);
});


test("toolbar insertion preserves slash-prefixed document text", async function preservePath(): Promise<void> {
    /** Only an explicitly selected slash command may remove a slash-prefixed word. */
    const editor = makeEditor("Path /server/path");
    insertPageBreak(editor);
    await tick();
    assert.equal(count(editor), 1);
    assert.match(html(editor), /Path \/server\/path/);
    editor.setRootElement(null);
});

test("slash command removal spans formatting boundaries without losing surrounding text", async function splitSlashTrigger(): Promise<void> {
    /** Mixed formatting must not leave a visible command after inserting a break. */
    const editor = makeEditor();
    restore(editor, '<p>Before <strong>/</strong>pa<em>ge</em></p>');
    insertPageBreak(editor, true);
    await tick();
    assert.equal(count(editor), 1);
    const saved = new DOMParser().parseFromString(html(editor), "text/html");
    assert.equal(saved.body.textContent!.trim(), "Before");
    editor.setRootElement(null);
});
