import {
    $applyNodeReplacement,
    type DOMConversionMap,
    type DOMExportOutput,
    type EditorConfig,
    ElementNode,
    type LexicalEditor,
    type NodeKey,
    type SerializedElementNode,
    type Spread,
} from "lexical"


type SerializedHtmlNode = Spread<{
    html: string,
    type: 'text-editor-html',
    version: 1,
}, SerializedElementNode>

const HTML_NODE_ATTRIBUTE = 'data-text-editor-html-node'

export default class HtmlNode extends ElementNode {
    __html: string

    constructor(html: string, key?: NodeKey) {
        super(key)
        this.__html = html
    }

    static getType(): string {
        return 'text-editor-html'
    }

    static clone(node: HtmlNode): HtmlNode {
        return new HtmlNode(node.__html, node.__key)
    }

    static importJSON(serializedNode: SerializedHtmlNode): HtmlNode {
        return $createHtmlNode(serializedNode.html)
    }

    static importDOM(): DOMConversionMap | null {
        return {
            div: (domNode: HTMLElement) => {
                if (!domNode.hasAttribute(HTML_NODE_ATTRIBUTE)) {
                    return null
                }

                return {
                    conversion: () => ({
                        forChild: () => null,
                        node: $createHtmlNode(normalizeHtmlNodeHtml(domNode.innerHTML)),
                    }),
                    priority: 3,
                }
            },
        }
    }

    createDOM(_config: EditorConfig, _editor: LexicalEditor): HTMLElement {
        const element = document.createElement('div')
        element.className = 'text-editor-html-node'
        element.contentEditable = 'false'
        element.dataset.htmlNodeKey = this.getKey()
        element.setAttribute(HTML_NODE_ATTRIBUTE, 'true')
        element.setAttribute('title', 'Double click to edit HTML')
        applyHtmlNodeEditorStyles(element)
        element.innerHTML = this.__html

        return element
    }

    updateDOM(prevNode: HtmlNode, dom: HTMLElement): boolean {
        if (prevNode.__html !== this.__html) {
            dom.innerHTML = this.__html
        }
        dom.dataset.htmlNodeKey = this.getKey()
        dom.setAttribute(HTML_NODE_ATTRIBUTE, 'true')
        applyHtmlNodeEditorStyles(dom)
        return false
    }

    exportDOM(_editor: LexicalEditor): DOMExportOutput {
        const element = document.createElement('div')
        const html = normalizeHtmlNodeHtml(this.__html)
        element.setAttribute(HTML_NODE_ATTRIBUTE, 'true')
        element.innerHTML = html
        return {
            element,
            after: (generatedElement) => {
                if (generatedElement instanceof HTMLElement) {
                    generatedElement.innerHTML = html
                }

                return generatedElement instanceof HTMLElement || generatedElement instanceof Text
                    ? generatedElement
                    : element
            },
        }
    }

    exportJSON(): SerializedHtmlNode {
        return {
            ...super.exportJSON(),
            html: this.__html,
            type: 'text-editor-html',
            version: 1,
        }
    }

    getTextContent(): string {
        const element = document.createElement('div')
        element.innerHTML = this.__html
        return element.textContent || ''
    }

    getHtml(): string {
        return this.getLatest().__html
    }

    setHtml(html: string): this {
        const writable = this.getWritable() as HtmlNode
        writable.__html = normalizeHtmlNodeHtml(html)
        return writable as this
    }

    canBeEmpty(): boolean {
        return true
    }

    canInsertTextBefore(): boolean {
        return false
    }

    canInsertTextAfter(): boolean {
        return false
    }

    isInline(): boolean {
        return false
    }
}

export function $createHtmlNode(html: string): HtmlNode {
    return $applyNodeReplacement(new HtmlNode(html))
}

export function $isHtmlNode(node: ElementNode): node is HtmlNode {
    return node instanceof HtmlNode
}

function applyHtmlNodeEditorStyles(element: HTMLElement): void {
    element.style.whiteSpace = 'normal'
    element.style.wordBreak = 'normal'
    element.style.overflowWrap = 'normal'
}

function normalizeHtmlNodeHtml(html: string): string {
    const element = document.createElement('div')
    element.innerHTML = html

    while (element.lastChild) {
        const lastChild = element.lastChild

        if (lastChild.nodeType === Node.TEXT_NODE && !lastChild.textContent?.trim()) {
            lastChild.remove()
            continue
        }

        if (lastChild instanceof HTMLBRElement) {
            lastChild.remove()
            continue
        }

        break
    }

    return element.innerHTML
}
