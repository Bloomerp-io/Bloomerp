import {
    $applyNodeReplacement,
    type DOMConversionMap,
    type DOMExportOutput,
    type EditorConfig,
    ElementNode,
    type LexicalEditor,
    type NodeKey,
} from "lexical";

export default class SpanNode extends ElementNode {
    constructor(key?: NodeKey) {
        super(key);
    }

    static getType(): string {
        return 'text-editor-span'
    }

    static clone(node: SpanNode): SpanNode {
        return new SpanNode(node.__key);
    }

    static importDOM(): DOMConversionMap | null {
        return {
            span: () => ({
                conversion: () => ({
                    node: $createSpanNode(),
                }),
                priority: 1,
            }),
        };
    }

    createDOM(_config: EditorConfig, _editor: LexicalEditor): HTMLElement {
        const element = document.createElement('span')
        return element
    }

    updateDOM(): boolean {
        return false;
    }

    exportDOM(_editor: LexicalEditor): DOMExportOutput {
        const element = document.createElement('span');
        return { element };
    }

    isInline(): boolean {
        return true;
    }
}


export function $createSpanNode(): SpanNode {
    return $applyNodeReplacement(new SpanNode());
}

export function $isSpanNode(node: ElementNode): node is SpanNode {
    return node instanceof SpanNode;
}
