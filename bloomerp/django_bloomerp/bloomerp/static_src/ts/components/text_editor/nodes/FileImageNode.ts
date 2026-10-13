import { $applyNodeReplacement, type DOMConversion, type DOMConversionMap, type DOMConversionOutput, type DOMExportOutput, type NodeKey, type SerializedElementNode, type Spread } from "lexical";
import { ImageNode } from "./ImageNode";
import type { ReferenceTarget } from "./ReferenceNode";

type SerializedFileImage = Spread<{ reference: ReferenceTarget; src: string; width: number | null }, SerializedElementNode>;

/** Restore a stored image reference while retaining occurrence identity. */
function convertFileImage(element: HTMLElement): DOMConversionOutput {
    const image = element as HTMLImageElement;
    const width = Number.parseInt(image.style.width || image.getAttribute("width") || "", 10);
    return { node: $createFileImageNode({ kind: "file", target_id: image.dataset.targetId!, label: image.alt || "Image", occurrence_id: image.dataset.occurrenceId }, image.getAttribute("src") ?? "", Number.isNaN(width) ? null : width) };
}

/** Prefer stored references over ordinary external or legacy inline images. */
function fileImageConversion(element: HTMLElement): DOMConversion | null {
    return element.dataset.referenceKind === "file" ? { conversion: convertFileImage, priority: 4 } : null;
}

/** Extend image resizing with a stored file identity and stable occurrence. */
export class FileImageNode extends ImageNode {
    __reference: ReferenceTarget;
    /** Identify the stored-file image node. */
    static getType(): string { return "bloomerp-file-image"; }
    /** Preserve image identity through history and resize operations. */
    static clone(node: FileImageNode): FileImageNode { return new FileImageNode(node.__reference, node.__src, node.__width, node.__key); }
    /** Restore stored-file images from editor JSON. */
    static importJSON(value: SerializedFileImage): FileImageNode { return $createFileImageNode(value.reference, value.src, value.width); }
    /** Read saved image references before the ordinary image conversion. */
    static importDOM(): DOMConversionMap { return { img: fileImageConversion }; }
    /** Create a stored image without placing its bytes in editor content. */
    constructor(reference: ReferenceTarget, src: string, width: number | null = null, key?: NodeKey) {
        super(src, reference.label, width, key);
        this.__reference = { ...reference, occurrence_id: reference.occurrence_id ?? crypto.randomUUID() };
    }
    /** Save image identity alongside its serving URL and dimensions. */
    exportDOM(): DOMExportOutput {
        const output = super.exportDOM();
        const element = output.element as HTMLElement;
        element.dataset.referenceKind = "file";
        element.dataset.targetId = this.__reference.target_id;
        element.dataset.occurrenceId = this.__reference.occurrence_id!;
        return output;
    }
    /** Persist stored-file identity for clipboard and editor JSON. */
    exportJSON(): SerializedFileImage { return { ...super.exportJSON(), type: FileImageNode.getType(), version: 1, reference: this.__reference, src: this.__src, width: this.__width }; }
    /** Expose the specific image occurrence to the attachment chips. */
    getReference(): ReferenceTarget { return { ...this.getLatest().__reference }; }
}

/** Insert a stored image using the registered custom Lexical node. */
export function $createFileImageNode(reference: ReferenceTarget, src: string, width: number | null = null): FileImageNode { return $applyNodeReplacement(new FileImageNode(reference, src, width)); }
