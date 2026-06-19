import htmx from "htmx.org";
import Sortable, { type SortableEvent } from "sortablejs";

import BaseComponent, { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutItem from "./BaseSectionedLayoutItem";
import { getCsrfToken } from "../../utils/cookies";
import { parseBoolean } from "../../utils/booleans";

export type SectionedLayoutItemPayload = {
    id: string;
    colspan: number;
    config: Record<string, unknown>;
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

type SearchMatch<TItem extends BaseSectionedLayoutItem> = {
    item: TItem;
    text: string;
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
    protected searchButton: HTMLButtonElement | null = null;
    protected searchPanel: HTMLElement | null = null;
    protected searchInput: HTMLInputElement | null = null;
    protected searchStatus: HTMLElement | null = null;
    protected searchButtonHandler: (() => void) | null = null;
    protected searchInputHandler: (() => void) | null = null;
    protected searchKeydownHandler: ((event: KeyboardEvent) => void) | null = null;
    protected searchActive = false;
    protected searchMatches: SearchMatch<TItem>[] = [];
    protected activeSearchMatchIndex: number | null = null;

    protected abstract getItemComponent(element: HTMLElement): TItem | null;
    protected abstract getItemSelector(): string;
    protected abstract renderItem(itemId: string, rowIndex: number, position?: number): Promise<void>;
    

    protected getSavePayload():SavePayload {
        // Get the content type id of the object
        

        return {
            content_type_id: Number.parseInt(this.element?.dataset.contentTypeId ?? "", 10) || null,
            layout: {
                rows: this.serializeRows(),
            },
        };
    }

    protected normalizeLayoutItemId(value: unknown): string | null {
        if (value === null || value === undefined) return null;
        const normalized = String(value).trim();
        return normalized ? normalized : null;
    }

    protected normalizeLayoutItemConfig(value: unknown): Record<string, unknown> {
        if (!value || typeof value !== "object" || Array.isArray(value)) return {};
        return value as Record<string, unknown>;
    }

    protected parseLayoutItemConfig(value: string | undefined): Record<string, unknown> {
        if (!value) return {};
        try {
            return this.normalizeLayoutItemConfig(JSON.parse(value));
        } catch {
            return {};
        }
    }

    protected async loadInitialItems(): Promise<void> {
        for (let rowIndex = 0; rowIndex < this.layoutRows.length; rowIndex += 1) {
            const row = this.layoutRows[rowIndex];
            const rowEl = this.rowElements[rowIndex];
            const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
            if (!targetGrid) continue;

            const expectedIds = new Set(row.items.map((item) => item.id));
            const seenIds = new Set<string>();

            Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector())).forEach((element) => {
                const itemId = this.normalizeLayoutItemId(element.dataset.layoutItemId);
                if (!itemId) {
                    element.remove();
                    return;
                }
                if (!expectedIds.has(itemId) || seenIds.has(itemId)) {
                    element.remove();
                    return;
                }

                seenIds.add(itemId);
                const component = this.getItemComponent(element);
                component?.setMaxCols(row.columns);
            });

            for (const item of row.items) {
                if (seenIds.has(item.id)) {
                    continue;
                }
                // eslint-disable-next-line no-await-in-loop
                await this.renderItem(item.id, rowIndex);
                seenIds.add(item.id);
            }
        }
    }

    protected handleReadModeKeyDown(_event: KeyboardEvent): void {
        // Optional subclass hook
    }

    protected isFnNavigationModifier(event: KeyboardEvent): boolean {
        return event.getModifierState("Fn");
    }

    protected getFnNavigationKey(event: KeyboardEvent): string | null {
        const fnModifierActive = this.isFnNavigationModifier(event);
        const isMacPlatform = navigator.platform.toLowerCase().includes("mac");

        switch (event.key) {
            case "ArrowLeft":
            case "ArrowRight":
            case "ArrowUp":
            case "ArrowDown":
                return fnModifierActive ? event.key : null;
            case "Home":
                return fnModifierActive || isMacPlatform ? "ArrowLeft" : null;
            case "End":
                return fnModifierActive || isMacPlatform ? "ArrowRight" : null;
            case "PageUp":
                return fnModifierActive || isMacPlatform ? "ArrowUp" : null;
            case "PageDown":
                return fnModifierActive || isMacPlatform ? "ArrowDown" : null;
            default:
                return null;
        }
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

        // Add event listener to edit button
        const editToggle = this.element.querySelector<HTMLElement>("[data-layout-edit-toggle]");
        editToggle?.addEventListener("click", () => this.toggleEditMode());

        // Add event listener to open sidebar button
        this.openSidebarButtons = Array.from(this.element.querySelectorAll<HTMLElement>("[data-layout-open-sidebar]"));
        this.openSidebarButtons.forEach((button) => {
            button.addEventListener("click", () => {
                void this.loadAvailableItems({ focusFirstItem: true });
            });
        });
        this.cacheSearchElements();
        this.searchButtonHandler = () => {
            if (this.searchActive) {
                this.closeSearch();
                return;
            }
            this.openSearch();
        };
        this.searchInputHandler = () => this.refreshSearchMatches();
        this.searchKeydownHandler = (event: KeyboardEvent) => this.onSearchKeyDown(event);
        this.searchButton?.addEventListener("click", this.searchButtonHandler);
        this.searchInput?.addEventListener("input", this.searchInputHandler);
        this.element.addEventListener("keydown", this.searchKeydownHandler, true);

        this.setupDnD();
        const initEditMode = this.parseBooleanDatasetValue(this.element.dataset.initEdit);
        this.itemLoadQueue = this.loadInitialItems().then(() => {
            this.reindexItems();
            this.syncAvailableItemsState();
            this.refreshSortables();

            if (initEditMode) {
                this.setEditMode(true);
            } else if (!this.editMode && this.items.length > 0) {
                this.focusItemByIndex(0);
            }

            if (this.searchActive) {
                this.refreshSearchMatches();
            }
        });
    }

    public override destroy(): void {
        this.destroySortables();
        if (this.searchButtonHandler) {
            this.searchButton?.removeEventListener("click", this.searchButtonHandler);
        }
        if (this.searchInputHandler) {
            this.searchInput?.removeEventListener("input", this.searchInputHandler);
        }
        if (this.searchKeydownHandler && this.element) {
            this.element.removeEventListener("keydown", this.searchKeydownHandler, true);
        }
        this.searchButton = null;
        this.searchPanel = null;
        this.searchInput = null;
        this.searchStatus = null;
        this.searchButtonHandler = null;
        this.searchInputHandler = null;
        this.searchKeydownHandler = null;
        this.searchMatches = [];
    }

    public override onAfterSwap(): void {
        this.cacheSearchElements();
        if (this.searchActive) {
            this.refreshSearchMatches();
        }
    }

    public toggleEditMode(): void {
        this.setEditMode(!this.editMode);
    }

    protected setEditMode(enabled: boolean): void {
        this.editMode = enabled;
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

    protected parseBooleanDatasetValue(value: string | undefined): boolean {
        return parseBoolean(value);
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
                            config: this.normalizeLayoutItemConfig(item.config),
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

    public focusFirstItemInRow(rowIndex: number): void {
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
        rowEl?.remove();
        this.layoutRows.splice(rowIndex, 1);
        this.reindexRows();
        this.syncAvailableItemsState();
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
                config: this.parseLayoutItemConfig(itemEl.dataset.layoutItemConfig),
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
                    config: this.parseLayoutItemConfig(itemEl.dataset.layoutItemConfig),
                }))
                .filter((item): item is SectionedLayoutItemPayload => item.id !== null);

            return { title, columns, items };
        });
    }

    public async loadAvailableItems(options?: { focusFirstItem?: boolean }): Promise<void> {
        const container = this.element?.querySelector<HTMLElement>("[data-layout-available-items]");
        const url = this.element?.dataset.layoutAvailableItemsUrl;
        if (!container || !url) return;

        await htmx.ajax("get", url, {
            target: container,
            swap: "innerHTML",
            values: this.element?.dataset.contentTypeId
                ? { content_type_id: this.element.dataset.contentTypeId }
                : undefined,
        });
        this.bindSidebarItems(container);
        this.syncAvailableItemsState();

        if (options?.focusFirstItem) {
            this.focusFirstAvailableSidebarItem();
        }
    }

    protected focusFirstAvailableSidebarItem(): void {
        let attemptsRemaining = 12;

        const tryFocus = () => {
            const firstAvailableItem = this.element?.querySelector<HTMLElement>(
                "[data-layout-sidebar-item]:not([disabled]):not([aria-disabled='true'])",
            );

            if (firstAvailableItem && this.isFocusableElement(firstAvailableItem) && this.isActionableElement(firstAvailableItem)) {
                firstAvailableItem.focus();
                if (document.activeElement === firstAvailableItem) {
                    return;
                }
            }

            attemptsRemaining -= 1;
            if (attemptsRemaining <= 0) return;
            window.requestAnimationFrame(tryFocus);
        };

        window.requestAnimationFrame(tryFocus);
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
                item.addEventListener("keydown", (event: KeyboardEvent) => {
                    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                        event.preventDefault();
                        event.stopPropagation();
                        this.moveSidebarItemFocus(item, event.key === "ArrowDown" ? 1 : -1);
                        return;
                    }

                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        item.click();
                    }
                });
            }
        });
        this.refreshSortables();
    }

    protected moveSidebarItemFocus(currentItem: HTMLElement, delta: number): void {
        const focusableSidebarItems = Array.from(
            this.element?.querySelectorAll<HTMLElement>("[data-layout-sidebar-item]:not([disabled]):not([aria-disabled='true'])") ?? [],
        );
        if (focusableSidebarItems.length === 0) return;

        const currentIndex = focusableSidebarItems.indexOf(currentItem);
        if (currentIndex < 0) {
            focusableSidebarItems[0]?.focus();
            return;
        }

        const nextIndex = Math.max(0, Math.min(focusableSidebarItems.length - 1, currentIndex + delta));
        focusableSidebarItems[nextIndex]?.focus();
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

    protected getSearchableItems(): TItem[] {
        return this.items.filter((item) => !item.element?.classList.contains("hidden"));
    }

    protected focusSearchMatch(item: TItem): void {
        const itemIndex = this.items.indexOf(item);
        if (itemIndex < 0) return;

        item.element?.scrollIntoView({ block: "center", inline: "nearest" });
        this.focusItemByIndex(itemIndex);
    }

    protected openSearch(): void {
        this.searchActive = true;
        this.searchPanel?.classList.remove("hidden");
        this.searchPanel?.setAttribute("aria-hidden", "false");
        this.searchButton?.setAttribute("aria-pressed", "true");
        this.refreshSearchMatches();
        this.searchInput?.focus();
        this.searchInput?.select();
    }

    protected closeSearch(): void {
        const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const focusWasInsideSearchPanel = !!(activeElement && this.searchPanel?.contains(activeElement));

        this.searchActive = false;
        this.activeSearchMatchIndex = null;
        this.searchMatches = [];
        this.searchPanel?.classList.add("hidden");
        this.searchPanel?.setAttribute("aria-hidden", "true");
        this.searchButton?.setAttribute("aria-pressed", "false");
        this.updateSearchStatus();

        if (focusWasInsideSearchPanel) {
            const currentItem = this.items[this.focusedItemIndex];
            if (currentItem) {
                this.focusSearchMatch(currentItem);
            } else {
                this.searchButton?.focus();
            }
        }
    }

    protected refreshSearchMatches(): void {
        const query = this.normalizeSearchQuery(this.searchInput?.value ?? "");
        const visibleItems = this.getSearchableItems();

        this.activeSearchMatchIndex = null;
        this.searchMatches = query
            ? visibleItems
                .map((item) => ({
                    item,
                    text: this.normalizeSearchQuery(item.getSearchText()),
                }))
                .filter((match) => match.text.includes(query))
            : [];

        this.updateSearchStatus();
    }

    protected focusNextSearchMatch(): void {
        if (this.searchMatches.length === 0) {
            this.updateSearchStatus();
            return;
        }

        const nextIndex = this.activeSearchMatchIndex === null
            ? 0
            : (this.activeSearchMatchIndex + 1) % this.searchMatches.length;
        const nextMatch = this.searchMatches[nextIndex];

        this.activeSearchMatchIndex = nextIndex;
        this.focusSearchMatch(nextMatch.item);
        this.updateSearchStatus();
    }

    protected normalizeSearchQuery(value: string): string {
        return value.trim().toLowerCase();
    }

    protected onSearchKeyDown(event: KeyboardEvent): void {
        if (!this.searchActive) return;
        if (event.altKey || event.ctrlKey || event.metaKey) return;

        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            this.closeSearch();
            return;
        }

        if (event.key === "Enter") {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            this.focusNextSearchMatch();
        }
    }

    protected updateSearchStatus(): void {
        if (!this.searchStatus) return;

        const totalMatches = this.searchMatches.length;
        if (!this.searchActive || totalMatches === 0) {
            this.searchStatus.textContent = "0 results";
            return;
        }

        if (this.activeSearchMatchIndex === null) {
            this.searchStatus.textContent = `? of ${totalMatches}`;
            return;
        }

        this.searchStatus.textContent = `${this.activeSearchMatchIndex + 1} of ${totalMatches}`;
    }

    protected cacheSearchElements(): void {
        this.searchButton = this.element?.querySelector<HTMLButtonElement>("[data-search-button]") ?? null;
        this.searchPanel = this.element?.querySelector<HTMLElement>("[data-form-search-panel]") ?? null;
        this.searchInput = this.element?.querySelector<HTMLInputElement>("[data-form-search-input]") ?? null;
        this.searchStatus = this.element?.querySelector<HTMLElement>("[data-form-search-status]") ?? null;
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
                "input, textarea, select, option, button, a, [contenteditable=\"true\"], [data-row-controls], [data-layout-item-controls], [data-layout-sidebar-item]",
            ),
        );
    }

    protected isFocusableElement(element: HTMLElement): boolean {
        if (typeof element.focus !== "function") return false;
        if (element.tabIndex >= 0) return true;
        return /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(element.tagName);
    }

    protected isActionableElement(element: HTMLElement): boolean {
        if (!element.isConnected) return false;
        if (element.hasAttribute("disabled") || element.getAttribute("aria-disabled") === "true") return false;

        const style = window.getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
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
