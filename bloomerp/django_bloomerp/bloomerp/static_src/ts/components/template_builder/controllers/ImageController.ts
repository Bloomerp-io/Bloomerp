import {
    $createParagraphNode,
    $createTextNode,
    $getNodeByKey,
    type LexicalEditor,
    type LexicalNode,
} from "lexical";

import { $createImageNode, ImageNode } from "../nodes/ImageNode";

type ImageControllerOptions = {
    host: HTMLElement;
    editor: LexicalEditor;
    editorRoot: HTMLDivElement;
    insertBlockNode: (node: LexicalNode) => void;
};

export class ImageController {
    private readonly host: HTMLElement;
    private readonly editor: LexicalEditor;
    private readonly editorRoot: HTMLDivElement;
    private readonly insertBlockNode: (node: LexicalNode) => void;
    private imageInput: HTMLInputElement | null = null;
    private pendingImageTargetKey: string | null = null;
    private selectedImageNodeKey: string | null = null;
    private imageResizeState: { nodeKey: string; startX: number; startWidth: number } | null = null;

    constructor(options: ImageControllerOptions) {
        this.host = options.host;
        this.editor = options.editor;
        this.editorRoot = options.editorRoot;
        this.insertBlockNode = options.insertBlockNode;
    }

    mount(): void {
        this.editorRoot.addEventListener("click", this.handleEditorClick);
        this.editorRoot.addEventListener("mousedown", this.handleEditorMouseDown);
        this.editorRoot.addEventListener("keydown", this.handleEditorKeyDown);
        this.ensureImageInput();
    }

    destroy(): void {
        this.editorRoot.removeEventListener("click", this.handleEditorClick);
        this.editorRoot.removeEventListener("mousedown", this.handleEditorMouseDown);
        this.editorRoot.removeEventListener("keydown", this.handleEditorKeyDown);
        document.removeEventListener("mousemove", this.handleImageResizeMove);
        document.removeEventListener("mouseup", this.handleImageResizeEnd);
        this.imageInput?.remove();
        this.imageInput = null;
    }

    promptImageUpload(): void {
        this.imageInput?.click();
    }

    private handleEditorClick = (event: Event): void => {
        const target = event.target as HTMLElement | null;
        const imageWrapper = target?.closest<HTMLElement>(".template-builder-image-node");
        const imageNodeKey = imageWrapper?.dataset.imageNodeKey;

        if (!imageNodeKey) {
            this.setSelectedImageNodeKey(null);
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        this.setSelectedImageNodeKey(imageNodeKey);

        if ((target as HTMLElement | null)?.closest("[data-image-resize-handle]")) {
            return;
        }

        if ((event as MouseEvent).detail === 2) {
            this.pendingImageTargetKey = imageNodeKey;
            this.promptImageUpload();
        }
    };

    private handleEditorMouseDown = (event: MouseEvent): void => {
        const target = event.target as HTMLElement | null;
        const resizeHandle = target?.closest<HTMLElement>("[data-image-resize-handle]");
        const nodeKey = resizeHandle?.dataset.imageResizeHandle;
        if (!nodeKey) return;

        const wrapper = resizeHandle.closest<HTMLElement>(".template-builder-image-node");
        const image = wrapper?.querySelector<HTMLImageElement>("img");
        if (!image) return;

        event.preventDefault();
        event.stopPropagation();
        this.setSelectedImageNodeKey(nodeKey);
        this.imageResizeState = {
            nodeKey,
            startX: event.clientX,
            startWidth: image.getBoundingClientRect().width,
        };

        document.addEventListener("mousemove", this.handleImageResizeMove);
        document.addEventListener("mouseup", this.handleImageResizeEnd);
    };

    private handleEditorKeyDown = (event: KeyboardEvent): void => {
        if (!this.selectedImageNodeKey) return;
        if (event.key !== "Backspace" && event.key !== "Delete") return;

        event.preventDefault();
        event.stopPropagation();
        const nodeKey = this.selectedImageNodeKey;

        this.editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if (node instanceof ImageNode) {
                node.remove();
            }
        });

        this.setSelectedImageNodeKey(null);
    };

    private handleImageResizeMove = (event: MouseEvent): void => {
        if (!this.imageResizeState) return;

        const nextWidth = Math.max(
            120,
            Math.min(700, this.imageResizeState.startWidth + (event.clientX - this.imageResizeState.startX))
        );

        this.editor.update(() => {
            const node = $getNodeByKey(this.imageResizeState?.nodeKey || "");
            if (node instanceof ImageNode) {
                node.setWidth(Math.round(nextWidth));
            }
        });
    };

    private handleImageResizeEnd = (): void => {
        this.imageResizeState = null;
        document.removeEventListener("mousemove", this.handleImageResizeMove);
        document.removeEventListener("mouseup", this.handleImageResizeEnd);
    };

    private setSelectedImageNodeKey(nodeKey: string | null): void {
        this.selectedImageNodeKey = nodeKey;

        this.editorRoot
            .querySelectorAll<HTMLElement>(".template-builder-image-node")
            .forEach((element) => {
                element.classList.toggle(
                    "template-builder-image-node-selected",
                    element.dataset.imageNodeKey === nodeKey
                );
            });
    }

    private ensureImageInput(): void {
        if (this.imageInput) return;

        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.className = "hidden";
        input.addEventListener("change", () => {
            const file = input.files?.[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result;
                if (typeof result === "string") {
                    if (this.pendingImageTargetKey) {
                        this.replaceImageBlock(this.pendingImageTargetKey, result, file.name || "Document image");
                    } else {
                        this.insertImageBlock(result, file.name || "Document image");
                    }
                }
                this.pendingImageTargetKey = null;
                input.value = "";
            };
            reader.readAsDataURL(file);
        });

        this.host.appendChild(input);
        this.imageInput = input;
    }

    private insertImageBlock(src: string, altText: string): void {
        this.editorRoot.focus();
        this.editor.update(() => {
            const imageNode = $createImageNode(src, altText);
            this.insertBlockNode(imageNode);

            const trailingParagraph = $createParagraphNode();
            trailingParagraph.append($createTextNode(""));
            imageNode.insertAfter(trailingParagraph);
            trailingParagraph.selectStart();
        });
    }

    private replaceImageBlock(nodeKey: string, src: string, altText: string): void {
        this.editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if (node instanceof ImageNode) {
                node.setImageData(src, altText);
            }
        });

        this.setSelectedImageNodeKey(nodeKey);
    }
}
