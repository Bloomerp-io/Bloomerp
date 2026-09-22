import {
    $applyNodeReplacement,
    $createTextNode,
    ElementNode,
    type DOMConversion,
    type DOMConversionMap,
    type DOMConversionOutput,
    type DOMExportOutput,
    type EditorConfig,
    type LexicalNode,
    type NodeKey,
    type SerializedElementNode,
} from "lexical";

/** Ignore nested HTML nodes after importing their plain code text. */
function ignoreCodeBlockChild(_node: LexicalNode, _parent: LexicalNode | null | undefined): null {
    return null;
}

/** Convert a pre element into one editable block of literal source text. */
function convertCodeBlock(element: HTMLElement): DOMConversionOutput {
    const block = $createCodeBlockNode();
    const content = element.querySelector("code") ?? element;
    if (content.textContent) {
        block.append($createTextNode(content.textContent));
    }
    return { node: block, forChild: ignoreCodeBlockChild };
}

/** Register the pre element conversion with Lexical's HTML importer. */
function getCodeBlockConversion(_element: HTMLElement): DOMConversion {
    return { conversion: convertCodeBlock, priority: 3 };
}

/** An editable block whose HTML representation keeps source whitespace intact. */
export class CodeBlockNode extends ElementNode {
    /** Return the stable Lexical node type used in serialized editor states. */
    static getType(): string {
        return "text-editor-code-block";
    }

    /** Copy a code block while retaining its identity in the editor state. */
    static clone(node: CodeBlockNode): CodeBlockNode {
        return new CodeBlockNode(node.__key);
    }

    /** Restore a code block from a serialized Lexical editor state. */
    static importJSON(_serializedNode: SerializedElementNode): CodeBlockNode {
        return $createCodeBlockNode();
    }

    /** Read saved and pasted preformatted HTML as a single code block. */
    static importDOM(): DOMConversionMap {
        return {
            pre: getCodeBlockConversion,
        };
    }

    /** Create an editable preformatted block in the editor. */
    createDOM(_config: EditorConfig): HTMLElement {
        const element = document.createElement("pre");
        element.className = "bloomerp-text-editor-code-block";
        return element;
    }

    /** Keep the existing pre element when its text children change. */
    updateDOM(_prevNode: CodeBlockNode, _dom: HTMLElement): boolean {
        return false;
    }

    /** Save plain code text inside pre/code without editor-only text markup. */
    exportDOM(): DOMExportOutput {
        const element = document.createElement("pre");
        element.setAttribute("data-text-editor-code-block", "true");
        return {
            element,
            after: this.finishExport.bind(this),
        };
    }

    /** Replace generated editor child markup with plain code text. */
    private finishExport(
        generatedElement: HTMLElement | DocumentFragment | Text | null | undefined,
    ): HTMLElement | Text | null | undefined {
        if (!(generatedElement instanceof HTMLElement)) return null;
        const code = document.createElement("code");
        code.textContent = this.getTextContent();
        generatedElement.replaceChildren(code);
        return generatedElement;
    }

    /** Permit an empty code block while the user is typing. */
    canBeEmpty(): boolean {
        return true;
    }
}

/** Create a code block in the current Lexical update. */
export function $createCodeBlockNode(): CodeBlockNode {
    return $applyNodeReplacement(new CodeBlockNode());
}

/** Identify a code block among Lexical nodes. */
export function $isCodeBlockNode(node: unknown): node is CodeBlockNode {
    return node instanceof CodeBlockNode;
}
