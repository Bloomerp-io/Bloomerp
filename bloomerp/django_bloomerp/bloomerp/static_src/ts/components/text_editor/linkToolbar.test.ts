import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import type { LexicalEditor } from "lexical";

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://local.example/' });
for (const key of ["window", "document", "HTMLElement", "HTMLAnchorElement", "Element", "Node", "Text", "MutationObserver", "DOMParser", "getComputedStyle", "DocumentFragment", "InputEvent", "KeyboardEvent", "HTMLBRElement", "AbortController"]) {
    Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true });
}
const { createEditor, $createParagraphNode, $createTextNode, $getRoot, $getSelection, $isElementNode, $isTextNode, CLICK_COMMAND } = await import("lexical");
const { LinkNode, $createLinkNode } = await import("@lexical/link");
const { $generateHtmlFromNodes } = await import("@lexical/html");
const { LinkToolbar } = await import("./linkToolbar.ts");

/** Create a real document with two links and differently formatted children. */
function fixture(): { editor: LexicalEditor; toolbar: InstanceType<typeof LinkToolbar>; root: HTMLElement; host: HTMLElement } {
    const host = document.createElement("div");
    const root = document.createElement("div");
    root.contentEditable = "true"; host.append(root); document.body.append(host);
    const editor = createEditor({ nodes: [LinkNode],
        /** Surface Lexical invariant failures. */
        onError(error: Error): never { throw error; },
    });
    editor.setRootElement(root);
    editor.update((): void => {
        $getRoot().append($createParagraphNode().append($createTextNode("Before "),
            $createLinkNode("https://first.example").append($createTextNode("First "), $createTextNode("bold").toggleFormat("bold")),
            $createTextNode(" between "), $createLinkNode("https://second.example").append($createTextNode("Second"))));
    }, { discrete: true });
    return { editor, root, host, toolbar: new LinkToolbar(editor, host) };
}
/** Dispatch an anchor click through Lexical's actual command system. */
function clickLink(editor: LexicalEditor, root: HTMLElement): void {
    const event = new dom.window.MouseEvent("click", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "target", { value: root.querySelector("a")!.firstChild });
    editor.update((): void => { assert.equal(editor.dispatchCommand(CLICK_COMMAND, event), true); }, { discrete: true });
    assert.equal(event.defaultPrevented, true);
}
/** Inspect persisted markup for unintended mutations. */
function html(editor: LexicalEditor): string {
    return editor.getEditorState().read((): string => $generateHtmlFromNodes(editor));
}
/** Invoke a floating control by accessible text. */
function button(toolbar: InstanceType<typeof LinkToolbar>, name: string): void {
    Array.from(toolbar.element.querySelectorAll("button")).find((item: HTMLButtonElement): boolean => item.textContent === name)!.click();
}
/** Release the editor and its fixture DOM. */
function dispose(f: ReturnType<typeof fixture>): void {
    f.toolbar.destroy(); f.editor.setRootElement(null); f.host.remove();
}

test("repeated clicks select the full formatted link without persisting highlight markup", (): void => {
    const f = fixture(); const before = html(f.editor);
    for (let i = 0; i < 3; i++) {
        clickLink(f.editor, f.root);
        assert.equal(f.toolbar.isVisible(), true);
        assert.equal(f.editor.getEditorState().read((): string => $getSelection()!.getTextContent()), "First bold");
    }
    const open = f.toolbar.element.querySelector("a")!;
    assert.equal(open.href, "https://first.example/");
    assert.equal(open.target, "_blank"); assert.equal(open.rel, "noopener noreferrer");
    assert.equal(html(f.editor), before); dispose(f);
});

test("save survives input focus and cancel preserves content and selection", (): void => {
    const f = fixture(); clickLink(f.editor, f.root);
    const input = f.toolbar.element.querySelector("input")!;
    input.focus(); input.value = "https://changed.example"; button(f.toolbar, "Save");
    assert.match(html(f.editor), /href="https:\/\/changed.example"/);
    assert.match(html(f.editor), /href="https:\/\/second.example"/);
    assert.match(html(f.editor), /<strong[^>]*>bold<\/strong>/);
    clickLink(f.editor, f.root); const before = html(f.editor);
    input.focus(); input.value = "https://discard.example"; button(f.toolbar, "Cancel");
    assert.equal(html(f.editor), before);
    assert.equal(f.editor.getEditorState().read((): string => $getSelection()!.getTextContent()), "First bold");
    dispose(f);
});

test("invalid destinations are rejected and unlink preserves formatted text", (): void => {
    const f = fixture(); clickLink(f.editor, f.root);
    const input = f.toolbar.element.querySelector("input")!;
    input.focus(); input.value = "javascript:alert(1)"; button(f.toolbar, "Save");
    assert.equal(f.toolbar.isVisible(), true); assert.match(html(f.editor), /first.example/);
    button(f.toolbar, "Remove link");
    assert.doesNotMatch(html(f.editor), /first.example/);
    assert.match(html(f.editor), /<strong[^>]*>bold<\/strong>/);
    assert.equal(f.editor.getEditorState().read((): string => $getRoot().getTextContent()), "Before First bold between Second");
    dispose(f);
});

test("read-only state and disposal hide controls and unregister click handling", (): void => {
    const f = fixture(); clickLink(f.editor, f.root);
    f.editor.setEditable(false); assert.equal(f.toolbar.isVisible(), false);
    f.editor.setEditable(true); clickLink(f.editor, f.root); f.toolbar.destroy();
    assert.equal(f.toolbar.element.isConnected, false);
    const event = new dom.window.MouseEvent("click");
    Object.defineProperty(event, "target", { value: f.root.querySelector("a") });
    assert.equal(f.editor.dispatchCommand(CLICK_COMMAND, event), false);
    f.editor.setRootElement(null); f.host.remove();
});


test("native normalization of selection points keeps controls open; a moved caret dismisses them", (): void => {
    const f = fixture(); clickLink(f.editor, f.root);
    f.editor.update((): void => {
        const paragraph = $getRoot().getFirstChild()!;
        assert.ok($isElementNode(paragraph));
        const link = paragraph.getChildren()[1];
        assert.ok($isElementNode(link));
        const first = link.getFirstChild()!;
        const last = link.getLastChild()!;
        assert.ok($isTextNode(first) && $isTextNode(last));
        first.select(0, 0).focus.set(last.getKey(), last.getTextContentSize(), "text");
    }, { discrete: true });
    assert.equal(f.toolbar.isVisible(), true);
    f.editor.update((): void => { $getRoot().selectEnd(); }, { discrete: true });
    assert.equal(f.toolbar.isVisible(), false);
    dispose(f);
});

test("unsafe and malformed imported destinations remain editable without an open action", (): void => {
    const f = fixture();
    for (const url of ["javascript:alert(1)", "http://[", "data:text/html,unsafe"]) {
        f.editor.update((): void => {
            const paragraph = $getRoot().getFirstChild()!;
            assert.ok($isElementNode(paragraph));
            const link = paragraph.getChildren()[1];
            assert.ok(link instanceof LinkNode);
            link.setURL(url);
        }, { discrete: true });
        clickLink(f.editor, f.root);
        assert.equal(f.toolbar.isVisible(), true);
        assert.equal(f.toolbar.element.querySelector("a")!.hasAttribute("href"), false);
    }
    dispose(f);
});

test("removing the active node while editing cannot update a different link", (): void => {
    const f = fixture(); clickLink(f.editor, f.root);
    const input = f.toolbar.element.querySelector("input")!;
    input.focus(); input.value = "https://stale.example";
    f.editor.update((): void => {
        const paragraph = $getRoot().getFirstChild()!;
        assert.ok($isElementNode(paragraph));
        paragraph.getChildren()[1].remove();
    }, { discrete: true });
    assert.equal(f.toolbar.isVisible(), false);
    button(f.toolbar, "Save");
    assert.doesNotMatch(html(f.editor), /stale.example/);
    assert.match(html(f.editor), /second.example/);
    dispose(f);
});
