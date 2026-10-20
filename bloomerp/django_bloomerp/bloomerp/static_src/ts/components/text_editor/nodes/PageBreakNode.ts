import {
    $applyNodeReplacement,
    $getNodeByKey,
    DecoratorNode,
    type DOMConversion,
    type DOMConversionMap,
    type DOMConversionOutput,
    type DOMExportOutput,
    type EditorConfig,
    type LexicalEditor,
    type LexicalNode,
    type SerializedLexicalNode,
} from "lexical";
import { t as _ } from "../../../utils/i18n.ts";

export const PAGE_BREAK_ATTRIBUTE = "data-document-template-page-break";

/** Discard editor controls if a visible marker is copied as HTML. */
function ignorePageBreakChild(_node: LexicalNode): null {
    return null;
}

/** Restore an atomic page break without importing its editor-only children. */
function convertPageBreak(_element: HTMLElement): DOMConversionOutput {
    return { node: $createPageBreakNode(), forChild: ignorePageBreakChild };
}

/** Recognize only the document-template page-break marker. */
function getPageBreakConversion(element: HTMLElement): DOMConversion | null {
    return element.getAttribute(PAGE_BREAK_ATTRIBUTE) === "true"
        ? { conversion: convertPageBreak, priority: 4 }
        : null;
}

/** Represent a printable page boundary with removable, editor-only controls. */
export class PageBreakNode extends DecoratorNode<null> {
    /** Identify the node independently of ordinary rich-text blocks. */
    static getType(): string {
        return "document-template-page-break";
    }

    /** Clone a marker while preserving its Lexical identity. */
    static clone(node: PageBreakNode): PageBreakNode {
        return new PageBreakNode(node.__key);
    }

    /** Restore a marker from saved editor state. */
    static importJSON(_value: SerializedLexicalNode): PageBreakNode {
        return $createPageBreakNode();
    }

    /** Preserve semantic markers when loading or pasting template HTML. */
    static importDOM(): DOMConversionMap {
        return { div: getPageBreakConversion };
    }

    /** Show a visible boundary and an accessible removal control in the editor. */
    createDOM(_config: EditorConfig, editor: LexicalEditor): HTMLElement {
        const element = document.createElement("div");
        element.setAttribute(PAGE_BREAK_ATTRIBUTE, "true");
        element.contentEditable = "false";
        element.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:1em;border-top:1px dashed currentColor;margin:1em 0;padding:0.5em 0;font:12px sans-serif;user-select:none";
        const label = document.createElement("span");
        label.textContent = _("Page break");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = _("Remove");
        button.setAttribute("aria-label", _("Remove page break"));
        button.style.cssText = "color:inherit;background:transparent;border:1px solid currentColor;border-radius:0.25em;padding:0.2em 0.5em;font:inherit;cursor:pointer";
        const key = this.getKey();

        /** Remove the current marker, keeping subsequent editing in a valid range. */
        function removePageBreak(event: MouseEvent): void {
            event.preventDefault();
            event.stopPropagation();
            if (!editor.isEditable()) return;
            /** Resolve the live node rather than retaining an outdated editor state. */
            function removeCurrentNode(): void {
                const node = $getNodeByKey(key);
                if (node instanceof PageBreakNode) {
                    node.selectNext();
                    node.remove();
                }
            }
            editor.update(removeCurrentNode);
            editor.focus();
        }

        /** Keep native button activation and tab navigation out of Lexical commands. */
        function handleControlKey(event: KeyboardEvent): void {
            if (["Enter", " ", "Tab"].includes(event.key)) event.stopPropagation();
        }

        button.addEventListener("click", removePageBreak);
        button.addEventListener("keydown", handleControlKey);
        element.append(label, button);
        return element;
    }

    /** Keep the existing DOM because page breaks have no mutable attributes. */
    updateDOM(_previous: PageBreakNode, _element: HTMLElement): boolean {
        return false;
    }

    /** Save only the PDF marker, without labels, buttons, or editor styling. */
    exportDOM(): DOMExportOutput {
        const element = document.createElement("div");
        element.setAttribute(PAGE_BREAK_ATTRIBUTE, "true");
        return { element };
    }

    /** Serialize the marker without editor-only presentation. */
    exportJSON(): SerializedLexicalNode {
        return { type: PageBreakNode.getType(), version: 1 };
    }

    /** Render directly through createDOM without an external decorator framework. */
    decorate(): null {
        return null;
    }

    /** Treat a page boundary as a block rather than inline text. */
    isInline(): boolean {
        return false;
    }

    /** Let Delete remove the boundary without trapping subsequent typing. */
    isKeyboardSelectable(): boolean {
        return false;
    }
}

/** Create a page boundary using the editor's configured replacement rules. */
export function $createPageBreakNode(): PageBreakNode {
    return $applyNodeReplacement(new PageBreakNode());
}
