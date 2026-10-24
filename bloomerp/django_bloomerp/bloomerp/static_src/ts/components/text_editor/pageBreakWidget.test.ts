/** Verify production widget save/load and editor-local action registration. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import type { OutputAsset, OutputChunk } from "rollup";
import { JSDOM, type DOMWindow } from "jsdom";
import type { BloomerpTextEditor } from "./BloomerpTextEditor.ts";
import type { LexicalEditor } from "lexical";
import type { ContextMenuController, ContextMenuItem } from "../../utils/contextMenu.ts";

const root = fileURLToPath(new URL("../../..", import.meta.url)).replace(/\/$/, "");
const entry = `${root}/page-break-widget-fixture.ts`;
const buildResult = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": `${root}/ts` } },
    plugins: [{
        name: "page-break-widget-fixture",
        /** Resolve an in-memory entry without altering the production source tree. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle production components and serializers together, with no mock editor. */
        load(id: string): string | null {
            return id === entry ? `
                import { BloomerpTextEditor } from '${root}/ts/components/text_editor/BloomerpTextEditor';
                import { DocumentTemplateTextEditor } from '${root}/ts/components/text_editor/DocumentTemplateTextEditor';
                import { PageBreakNode } from '${root}/ts/components/text_editor/nodes/PageBreakNode';
                import { loadTranslations } from '${root}/ts/utils/i18n';
                import { $getRoot } from 'lexical';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                import { insertPageBreak } from '${root}/ts/components/text_editor/utils/pageBreakBehavior';
                import { launchContextMenu } from '${root}/ts/components/text_editor/utils/editorContextMenu';
                registerComponent('bloomerp-text-editor', BloomerpTextEditor);
                registerComponent('document-template-text-editor', DocumentTemplateTextEditor);
                /** Inspect the actual production node registry. */
                function hasPageBreakNode(editor: import('lexical').LexicalEditor): boolean {
                    return editor.hasNodes([PageBreakNode]);
                }
                /** Position a real caret for toolbar and menu invocation regressions. */
                function selectEnd(editor: import('lexical').LexicalEditor): void {
                    /** Select the end of the current document. */
                    function selectDocumentEnd(): void { $getRoot().selectEnd(); }
                    editor.update(selectDocumentEnd, {discrete: true});
                }
                export { initComponents, getComponent, insertPageBreak, launchContextMenu, selectEnd, hasPageBreakNode, loadTranslations };
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "PageBreakFixture" } },
});
const bundle = Array.isArray(buildResult) ? buildResult[0] : buildResult;
assert("output" in bundle);
/** Find the bundled executable containing the real widget and Lexical instance. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === "chunk");
assert(script?.type === "chunk");
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    PageBreakFixture: {
        initComponents(element: HTMLElement): void;
        getComponent(element: HTMLElement): BloomerpTextEditor;
        insertPageBreak(editor: LexicalEditor, fromSlashMenu?: boolean): void;
        selectEnd(editor: LexicalEditor): void;
        hasPageBreakNode(editor: LexicalEditor): boolean;
        loadTranslations(): Promise<void>;
        launchContextMenu(editor: LexicalEditor, menu: ContextMenuController, keys: string[], query: string): void;
    };
}

/** Flush Lexical microtasks, animation frames, and widget change listeners. */
async function tick(): Promise<void> {
    await new Promise<void>(function schedule(resolve: () => void): void {
        /** Let jsdom animation frames run before checking the action menu. */
        setTimeout(resolve, 30);
    });
}

/** Mount an isolated editor through the production component registry. */
function mount(w: FixtureWindow, id: string, componentName: string = "bloomerp-text-editor", value: string = "", lazy: boolean = false): BloomerpTextEditor {
    const host = w.document.createElement("div");
    host.setAttribute("bloomerp-component", componentName);
    host.dataset.editorId = id;
    host.dataset.includeToolbar = "true";
    host.innerHTML = `<style id="text-editor-styling-${id}"></style><div id="actions-toolbar-${id}"></div><div id="editor-${id}" contenteditable="true"></div><input type="hidden" data-text-editor-input="true">`;
    host.querySelector("input")!.value = value;
    w.document.body.appendChild(host);
    if (!lazy) w.PageBreakFixture.initComponents(host);
    return w.PageBreakFixture.getComponent(host);
}

test("template marker persists through widget values and actions never leak to ordinary editors", async function widgetRoundTrip(): Promise<void> {
    /** Exercise the real hidden-input, event, toolbar and slash-menu integration. */
    const dom = new JSDOM("<!doctype html><html><body></body></html>", { runScripts: "outside-only", url: "https://app.example/", pretendToBeVisual: true });
    const w = dom.window as FixtureWindow;
    w.CSS ??= {} as typeof CSS;
    /** Fixture IDs use only safe characters, so no selector escaping is needed. */
    w.CSS.escape = function escape(value: string): string { return value; };
    /** Supply deterministic caret geometry absent from jsdom's layout engine. */
    w.Range.prototype.getClientRects = function getClientRects(): DOMRectList { return [] as unknown as DOMRectList; };
    /** Supply a zero rectangle for the context menu's position fallback. */
    w.Range.prototype.getBoundingClientRect = function getBoundingClientRect(): DOMRect { return new w.DOMRect(); };
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Adapt HTMX's optional XPath result type to jsdom's required argument. */
    w.XPathExpression.prototype.evaluate = function evaluateXPath(context: Node, type?: number, result?: XPathResult | null): XPathResult {
        return evaluate.call(this, context, type ?? 0, result ?? null);
    };
    w.eval(scriptCode);
    const widgets: BloomerpTextEditor[] = [];
    try {
        const ordinaryBefore = mount(w, "ordinary-before", "bloomerp-text-editor", "<p>Ordinary</p>");
        const template = mount(w, "template", "document-template-text-editor", '<p>Before</p><div data-document-template-page-break="true"></div><p>After</p>', true);
        widgets.push(ordinaryBefore, template);
        assert.equal(w.PageBreakFixture.hasPageBreakNode(template.editor!), true);
        assert.equal(template.element!.hasAttribute("data-editor-context"), false);
        const originalEditor = template.editor;
        w.PageBreakFixture.initComponents(template.element!);
        assert.equal(w.PageBreakFixture.getComponent(template.element!), template);
        assert.equal(template.editor, originalEditor);
        assert.equal(template.element!.querySelectorAll('[aria-label="Remove page break"]').length, 1);
        const ordinaryAfter = mount(w, "ordinary-after");
        widgets.push(ordinaryAfter);
        await tick();
        for (const ordinary of [ordinaryBefore, ordinaryAfter]) {
            assert.equal(w.PageBreakFixture.hasPageBreakNode(ordinary.editor!), false);
            assert.equal(ordinary.getAction("page_break"), undefined);
            assert.equal(ordinary.getActions().some(function isPageBreak(action: { label: string }): boolean {
                /** Check instance-local toolbar options. */
                return action.label === "Page break";
            }), false);
            assert.equal(ordinary.slashExtraActions.includes("page_break"), false);
            assert.doesNotMatch(ordinary.element!.textContent!, /Page break/);
        }
        assert.equal(template.slashExtraActions.includes("page_break"), true);
        let menuItems: ContextMenuItem[] = [];
        const menu = {
            /** Capture the real slash-menu resolution without rendering menu chrome. */
            showAt(_position: { x: number; y: number }, _element: HTMLElement, items: ContextMenuItem[]): void { menuItems = items; },
            /** Record an empty menu result. */
            hide(): void { menuItems = []; },
        } as unknown as ContextMenuController;
        w.PageBreakFixture.launchContextMenu(template.editor!, menu, template.slashExtraActions, "Page break");
        await tick();
        assert.equal(menuItems.length, 1);
        assert.equal(menuItems[0].label, "Page break");
        const saved = template.getValue() as string;
        assert.match(saved, /<div data-document-template-page-break="true"><\/div>/);
        assert.doesNotMatch(saved, /Page break|Remove|button|dashed/);
        assert.equal(template.element!.querySelector<HTMLInputElement>('input')!.value, saved);
        const restored = mount(w, "restored", "document-template-text-editor", saved);
        widgets.push(restored);
        await tick();
        assert.equal(restored.getValue(), saved);
        assert.equal(restored.element!.querySelectorAll('[aria-label="Remove page break"]').length, 1);
        let changes = 0;
        /** Count persisted document changes emitted by removal. */
        function changed(): void { changes += 1; }
        restored.element!.addEventListener("bloomerp:widget-change", changed);
        restored.element!.querySelector<HTMLButtonElement>('[aria-label="Remove page break"]')!.click();
        await tick();
        assert.equal(changes, 1);
        assert.doesNotMatch(restored.getValue() as string, /data-document-template-page-break/);
        assert.equal(restored.element!.querySelector<HTMLInputElement>('input')!.value, restored.getValue());
        assert.match(restored.getValue() as string, /After/);
        restored.setValue(saved);
        await tick();
        assert.equal(restored.getValue(), saved);
        assert.equal(changes, 1, "Programmatic restoration must not emit a user change");
        assert.equal(restored.element!.querySelectorAll('[aria-label="Remove page break"]').length, 1);
        template.setValue("<p>Path /server/path</p>");
        w.PageBreakFixture.selectEnd(template.editor!);
        const toolbarButton = Array.from(template.element!.querySelectorAll<HTMLButtonElement>("button")).find(function pageBreakButton(button: HTMLButtonElement): boolean {
            /** Click the actual toolbar control rather than calling its handler directly. */
            return button.textContent!.trim() === "Page break";
        });
        assert.ok(toolbarButton);
        toolbarButton.click();
        await tick();
        assert.match(template.getValue() as string, /Path \/server\/path/);
        assert.match(template.getValue() as string, /data-document-template-page-break/);
        template.setValue("<p>Path /page</p>");
        w.PageBreakFixture.selectEnd(template.editor!);
        w.PageBreakFixture.launchContextMenu(template.editor!, menu, template.slashExtraActions, "page");
        await tick();
        assert.equal(menuItems.length, 1);
        menuItems[0].onClick!({ trigger: template.element!, event: new w.MouseEvent("click"), hide: menu.hide });
        await tick();
        assert.doesNotMatch(template.getValue() as string, /\/page/);
        assert.match(template.getValue() as string, /Path/);
        assert.match(template.getValue() as string, /data-document-template-page-break/);
        w.BLOOMERP_I18N_CATALOG_URL = "/translations/";
        /** Return a non-English catalog through the production translation loader. */
        w.fetch = async function fetchCatalog(): Promise<Response> {
            return new Response(JSON.stringify({ catalog: {
                "Page break": "Pagina-einde", "Remove": "Verwijderen", "Remove page break": "Pagina-einde verwijderen",
            } }), { status: 200, headers: { "Content-Type": "application/json" } });
        };
        await w.PageBreakFixture.loadTranslations();
        const translated = mount(w, "translated", "document-template-text-editor", saved);
        widgets.push(translated);
        await tick();
        assert.equal(translated.getAction("page_break")!.label, "Pagina-einde");
        const translatedMarker = translated.element!.querySelector<HTMLElement>('[data-document-template-page-break]')!;
        assert.equal(translatedMarker.querySelector("span")!.textContent, "Pagina-einde");
        assert.equal(translatedMarker.querySelector("button")!.textContent, "Verwijderen");
        assert.equal(translatedMarker.querySelector("button")!.getAttribute("aria-label"), "Pagina-einde verwijderen");
        assert.equal(translated.getValue(), saved);
        assert.doesNotMatch(translated.getValue() as string, /Pagina-einde|Verwijderen/);
    } finally {
        for (const widget of widgets) widget.destroy();
        dom.window.close();
    }
});
