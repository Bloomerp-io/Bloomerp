import { $getSelection, $setSelection, $getRoot, $insertNodes, type BaseSelection, type LexicalEditor, $isRangeSelection } from "lexical";
import { getContextMenu, type ContextMenuItem, type ContextMenuSubmenu } from "@/utils/contextMenu";
import { getSdk } from "@/sdk/getSdk";
import { t } from "@/utils/i18n";
import { $createReferenceNode, type ReferenceTarget } from "../nodes/ReferenceNode";
import { $insertImageNode } from "../nodes/ImageNode";
import { $createFileImageNode } from "../nodes/FileImageNode";
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./wordSelector";

/** Upload one file node with CSRF protection and return its stable identity. */
export async function uploadReferenceFile(host: HTMLElement, file: File, signal?: AbortSignal): Promise<ReferenceTarget> {
    const data = new FormData();
    data.append("file", file);
    const csrf = document.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')?.value ?? "";
    const response = await fetch(host.dataset.referenceUploadUrl!, { method: "POST", body: data, headers: { "X-CSRFToken": csrf }, signal });
    if (!response.ok) throw new Error(t("File upload failed"));
    const result = await response.json() as { file_id: string; name: string };
    return { kind: "file", target_id: result.file_id, label: result.name };
}

/** Share searchable target selection between the toolbar and editor commands. */
export class ReferencePicker {
    private selection: BaseSelection | null = null;
    private inlineWord = "";
    private inlineSelection: BaseSelection | null = null;
    private inlineRequest: AbortController | null = null;
    private inlineTimer?: ReturnType<typeof setTimeout>;
    private readonly inlineMenu = getContextMenu(`inline-mentions-${crypto.randomUUID()}`);
    private readonly unregisterInline: () => void;
    private readonly menu = getContextMenu(`reference-picker-${crypto.randomUUID()}`);
    private readonly lifecycle = new AbortController();
    /** Bind reference insertion to this editor and its route metadata. */
    constructor(private readonly host: HTMLElement, private readonly editor: LexicalEditor) {
        this.inlineMenu.element.dataset.inlineMentionPicker = "true";
        this.unregisterInline = editor.registerUpdateListener(this.onInlineUpdate);
        host.addEventListener("focusout", this.dismissInline, { signal: this.lifecycle.signal });
    }
    /** Track a query typed after an at-sign without changing text or moving focus. */
    private onInlineUpdate = (): void => {
        const root = this.editor.getRootElement();
        let word = "";
        const picker = this;
        /** Capture the editor-owned query and range after the current edit commits. */
        function readInlineQuery(): void {
            const selection = $getSelection();
            if (root?.contains(document.activeElement) && $isRangeSelection(selection) && selection.isCollapsed()) {
                const current = getCurrentWordFromSelection();
                if (/^@[\p{L}\p{N}_.-]+$/u.test(current)) {
                    word = current;
                    picker.inlineSelection = selection.clone();
                }
            }
        }
        this.editor.getEditorState().read(readInlineQuery);
        if (word === this.inlineWord) return;
        this.inlineWord = word;
        clearTimeout(this.inlineTimer);
        this.inlineRequest?.abort();
        if (!word) {
            this.inlineMenu.hide();
            return;
        }
        if (this.inlineMenu.element.classList.contains("hidden")) {
            this.inlineMenu.showAt(this.caretPosition(), this.host, []);
            this.inlineMenu.element.setAttribute("aria-label", t("Mention suggestions"));
        }
        this.inlineMenu.setLoading(true);
        this.inlineTimer = setTimeout(this.loadInline.bind(this, word), 150);
    };
    /** Search staff suggestions while the query and caret remain in the editor. */
    private async loadInline(word: string): Promise<void> {
        const controller = new AbortController();
        this.inlineRequest = controller;
        try {
            const result = await getSdk().client.request<{ items: ReferenceTarget[] }>(this.host.dataset.referenceSearchUrl!, { query: { kind: "user", q: word.slice(1) }, signal: controller.signal });
            if (controller.signal.aborted || this.lifecycle.signal.aborted || this.inlineWord !== word || this.inlineMenu.element.classList.contains("hidden")) return;
            this.inlineMenu.showAt(this.caretPosition(), this.host, result.items.map(this.inlineItem));
            this.inlineMenu.element.setAttribute("aria-label", t("Mention suggestions"));
        } catch (error) {
            if (!controller.signal.aborted && !this.inlineMenu.element.classList.contains("hidden")) {
                this.inlineMenu.showAt(this.caretPosition(), this.host, [{ label: t("Search unavailable"), disabled: true }]);
                this.inlineMenu.element.setAttribute("aria-label", t("Mention suggestions"));
            }
        }
    }
    /** Bind a suggestion to replacing only the editor's pending mention query. */
    private inlineItem = (target: ReferenceTarget): ContextMenuItem => ({ label: target.label, icon: target.icon, onClick: this.insertInline.bind(this, target) });
    /** Replace the typed query only after the user explicitly chooses a suggestion. */
    private insertInline(target: ReferenceTarget): void {
        const word = this.inlineWord;
        const selection = this.inlineSelection?.clone() ?? null;
        const editor = this.editor;
        this.dismissInline();
        this.inlineWord = "";
        /** Restore the query range and replace its plain text with an atomic reference. */
        function replaceInlineQuery(): void {
            $setSelection(selection);
            if (getCurrentWordFromSelection() === word && removeTextFromCurrentSelection(word)) $insertNodes([$createReferenceNode(target)]);
        }
        editor.update(replaceInlineQuery, { discrete: true });
        editor.focus();
    }
    /** Dismiss suggestions without deleting the query, including on blur or teardown. */
    private dismissInline = (): void => {
        clearTimeout(this.inlineTimer);
        this.inlineRequest?.abort();
        this.inlineMenu.hide();
    };
    /** Open searchable targets beside the insertion caret before search takes focus. */
    open(kind: "user" | "object" | "file"): void {
        this.dismissInline();
        this.menu.showSubmenu(this.submenu(kind), this.host, this.caretPosition());
    }
    /** Measure the editor caret, using its active paragraph when the range is empty. */
    private caretPosition(): { x: number; y: number } {
        const root = this.editor.getRootElement();
        const selection = window.getSelection();
        if (root && selection?.rangeCount) {
            const range = selection.getRangeAt(0).cloneRange();
            if (root.contains(range.commonAncestorContainer)) {
                range.collapse(false);
                let rect = range.getBoundingClientRect();
                if (!rect.height && range.endContainer instanceof Text && range.endOffset > 0) {
                    range.setStart(range.endContainer, range.endOffset - 1);
                    rect = range.getBoundingClientRect();
                    if (rect.height) return { x: rect.right, y: rect.bottom + 4 };
                }
                if (rect.height) return { x: rect.left, y: rect.bottom + 4 };
            }
        }
        let anchor: HTMLElement | null = root;
        const editor = this.editor;
        /** Locate the saved paragraph when toolbar focus hides the native caret range. */
        function findAnchor(): void {
            const selection = $getSelection();
            if ($isRangeSelection(selection)) anchor = editor.getElementByKey(selection.anchor.key) ?? root;
        }
        editor.getEditorState().read(findAnchor);
        const rect = (anchor ?? this.host).getBoundingClientRect();
        const style = window.getComputedStyle(root ?? this.host);
        const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.2;
        return { x: rect.left + Number.parseFloat(style.paddingLeft || "0"), y: rect.top + Number.parseFloat(style.paddingTop || "0") + lineHeight + 4 };
    }
    /** Build a submenu with selection capture and cancellable searching. */
    submenu(kind: "user" | "object" | "file"): ContextMenuSubmenu {
        return { label: kind === "user" ? t("Mention") : kind === "object" ? t("Object") : t("Image"), onOpen: this.capture, search: { placeholder: t("Search…"), load: this.load.bind(this, kind) } };
    }
    /** Remove command text and retain the range before search takes focus. */
    private capture = (): void => {
        this.editor.update(this.removeTrigger, { discrete: true });
        this.editor.getEditorState().read(this.saveSelection);
    };
    /** Remove only the active slash or mention trigger. */
    private removeTrigger = (): void => {
        const word = getCurrentWordFromSelection();
        if (word.startsWith("@") || word.startsWith("/")) removeTextFromCurrentSelection(word);
    };
    /** Retain the committed selection for asynchronous target insertion. */
    private saveSelection = (): void => { this.selection = $getSelection()?.clone() ?? null; };
    /** Load readable target leaves, optionally offering a new image upload. */
    private async load(kind: "user" | "object" | "file", query: string, signal: AbortSignal): Promise<ContextMenuItem[]> {
        const result = await getSdk().client.request<{ items: ReferenceTarget[] }>(this.host.dataset.referenceSearchUrl!, { query: { kind, q: query, images: kind === "file" ? "true" : undefined }, signal });
        const items = result.items.map(this.toItem);
        if (kind === "file") items.unshift({ label: t("Upload image"), icon: "fa-solid fa-upload", onClick: this.upload });
        return items;
    }
    /** Bind each readable result to insertion at the retained selection. */
    private toItem = (target: ReferenceTarget): ContextMenuItem => ({ label: target.label, icon: target.icon, group: target.kind === "object" ? target.model_label : undefined, onClick: this.insert.bind(this, target) });
    /** Insert one reference with a new occurrence identity. */
    private insert(target: ReferenceTarget): void {
        const editor = this.editor;
        const selection = this.selection;
        const url = `${this.host.dataset.referenceServeUrl}?file_id=${encodeURIComponent(target.target_id)}`;
        /** Restore the range before adding the selected target. */
        function insertTarget(): void {
            $setSelection(selection?.clone() ?? null);
            if (!$getSelection()) $getRoot().selectEnd();
            if (target.kind === "file") {
                $insertImageNode($createFileImageNode(target, url));
            } else {
                $insertNodes([$createReferenceNode(target)]);
            }
        }
        editor.update(insertTarget, { discrete: true });
        editor.focus();
    }
    /** Select and upload an image without embedding its binary in the HTML. */
    private upload = (): void => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/png,image/jpeg,image/gif,image/webp,image/avif";
        input.addEventListener("change", this.uploadSelection.bind(this, input), { once: true, signal: this.lifecycle.signal });
        input.click();
    };
    /** Insert the uploaded file or surface the failed upload to the user. */
    private async uploadSelection(input: HTMLInputElement): Promise<void> {
        const file = input.files?.[0];
        if (!file) return;
        try { this.insert(await uploadReferenceFile(this.host, file, this.lifecycle.signal)); }
        catch (error) { if (!this.lifecycle.signal.aborted) window.alert(String(error)); }
    }
    /** Cancel requests and dismiss this editor's menu when removed. */
    destroy(): void {
        this.lifecycle.abort();
        this.unregisterInline();
        this.dismissInline();
        this.inlineMenu.destroy();
        this.menu.destroy();
    }
}
