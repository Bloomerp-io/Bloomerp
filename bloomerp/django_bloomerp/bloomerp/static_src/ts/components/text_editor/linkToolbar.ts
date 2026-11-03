import { $isLinkNode, type LinkNode } from "@lexical/link";
import {
    $getNearestNodeFromDOMNode, $getNodeByKey, $getSelection, $isRangeSelection,
    CLICK_COMMAND, COMMAND_PRIORITY_HIGH, type LexicalEditor, type LexicalNode,
} from "lexical";
import { normalizeLinkHref } from "./utils/linkBehavior.ts";
import { getContextMenuLayer } from "../../utils/contextMenuLayer.ts";
import { t } from "../../utils/i18n.ts";

/** Edit a clicked link by identity while retaining the editor's native selection highlight. */
export class LinkToolbar {
    public readonly element = document.createElement("form");
    private readonly href = document.createElement("input");
    private readonly open = document.createElement("a");
    private readonly lifecycle = new AbortController();
    private readonly unregister: (() => void)[];
    private readonly editor: LexicalEditor;
    private readonly host: HTMLElement;
    private key: string | null = null;

    /** Own the floating controls and all subscriptions for one editor instance. */
    public constructor(editor: LexicalEditor, host: HTMLElement) {
        this.editor = editor;
        this.host = host;
        this.element.className = "text-editor-selection-toolbar text-editor-link-toolbar";
        this.element.setAttribute("aria-label", t("Edit link"));
        this.element.dataset.editorLinkToolbar = host.dataset.editorId ?? "";
        this.element.hidden = true;
        if (typeof this.element.showPopover === "function") this.element.setAttribute("popover", "manual");
        this.href.className = "input";
        this.href.setAttribute("aria-label", t("Link URL"));
        this.href.required = true;
        this.open.className = "text-editor-action-button";
        this.open.textContent = t("Open in new tab");
        this.open.target = "_blank";
        this.open.rel = "noopener noreferrer";
        this.element.append(this.href, this.button(t("Save"), "submit"),
            this.button(t("Cancel"), "button", this.cancel),
            this.button(t("Remove link"), "button", this.unlink), this.open);
        document.body.appendChild(this.element);
        const options = { signal: this.lifecycle.signal };
        this.element.addEventListener("submit", this.save, options);
        this.href.addEventListener("input", this.clearValidation, options);
        document.addEventListener("pointerdown", this.onPointerDown, options);
        document.addEventListener("keydown", this.onKeyDown, options);
        window.addEventListener("resize", this.position, options);
        window.addEventListener("scroll", this.position, { ...options, capture: true });
        this.unregister = [
            editor.registerCommand(CLICK_COMMAND, this.onClick, COMMAND_PRIORITY_HIGH),
            editor.registerUpdateListener(this.refresh),
            editor.registerEditableListener(this.refresh),
        ];
    }

    /** Create a labelled action without submitting the surrounding application form. */
    private button(label: string, type: "button" | "submit", handler?: () => void): HTMLButtonElement {
        const button = document.createElement("button");
        button.type = type;
        button.className = "text-editor-action-button";
        button.textContent = label;
        if (handler) button.addEventListener("click", handler, { signal: this.lifecycle.signal });
        return button;
    }

    /** Resolve only attached links in this editable document. */
    private getLink(): LinkNode | null {
        if (!this.editor.isEditable() || this.host.dataset.disabled === "true" || !this.host.isConnected) return null;
        const node = this.key ? $getNodeByKey(this.key) : null;
        return $isLinkNode(node) && node.isAttached() ? node : null;
    }

    /** Select the complete link, including differently formatted children, instead of navigating. */
    private onClick = (event: MouseEvent): boolean => {
        if (!this.editor.isEditable() || this.host.dataset.disabled === "true") return false;
        const target = event.target;
        if (!(target instanceof Node) || !this.editor.getRootElement()?.contains(target)) return false;
        let node = $getNearestNodeFromDOMNode(target);
        while (node && !$isLinkNode(node)) node = node.getParent();
        if (!$isLinkNode(node)) return false;
        event.preventDefault();
        this.key = node.getKey();
        node.select(0, node.getChildrenSize());
        this.href.value = node.getURL();
        this.clearValidation();
        // Imported links may be relative; resolve them before applying the existing safe URL policy.
        let destination: string | null = null;
        try { destination = normalizeLinkHref(new URL(node.getURL(), document.baseURI).href); }
        catch { /* Malformed imported destinations remain editable but cannot be opened. */ }
        this.open.hidden = !destination;
        if (destination) this.open.href = destination;
        else this.open.removeAttribute("href");
        this.element.hidden = false;
        this.position();
        return true;
    };

    /** Report whether the general selection toolbar should defer to link controls. */
    public isVisible(): boolean { return !this.element.hidden; }

    /** Keep controls tied to the original node and dismiss stale or moved selections. */
    private refresh = (): void => {
        if (!this.isVisible()) return;
        this.editor.getEditorState().read((): void => {
            const selection = $getSelection();
            const link = this.getLink();
            // Browser selectionchange normalizes element points into text points.
            // Compare the selected link content and ancestry instead of point representation.
            /** Accept either the link element or one of its formatted text descendants. */
            function isWithinLink(node: LexicalNode): boolean {
                for (let current: LexicalNode | null = node; current; current = current.getParent()) {
                    if (current.is(link)) return true;
                }
                return false;
            }
            const containsSelection = link && $isRangeSelection(selection)
                && selection.getTextContent() === link.getTextContent()
                && isWithinLink(selection.anchor.getNode()) && isWithinLink(selection.focus.getNode());
            if (!link || (!this.element.contains(document.activeElement) && !containsSelection)) this.hide();
        });
        this.position();
    };

    /** Reuse floating-toolbar layers and keep controls above the clicked link. */
    private position = (): void => {
        if (!this.isVisible() || !this.key) return;
        const anchor = this.editor.getElementByKey(this.key);
        if (!anchor?.isConnected) { this.hide(); return; }
        const rect = anchor.getBoundingClientRect();
        this.element.style.zIndex = String(getContextMenuLayer(this.host));
        if (this.element.hasAttribute("popover") && !this.element.matches(":popover-open")) this.element.showPopover();
        const bounds = this.element.getBoundingClientRect();
        this.element.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - bounds.width - 8))}px`;
        this.element.style.top = `${Math.max(8, rect.top - bounds.height - 8)}px`;
    };

    /** Clear validation after the user edits the destination. */
    private clearValidation = (): void => { this.href.setCustomValidity(""); };

    /** Update only the captured link, preserving its content, formatting and selection. */
    private save = (event: SubmitEvent): void => {
        event.preventDefault();
        const url = normalizeLinkHref(this.href.value);
        if (!url) {
            this.href.setCustomValidity(t("Enter a valid http, https, mailto, or tel URL."));
            this.href.reportValidity();
            return;
        }
        this.editor.update((): void => {
            const link = this.getLink();
            if (link) { link.setURL(url); link.select(0, link.getChildrenSize()); }
        }, { discrete: true, tag: "history-push" });
        this.hide();
        this.editor.focus();
    };

    /** Unwrap the link without removing or flattening its formatted text children. */
    private unlink = (): void => {
        this.editor.update((): void => {
            const link = this.getLink();
            if (!link) return;
            link.select(0, link.getChildrenSize());
            for (const child of link.getChildren()) link.insertBefore(child);
            link.remove();
        }, { discrete: true, tag: "history-push" });
        this.hide();
        this.editor.focus();
    };

    /** Discard unsaved input and restore the original complete link selection. */
    private cancel = (): void => {
        this.editor.update((): void => {
            const link = this.getLink();
            if (link) link.select(0, link.getChildrenSize());
        }, { discrete: true });
        this.hide();
        this.editor.focus();
    };

    /** Dismiss when another surface is clicked while allowing controls to take focus. */
    private onPointerDown = (event: PointerEvent): void => {
        if (event.target instanceof Node && !this.element.contains(event.target)) this.hide();
    };

    /** Support keyboard cancellation from both the link selection and its controls. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === "Escape" && this.isVisible()) { event.preventDefault(); this.cancel(); }
    };

    /** Remove transient UI state without persisting highlight markup in the document. */
    public hide(): void {
        if (this.element.hasAttribute("popover") && this.element.matches(":popover-open")) this.element.hidePopover();
        this.element.hidden = true;
        this.key = null;
    }

    /** Dispose listeners and the body-mounted overlay when the editor is destroyed. */
    public destroy(): void {
        this.lifecycle.abort();
        for (const unregister of this.unregister) unregister();
        this.hide();
        this.element.remove();
    }
}
