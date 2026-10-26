import {
    $applyNodeReplacement,
    DecoratorNode,
    type DOMConversion,
    type DOMConversionMap,
    type DOMConversionOutput,
    type DOMExportOutput,
    type EditorConfig,
    type LexicalEditor,
    type LexicalNode,
    type NodeKey,
    type SerializedLexicalNode,
    type Spread,
} from "lexical";
import { t as _ } from "../../../utils/i18n";
import { renderMermaid } from "../../../utils/mermaid";

type SerializedMermaidNode = Spread<{
    source: string;
    type: "text-editor-mermaid";
    version: 1;
}, SerializedLexicalNode>;

const MERMAID_ATTRIBUTE = "data-text-editor-mermaid";
const renderVersions = new WeakMap<HTMLElement, number>();

/** Keep saved source atomic instead of importing its nested code text. */
function discardMermaidChild(_node: LexicalNode, _parent: LexicalNode | null | undefined): null {
    return null;
}

/** Restore a diagram from its inert, escaped source representation. */
function convertMermaid(element: HTMLElement): DOMConversionOutput {
    const source = (element.querySelector("code") ?? element).textContent ?? "";
    return { node: $createMermaidNode(source), forChild: discardMermaidChild };
}

/** Prefer the diagram importer over ordinary preformatted code blocks. */
function getMermaidConversion(element: HTMLElement): DOMConversion | null {
    return element.getAttribute(MERMAID_ATTRIBUTE) === "true"
        ? { conversion: convertMermaid, priority: 4 }
        : null;
}

/** Render the latest diagram while ignoring responses for replaced or detached nodes. */
async function renderNodePreview(element: HTMLElement, source: string): Promise<void> {
    const version = (renderVersions.get(element) ?? 0) + 1;
    renderVersions.set(element, version);
    element.setAttribute("aria-busy", "true");
    element.textContent = _("Rendering diagram…");
    try {
        const svg = await renderMermaid(source);
        if (renderVersions.get(element) !== version || !element.isConnected) return;
        element.innerHTML = svg;
    } catch (_error: unknown) {
        if (renderVersions.get(element) !== version || !element.isConnected) return;
        const message = document.createElement("p");
        message.className = "text-sm text-danger-dark";
        message.textContent = _("This diagram could not be rendered. Double-click to edit its source.");
        const code = document.createElement("pre");
        code.className = "overflow-x-auto whitespace-pre-wrap text-sm";
        code.textContent = source;
        element.replaceChildren(message, code);
    } finally {
        if (renderVersions.get(element) === version) element.removeAttribute("aria-busy");
    }
}

/** Own a rendered diagram while persisting only its editable Mermaid source. */
export class MermaidNode extends DecoratorNode<null> {
    __source: string;

    /** Create a diagram with immutable editor identity and its original source. */
    constructor(source: string, key?: NodeKey) {
        super(key);
        this.__source = source;
    }

    /** Identify the custom node in Lexical clipboard and history state. */
    static getType(): string {
        return "text-editor-mermaid";
    }

    /** Preserve source and identity when Lexical copies its immutable state. */
    static clone(node: MermaidNode): MermaidNode {
        return new MermaidNode(node.__source, node.__key);
    }

    /** Restore diagram source from serialized clipboard or editor state. */
    static importJSON(serializedNode: SerializedMermaidNode): MermaidNode {
        return $createMermaidNode(serializedNode.source);
    }

    /** Recognize only explicitly marked diagram source in saved or pasted HTML. */
    static importDOM(): DOMConversionMap {
        return { pre: getMermaidConversion };
    }

    /** Create a keyboard-reachable diagram whose children are owned by the renderer. */
    createDOM(_config: EditorConfig, _editor: LexicalEditor): HTMLElement {
        const element = document.createElement("div");
        element.className = "text-editor-mermaid-node my-3 overflow-x-auto rounded-xl border border-gray-200 p-3";
        element.contentEditable = "false";
        element.dataset.mermaidNodeKey = this.getKey();
        element.tabIndex = 0;
        element.setAttribute("role", "button");
        element.setAttribute("aria-label", _("Mermaid diagram. Press Enter to edit."));
        element.title = _("Double-click to edit diagram");
        void renderNodePreview(element, this.__source);
        return element;
    }

    /** Refresh a changed source without replacing the selected diagram wrapper. */
    updateDOM(previous: MermaidNode, element: HTMLElement): boolean {
        if (previous.__source !== this.__source) void renderNodePreview(element, this.__source);
        element.dataset.mermaidNodeKey = this.getKey();
        return false;
    }

    /** Keep rendering in the native DOM without requiring a framework decorator. */
    decorate(_editor: LexicalEditor, _config: EditorConfig): null {
        return null;
    }

    /** Store escaped source rather than renderer-generated SVG or editor controls. */
    exportDOM(): DOMExportOutput {
        const element = document.createElement("pre");
        element.setAttribute(MERMAID_ATTRIBUTE, "true");
        const code = document.createElement("code");
        code.textContent = this.__source;
        element.appendChild(code);
        return { element };
    }

    /** Retain the source in Lexical's JSON clipboard representation. */
    exportJSON(): SerializedMermaidNode {
        return { ...super.exportJSON(), source: this.__source, type: "text-editor-mermaid", version: 1 };
    }

    /** Return the source as a useful plain-text clipboard representation. */
    getTextContent(): string {
        return this.getSource();
    }

    /** Read the latest source from immutable editor state. */
    getSource(): string {
        return this.getLatest().__source;
    }

    /** Replace source through Lexical so edits participate in undo and HTML saving. */
    setSource(source: string): this {
        const writable = this.getWritable();
        writable.__source = source;
        return writable;
    }

    /** Keep diagrams as standalone blocks rather than inline text decorations. */
    isInline(): boolean {
        return false;
    }

    /** Allow keyboard selection and normal editor deletion of the diagram block. */
    isKeyboardSelectable(): boolean {
        return true;
    }
}

/** Create a registered diagram node inside the active editor update. */
export function $createMermaidNode(source: string): MermaidNode {
    return $applyNodeReplacement(new MermaidNode(source));
}

/** Identify diagram nodes before reading or mutating their source. */
export function $isMermaidNode(node: LexicalNode | null | undefined): node is MermaidNode {
    return node instanceof MermaidNode;
}
