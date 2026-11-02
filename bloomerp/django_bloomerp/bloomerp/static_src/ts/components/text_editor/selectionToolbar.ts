import type { BaseSelection } from "lexical";
import { $isTableCellNode, $isTableSelection } from "@lexical/table";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import { ActionToolbar } from "./actionToolbar";
import { getContextMenuLayer } from "@/utils/contextMenuLayer";

const SELECTION_SHOW_DELAY_MS = 150;

/** Position shared actions beside selected text or a rectangular table-cell selection. */
export class SelectionToolbar {
    public readonly element = document.createElement("div");
    private readonly controls: ActionToolbar;
    private readonly lifecycle = new AbortController();
    private readonly unregister: () => void;
    private selection: BaseSelection | null = null;
    private frame: number | null = null;
    private revealTimer: number | null = null;
    private selecting = false;

    /** Observe editor selection and viewport changes with instance-owned cleanup. */
    public constructor(private readonly host: BloomerpTextEditor) {
        this.element.className = "text-editor-selection-toolbar";
        this.element.dataset.editorSelectionToolbar = host.element.dataset.editorId;
        this.element.hidden = true;
        if (typeof this.element.showPopover === "function") this.element.setAttribute("popover", "manual");
        this.controls = new ActionToolbar(host, "selection", this.getSelection);
        this.element.appendChild(this.controls.element);
        document.body.appendChild(this.element);
        document.addEventListener("selectionchange", this.scheduleRefresh, { signal: this.lifecycle.signal });
        document.addEventListener("pointerup", this.onPointerUp, { signal: this.lifecycle.signal });
        document.addEventListener("pointercancel", this.onPointerUp, { signal: this.lifecycle.signal });
        document.addEventListener("pointerdown", this.onPointerDown, { signal: this.lifecycle.signal });
        document.addEventListener("keydown", this.onKeyDown, { signal: this.lifecycle.signal });
        window.addEventListener("scroll", this.scheduleRefresh, { capture: true, signal: this.lifecycle.signal });
        window.addEventListener("resize", this.scheduleRefresh, { signal: this.lifecycle.signal });
        this.unregister = host.editor!.registerUpdateListener(this.scheduleRefresh);
    }

    /** Supply the last valid range when a dropdown takes keyboard focus. */
    private getSelection = (): BaseSelection | null => this.selection;

    /** Coalesce drag, editor-update, and scrolling events into one positioning pass. */
    private scheduleRefresh = (): void => {
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(this.refresh);
    };

    /** Keep the floating toolbar visible only for text selected in its own editor. */
    private refresh = (): void => {
        this.frame = null;
        if (this.selecting) { this.hide(); return; }
        if (this.element.contains(document.activeElement) && !this.element.hidden) { this.controls.refresh(); return; }
        const rect = this.selectionRect();
        if (!rect) { this.hide(); return; }
        if (this.element.hidden) {
            this.cancelReveal();
            this.revealTimer = window.setTimeout(this.reveal, SELECTION_SHOW_DELAY_MS);
            return;
        }
        this.showAt(rect);
    };

    /** Measure a visible text range or selected cells inside this editable widget. */
    private selectionRect(): DOMRect | null {
        const editor = this.host.editor;
        const root = editor?.getRootElement();
        if (!root || !editor.isEditable() || this.host.element.dataset.disabled === "true") return null;
        const saved = this.host.actionRegistry.captureSelection();
        if ($isTableSelection(saved)) {
            if (!root.contains(document.activeElement)) return null;
            const tableSelection = saved;
            let available = false;
            for (const entry of this.host.actionRegistry.list("selection", saved)) {
                if (entry.action.group === "table") { available = true; break; }
            }
            if (!available) return null;
            const bounds: DOMRect[] = [];
            /** Measure native cells because table selections may collapse the browser's text range. */
            function measureCells(): void {
                for (const node of tableSelection.getNodes()) {
                    if (!$isTableCellNode(node) || node.getParent()?.getParent()?.getKey() !== tableSelection.tableKey) continue;
                    const element = editor!.getElementByKey(node.getKey());
                    if (element && root!.contains(element)) bounds.push(element.getBoundingClientRect());
                }
            }
            editor.getEditorState().read(measureCells);
            if (!bounds.length) return null;
            let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
            for (const rect of bounds) {
                left = Math.min(left, rect.left); top = Math.min(top, rect.top);
                right = Math.max(right, rect.right); bottom = Math.max(bottom, rect.bottom);
            }
            if (bottom < 0 || top > window.innerHeight || right <= left || bottom <= top) return null;
            return new DOMRect(left, top, right - left, bottom - top);
        }
        const selection = document.getSelection();
        if (!selection || selection.isCollapsed || !selection.rangeCount
            || !root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
        const rect = selection.getRangeAt(0).getBoundingClientRect();
        if ((!rect.width && !rect.height) || rect.bottom < 0 || rect.top > window.innerHeight) return null;
        return rect;
    }

    /** Reveal once selection has settled, rechecking it before showing stale controls. */
    private reveal = (): void => {
        this.revealTimer = null;
        const rect = this.selectionRect();
        if (this.selecting || !rect) { this.hide(); return; }
        this.showAt(rect);
    };

    /** Update the saved range and position without delaying an already visible toolbar. */
    private showAt(rect: DOMRect): void {
        this.selection = this.host.actionRegistry.captureSelection();
        this.controls.refresh();
        this.element.hidden = false;
        this.element.style.zIndex = String(getContextMenuLayer(this.host.element));
        if (this.element.hasAttribute("popover") && !this.element.matches(":popover-open")) this.element.showPopover();
        const bounds = this.element.getBoundingClientRect();
        this.element.style.left = `${Math.max(8, Math.min(rect.left + rect.width / 2 - bounds.width / 2, window.innerWidth - bounds.width - 8))}px`;
        const top = rect.top - bounds.height - 8;
        this.element.style.top = `${Math.max(8, Math.min(top >= 8 ? top : rect.bottom + 8, window.innerHeight - bounds.height - 8))}px`;
    }

    /** Cancel a pending appearance when selection changes, collapses, or is dismissed. */
    private cancelReveal(): void {
        if (this.revealTimer !== null) window.clearTimeout(this.revealTimer);
        this.revealTimer = null;
    }

    /** Dismiss controls without changing the document's selection or content. */
    public hide(): void {
        this.cancelReveal();
        this.controls.closeMenu();
        if (this.element.hasAttribute("popover") && this.element.matches(":popover-open")) this.element.hidePopover();
        this.element.hidden = true;
    }

    /** Hide controls during a new drag and when another editor or dialog receives focus. */
    private onPointerDown = (event: PointerEvent): void => {
        const target = event.target as Node;
        if (this.element.contains(target)) return;
        if (this.host.editor?.getRootElement()?.contains(target) && event.button === 0) this.selecting = true;
        this.hide();
    };

    /** Start the settle delay after pointer selection has finished. */
    private onPointerUp = (): void => {
        this.selecting = false;
        this.scheduleRefresh();
    };

    /** Let Escape dismiss floating controls while preserving the selected editor text. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key !== "Escape" || (this.element.hidden && this.revealTimer === null)) return;
        this.hide();
        if (this.element.contains(document.activeElement)) this.host.editor?.focus();
    };

    /** Release the overlay, menus, animation frame, and all editor/document listeners. */
    public destroy(): void {
        this.lifecycle.abort();
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.unregister();
        this.hide();
        this.controls.destroy();
        this.element.remove();
    }
}
