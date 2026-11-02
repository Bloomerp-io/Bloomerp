import { $getNearestNodeFromDOMNode, $getNodeByKey, $getSelection, $isRangeSelection, type LexicalEditor, type NodeKey } from "lexical";
import { $findCellNode, $findTableNode, $isTableNode } from "@lexical/table";
import { mergeRegister } from "@lexical/utils";
import { t } from "@/utils/i18n";
import { getContextMenuLayer } from "@/utils/contextMenuLayer";
import { $editTableStructure, $supportsTableStructure, type TableAction, type TableAxis } from "./tableStructure";

type TableTarget = { key: NodeKey; axis: TableAxis; index: number };
type TableDrag = { target: TableTarget; pointerId: number; x: number; y: number; moved: boolean; destination: number | null; handle: HTMLButtonElement };

/** Own edge handles, contextual actions, and one undoable transaction per completed row or column drag. */
class TableControls {
    private readonly lifecycle = new AbortController();
    private readonly overlay = document.createElement("div");
    private readonly row = this.button("row", "Row options", "⋮");
    private readonly column = this.button("column", "Column options", "⋯");
    private readonly addRow = this.button("add-row", "Add row", "+");
    private readonly addColumn = this.button("add-column", "Add column", "+");
    private readonly menu = document.createElement("div");
    private readonly marker = document.createElement("div");
    private readonly unregister: () => void;
    private readonly observer: ResizeObserver | null;
    private tableKey: NodeKey | null = null;
    private rowIndex = 0;
    private columnIndex = 0;
    private frame: number | null = null;
    private menuTarget: TableTarget | null = null;
    private drag: TableDrag | null = null;
    private pointer: { x: number; y: number } | null = null;
    private suppressClick = false;

    /** Mount controls outside document content so editor styling and PDF export cannot include them. */
    public constructor(private readonly editor: LexicalEditor, private readonly host: HTMLElement) {
        this.overlay.className = "bloomerp-table-controls";
        this.overlay.hidden = true;
        this.menu.className = "bloomerp-table-menu";
        this.menu.setAttribute("role", "menu");
        this.menu.hidden = true;
        this.marker.className = "bloomerp-table-drop-marker";
        this.marker.hidden = true;
        this.overlay.append(this.row, this.column, this.addRow, this.addColumn, this.marker, this.menu);
        document.body.appendChild(this.overlay);
        this.observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(this.schedule);
        const signal = this.lifecycle.signal;
        document.addEventListener("pointermove", this.onPointerMove, { signal });
        document.addEventListener("pointerup", this.onPointerUp, { signal });
        document.addEventListener("pointercancel", this.onPointerCancel, { signal });
        document.addEventListener("pointerdown", this.onOutsidePointerDown, { signal });
        document.addEventListener("keydown", this.onKeyDown, { signal });
        this.overlay.addEventListener("pointerdown", this.onPointerDown, { signal });
        this.overlay.addEventListener("lostpointercapture", this.onPointerCancel, { signal });
        this.overlay.addEventListener("mousedown", this.preserveSelection, { signal });
        this.overlay.addEventListener("click", this.onClick, { signal });
        window.addEventListener("scroll", this.onGeometryChange, { capture: true, signal });
        window.addEventListener("resize", this.onGeometryChange, { signal });
        this.unregister = mergeRegister(editor.registerUpdateListener(this.onUpdate), editor.registerEditableListener(this.onEditable));
    }

    /** Create a focusable control with a readable name and a minimal visual glyph. */
    private button(control: string, label: string, glyph: string): HTMLButtonElement {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "bloomerp-table-edge-control";
        button.dataset.tableControl = control;
        button.setAttribute("aria-label", t(label));
        button.title = t(label);
        button.textContent = glyph;
        if (control === "row" || control === "column") {
            button.setAttribute("aria-haspopup", "menu");
            button.setAttribute("aria-expanded", "false");
        }
        return button;
    }

    /** Respect both the widget disabled flag and Lexical's live editability state. */
    private editable(): boolean { return this.editor.isEditable() && this.host.dataset.disabled !== "true"; }

    /** Resolve only a connected table still owned by this editor. */
    private table(): HTMLTableElement | null {
        const element = this.tableKey ? this.editor.getElementByKey(this.tableKey) : null;
        return element instanceof HTMLTableElement && this.editor.getRootElement()?.contains(element) ? element : null;
    }

    /** Observe the active table while keeping independent editors' controls isolated. */
    private activate(table: HTMLTableElement | null): void {
        let key: NodeKey | null = null;
        if (table && this.editor.getRootElement()?.contains(table)) {
            /** Resolve a rendered table without changing editor selection or history. */
            const identify = (): void => {
                const node = $getNearestNodeFromDOMNode(table);
                if ($isTableNode(node)) key = node.getKey();
            };
            this.editor.read(identify);
        }
        if (key === this.tableKey) return;
        this.closeMenu();
        this.cancelDrag();
        this.tableKey = key;
        this.observer?.disconnect();
        if (key && table) this.observer?.observe(table);
    }

    /** Keep handles available to keyboard users at the current cell after edits and undo. */
    private onUpdate = (): void => {
        if (!this.menuTarget && !this.drag) {
            /** Resolve the current cell after Lexical has committed its latest state. */
            const identifySelection = (): void => {
                const selection = $getSelection();
                if (!$isRangeSelection(selection)) return;
                const cell = $findCellNode(selection.anchor.getNode());
                const table = cell ? $findTableNode(cell) : null;
                if (!table) return;
                const element = this.editor.getElementByKey(table.getKey());
                if (element instanceof HTMLTableElement) {
                    this.activate(element);
                    this.rowIndex = cell!.getParent()!.getIndexWithinParent();
                    this.columnIndex = cell!.getIndexWithinParent();
                }
            };
            this.editor.getEditorState().read(identifySelection);
        }
        if (this.menuTarget && !this.editor.getElementByKey(this.menuTarget.key)) this.closeMenu();
        this.schedule();
    };

    /** Remove transient interaction state as soon as the widget becomes read-only. */
    private onEditable = (): void => {
        if (!this.editable()) { this.closeMenu(); this.cancelDrag(); this.tableKey = null; }
        this.schedule();
    };

    /** Coalesce layout reads after editor, viewport, and pointer changes. */
    private schedule = (): void => {
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(this.render);
    };

    /** Close viewport-anchored menus before repositioning controls after scrolling. */
    private onGeometryChange = (): void => { this.closeMenu(); this.schedule(); };

    /** Preserve the text selection while interacting with controls outside the editor. */
    private preserveSelection = (event: MouseEvent): void => { event.preventDefault(); };

    /** Find the physical column edges from the first unmerged row, including WebKit geometry. */
    private columns(table: HTMLTableElement): DOMRect[] {
        for (const row of table.rows) {
            if (Array.from(row.cells).every(isSingleColumn)) return Array.from(row.cells, cellBounds);
        }
        return [];
    }

    /** Reveal controls only inside their matching narrow table-edge hover zones. */
    private onPointerMove = (event: PointerEvent): void => {
        this.pointer = { x: event.clientX, y: event.clientY };
        if (this.drag) { this.previewDrag(event); return; }
        if (this.menuTarget || this.overlay.contains(event.target as Node)) { this.schedule(); return; }
        if (!this.editable()) { this.activate(null); this.schedule(); return; }
        let hovered: HTMLTableElement | null = null;
        for (const table of this.editor.getRootElement()?.querySelectorAll("table") ?? []) {
            const rect = table.getBoundingClientRect();
            if (event.clientX >= rect.left - 24 && event.clientX <= rect.right + 20 && event.clientY >= rect.top - 24 && event.clientY <= rect.bottom + 20) {
                hovered = table;
                break;
            }
        }
        this.activate(hovered);
        if (hovered) {
            const rect = hovered.getBoundingClientRect();
            const rows = Array.from(hovered.rows, rowBounds);
            const columns = this.columns(hovered);
            this.rowIndex = Math.max(0, rows.findIndex(containsY));
            this.columnIndex = Math.max(0, columns.findIndex(containsX));
        }
        this.schedule();

        /** Match the hovered physical row without relying on text or selection position. */
        function containsY(bounds: DOMRect): boolean { return event.clientY >= bounds.top && event.clientY <= bounds.bottom; }
        /** Match the hovered physical column without relying on editable text targets. */
        function containsX(bounds: DOMRect): boolean { return event.clientX >= bounds.left && event.clientX <= bounds.right; }
    };

    /** Position the handles outside the table without covering cell text or resize dividers. */
    private render = (): void => {
        this.frame = null;
        const table = this.table();
        this.overlay.hidden = !table || !this.editable();
        if (!table || !this.editable()) { this.closeMenu(); this.cancelDrag(); return; }
        const rect = table.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) { this.overlay.hidden = true; this.closeMenu(); return; }
        const point = this.pointer;
        this.row.dataset.revealed = String(this.menuTarget?.axis === "row" || !!point && point.x >= rect.left - 24 && point.x <= rect.left + 12 && point.y >= rect.top && point.y <= rect.bottom);
        this.column.dataset.revealed = String(this.menuTarget?.axis === "column" || !!point && point.y >= rect.top - 24 && point.y <= rect.top + 10 && point.x >= rect.left && point.x <= rect.right);
        this.addRow.dataset.revealed = String(!!point && point.y >= rect.bottom && point.y <= rect.bottom + 20 && point.x >= rect.left && point.x <= rect.right);
        this.addColumn.dataset.revealed = String(!!point && point.x >= rect.right && point.x <= rect.right + 20 && point.y >= rect.top && point.y <= rect.bottom);
        this.overlay.style.zIndex = String(getContextMenuLayer(this.host) + 1);
        const row = table.rows[Math.min(this.rowIndex, table.rows.length - 1)]?.getBoundingClientRect();
        const columns = this.columns(table);
        const column = columns[Math.min(this.columnIndex, columns.length - 1)];
        place(this.row, rect.left - 22, row ? row.top + row.height / 2 - 9 : rect.top, 18, 18);
        place(this.column, column ? column.left + column.width / 2 - 10 : rect.left, rect.top - 20, 20, 16);
        place(this.addRow, rect.left, rect.bottom + 1, rect.width, 18);
        place(this.addColumn, rect.right + 1, rect.top, 18, rect.height);
    };

    /** Begin a possible drag; a click without movement opens the matching contextual menu. */
    private onPointerDown = (event: PointerEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>("[data-table-control]") : null;
        if (!button || !this.tableKey || !this.editable() || event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        this.suppressClick = false;
        const axis = button.dataset.tableControl;
        if (axis !== "row" && axis !== "column") return;
        this.closeMenu();
        let supported = false;
        /** Avoid showing a reorder preview for tables whose merged cells cannot be moved intact. */
        const inspect = (): void => {
            const table = $getNodeByKey(this.tableKey!);
            supported = $isTableNode(table) && $supportsTableStructure(table);
        };
        this.editor.getEditorState().read(inspect);
        if (!supported) return;
        this.drag = { target: { key: this.tableKey, axis, index: axis === "row" ? this.rowIndex : this.columnIndex }, pointerId: event.pointerId,
            x: event.clientX, y: event.clientY, moved: false, destination: null, handle: button };
        button.setPointerCapture(event.pointerId);
    };

    /** Mark the destination boundary while leaving table content untouched until drop. */
    private previewDrag(event: PointerEvent): void {
        const drag = this.drag;
        const table = this.table();
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (!table || !this.editable()) { this.cancelDrag(); return; }
        if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5 && !drag.moved) return;
        event.preventDefault();
        drag.moved = true;
        drag.handle.dataset.dragging = "true";
        const rect = table.getBoundingClientRect();
        const axis = drag.target.axis;
        const bounds = axis === "row" ? Array.from(table.rows, rowBounds) : this.columns(table);
        const coordinate = axis === "row" ? event.clientY : event.clientX;
        let boundary = bounds.length;
        for (let index = 0; index < bounds.length; index++) {
            const center = axis === "row" ? bounds[index].top + bounds[index].height / 2 : bounds[index].left + bounds[index].width / 2;
            if (coordinate < center) { boundary = index; break; }
        }
        const inside = event.clientX >= rect.left - 60 && event.clientX <= rect.right + 60 && event.clientY >= rect.top - 60 && event.clientY <= rect.bottom + 60;
        drag.destination = inside ? boundary - (boundary > drag.target.index ? 1 : 0) : null;
        this.marker.hidden = !inside || drag.destination === drag.target.index;
        const edge = axis === "row" ? bounds[boundary]?.top ?? rect.bottom : bounds[boundary]?.left ?? rect.right;
        if (axis === "row") place(this.marker, rect.left, edge - 1, rect.width, 2);
        else place(this.marker, edge - 1, rect.top, 2, rect.height);
    }

    /** Commit one completed drop and suppress the click produced by releasing the drag handle. */
    private onPointerUp = (event: PointerEvent): void => {
        const drag = this.drag;
        if (!drag || drag.pointerId !== event.pointerId) return;
        this.suppressClick = drag.moved;
        this.cancelDrag();
        if (drag.moved && drag.destination !== null) this.execute(drag.target, "move", drag.destination);
    };

    /** Discard the pending drag when pointer capture is cancelled by the browser. */
    private onPointerCancel = (event: PointerEvent): void => {
        if (this.drag?.pointerId === event.pointerId) { this.suppressClick = true; this.cancelDrag(); }
    };

    /** Release pointer capture and remove the insertion preview without editing the document. */
    private cancelDrag(): void {
        const drag = this.drag;
        this.drag = null;
        this.marker.hidden = true;
        if (!drag) return;
        delete drag.handle.dataset.dragging;
        if (drag.handle.hasPointerCapture(drag.pointerId)) drag.handle.releasePointerCapture(drag.pointerId);
    }

    /** Route edge-button clicks and contextual actions to the precise table and axis index. */
    private onClick = (event: MouseEvent): void => {
        if (this.suppressClick) { this.suppressClick = false; return; }
        const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>("button") : null;
        if (!button || button.disabled || !this.tableKey || !this.editable()) return;
        const action = button.dataset.tableAction as TableAction | undefined;
        if (action && this.menuTarget) { this.execute(this.menuTarget, action); this.closeMenu(); return; }
        const control = button.dataset.tableControl;
        const axis = control === "row" || control === "add-row" ? "row" : "column";
        const table = this.table();
        if (!table) return;
        const index = control === "add-row" ? table.rows.length - 1 : control === "add-column" ? this.columns(table).length - 1 : axis === "row" ? this.rowIndex : this.columnIndex;
        const target = { key: this.tableKey, axis, index } as TableTarget;
        if (control === "add-row" || control === "add-column") this.execute(target, "insert-after");
        else this.openMenu(target, button);
    };

    /** Apply structural edits in one standalone history entry and restore editor focus. */
    private execute(target: TableTarget, action: TableAction, destination?: number): void {
        if (!this.editable()) return;
        /** Resolve a fresh node so stale menus cannot edit a removed or replaced table. */
        const edit = (): void => {
            const table = $getNodeByKey(target.key);
            if ($isTableNode(table)) $editTableStructure(table, target.axis, target.index, action, destination);
        };
        this.editor.update(edit, { discrete: true, tag: "history-push" });
        this.editor.focus();
        this.schedule();
    }

    /** Build an accessible contextual menu for a particular physical row or column. */
    private openMenu(target: TableTarget, trigger: HTMLButtonElement): void {
        this.closeMenu();
        this.menuTarget = target;
        let supported = false;
        let count = 0;
        /** Read current capabilities before showing any potentially stale menu commands. */
        const inspect = (): void => {
            const table = $getNodeByKey(target.key);
            if (!$isTableNode(table)) return;
            supported = $supportsTableStructure(table);
            count = target.axis === "row" ? table.getChildrenSize() : table.getColumnCount();
        };
        this.editor.getEditorState().read(inspect);
        const row = target.axis === "row";
        this.menu.replaceChildren();
        this.menu.setAttribute("aria-label", t(row ? "Row options" : "Column options"));
        this.menuItem("insert-before", row ? "Insert row above" : "Insert column left", !supported, !supported);
        this.menuItem("insert-after", row ? "Insert row below" : "Insert column right", !supported, !supported);
        this.menuItem("move-before", row ? "Move row up" : "Move column left", !supported || target.index === 0, !supported);
        this.menuItem("move-after", row ? "Move row down" : "Move column right", !supported || target.index >= count - 1, !supported);
        this.menuItem("delete", row ? "Delete row" : "Delete column", !supported, !supported);
        this.menuItem("delete-table", "Delete table", false);
        this.menu.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        trigger.dataset.revealed = "true";
        const bounds = trigger.getBoundingClientRect();
        const menuBounds = this.menu.getBoundingClientRect();
        this.menu.style.left = `${Math.max(8, Math.min(bounds.left, window.innerWidth - menuBounds.width - 8))}px`;
        this.menu.style.top = `${Math.max(8, Math.min(bounds.bottom + 5, window.innerHeight - menuBounds.height - 8))}px`;
        this.menu.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
    }

    /** Append an action with an explicit disabled state and destructive-action styling. */
    private menuItem(action: TableAction, label: string, disabled: boolean, merged: boolean = false): void {
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("role", "menuitem");
        button.dataset.tableAction = action;
        button.textContent = t(label);
        button.disabled = disabled;
        if (merged) button.title = t("Merged cells must be separated before changing rows or columns");
        this.menu.appendChild(button);
    }

    /** Hide the contextual menu and reset both handle expansion states. */
    private closeMenu(): void {
        this.menuTarget = null;
        this.menu.hidden = true;
        this.row.setAttribute("aria-expanded", "false");
        this.column.setAttribute("aria-expanded", "false");
    }

    /** Dismiss the menu on an outside pointer press without moving the document selection. */
    private onOutsidePointerDown = (event: PointerEvent): void => {
        if (!this.overlay.contains(event.target as Node)) this.closeMenu();
    };

    /** Support Escape cancellation and standard menu navigation without trapping Tab focus. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === "Escape" && (this.drag || this.menuTarget)) {
            event.preventDefault();
            event.stopPropagation();
            const axis = this.drag?.target.axis ?? this.menuTarget?.axis;
            this.suppressClick = !!this.drag;
            this.cancelDrag();
            this.closeMenu();
            (axis === "row" ? this.row : this.column).focus({ preventScroll: true });
            return;
        }
        if (!this.menuTarget || !this.menu.contains(event.target as Node)) return;
        if (event.key === "Tab") { this.closeMenu(); return; }
        const buttons = Array.from(this.menu.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        let next: number;
        if (event.key === "ArrowDown") next = (current + 1) % buttons.length;
        else if (event.key === "ArrowUp") next = (current + buttons.length - 1) % buttons.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = buttons.length - 1;
        else return;
        event.preventDefault();
        event.stopPropagation();
        buttons[next]?.focus();
    };

    /** Release every listener, observer, pending frame, and body-mounted control on editor teardown. */
    public destroy(): void {
        this.cancelDrag();
        this.lifecycle.abort();
        this.unregister();
        this.observer?.disconnect();
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.overlay.remove();
    }
}

/** Position one body-mounted control using viewport coordinates. */
function place(element: HTMLElement, left: number, top: number, width: number, height: number): void {
    Object.assign(element.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
}
/** Read a rendered cell's physical bounds for column handles. */
function cellBounds(cell: HTMLTableCellElement): DOMRect { return cell.getBoundingClientRect(); }
/** Read a rendered row's physical bounds for row handles. */
function rowBounds(row: HTMLTableRowElement): DOMRect { return row.getBoundingClientRect(); }
/** Identify rows whose cells expose each physical column separately. */
function isSingleColumn(cell: HTMLTableCellElement): boolean { return cell.colSpan === 1; }

/** Register row and column controls with editor-owned lifecycle cleanup. */
export function registerTableControls(editor: LexicalEditor, host: HTMLElement): () => void {
    const controls = new TableControls(editor, host);
    return controls.destroy.bind(controls);
}
