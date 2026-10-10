import { $applyNodeReplacement, TextNode, type DOMConversionMap, type DOMConversion, type DOMConversionOutput, type DOMExportOutput, type EditorConfig, type NodeKey, type SerializedTextNode, type Spread } from "lexical";

export type ReferenceTarget = { kind: "user" | "object" | "file" | "label"; target_id: string; content_type_id?: number; label: string; icon?: string; url?: string; model_label?: string; occurrence_id?: string; field_id?: number };
type SerializedReference = Spread<{ reference: ReferenceTarget }, SerializedTextNode>;

/** Read an atomic inline reference from its stable HTML attributes. */
function convertReference(element: HTMLElement): DOMConversionOutput {
    const node = $createReferenceNode({ kind: element.dataset.referenceKind as "user" | "object", target_id: element.dataset.targetId!, content_type_id: element.dataset.targetContentTypeId ? Number(element.dataset.targetContentTypeId) : undefined, label: element.textContent ?? "", occurrence_id: element.dataset.occurrenceId });
    return { node, forChild: discardChild };
}

/** Keep the reference label atomic rather than importing nested text children. */
function discardChild(): null { return null; }

/** Match only spans carrying a supported reference identity. */
function referenceConversion(element: HTMLElement): DOMConversion | null {
    return ["user", "object"].includes(element.dataset.referenceKind ?? "") ? { conversion: convertReference, priority: 4 } : null;
}

/** Serialize one independently removable inline mention or object reference. */
export class ReferenceNode extends TextNode {
    __reference: ReferenceTarget;

    /** Identify this custom Lexical node. */
    static getType(): string { return "bloomerp-reference"; }
    /** Retain occurrence identity through undo and immutable editor updates. */
    static clone(node: ReferenceNode): ReferenceNode { return new ReferenceNode(node.__reference, node.__key); }
    /** Restore the serialized target and occurrence. */
    static importJSON(value: SerializedReference): ReferenceNode { return $createReferenceNode(value.reference); }
    /** Import the reference HTML emitted by the editor. */
    static importDOM(): DOMConversionMap { return { span: referenceConversion }; }
    /** Create a token with a persistent occurrence identity. */
    constructor(reference: ReferenceTarget, key?: NodeKey) {
        super(reference.label, key);
        this.__reference = { ...reference, occurrence_id: reference.occurrence_id ?? crypto.randomUUID() };
        this.__mode = 1;
    }
    /** Render an atomic reference with escaped text. */
    createDOM(config: EditorConfig): HTMLElement {
        const element = super.createDOM(config);
        this.decorate(element);
        return element;
    }
    /** Preserve the token element unless its target changes. */
    updateDOM(previous: ReferenceNode, element: HTMLElement, config: EditorConfig): boolean {
        const replace = super.updateDOM(previous, element, config);
        this.decorate(element);
        return replace;
    }
    /** Persist target and occurrence identity in portable HTML. */
    exportDOM(): DOMExportOutput {
        const element = document.createElement("span");
        element.textContent = this.__reference.label;
        this.decorate(element);
        return { element };
    }
    /** Persist the reference in Lexical clipboard and editor JSON. */
    exportJSON(): SerializedReference { return { ...super.exportJSON(), type: ReferenceNode.getType(), reference: this.__reference, version: 1 }; }
    /** Expose immutable reference data to scoped chip synchronization. */
    getReference(): ReferenceTarget { return { ...this.getLatest().__reference }; }
    /** Apply stable attributes to both saved HTML and the editor token. */
    private decorate(element: HTMLElement): void {
        element.dataset.referenceKind = this.__reference.kind;
        element.dataset.targetId = this.__reference.target_id;
        element.dataset.occurrenceId = this.__reference.occurrence_id!;
        if (this.__reference.content_type_id) element.dataset.targetContentTypeId = String(this.__reference.content_type_id);
        element.classList.add("text-primary", "font-medium");
    }
    /** Prevent users from editing only part of the reference label. */
    isTextEntity(): boolean { return true; }
}

/** Insert a reference using Lexical's registered node replacement mechanism. */
export function $createReferenceNode(reference: ReferenceTarget): ReferenceNode { return $applyNodeReplacement(new ReferenceNode(reference)); }
