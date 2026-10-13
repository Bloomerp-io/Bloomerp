import { $createLinkNode, $toggleLink } from "@lexical/link";
import {
    $createTextNode, $getSelection, $isRangeSelection,
    COMMAND_PRIORITY_LOW, PASTE_COMMAND,
    type LexicalEditor, type LexicalNode,
} from "lexical";

/** Accept explicit, safe link destinations without interpreting arbitrary prose as a URL. */
export function normalizeLinkHref(value: string): string | null {
    const href = value.trim();
    if (!href || /[\s\u0000-\u001f\u007f]/u.test(href)) return null;
    try {
        const url = new URL(href);
        if ((url.protocol === "https:" || url.protocol === "http:") && url.hostname) return href;
        if ((url.protocol === "mailto:" || url.protocol === "tel:") && url.pathname) return href;
    } catch {
        return null;
    }
    return null;
}

/** Leave pasted source code literal rather than turning it into interactive content. */
function isCodeSelection(node: LexicalNode): boolean {
    for (let current: LexicalNode | null = node; current; current = current.getParent()) {
        if (["code", "text-editor-code-block"].includes(current.getType())) return true;
    }
    return false;
}

/** Insert a named link, or apply its destination to selected formatted text. */
export function $insertEditorLink(href: string, name?: string): boolean {
    const url = normalizeLinkHref(href);
    const selection = $getSelection();
    if (!url || !$isRangeSelection(selection) || isCodeSelection(selection.anchor.getNode())) return false;
    if (!selection.isCollapsed() && (name === undefined || name === selection.getTextContent())) {
        $toggleLink(url);
    } else {
        const link = $createLinkNode(url);
        link.append($createTextNode(name?.trim() || url));
        selection.insertNodes([link]);
        link.selectNext(0, 0);
    }
    return true;
}

/** Register normal Cmd/Ctrl+V handling while leaving HTML, images, and references to rich text. */
export function registerLinkBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    /** Consume only a single plain URL in an editable selection. */
    function pasteLink(event: ClipboardEvent | InputEvent | KeyboardEvent): boolean {
        if (!editor.isEditable() || host.dataset.disabled === "true" || !(event instanceof ClipboardEvent)) return false;
        const clipboard = event.clipboardData;
        if (!clipboard || clipboard.files.length || clipboard.getData("text/html")
            || clipboard.types.includes("application/x-lexical-editor")
            || Array.from(clipboard.items).some((item: DataTransferItem): boolean => item.kind === "file")) return false;
        const href = normalizeLinkHref(clipboard.getData("text/plain"));
        if (!href || !$insertEditorLink(href)) return false;
        event.preventDefault();
        return true;
    }
    return editor.registerCommand(PASTE_COMMAND, pasteLink, COMMAND_PRIORITY_LOW);
}
