import {
    $createParagraphNode,
    $createTextNode,
    $getNodeByKey,
    $getRoot,
    $getSelection,
    $insertNodes,
    $isRangeSelection,
    type LexicalEditor,
    type NodeKey,
} from "lexical";

import { $createImageNode, ImageNode } from "../nodes/ImageNode";

type ImageBehaviorState = {
    fileInput: HTMLInputElement | null;
    pendingImageTargetKey: NodeKey | null;
    selectedImageNodeKey: NodeKey | null;
    resizeState: { nodeKey: NodeKey; startX: number; startWidth: number } | null;
    rootElement: HTMLElement | null;
    handleClick: (event: Event) => void;
    handleMouseDown: (event: MouseEvent) => void;
    handleKeyDown: (event: KeyboardEvent) => void;
    handleResizeMove: (event: MouseEvent) => void;
    handleResizeEnd: () => void;
};

const imageBehaviorStates = new WeakMap<LexicalEditor, ImageBehaviorState>();

export function registerImageBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    const state = {
        fileInput: null,
        pendingImageTargetKey: null,
        selectedImageNodeKey: null,
        resizeState: null,
        rootElement: editor.getRootElement(),
    } as ImageBehaviorState;

    state.handleClick = handleEditorClick(editor, state);
    state.handleMouseDown = handleEditorMouseDown(editor, state);
    state.handleKeyDown = handleEditorKeyDown(editor, state);
    state.handleResizeMove = handleImageResizeMove(editor, state);
    state.handleResizeEnd = handleImageResizeEnd(state);

    ensureImageInput(editor, host, state);

    const rootElement = state.rootElement;
    rootElement?.addEventListener("click", state.handleClick);
    rootElement?.addEventListener("mousedown", state.handleMouseDown);
    rootElement?.addEventListener("keydown", state.handleKeyDown);
    imageBehaviorStates.set(editor, state);

    return () => {
        rootElement?.removeEventListener("click", state.handleClick);
        rootElement?.removeEventListener("mousedown", state.handleMouseDown);
        rootElement?.removeEventListener("keydown", state.handleKeyDown);
        document.removeEventListener("mousemove", state.handleResizeMove);
        document.removeEventListener("mouseup", state.handleResizeEnd);
        state.fileInput?.remove();
        state.fileInput = null;
        imageBehaviorStates.delete(editor);
    };
}

export function promptImageUpload(editor: LexicalEditor): void {
    const state = imageBehaviorStates.get(editor);
    state?.fileInput?.click();
}

function handleEditorClick(editor: LexicalEditor, state: ImageBehaviorState): (event: Event) => void {
    return (event: Event) => {
        const target = event.target as HTMLElement | null;
        const imageWrapper = target?.closest<HTMLElement>(".text-editor-image-node");
        const imageNodeKey = imageWrapper?.dataset.imageNodeKey ?? null;

        if (!imageNodeKey) {
            setSelectedImageNodeKey(editor, state, null);
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        state.rootElement?.focus();
        setSelectedImageNodeKey(editor, state, imageNodeKey);

        if (target?.closest("[data-image-resize-handle]")) {
            return;
        }

        if ((event as MouseEvent).detail === 2) {
            state.pendingImageTargetKey = imageNodeKey;
            promptImageUpload(editor);
        }
    };
}

function handleEditorMouseDown(editor: LexicalEditor, state: ImageBehaviorState): (event: MouseEvent) => void {
    return (event: MouseEvent) => {
        const target = event.target as HTMLElement | null;
        const resizeHandle = target?.closest<HTMLElement>("[data-image-resize-handle]");
        const nodeKey = resizeHandle?.dataset.imageResizeHandle;
        if (!nodeKey) return;

        const wrapper = resizeHandle.closest<HTMLElement>(".text-editor-image-node");
        const image = wrapper?.querySelector<HTMLImageElement>("img");
        if (!image) return;

        event.preventDefault();
        event.stopPropagation();
        setSelectedImageNodeKey(editor, state, nodeKey);
        state.resizeState = {
            nodeKey,
            startX: event.clientX,
            startWidth: image.getBoundingClientRect().width,
        };

        document.addEventListener("mousemove", state.handleResizeMove);
        document.addEventListener("mouseup", state.handleResizeEnd);
    };
}

function handleEditorKeyDown(editor: LexicalEditor, state: ImageBehaviorState): (event: KeyboardEvent) => void {
    return (event: KeyboardEvent) => {
        if (!state.selectedImageNodeKey) return;
        if (event.key !== "Backspace" && event.key !== "Delete") return;

        event.preventDefault();
        event.stopPropagation();
        const nodeKey = state.selectedImageNodeKey;

        editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if (node instanceof ImageNode) {
                node.remove();
            }
        });

        setSelectedImageNodeKey(editor, state, null);
    };
}

function handleImageResizeMove(editor: LexicalEditor, state: ImageBehaviorState): (event: MouseEvent) => void {
    return (event: MouseEvent) => {
        if (!state.resizeState) return;

        const nextWidth = Math.max(
            120,
            Math.min(900, state.resizeState.startWidth + (event.clientX - state.resizeState.startX)),
        );

        editor.update(() => {
            const node = $getNodeByKey(state.resizeState?.nodeKey || "");
            if (node instanceof ImageNode) {
                node.setWidth(Math.round(nextWidth));
            }
        });
    };
}

function handleImageResizeEnd(state: ImageBehaviorState): () => void {
    return () => {
        state.resizeState = null;
        document.removeEventListener("mousemove", state.handleResizeMove);
        document.removeEventListener("mouseup", state.handleResizeEnd);
    };
}

function setSelectedImageNodeKey(
    editor: LexicalEditor,
    state: ImageBehaviorState,
    nodeKey: NodeKey | null,
): void {
    state.selectedImageNodeKey = nodeKey;

    state.rootElement
        ?.querySelectorAll<HTMLElement>(".text-editor-image-node")
        .forEach((element) => {
            const isSelected = element.dataset.imageNodeKey === nodeKey;
            const image = element.querySelector("img");
            const handle = element.querySelector("[data-image-resize-handle]");

            element.classList.toggle("text-editor-image-node-selected", isSelected);
            image?.classList.toggle("ring-2", isSelected);
            image?.classList.toggle("ring-blue-500", isSelected);
            image?.classList.toggle("ring-offset-2", isSelected);
            handle?.classList.toggle("hidden", !isSelected);
        });
}

function ensureImageInput(editor: LexicalEditor, host: HTMLElement, state: ImageBehaviorState): void {
    if (state.fileInput) return;

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
                if (state.pendingImageTargetKey) {
                    replaceImage(editor, state, state.pendingImageTargetKey, result, file.name || "Image");
                } else {
                    insertImage(editor, state, result, file.name || "Image");
                }
            }
            state.pendingImageTargetKey = null;
            input.value = "";
        };
        reader.readAsDataURL(file);
    });

    host.appendChild(input);
    state.fileInput = input;
}

function insertImage(editor: LexicalEditor, state: ImageBehaviorState, src: string, altText: string): void {
    state.rootElement?.focus();
    editor.update(() => {
        const imageNode = $createImageNode(src, altText);
        const trailingParagraph = $createParagraphNode();
        trailingParagraph.append($createTextNode(""));

        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
            $insertNodes([imageNode, trailingParagraph]);
        } else {
            $getRoot().append(imageNode, trailingParagraph);
        }

        trailingParagraph.selectStart();
    });
}

function replaceImage(
    editor: LexicalEditor,
    state: ImageBehaviorState,
    nodeKey: NodeKey,
    src: string,
    altText: string,
): void {
    editor.update(() => {
        const node = $getNodeByKey(nodeKey);
        if (node instanceof ImageNode) {
            node.setImageData(src, altText);
        }
    });

    setSelectedImageNodeKey(editor, state, nodeKey);
}
