import {
    $applyNodeReplacement,
    ElementNode,
    type DOMConversionMap,
    type DOMExportOutput,
    type EditorConfig,
    type NodeKey,
} from "lexical";

export class ImageNode extends ElementNode {
    __src: string;
    __altText: string;
    __width: number | null;

    static getType(): string {
        return "template-image";
    }

    static clone(node: ImageNode): ImageNode {
        return new ImageNode(node.__src, node.__altText, node.__width, node.__key);
    }

    static importDOM(): DOMConversionMap | null {
        return {
            img: (domNode: HTMLElement) => ({
                conversion: () => {
                    const image = domNode as HTMLImageElement;
                    return {
                        node: $createImageNode(
                            image.src,
                            image.alt || "Document image",
                            image.width || null
                        ),
                    };
                },
                priority: 2,
            }),
        };
    }

    constructor(src: string, altText = "Document image", width: number | null = null, key?: NodeKey) {
        super(key);
        this.__src = src;
        this.__altText = altText;
        this.__width = width;
    }

    setImageData(src: string, altText: string, width?: number | null): this {
        const writable = this.getWritable() as ImageNode;
        writable.__src = src;
        writable.__altText = altText;
        if (typeof width !== "undefined") {
            writable.__width = width;
        }
        return writable as this;
    }

    setWidth(width: number | null): this {
        const writable = this.getWritable() as ImageNode;
        writable.__width = width;
        return writable as this;
    }

    getWidth(): number | null {
        return this.getLatest().__width;
    }

    createDOM(_config: EditorConfig): HTMLElement {
        const wrapper = document.createElement("figure");
        wrapper.className = "template-builder-image-node";
        wrapper.contentEditable = "false";
        wrapper.dataset.imageNodeKey = this.getKey();
        wrapper.setAttribute("title", "Click to replace image");

        const image = document.createElement("img");
        image.src = this.__src;
        image.alt = this.__altText;
        image.style.maxWidth = "100%";
        image.style.height = "auto";
        image.style.display = "block";
        if (this.__width) {
            image.style.width = `${this.__width}px`;
        }
        image.style.borderRadius = "12px";
        image.style.border = "1px solid #cbd5e1";
        wrapper.appendChild(image);

        const hint = document.createElement("figcaption");
        hint.textContent = "Click image to replace";
        hint.style.marginTop = "0.5rem";
        hint.style.fontSize = "0.75rem";
        hint.style.color = "#64748b";
        wrapper.appendChild(hint);

        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = "template-builder-image-resize-handle";
        handle.setAttribute("data-image-resize-handle", this.getKey());
        handle.setAttribute("aria-label", "Resize image");
        wrapper.appendChild(handle);

        return wrapper;
    }

    updateDOM(prevNode: ImageNode, dom: HTMLElement): boolean {
        if (
            prevNode.__src === this.__src &&
            prevNode.__altText === this.__altText &&
            prevNode.__width === this.__width
        ) {
            return false;
        }

        const image = dom.querySelector("img");
        if (image) {
            image.src = this.__src;
            image.alt = this.__altText;
            image.style.width = this.__width ? `${this.__width}px` : "";
        }
        dom.setAttribute("data-image-node-key", this.getKey());
        dom.setAttribute("title", "Click to replace image");
        return false;
    }

    exportDOM(): DOMExportOutput {
        const element = document.createElement("img");
        element.setAttribute("src", this.__src);
        element.setAttribute("alt", this.__altText);
        const inlineWidth = this.__width ? `width:${this.__width}px;` : "";
        element.setAttribute("style", `${inlineWidth}display:block;max-width:100%;height:auto;border:1px solid #cbd5e1;border-radius:12px;`);
        return { element };
    }

    getTextContent(): string {
        return this.__altText || "[Image]";
    }

    canBeEmpty(): boolean {
        return true;
    }

    canInsertTextBefore(): boolean {
        return false;
    }

    canInsertTextAfter(): boolean {
        return false;
    }

    isInline(): boolean {
        return false;
    }
}

export function $createImageNode(src: string, altText?: string, width?: number | null): ImageNode {
    return $applyNodeReplacement(new ImageNode(src, altText, width ?? null));
}
