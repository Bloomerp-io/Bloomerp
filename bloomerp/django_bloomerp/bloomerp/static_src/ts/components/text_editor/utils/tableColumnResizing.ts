import { $getNearestNodeFromDOMNode, $getNodeByKey, type LexicalEditor, type NodeKey } from "lexical";
import { mergeRegister } from "@lexical/utils";
import { t } from "@/utils/i18n";
import { getContextMenuLayer } from "@/utils/contextMenuLayer";
import { applyTableColumnWidths, ResizableTableNode } from "../nodes/ResizableTableNode";

type ColumnDrag = {
    key: NodeKey; index: number; pointerId: number; startX: number; widths: number[]; preview: number[];
    table: HTMLTableElement; handle: HTMLElement; tableStyle: string; columnStyles: string[];
};

/** Adjust neighboring columns while preserving the table's total width and minimum cell size. */
export function resizeColumnPair(widths: readonly number[], index: number, delta: number): number[] {
    const result = [...widths];
    if (index < 0 || index + 1 >= result.length || !Number.isFinite(delta)) return result;
    const total = result[index] + result[index + 1];
    const minimum = Math.min(32, total / 2);
    result[index] = Math.max(minimum, Math.min(result[index] + delta, total - minimum));
    result[index + 1] = total - result[index];
    return result;
}

/** Measure physical column boundaries, including tables whose cells contain merged columns. */
function columnWidths(table: HTMLTableElement): number[] {
    const columns = Array.from(table.querySelectorAll<HTMLTableColElement>(":scope > colgroup > col"));
    const measured = columns.map(measureColumn);
    if (measured.length && !measured.some(invalidWidth)) return measured;
    const firstRow = table.rows[0];
    let available = 0;
    if (firstRow) for (const cell of firstRow.cells) available += cell.getBoundingClientRect().width;
    const weights = columns.map(readColumnWeight);
    if (weights.length && !weights.some(invalidWidth)) {
        let total = 0;
        for (const weight of weights) total += weight;
        /** WebKit exposes zero-width col boxes, so use their saved proportions and real row width. */
        function proportionalWidth(weight: number): number { return weight / total * available; }
        return weights.map(proportionalWidth);
    }
    const widths = new Array<number>(columns.length).fill(0);
    const occupied = new Array<number>(columns.length).fill(0);
    for (const row of table.rows) {
        let index = 0;
        for (const cell of row.cells) {
            while (occupied[index] > 0) index++;
            const width = cell.getBoundingClientRect().width / cell.colSpan;
            for (let offset = 0; offset < cell.colSpan && index + offset < widths.length; offset++) {
                if (!widths[index + offset] || cell.colSpan === 1) widths[index + offset] = width;
                occupied[index + offset] = Math.max(1, cell.rowSpan);
            }
            index += cell.colSpan;
        }
        for (let index = 0; index < occupied.length; index++) occupied[index] = Math.max(0, occupied[index] - 1);
    }
    return widths;
}

/** Read native column geometry when the browser exposes physical column boxes. */
function measureColumn(column: HTMLTableColElement): number { return column.getBoundingClientRect().width; }
/** Read the normalized inline percentage produced by the table node. */
function readColumnWeight(column: HTMLTableColElement): number { return Number.parseFloat(column.style.width); }

/** Own pointer previews and one undoable persisted update per completed column drag. */
class TableColumnResizer {
    private readonly lifecycle = new AbortController();
    private readonly overlay = document.createElement("div");
    private readonly observer: ResizeObserver | null;
    private readonly unregister: () => void;
    private tableKey: NodeKey | null = null;
    private frame: number | null = null;
    private drag: ColumnDrag | null = null;

    /** Attach a body-mounted interaction layer outside the printable editable document. */
    public constructor(private readonly editor: LexicalEditor, private readonly host: HTMLElement) {
        this.observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(this.schedule);
        this.overlay.className = "bloomerp-table-column-handles";
        this.overlay.hidden = true;
        document.body.appendChild(this.overlay);
        const signal = this.lifecycle.signal;
        document.addEventListener("pointermove", this.onPointerMove, { signal });
        document.addEventListener("pointerup", this.onPointerUp, { signal });
        document.addEventListener("pointercancel", this.onPointerCancel, { signal });
        document.addEventListener("keydown", this.onKeyDown, { signal });
        this.overlay.addEventListener("pointerdown", this.onPointerDown, { signal });
        window.addEventListener("scroll", this.schedule, { capture: true, signal });
        window.addEventListener("resize", this.schedule, { signal });
        this.unregister = mergeRegister(editor.registerUpdateListener(this.schedule), editor.registerEditableListener(this.onEditable));
    }

    /** Coalesce geometry refreshes without recording transient pointer movement in editor history. */
    private schedule = (): void => {
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(this.render);
    };

    /** Resolve the current table only while it still belongs to this editor's DOM. */
    private table(): HTMLTableElement | null {
        const element = this.tableKey ? this.editor.getElementByKey(this.tableKey) : null;
        return element instanceof HTMLTableElement && this.editor.getRootElement()?.contains(element) ? element : null;
    }

    /** Match the widget's disabled contract as well as Lexical's current editing mode. */
    private isEditable(): boolean { return this.editor.isEditable() && this.host.dataset.disabled !== "true"; }

    /** Hide all controls when the editor becomes read-only. */
    private onEditable = (editable: boolean): void => {
        if (!editable) { this.cancelDrag(); this.tableKey = null; }
        this.schedule();
    };

    /** Track hovered tables, or preview a constrained pair of widths during a captured drag. */
    private onPointerMove = (event: PointerEvent): void => {
        if (this.drag) {
            if (event.pointerId !== this.drag.pointerId) return;
            if (!this.isEditable() || !this.drag.table.isConnected) { this.cancelDrag(); return; }
            event.preventDefault();
            this.drag.preview = resizeColumnPair(this.drag.widths, this.drag.index, event.clientX - this.drag.startX);
            applyTableColumnWidths(this.drag.table, this.drag.preview);
            this.schedule();
            return;
        }
        if (this.overlay.contains(event.target as Node)) return;
        const table = event.target instanceof Element ? event.target.closest("table") : null;
        let key: NodeKey | null = null;
        if (this.isEditable() && table && this.editor.getRootElement()?.contains(table)) {
            /** Resolve a rendered table to its native-compatible editor node. */
            function identify(): void {
                const node = $getNearestNodeFromDOMNode(table!);
                if (node instanceof ResizableTableNode) key = node.getKey();
            }
            this.editor.read(identify);
        }
        if (key === this.tableKey) return;
        this.tableKey = key;
        this.observer?.disconnect();
        if (table && key) this.observer?.observe(table);
        this.schedule();
    };

    /** Place narrow draggable separators over internal column edges without changing table markup. */
    private render = (): void => {
        this.frame = null;
        const table = this.table();
        if (!table || !this.isEditable()) {
            this.cancelDrag();
            this.overlay.hidden = true;
            return;
        }
        const bounds = table.getBoundingClientRect();
        const widths = columnWidths(table);
        this.overlay.hidden = bounds.bottom < 0 || bounds.top > window.innerHeight || widths.length < 2;
        this.overlay.style.zIndex = String(getContextMenuLayer(this.host));
        while (this.overlay.children.length > widths.length - 1) this.overlay.lastElementChild?.remove();
        let edge = bounds.left;
        for (let index = 0; index < widths.length - 1; index++) {
            let handle = this.overlay.children[index] as HTMLElement | undefined;
            if (!handle) {
                handle = document.createElement("div");
                handle.className = "bloomerp-table-column-handle";
                handle.setAttribute("role", "separator");
                handle.setAttribute("aria-orientation", "vertical");
                handle.setAttribute("aria-label", `${t("Resize column")} ${index + 1}`);
                handle.tabIndex = 0;
                handle.dataset.columnIndex = String(index);
                this.overlay.appendChild(handle);
            }
            edge += widths[index];
            handle.style.left = `${edge}px`;
            handle.style.top = `${bounds.top}px`;
            handle.style.height = `${bounds.height}px`;
            handle.setAttribute("aria-valuenow", String(Math.round(widths[index])));
        }
    };

    /** Preserve selection and start a preview at the chosen internal column boundary. */
    private onPointerDown = (event: PointerEvent): void => {
        const handle = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-column-index]") : null;
        const table = this.table();
        if (!handle || !table || !this.tableKey || !this.isEditable() || event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const widths = columnWidths(table);
        if (widths.some(invalidWidth)) return;
        this.drag = {
            key: this.tableKey, index: Number(handle.dataset.columnIndex), pointerId: event.pointerId,
            startX: event.clientX, widths, preview: [...widths], table, handle,
            tableStyle: table.style.cssText, columnStyles: Array.from(table.querySelectorAll<HTMLTableColElement>(":scope > colgroup > col"), readColumnStyle),
        };
        handle.dataset.dragging = "true";
        handle.setPointerCapture(event.pointerId);
    };

    /** Commit a completed drag as one history entry and one saved-template change. */
    private onPointerUp = (event: PointerEvent): void => {
        const drag = this.drag;
        if (!drag || event.pointerId !== drag.pointerId) return;
        this.cancelDrag();
        if (Math.abs(drag.preview[drag.index] - drag.widths[drag.index]) >= 0.5) {
            this.commit(drag.key, drag.preview);
            this.editor.focus();
        }
    };

    /** Restore original DOM styles on pointer cancellation. */
    private onPointerCancel = (event: PointerEvent): void => {
        if (this.drag?.pointerId === event.pointerId) this.cancelDrag();
    };

    /** Cancel a preview or resize the focused separator using the arrow keys. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === "Escape" && this.drag) { event.preventDefault(); this.cancelDrag(); return; }
        const handle = event.target instanceof HTMLElement && this.overlay.contains(event.target) ? event.target : null;
        const table = this.table();
        if (!handle || !table || !this.tableKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        this.commit(this.tableKey, resizeColumnPair(columnWidths(table), Number(handle.dataset.columnIndex), event.key === "ArrowRight" ? 8 : -8));
    };

    /** Update only a still-attached, editable table with a matching physical column count. */
    private commit(key: NodeKey, widths: number[]): void {
        if (!this.isEditable()) return;
        /** Persist proportions once the pointer preview is complete. */
        function saveWidths(): void {
            const table = $getNodeByKey(key);
            if (table instanceof ResizableTableNode && table.isAttached() && table.getColumnCount() === widths.length) table.setColWidths(widths);
        }
        this.editor.update(saveWidths, { discrete: true, tag: "history-push" });
        this.schedule();
    }

    /** Discard transient styles and release pointer capture without mutating editor content. */
    private cancelDrag(): void {
        const drag = this.drag;
        if (!drag) return;
        this.drag = null;
        delete drag.handle.dataset.dragging;
        if (drag.handle.hasPointerCapture(drag.pointerId)) drag.handle.releasePointerCapture(drag.pointerId);
        drag.table.style.cssText = drag.tableStyle;
        const columns = drag.table.querySelectorAll<HTMLTableColElement>(":scope > colgroup > col");
        columns.forEach(restoreColumn);
        /** Put back each column's original style when the preview ends. */
        function restoreColumn(column: HTMLTableColElement, index: number): void { column.style.cssText = drag!.columnStyles[index] ?? ""; }
        this.schedule();
    }

    /** Release pointer handlers, observers, frames, and the nonprinting interaction layer. */
    public destroy(): void {
        this.cancelDrag();
        this.lifecycle.abort();
        this.unregister();
        this.observer?.disconnect();
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.overlay.remove();
    }
}

/** Reject invisible or invalid column geometry before starting a resize operation. */
function invalidWidth(width: number): boolean { return !Number.isFinite(width) || width <= 0; }
/** Retain each column's complete original style for cancellation and teardown. */
function readColumnStyle(column: HTMLTableColElement): string { return column.style.cssText; }

/** Register native-compatible column dragging with an editor-owned cleanup function. */
export function registerTableColumnResizing(editor: LexicalEditor, host: HTMLElement): () => void {
    const resizer = new TableColumnResizer(editor, host);
    return resizer.destroy.bind(resizer);
}
