import type { ContextMenuController } from "@/utils/contextMenu";
import { getComponent } from "@/components/BaseComponent";
import { $getSelection, $isRangeSelection, $isTextNode, LexicalEditor } from "lexical";
import { createActionMenuItems } from "../actionMenu";
import type { BloomerpTextEditor } from "../BloomerpTextEditor";

/** Measure the caret, falling back to the editor bounds when it has no visible text. */
function getCaretRect(root: HTMLElement): DOMRect {
    const selection = window.getSelection();
    const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

    if (range) {
        const slashProbe = range.cloneRange();
        const isTextNode = slashProbe.endContainer.nodeType === Node.TEXT_NODE;

        if (isTextNode && slashProbe.endOffset > 0) {
            slashProbe.setStart(slashProbe.endContainer, slashProbe.endOffset - 1);
            const slashRect = Array.from(slashProbe.getClientRects()).at(-1);
            if (slashRect && (slashRect.width > 0 || slashRect.height > 0)) {
                return slashRect;
            }
        }

        const marker = document.createElement('span');
        marker.textContent = '\u200b';

        const markerRange = range.cloneRange();
        markerRange.collapse(true);
        markerRange.insertNode(marker);

        const markerRect = marker.getBoundingClientRect();
        marker.remove();

        selection?.removeAllRanges();
        selection?.addRange(range);

        if (markerRect.width > 0 || markerRect.height > 0) {
            return markerRect;
        }
    }

    return root.getBoundingClientRect();
}

/** Measure the last typed slash-query character without changing editor content. */
function getSlashRect(editor: LexicalEditor): DOMRect {
    const root = editor.getRootElement();

    let rect: DOMRect | null = null;

    /** Read the typed character corresponding to the current Lexical caret. */
    function measure(): void {
        const selection = $getSelection();
        if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
            return;
        }

        const node = selection.anchor.getNode();
        if (!$isTextNode(node)) {
            return;
        }

        const element = editor.getElementByKey(node.getKey());
        const textNode = element?.firstChild;
        const offset = selection.anchor.offset;

        if (!(textNode instanceof Text) || offset <= 0) {
            return;
        }

        const range = document.createRange();
        range.setStart(textNode, offset - 1);
        range.setEnd(textNode, offset);

        const measured = Array.from(range.getClientRects()).at(-1) ?? range.getBoundingClientRect();
        if (measured.width > 0 || measured.height > 0) {
            rect = measured;
        }
    }
    editor.getEditorState().read(measure);

    return rect ?? getCaretRect(root);
}

/** Show slash commands from the owning editor's scoped capability registry. */
export function launchContextMenu(textEditor: BloomerpTextEditor, contextMenu: ContextMenuController, query?: string): void;
/** Support existing specialized editors while their callers migrate to the owning widget. */
export function launchContextMenu(editor: LexicalEditor, contextMenu: ContextMenuController, keys: string[], query?: string): void;
/** Resolve both entry points to the same scoped registry and slash-menu presenter. */
export function launchContextMenu(
    owner: BloomerpTextEditor | LexicalEditor,
    contextMenu: ContextMenuController,
    queryOrKeys: string | string[] = "",
    legacyQuery: string = "",
): void {
    let textEditor: BloomerpTextEditor | null;
    if ("actionRegistry" in owner) textEditor = owner;
    else {
        const element = owner.getRootElement()?.closest<HTMLElement>("[bloomerp-component]");
        textEditor = element ? getComponent(element) as BloomerpTextEditor | null : null;
    }
    if (!textEditor?.actionRegistry) return;
    const keys = Array.isArray(queryOrKeys) ? queryOrKeys : null;
    const query = typeof queryOrKeys === "string" ? queryOrKeys : legacyQuery;
    const editor = textEditor.editor;
    const root = editor?.getRootElement();
    if (!editor || !root) return;
    const selection = textEditor.actionRegistry.captureSelection();
    const normalizedQuery = query.trim().toLowerCase();
    /** Search both translated labels and stable command identifiers. */
    function matches(entry: import("../actionRegistry").RegisteredAction): boolean {
        return (!keys || keys.includes(entry.id))
            && (!normalizedQuery || `${entry.id} ${entry.action.label}`.toLowerCase().includes(normalizedQuery));
    }
    const entries = textEditor.actionRegistry.list("slash", selection).filter(matches);
    const items = createActionMenuItems(textEditor, entries, "slash", selection);
    if (!items.length) { contextMenu.hide(); return; }
    /** Place the shared searchable menu beside the current slash trigger. */
    function show(): void {
        const rect = getSlashRect(editor!);
        contextMenu.showAt({ x: rect.left, y: rect.bottom + 8 }, root!, items, { anchorRect: rect });
    }
    requestAnimationFrame(show);
}
