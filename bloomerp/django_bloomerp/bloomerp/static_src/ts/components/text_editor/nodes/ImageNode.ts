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
        return "text-editor-image";
    }

    static clone(node: ImageNode): ImageNode {
        return new ImageNode(node.__src, node.__altText, node.__width, node.__key);
    }

    static importDOM(): DOMConversionMap | null {
        return {
            img: (domNode: HTMLElement) => ({
                conversion: () => {
                    const image = domNode as HTMLImageElement;
                    const parsedWidth = Number.parseInt(image.style.width || image.getAttribute("width") || "", 10);

                    return {
                        node: $createImageNode(
                            image.src,
                            image.alt || "Image",
                            Number.isNaN(parsedWidth) ? null : parsedWidth,
                        ),
                    };
                },
                priority: 2,
            }),
        };
    }

    constructor(src: string, altText = "Image", width: number | null = null, key?: NodeKey) {
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

    createDOM(_config: EditorConfig): HTMLElement {
        const wrapper = document.createElement("figure");
        wrapper.className = "text-editor-image-node relative my-3 inline-block max-w-full cursor-pointer";
        wrapper.contentEditable = "false";
        wrapper.dataset.imageNodeKey = this.getKey();
        wrapper.setAttribute("title", "Double click to replace image");

        const image = document.createElement("img");
        image.src = this.__src;
        image.alt = this.__altText;
        image.className = "block h-auto max-w-full rounded-lg border border-gray-200";
        if (this.__width) {
            image.style.width = `${this.__width}px`;
        }
        wrapper.appendChild(image);

        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = "text-editor-image-resize-handle absolute -right-2 -bottom-2 hidden h-4 w-4 cursor-nwse-resize rounded-full border-2 border-white bg-blue-600 shadow";
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
        dom.dataset.imageNodeKey = this.getKey();
        dom.setAttribute("title", "Double click to replace image");
        return false;
    }

    exportDOM(): DOMExportOutput {
        const element = document.createElement("img");
        element.setAttribute("src", this.__src);
        element.setAttribute("alt", this.__altText);

        const style = [
            this.__width ? `width:${this.__width}px` : "",
            "display:block",
            "max-width:100%",
            "height:auto",
        ].filter(Boolean).join(";");

        element.setAttribute("style", style);
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
