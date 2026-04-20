import htmx from "htmx.org";
import Sortable, { type SortableEvent } from "sortablejs";

import BaseComponent, { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutItem from "./BaseSectionedLayoutItem";
import { getCsrfToken } from "../../utils/cookies";

export type SectionedLayoutItemPayload = {
    id: string;
    colspan: number;
};

export type SectionedLayoutRowPayload = {
    title: string | null;
    columns: number;
    items: SectionedLayoutItemPayload[];
};

type SavePayload = {
    layout: {
        rows: SectionedLayoutRowPayload[];
    };
    [key: string]: unknown;
};

export default abstract class BaseSectionedLayoutContainer<TItem extends BaseSectionedLayoutItem> extends BaseComponent {
    private static readonly SAVE_DEBOUNCE_MS = 120;
    private static readonly DRAG_START_TOLERANCE_PX = 8;
    private static readonly DRAG_SWAP_THRESHOLD = 0.8;

    protected layoutRoot: HTMLElement | null = null;
    protected editMode = false;
    protected items: TItem[] = [];
    protected rowElements: HTMLElement[] = [];
    protected focusedItemIndex = 0;
    protected focusedRowIndex = 0;
    protected isRowFocused = false;
    protected layoutRows: SectionedLayoutRowPayload[] = [];
    protected openSidebarButtons: HTMLElement[] = [];
    protected itemLoadQueue: Promise<void> = Promise.resolve();
    protected saveTimeoutId: number | null = null;
    protected saveInFlight: Promise<void> | null = null;
    protected pendingSaveAfterFlight = false;
    protected rowSortable: Sortable | null = null;
    protected gridSortables: Sortable[] = [];
    protected sidebarSortable: Sortable | null = null;

    protected abstract getItemComponent(element: HTMLElement): TItem | null;
    protected abstract getItemSelector(): string;
    protected abstract renderItem(itemId: string, rowIndex: number, position?: number): Promise<void>;
    protected abstract getSavePayload(): SavePayload;

    protected normalizeLayoutItemId(value: unknown): string | null {
        if (value === null || value === undefined) return null;
        const normalized = String(value).trim();
        return normalized ? normalized : null;
    }

    protected async loadInitialItems(): Promise<void> {
        return Promise.resolve();
    }

    protected handleReadModeKeyDown(_event: KeyboardEvent): void {
        // Optional subclass hook
    }

    protected shouldApplyFocusedItemClass(): boolean {
        return this.editMode;
    }

    protected onInitialItemFocus(item: TItem): void {
        void item;
    }

    public initialize(): void {
        if (!this.element) return;

        this.layoutRoot = this.element.querySelector<HTMLElement>("[data-layout-root]") ?? this.element;
        this.layoutRows = this.parseLayoutData();
        this.rowElements = Array.from(this.element.querySelectorAll<HTMLElement>("[data-layout-row]"));

        if (this.rowElements.length === 0) {
            this.renderRows();
        } else {
            this.bindRows();
        }

        this.reindexItems();
        this.items.forEach((item) => item.setEditMode(false));

        this.element.addEventListener("click", (event: MouseEvent) => this.onClick(event));
        this.element.addEventListener("keydown", (event: KeyboardEvent) => this.onKeyDown(event));
        this.element.addEventListener("layout:item-colspan-change", () => {
            void this.requestSave();
        });

        const editToggle = this.element.querySelector<HTMLElement>("[data-layout-edit-toggle]");
        editToggle?.addEventListener("click", () => this.toggleEditMode());

        this.openSidebarButtons = Array.from(this.element.querySelectorAll<HTMLElement>("[data-layout-open-sidebar]"));
        this.openSidebarButtons.forEach((button) => {
            button.addEventListener("click", () => {
                void this.loadAvailableItems();
            });
        });

        this.setupDnD();
        this.itemLoadQueue = this.loadInitialItems().then(() => {
            this.reindexItems();
            this.syncAvailableItemsState();
            this.refreshSortables();
            if (!this.editMode && this.items.length > 0) {
                this.focusItemByIndex(0);
            }
        });
    }

    public override destroy(): void {
        this.destroySortables();
    }

    protected toggleEditMode(): void {
        this.editMode = !this.editMode;
        this.items.forEach((item) => item.setEditMode(this.editMode));
        this.updateRowControlVisibility();
        this.updateSortableDisabledState();

        if (this.editMode) {
            if (this.rowElements.length > 0) {
                this.focusRowByIndex(this.focusedRowIndex);
            } else if (this.items.length > 0) {
                this.focusItemByIndex(this.focusedItemIndex);
            }
            void this.loadAvailableItems();
        } else {
            this.isRowFocused = false;
            this.updateRowControlVisibility();
        }
    }

    protected parseLayoutData(): SectionedLayoutRowPayload[] {
        const raw = this.element?.getAttribute("data-layout");
        if (!raw) {
            return [{ title: null, columns: 4, items: [] }];
        }

        try {
            const parsed = JSON.parse(raw) as { rows?: SectionedLayoutRowPayload[] };
            if (!Array.isArray(parsed.rows) || parsed.rows.length === 0) {
                return [{ title: null, columns: 4, items: [] }];
            }
            return parsed.rows.map((row) => ({
                title: typeof row.title === "string" && row.title.trim() ? row.title.trim() : null,
                columns: this.clampRowCols(row.columns),
                items: Array.isArray(row.items)
                    ? row.items
                        .map((item) => ({
                            id: this.normalizeLayoutItemId(item.id),
                            colspan: this.clampColspan(item.colspan, row.columns),
                        }))
                        .filter((item): item is SectionedLayoutItemPayload => item.id !== null)
                    : [],
            }));
        } catch {
            return [{ title: null, columns: 4, items: [] }];
        }
    }

    protected renderRows(): void {
        if (!this.layoutRoot) return;
        this.layoutRoot.innerHTML = "";
        this.rowElements = [];

        this.layoutRows.forEach((row, index) => {
            const rowEl = this.createRowElement(row, index);
            this.layoutRoot?.appendChild(rowEl);
            this.rowElements.push(rowEl);
        });

        this.bindRows();
    }

    protected createRowElement(row: SectionedLayoutRowPayload, index: number): HTMLElement {
        const rowEl = document.createElement("div");
        rowEl.className = "workspace-row";
        rowEl.dataset.layoutRow = "true";
        rowEl.dataset.rowIndex = String(index);
        rowEl.dataset.rowTitle = row.title ?? "";
        rowEl.dataset.rowColumns = String(row.columns);
        rowEl.tabIndex = -1;

        rowEl.innerHTML = `
            <div class="workspace-row__header" data-row-header>
                <span class="workspace-row__title ${row.title ? "" : "workspace-row__title--empty"}" data-row-title-display>${row.title ?? "&nbsp;"}</span>
                <div class="workspace-row__controls" data-row-controls>
                    <input type="text" class="input input-sm min-w-32" data-row-title-input value="${row.title ?? ""}" placeholder="Row title" />
                    <input type="number" min="1" max="12" value="${row.columns}" class="workspace-row__input" data-row-cols-input />
                    <button type="button" class="workspace-row__add" data-add-row title="Add row below">
                        <i class="fa fa-plus"></i>
                    </button>
                    <button type="button" class="workspace-row__drag" data-row-drag-handle title="Drag row">
                        <i class="fa fa-grip-vertical"></i>
                    </button>
                    <button type="button" class="workspace-row__remove" data-remove-row title="Remove row">
                        <i class="fa fa-xmark"></i>
                    </button>
                </div>
            </div>
            <div class="workspace-row__grid" data-layout-grid style="grid-template-columns: repeat(${row.columns}, minmax(0, 1fr));"></div>
        `;

        return rowEl;
    }

    protected bindRows(): void {
        this.rowElements = Array.from(this.element?.querySelectorAll<HTMLElement>("[data-layout-row]") ?? []);
        this.rowElements.forEach((rowEl, index) => {
            rowEl.dataset.rowIndex = String(index);

            const header = rowEl.querySelector<HTMLElement>("[data-row-header]");
            header?.setAttribute("draggable", "false");

            const dragHandle = rowEl.querySelector<HTMLElement>("[data-row-drag-handle]");
            dragHandle?.setAttribute("draggable", "false");
            if (dragHandle && !dragHandle.dataset.bound) {
                dragHandle.dataset.bound = "true";
                dragHandle.addEventListener("mousedown", () => {
                    this.focusRowByIndex(this.getRowIndexFromElement(dragHandle));
                });
            }

            const colsInput = rowEl.querySelector<HTMLInputElement>("[data-row-cols-input]");
            if (colsInput && !colsInput.dataset.bound) {
                colsInput.dataset.bound = "true";
                colsInput.addEventListener("change", () => {
                    const next = this.clampRowCols(Number.parseInt(colsInput.value, 10));
                    colsInput.value = String(next);
                    this.updateRowColumns(this.getRowIndexFromElement(colsInput), next);
                });
            }

            const titleInput = rowEl.querySelector<HTMLInputElement>("[data-row-title-input]");
            if (titleInput && !titleInput.dataset.bound) {
                titleInput.dataset.bound = "true";
                titleInput.addEventListener("input", () => {
                    const currentRow = titleInput.closest<HTMLElement>("[data-layout-row]");
                    const nextTitle = titleInput.value.trim();
                    if (!currentRow) return;
                    currentRow.dataset.rowTitle = nextTitle;
                    this.updateRowTitleDisplay(currentRow, nextTitle);
                });
                titleInput.addEventListener("change", () => {
                    this.updateRowTitle(this.getRowIndexFromElement(titleInput), titleInput.value);
                });
            }

            const removeButton = rowEl.querySelector<HTMLElement>("[data-remove-row]");
            if (removeButton && !removeButton.dataset.bound) {
                removeButton.dataset.bound = "true";
                removeButton.addEventListener("click", () => {
                    this.removeRow(this.getRowIndexFromElement(removeButton));
                });
            }

            const addRowButton = rowEl.querySelector<HTMLElement>("[data-add-row]");
            if (addRowButton && !addRowButton.dataset.bound) {
                addRowButton.dataset.bound = "true";
                addRowButton.addEventListener("click", () => {
                    this.addRowAfter(this.getRowIndexFromElement(addRowButton));
                });
            }

            const grid = rowEl.querySelector<HTMLElement>("[data-layout-grid]");
            if (grid && !grid.dataset.bound) {
                grid.dataset.bound = "true";
            }
        });

        this.updateRowControlVisibility();
        this.refreshSortables();
    }

    protected onClick(event: MouseEvent): void {
        const target = event.target as HTMLElement | null;
        if (!target) return;
        if (this.isInteractiveTarget(target)) return;

        const rowElement = target.closest<HTMLElement>("[data-layout-row]");
        const itemElement = target.closest<HTMLElement>(this.getItemSelector());

        if (itemElement) {
            const index = Number.parseInt(itemElement.dataset.itemIndex ?? "0", 10);
            this.focusItemByIndex(index);
            return;
        }

        if (this.editMode && rowElement) {
            const rowIndex = Number.parseInt(rowElement.dataset.rowIndex ?? "0", 10);
            this.focusRowByIndex(rowIndex);
        }
    }

    protected onKeyDown(event: KeyboardEvent): void {
        if (!this.editMode) {
            this.handleReadModeKeyDown(event);
            return;
        }

        const target = event.target as HTMLElement | null;
        if (target && this.isInteractiveTarget(target)) {
            return;
        }

        if (this.items.length === 0 && this.rowElements.length === 0) return;

        const addRowCombo = this.isRowFocused && event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey && (event.key === "+" || event.key === "=");
        if (addRowCombo) {
            event.preventDefault();
            this.addRowAfter(this.focusedRowIndex);
            return;
        }

        const removeRowCombo = this.isRowFocused && event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey && (event.key === "-" || event.key === "_");
        if (removeRowCombo) {
            event.preventDefault();
            this.removeRow(this.focusedRowIndex);
            return;
        }

        const resizeCombo = event.altKey && event.shiftKey && (event.key === "ArrowLeft" || event.key === "ArrowRight");
        if (resizeCombo) {
            event.preventDefault();
            if (this.isRowFocused) {
                const delta = event.key === "ArrowRight" ? 1 : -1;
                const current = this.layoutRows[this.focusedRowIndex];
                if (!current) return;
                this.updateRowColumns(this.focusedRowIndex, current.columns + delta);
                return;
            }

            const item = this.items[this.focusedItemIndex];
            if (!item) return;
            item.setColspan(item.getColspan() + (event.key === "ArrowRight" ? 1 : -1));
            return;
        }

        const moveCombo = event.altKey && !event.shiftKey && !event.metaKey && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key);
        if (moveCombo) {
            event.preventDefault();
            if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                if (this.isRowFocused) {
                    this.moveRow(this.focusedRowIndex, this.focusedRowIndex + (event.key === "ArrowDown" ? 1 : -1));
                    return;
                }
                this.moveItemBetweenRows(this.focusedItemIndex, event.key === "ArrowDown" ? 1 : -1);
                return;
            }

            if (!this.isRowFocused) {
                this.moveItemWithinRow(this.focusedItemIndex, event.key === "ArrowRight" ? 1 : -1);
            }
            return;
        }

        const removeCombo = event.altKey && !event.shiftKey && !event.metaKey && !event.ctrlKey && ["Backspace", "Delete"].includes(event.key);
        if (removeCombo) {
            event.preventDefault();
            if (this.isRowFocused) {
                this.removeRow(this.focusedRowIndex);
                return;
            }

            const item = this.items[this.focusedItemIndex];
            if (item) {
                this.removeItem(item);
            }
            return;
        }

        if (event.altKey || event.metaKey || event.shiftKey) return;

        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
            event.preventDefault();
            if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                if (!this.isRowFocused) {
                    this.focusRowByIndex(this.getRowIndexForItem(this.items[this.focusedItemIndex]));
                    return;
                }
                this.focusRowByIndex(this.focusedRowIndex + (event.key === "ArrowDown" ? 1 : -1));
                return;
            }

            if (this.isRowFocused) {
                this.focusFirstItemInRow(this.focusedRowIndex);
                return;
            }

            this.focusItemByIndex(this.focusedItemIndex + (event.key === "ArrowRight" ? 1 : -1));
        }
    }

    protected setupDnD(): void {
        this.refreshSortables();
    }

    protected reindexItems(): void {
        if (!this.element) return;

        const itemElements = Array.from(this.element.querySelectorAll<HTMLElement>(this.getItemSelector()));
        this.items = itemElements
            .map((element) => {
                const item = this.getItemComponent(element);
                if (!item) return null;
                return item;
            })
            .filter((item): item is TItem => item !== null);

        this.items.forEach((item, index) => {
            if (!item.element) return;
            item.element.dataset.itemIndex = String(index);
            item.setEditMode(this.editMode);
            item.setMaxCols(this.getRowColumnsForItem(item));

            const removeButton = item.element.querySelector<HTMLElement>("[data-layout-remove-item]");
            if (removeButton && !removeButton.dataset.bound) {
                removeButton.dataset.bound = "true";
                removeButton.addEventListener("click", () => {
                    this.removeItem(item);
                });
            }
        });

        this.focusedItemIndex = Math.min(this.focusedItemIndex, Math.max(0, this.items.length - 1));
    }

    protected getRowColumnsForItem(item: TItem): number {
        const rowIndex = this.getRowIndexForItem(item);
        return this.layoutRows[rowIndex]?.columns ?? 1;
    }

    protected focusItemByIndex(index: number): void {
        if (this.items.length === 0) return;

        const bounded = Math.max(0, Math.min(index, this.items.length - 1));
        this.focusedItemIndex = bounded;
        this.isRowFocused = false;

        this.items.forEach((item, itemIndex) => {
            item.element?.classList.toggle("workspace-tile--focused", itemIndex === bounded && this.shouldApplyFocusedItemClass());
            if (item.element) {
                item.element.tabIndex = itemIndex === bounded ? 0 : -1;
            }
        });

        this.updateRowControlVisibility();
        const focusedItem = this.items[bounded];
        if (!focusedItem) return;
        this.onInitialItemFocus(focusedItem);

        if (this.editMode) {
            focusedItem.focusEditModeTarget();
            return;
        }

        focusedItem.focusReadModeTarget();
    }

    protected focusRowByIndex(index: number): void {
        if (this.rowElements.length === 0) return;
        const bounded = Math.max(0, Math.min(index, this.rowElements.length - 1));
        this.focusedRowIndex = bounded;
        this.isRowFocused = true;

        this.items.forEach((item) => {
            item.element?.classList.remove("workspace-tile--focused");
            if (item.element) {
                item.element.tabIndex = -1;
            }
        });

        this.updateRowControlVisibility();
        this.rowElements[bounded]?.focus();
    }

    protected focusFirstItemInRow(rowIndex: number): void {
        const rowEl = this.rowElements[rowIndex];
        const itemEl = rowEl?.querySelector<HTMLElement>(this.getItemSelector());
        if (!itemEl) return;
        this.focusItemByIndex(Number.parseInt(itemEl.dataset.itemIndex ?? "0", 10));
    }

    protected updateRowControlVisibility(): void {
        this.element?.classList.toggle("workspace-edit-mode", this.editMode);
        this.element?.classList.toggle("workspace-row-selection", this.isRowFocused);
        this.openSidebarButtons.forEach((button) => {
            button.classList.toggle("hidden", !this.editMode);
            button.classList.toggle("inline-flex", this.editMode);
        });

        this.rowElements.forEach((rowEl, index) => {
            const isFocused = this.isRowFocused && index === this.focusedRowIndex;
            rowEl.classList.toggle("workspace-row--focused", isFocused);
            rowEl.tabIndex = isFocused ? 0 : -1;
        });
    }

    protected updateRowColumns(rowIndex: number, columns: number): void {
        const row = this.layoutRows[rowIndex];
        const rowEl = this.rowElements[rowIndex];
        if (!row || !rowEl) return;

        row.columns = this.clampRowCols(columns);
        rowEl.dataset.rowColumns = String(row.columns);
        const colsInput = rowEl.querySelector<HTMLInputElement>("[data-row-cols-input]");
        if (colsInput) {
            colsInput.value = String(row.columns);
        }
        const grid = rowEl.querySelector<HTMLElement>("[data-layout-grid]");
        if (grid) {
            grid.style.gridTemplateColumns = `repeat(${row.columns}, minmax(0, 1fr))`;
        }

        this.reindexItems();
        this.syncItemMaxColumns();
        void this.requestSave();
    }

    protected updateRowTitle(rowIndex: number, title: string): void {
        const row = this.layoutRows[rowIndex];
        const rowEl = this.rowElements[rowIndex];
        if (!row || !rowEl) return;

        row.title = title.trim() ? title.trim() : null;
        rowEl.dataset.rowTitle = row.title ?? "";
        this.updateRowTitleDisplay(rowEl, row.title);

        void this.requestSave();
    }

    protected removeRow(rowIndex: number): void {
        if (this.rowElements.length <= 1) return;

        const rowEl = this.rowElements[rowIndex];
        const destinationRow = this.rowElements[rowIndex + 1] ?? this.rowElements[rowIndex - 1];
        const destinationGrid = destinationRow?.querySelector<HTMLElement>("[data-layout-grid]");
        if (rowEl && destinationGrid) {
            const items = Array.from(rowEl.querySelectorAll<HTMLElement>(this.getItemSelector()));
            items.forEach((item) => destinationGrid.appendChild(item));
        }

        rowEl?.remove();
        this.layoutRows.splice(rowIndex, 1);
        this.reindexRows();
        const nextFocusIndex = Math.max(0, Math.min(rowIndex, this.rowElements.length - 1));
        this.focusRowByIndex(nextFocusIndex);
        void this.requestSave();
    }

    protected addRowAfter(rowIndex: number): void {
        if (!this.layoutRoot) return;

        const boundedRowIndex = Math.max(0, Math.min(rowIndex, this.rowElements.length - 1));
        const referenceRow = this.layoutRows[boundedRowIndex];
        const nextRow: SectionedLayoutRowPayload = {
            title: null,
            columns: referenceRow?.columns ?? 4,
            items: [],
        };

        const nextIndex = boundedRowIndex + 1;
        this.layoutRows.splice(nextIndex, 0, nextRow);
        const nextRowElement = this.createRowElement(nextRow, nextIndex);
        const anchor = this.rowElements[nextIndex] ?? null;
        this.layoutRoot.insertBefore(nextRowElement, anchor);
        this.reindexRows();
        this.focusRowByIndex(nextIndex);
        void this.requestSave();
    }

    protected removeItem(item: TItem): void {
        const removedIndex = this.items.indexOf(item);
        item.element?.remove();
        this.reindexItems();
        if (this.items.length > 0) {
            this.focusItemByIndex(Math.max(0, Math.min(removedIndex, this.items.length - 1)));
        }
        this.syncAvailableItemsState();
        void this.requestSave();
    }

    protected reindexRows(): void {
        this.rowElements = Array.from(this.element?.querySelectorAll<HTMLElement>("[data-layout-row]") ?? []);
        this.layoutRows = this.rowElements.map((rowEl) => ({
            title: rowEl.dataset.rowTitle?.trim() || null,
            columns: this.clampRowCols(Number.parseInt(rowEl.dataset.rowColumns ?? "4", 10)),
            items: Array.from(rowEl.querySelectorAll<HTMLElement>(this.getItemSelector())).map((itemEl) => ({
                id: this.normalizeLayoutItemId(itemEl.dataset.layoutItemId),
                colspan: this.clampColspan(Number.parseInt(itemEl.dataset.colspan ?? "1", 10), this.clampRowCols(Number.parseInt(rowEl.dataset.rowColumns ?? "4", 10))),
            })).filter((item): item is SectionedLayoutItemPayload => item.id !== null),
        }));
        this.bindRows();
        this.reindexItems();
        this.syncItemMaxColumns();
    }

    protected moveRow(fromIndex: number, toIndex: number): void {
        if (!this.layoutRoot || fromIndex === toIndex) return;
        const boundedTo = Math.max(0, Math.min(toIndex, this.rowElements.length - 1));
        const row = this.rowElements[fromIndex];
        if (!row) return;

        const anchor = this.rowElements[boundedTo + (boundedTo > fromIndex ? 1 : 0)] ?? null;
        this.layoutRoot.insertBefore(row, anchor);
        this.reindexRows();
        this.focusRowByIndex(boundedTo);
        void this.requestSave();
    }

    protected moveItemWithinRow(itemIndex: number, delta: number): void {
        const item = this.items[itemIndex];
        if (!item?.element) return;

        const row = item.element.closest<HTMLElement>("[data-layout-row]");
        const grid = row?.querySelector<HTMLElement>("[data-layout-grid]");
        if (!row || !grid) return;

        const rowItems = Array.from(row.querySelectorAll<HTMLElement>(this.getItemSelector()));
        const currentIndex = rowItems.indexOf(item.element);
        const nextIndex = currentIndex + delta;
        if (nextIndex < 0 || nextIndex >= rowItems.length) return;

        const anchor = rowItems[delta > 0 ? nextIndex + 1 : nextIndex] ?? null;
        if (anchor) {
            grid.insertBefore(item.element, anchor);
        } else {
            grid.appendChild(item.element);
        }

        this.reindexItems();
        this.focusItemByIndex(this.items.indexOf(item));
        void this.requestSave();
    }

    protected moveItemBetweenRows(itemIndex: number, deltaRows: number): void {
        const item = this.items[itemIndex];
        if (!item?.element) return;

        const currentRowIndex = this.getRowIndexForItem(item);
        const targetRowIndex = Math.max(0, Math.min(this.rowElements.length - 1, currentRowIndex + deltaRows));
        if (targetRowIndex === currentRowIndex) return;

        const targetGrid = this.rowElements[targetRowIndex]?.querySelector<HTMLElement>("[data-layout-grid]");
        if (!targetGrid) return;

        targetGrid.appendChild(item.element);
        item.setMaxCols(this.layoutRows[targetRowIndex]?.columns ?? 1);
        this.reindexItems();
        this.focusItemByIndex(this.items.indexOf(item));
        void this.requestSave();
    }

    protected getRowIndexForItem(item?: TItem): number {
        const rowEl = item?.element?.closest<HTMLElement>("[data-layout-row]");
        const rowIndex = Number.parseInt(rowEl?.dataset.rowIndex ?? "0", 10);
        return Number.isFinite(rowIndex) ? rowIndex : 0;
    }

    protected syncItemMaxColumns(): void {
        this.items.forEach((item) => {
            item.setMaxCols(this.getRowColumnsForItem(item));
        });
    }

    protected requestSave(): Promise<void> {
        return new Promise((resolve) => {
            if (this.saveTimeoutId !== null) {
                window.clearTimeout(this.saveTimeoutId);
            }

            this.saveTimeoutId = window.setTimeout(() => {
                this.saveTimeoutId = null;
                void this.flushSave().then(resolve);
            }, BaseSectionedLayoutContainer.SAVE_DEBOUNCE_MS);
        });
    }

    protected async flushSave(): Promise<void> {
        if (!this.element) return;
        if (this.saveInFlight) {
            this.pendingSaveAfterFlight = true;
            await this.saveInFlight;
            return;
        }

        this.saveInFlight = this.performSave();
        try {
            await this.saveInFlight;
        } finally {
            this.saveInFlight = null;
            if (this.pendingSaveAfterFlight) {
                this.pendingSaveAfterFlight = false;
                await this.flushSave();
            }
        }
    }

    protected async performSave(): Promise<void> {
        if (!this.element) return;
        const payload = this.getSavePayload();
        this.element.setAttribute("data-layout", JSON.stringify(payload.layout));
        this.layoutRows = payload.layout.rows;

        const saveUrl = this.element.dataset.layoutSaveUrl;
        if (!saveUrl) return;

        await fetch(saveUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...(getCsrfToken() ? { "X-CSRFToken": getCsrfToken() ?? "" } : {}),
            },
            body: JSON.stringify(payload),
        });
    }

    protected serializeRows(): SectionedLayoutRowPayload[] {
        return this.rowElements.map((rowEl) => {
            const columns = this.clampRowCols(Number.parseInt(rowEl.dataset.rowColumns ?? "4", 10));
            const title = rowEl.dataset.rowTitle?.trim() || null;
            const items = Array.from(rowEl.querySelectorAll<HTMLElement>(this.getItemSelector()))
                .map((itemEl) => ({
                    id: this.normalizeLayoutItemId(itemEl.dataset.layoutItemId),
                    colspan: this.clampColspan(Number.parseInt(itemEl.dataset.colspan ?? "1", 10), columns),
                }))
                .filter((item): item is SectionedLayoutItemPayload => item.id !== null);

            return { title, columns, items };
        });
    }

    protected async loadAvailableItems(): Promise<void> {
        const container = this.element?.querySelector<HTMLElement>("[data-layout-available-items]");
        const url = this.element?.dataset.layoutAvailableItemsUrl;
        if (!container || !url) return;

        await htmx.ajax("get", url, {
            target: container,
            swap: "innerHTML",
        });
        this.bindSidebarItems(container);
        this.syncAvailableItemsState();
    }

    protected bindSidebarItems(container: HTMLElement): void {
        const items = Array.from(container.querySelectorAll<HTMLElement>("[data-layout-sidebar-item]"));
        items.forEach((item) => {
            if (!item.dataset.bound) {
                item.dataset.bound = "true";
                item.setAttribute("draggable", "false");
                item.addEventListener("click", () => {
                    if (!this.editMode) return;
                    const itemId = this.normalizeLayoutItemId(item.dataset.layoutItemId);
                    if (!itemId) return;
                    if (this.items.some((layoutItem) => layoutItem.getLayoutItemId() === itemId)) return;
                    const targetRowIndex = this.isRowFocused ? this.focusedRowIndex : Math.max(0, this.getRowIndexForItem(this.items[this.focusedItemIndex]));
                    void this.renderItem(itemId, targetRowIndex).then(() => {
                        this.reindexItems();
                        this.syncAvailableItemsState();
        void this.requestSave();
                    });
                });
            }
        });
        this.refreshSortables();
    }

    protected syncAvailableItemsState(): void {
        const usedIds = new Set(this.items.map((item) => item.getLayoutItemId()));
        const sidebarItems = this.element?.querySelectorAll<HTMLElement>("[data-layout-sidebar-item]") ?? [];
        sidebarItems.forEach((sidebarItem) => {
            const itemId = this.normalizeLayoutItemId(sidebarItem.dataset.layoutItemId);
            const used = itemId !== null && usedIds.has(itemId);
            sidebarItem.classList.toggle("opacity-50", used);
            sidebarItem.toggleAttribute("disabled", used);
            sidebarItem.setAttribute("aria-disabled", used ? "true" : "false");
            sidebarItem.setAttribute("draggable", "false");
        });
    }

    protected destroySortables(): void {
        this.rowSortable?.destroy();
        this.rowSortable = null;

        this.gridSortables.forEach((sortable) => sortable.destroy());
        this.gridSortables = [];

        this.sidebarSortable?.destroy();
        this.sidebarSortable = null;
    }

    protected refreshSortables(): void {
        if (!this.layoutRoot) return;

        this.destroySortables();
        this.rowSortable = Sortable.create(this.layoutRoot, {
            animation: 180,
            easing: "cubic-bezier(0.22, 1, 0.36, 1)",
            draggable: "[data-layout-row]",
            handle: "[data-row-drag-handle]",
            forceFallback: true,
            fallbackOnBody: true,
            fallbackTolerance: BaseSectionedLayoutContainer.DRAG_START_TOLERANCE_PX,
            swapThreshold: BaseSectionedLayoutContainer.DRAG_SWAP_THRESHOLD,
            disabled: !this.editMode,
            ghostClass: "workspace-row--drag-ghost",
            chosenClass: "workspace-row--drag-chosen",
            dragClass: "workspace-row--dragging",
            onEnd: (event) => this.onRowSortEnd(event),
        });

        this.gridSortables = this.rowElements
            .map((rowEl) => {
                const grid = rowEl.querySelector<HTMLElement>("[data-layout-grid]");
                if (!grid) return null;

                return Sortable.create(grid, {
                    group: "layout-items",
                    animation: 180,
                    easing: "cubic-bezier(0.22, 1, 0.36, 1)",
                    draggable: this.getItemSelector(),
                    handle: "[data-layout-item-drag-handle]",
                    forceFallback: true,
                    fallbackOnBody: true,
                    fallbackTolerance: BaseSectionedLayoutContainer.DRAG_START_TOLERANCE_PX,
                    emptyInsertThreshold: 24,
                    swapThreshold: BaseSectionedLayoutContainer.DRAG_SWAP_THRESHOLD,
                    invertSwap: true,
                    disabled: !this.editMode,
                    ghostClass: "workspace-tile--drag-ghost",
                    chosenClass: "workspace-tile--drag-chosen",
                    dragClass: "workspace-tile--dragging",
                    onAdd: (event) => this.onItemSortAdd(event, rowEl),
                    onEnd: (event) => this.onItemSortEnd(event),
                });
            })
            .filter((sortable): sortable is Sortable => sortable !== null);

        const sidebarList = this.element?.querySelector<HTMLElement>("[data-layout-available-items-list]");
        if (sidebarList) {
            this.sidebarSortable = Sortable.create(sidebarList, {
                group: {
                    name: "layout-items",
                    pull: "clone",
                    put: false,
                },
                sort: false,
                animation: 180,
                easing: "cubic-bezier(0.22, 1, 0.36, 1)",
                draggable: "[data-layout-sidebar-item]",
                filter: "[disabled]",
                forceFallback: true,
                fallbackOnBody: true,
                fallbackTolerance: BaseSectionedLayoutContainer.DRAG_START_TOLERANCE_PX,
                disabled: !this.editMode,
                ghostClass: "workspace-sidebar-item--drag-ghost",
                chosenClass: "workspace-sidebar-item--drag-chosen",
                dragClass: "workspace-sidebar-item--dragging",
                onMove: (event) => this.canDragSidebarItem(event.dragged as HTMLElement | null),
            });
        }
    }

    protected updateSortableDisabledState(): void {
        this.rowSortable?.option("disabled", !this.editMode);
        this.gridSortables.forEach((sortable) => sortable.option("disabled", !this.editMode));
        this.sidebarSortable?.option("disabled", !this.editMode);
    }

    protected onRowSortEnd(event: SortableEvent): void {
        if (typeof event.oldIndex !== "number" || typeof event.newIndex !== "number" || event.oldIndex === event.newIndex) {
            return;
        }

        this.reindexRows();
        this.focusRowByIndex(event.newIndex);
        void this.requestSave();
    }

    protected onItemSortAdd(event: SortableEvent, rowEl: HTMLElement): void {
        if (!this.isSidebarList(event.from)) return;

        const placeholder = event.item as HTMLElement | null;
        const itemId = this.normalizeLayoutItemId(placeholder?.dataset.layoutItemId);
        const position = typeof event.newIndex === "number" ? event.newIndex : undefined;
        placeholder?.remove();

        if (!itemId || this.items.some((item) => item.getLayoutItemId() === itemId)) {
            this.syncAvailableItemsState();
            return;
        }

        const rowIndex = this.getRowIndexFromElement(rowEl);
        void this.renderItem(itemId, rowIndex, position).then(() => {
            this.reindexRows();
            this.syncAvailableItemsState();
            const insertedIndex = this.items.findIndex((item) => item.getLayoutItemId() === itemId);
            if (insertedIndex >= 0) {
                this.focusItemByIndex(insertedIndex);
            }
            void this.requestSave();
        });
    }

    protected onItemSortEnd(event: SortableEvent): void {
        if (this.isSidebarList(event.from)) return;

        const itemEl = event.item as HTMLElement | null;
        if (!itemEl?.matches(this.getItemSelector())) return;
        if (typeof event.oldIndex !== "number" || typeof event.newIndex !== "number") return;
        if (event.from === event.to && event.oldIndex === event.newIndex) return;

        this.reindexRows();
        this.syncAvailableItemsState();
        const movedItem = this.getItemComponent(itemEl);
        const movedIndex = movedItem ? this.items.indexOf(movedItem) : -1;
        if (movedIndex >= 0) {
            this.focusItemByIndex(movedIndex);
        }
        void this.requestSave();
    }

    protected isSidebarList(element: HTMLElement | null | undefined): boolean {
        return Boolean(element?.matches("[data-layout-available-items-list]"));
    }

    protected canDragSidebarItem(item: HTMLElement | null): boolean {
        return Boolean(item && !item.hasAttribute("disabled"));
    }

    protected getInsertPosition(rowEl: HTMLElement | null, x: number, y: number): number {
        const rowItems = Array.from(rowEl?.querySelectorAll<HTMLElement>(this.getItemSelector()) ?? []);
        const afterItem = this.getItemAfterElement(rowEl?.querySelector<HTMLElement>("[data-layout-grid]") ?? null, x, y);
        if (!afterItem) return rowItems.length;
        return rowItems.indexOf(afterItem);
    }

    protected getItemAfterElement(container: HTMLElement | null, x: number, y: number): HTMLElement | null {
        if (!container) return null;

        const items = Array.from(container.querySelectorAll<HTMLElement>(`${this.getItemSelector()}:not(.workspace-tile--dragging)`));
        if (items.length === 0) return null;

        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.POSITIVE_INFINITY, element: null };
        items.forEach((item) => {
            const box = item.getBoundingClientRect();
            const centerX = box.left + box.width / 2;
            const centerY = box.top + box.height / 2;
            const offset = Math.hypot(centerX - x, centerY - y);
            if (offset < closest.offset) {
                closest = { offset, element: item };
            }
        });
        return closest.element;
    }

    protected getRowAfterElement(y: number): HTMLElement | null {
        const rows = Array.from(this.element?.querySelectorAll<HTMLElement>("[data-layout-row]:not(.workspace-row--dragging)") ?? []);
        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.NEGATIVE_INFINITY, element: null };
        rows.forEach((row) => {
            const box = row.getBoundingClientRect();
            const offset = y - (box.top + box.height / 2);
            if (offset < 0 && offset > closest.offset) {
                closest = { offset, element: row };
            }
        });
        return closest.element;
    }

    protected getRowForPoint(y: number): HTMLElement | null {
        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.POSITIVE_INFINITY, element: null };
        this.rowElements.forEach((row) => {
            const box = row.getBoundingClientRect();
            const centerY = box.top + box.height / 2;
            const offset = Math.abs(centerY - y);
            if (offset < closest.offset) {
                closest = { offset, element: row };
            }
        });
        return closest.element;
    }

    protected clampRowCols(value: number): number {
        if (!Number.isFinite(value)) return 1;
        return Math.max(1, Math.min(12, Math.round(value)));
    }

    protected clampColspan(value: number, columns: number): number {
        if (!Number.isFinite(value)) return 1;
        return Math.max(1, Math.min(this.clampRowCols(columns), Math.round(value)));
    }

    protected isInteractiveTarget(target: HTMLElement): boolean {
        return Boolean(
            target.closest(
                "input, textarea, select, option, button, a, [contenteditable=\"true\"], [data-row-controls], [data-layout-item-controls]",
            ),
        );
    }

    protected getRowIndexFromElement(element: HTMLElement | null): number {
        const rowEl = element?.closest<HTMLElement>("[data-layout-row]");
        const rowIndex = Number.parseInt(rowEl?.dataset.rowIndex ?? "0", 10);
        return Number.isFinite(rowIndex) ? rowIndex : 0;
    }

    protected updateRowTitleDisplay(rowEl: HTMLElement, title: string | null): void {
        const display = rowEl.querySelector<HTMLElement>("[data-row-title-display]");
        if (!display) return;

        const hasTitle = Boolean(title);
        display.textContent = hasTitle ? (title ?? "") : " ";
        display.classList.toggle("workspace-row__title--empty", !hasTitle);
    }

    protected async insertRenderedItem(targetGrid: HTMLElement, position: number | undefined): Promise<void> {
        initComponents(targetGrid);
        this.reindexItems();
        if (typeof position !== "number") return;

        const rendered = this.items[this.items.length - 1];
        if (!rendered?.element) return;
        const siblings = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
        const anchor = siblings[position] ?? null;
        if (anchor && anchor !== rendered.element) {
            targetGrid.insertBefore(rendered.element, anchor);
        }
        this.reindexItems();
    }
}
