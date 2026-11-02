import { $generateNodesFromDOM } from "@lexical/html";
import { $getNodeByKey, $insertNodes, $isElementNode, COMMAND_PRIORITY_HIGH, PASTE_COMMAND, type LexicalEditor, type LexicalNode, type NodeKey } from "lexical";
import { $createFileImageNode, FileImageNode } from "../text_editor/nodes/FileImageNode";
import { $createImageNode, $insertImageNode, ImageNode } from "../text_editor/nodes/ImageNode";
import { uploadReferenceFile } from "../text_editor/utils/referencePicker";

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;

/** Decode only bounded clipboard image data, without fetching clipboard URLs. */
function clipboardImage(source: string): File {
    const match = /^data:(image\/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/]*={0,2})$/i.exec(source);
    if (!match || match[2].length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4) {
        throw new RangeError("Paste a supported image smaller than 20 MB.");
    }
    const binary = atob(match[2]);
    if (binary.length > MAX_IMAGE_BYTES) throw new RangeError("Paste an image smaller than 20 MB.");
    const bytes = Uint8Array.from(binary, (character: string): number => character.charCodeAt(0));
    return new File([bytes], `pasted-image.${match[1].split("/")[1]}`, { type: match[1].toLowerCase() });
}

/** Store clipboard images only in email composers and replace each occurrence at its original position. */
export function registerEmailImagePaste(editor: LexicalEditor, host: HTMLElement, showError: (error: unknown) => void): () => void {
    const lifecycle = new AbortController();
    const previews = new Set<string>();

    /** Replace a pending occurrence only while its editor and original node still exist. */
    async function uploadImage(key: NodeKey, file: File): Promise<void> {
        try {
            const reference = await uploadReferenceFile(host, file, lifecycle.signal);
            if (lifecycle.signal.aborted) return;
            /** Keep edits, removals, and neighboring paragraphs made during the upload. */
            function replacePendingImage(): void {
                const previous = $getNodeByKey(key);
                if (!(previous instanceof ImageNode) || !previous.isAttached()) return;
                const source = `${host.dataset.referenceServeUrl}?file_id=${encodeURIComponent(reference.target_id)}`;
                previous.replace($createFileImageNode({ ...reference, label: previous.__altText }, source, previous.__width));
            }
            editor.update(replacePendingImage, { discrete: true });
        } catch (error: unknown) {
            if (!lifecycle.signal.aborted) showError(error);
        }
    }

    /** Consume image files or embedded image HTML while leaving normal and stored-reference paste unchanged. */
    function pasteImages(event: ClipboardEvent | InputEvent | KeyboardEvent): boolean {
        if (!(event instanceof ClipboardEvent) || !event.clipboardData || !editor.isEditable() || host.dataset.disabled === "true") return false;
        const files = Array.from(event.clipboardData.files).filter((file: File): boolean => file.type.startsWith("image/"));
        const html = event.clipboardData.getData("text/html");
        const document = new DOMParser().parseFromString(html, "text/html");
        const imageElements = [...document.querySelectorAll<HTMLImageElement>("img:not([data-reference-kind=file])")];
        const embedded = imageElements.some((image: HTMLImageElement): boolean => image.getAttribute("src")?.startsWith("data:") ?? false);
        if (!files.length && !embedded) return false;
        if (html.trim() && !embedded && imageElements.length !== files.length) return false;
        event.preventDefault();
        const pending: Array<{ key: NodeKey; file: File }> = [];
        try {
            if (files.some((file: File): boolean => !/^image\/(png|jpeg|gif|webp)$/.test(file.type))) throw new RangeError("Inline email images must be PNG, JPEG, GIF or WebP.");
            if (imageElements.length && (embedded || imageElements.length === files.length)) {
                const uploads = new Map<string, File>();
                for (const [index, image] of imageElements.entries()) {
                    const source = image.getAttribute("src") ?? "";
                    if (!source.startsWith("data:") && (imageElements.length !== files.length || !files[index])) continue;
                    const file = source.startsWith("data:") ? clipboardImage(source) : files[index];
                    if (file.size > MAX_IMAGE_BYTES) throw new RangeError("Paste an image smaller than 20 MB.");
                    const preview = URL.createObjectURL(file);
                    previews.add(preview);
                    uploads.set(preview, file);
                    image.src = preview;
                }
                for (const element of document.querySelectorAll<HTMLElement>("[data-reference-kind]")) element.dataset.occurrenceId = crypto.randomUUID();
                const nodes = $generateNodesFromDOM(editor, document);
                /** Match imported image nodes to the local clipboard bytes before insertion. */
                function collectImages(node: LexicalNode): void {
                    if (node instanceof ImageNode && !(node instanceof FileImageNode)) {
                        const file = uploads.get(node.__src);
                        if (file) pending.push({ key: node.getKey(), file });
                    } else if ($isElementNode(node)) {
                        for (const child of node.getChildren()) collectImages(child);
                    }
                }
                for (const node of nodes) collectImages(node);
                $insertNodes(nodes);
            } else {
                if (files.some((file: File): boolean => file.size > MAX_IMAGE_BYTES)) throw new RangeError("Paste an image smaller than 20 MB.");
                for (const file of files) {
                    const preview = URL.createObjectURL(file);
                    previews.add(preview);
                    const node = $createImageNode(preview, file.name);
                    $insertImageNode(node);
                    pending.push({ key: node.getKey(), file });
                }
            }
            for (const { key, file } of pending) void uploadImage(key, file);
        } catch (error: unknown) {
            showError(error instanceof RangeError ? error : new RangeError("This pasted image could not be read. Try uploading it instead."));
        }
        return true;
    }

    const unregister = editor.registerCommand(PASTE_COMMAND, pasteImages, COMMAND_PRIORITY_HIGH);
    /** Cancel uploads and release local previews when this email composer is removed. */
    return function disposeEmailImagePaste(): void {
        lifecycle.abort();
        unregister();
        for (const preview of previews) URL.revokeObjectURL(preview);
        previews.clear();
    };
}
