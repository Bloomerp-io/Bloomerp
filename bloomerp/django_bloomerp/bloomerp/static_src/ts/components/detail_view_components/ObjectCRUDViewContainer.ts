import htmx from "htmx.org";

import { type ContextMenuItem, getContextMenu } from "../../utils/contextMenu";
import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import { DetailViewCell, type DetailViewCellChangeDetail, type DetailViewCellSnapshot, type DetailViewCellValue } from "./DetailViewCell";

type RowInfo = {
    element: HTMLElement;
    columns: number;
    items: DetailViewCell[];
};

type PendingCellChange = {
    cell: DetailViewCell;
    previousValue: DetailViewCellValue;
    value: DetailViewCellValue;
    target: HTMLElement | null;
    previousSnapshot: DetailViewCellSnapshot;
    snapshot: DetailViewCellSnapshot;
};

export default class ObjectCRUDViewContainer extends BaseSectionedLayoutContainer<DetailViewCell> {
    private currentItem: DetailViewCell | null = null;
    private focusInHandler: ((event: FocusEvent) => void) | null = null;
    private nonRequiredFieldsVisible: boolean = true;
    private toggleVisibilityBtn: HTMLButtonElement | null = null;
    private toggleVisibilityLabel: HTMLElement | null = null;
    private openFullFormBtn: HTMLButtonElement | null = null;
    private toggleVisibilityHandler: (() => void) | null = null;
    private openFullFormHandler: (() => void) | null = null;
    private btnContainer: HTMLElement | null = null;
    private backBtn: HTMLButtonElement | null = null;
    private resetBtn: HTMLButtonElement | null = null;
    private pendingChanges: PendingCellChange[] = [];
    private detailViewCellChangeHandler: ((event: Event) => void) | null = null;
    private backButtonHandler: (() => void) | null = null;
    private resetButtonHandler: (() => void) | null = null;
    private undoShortcutHandler: ((event: KeyboardEvent) => void) | null = null;

    protected getItemSelector(): string {
        return `[${componentIdentifier}="detail-view-value"]`;
    }

    protected getItemComponent(element: HTMLElement): DetailViewCell | null {
        const component = getComponent(element);
        return component instanceof DetailViewCell ? component : null;
    }

    protected override shouldApplyFocusedItemClass(): boolean {
        return this.editMode;
    }

    protected override onInitialItemFocus(item: DetailViewCell): void {
        this.currentItem = item;
    }

    public override initialize(): void {
        super.initialize();
        this.items.forEach((item) => {
            if (!item.element || item.element.hasAttribute("tabindex")) return;
            item.element.setAttribute("tabindex", "0");
        });

        // Get the required fields visible
        this.nonRequiredFieldsVisible = !(this.element.dataset.nonRequiredFieldsVisible?.toLowerCase() === "false");
        this.toggleVisibilityBtn = this.element.querySelector<HTMLButtonElement>("[data-toggle-non-required-fields]");
        this.toggleVisibilityLabel = this.element.querySelector<HTMLElement>("[data-toggle-non-required-fields-label]");
        this.openFullFormBtn = this.element.querySelector<HTMLButtonElement>("[data-open-full-form]");
        this.toggleVisibilityHandler = () => this.toggleNonRequiredFieldsVisibility();
        this.openFullFormHandler = () => this.openFullForm();
        this.toggleVisibilityBtn?.addEventListener("click", this.toggleVisibilityHandler);
        this.openFullFormBtn?.addEventListener("click", this.openFullFormHandler);
        this.cacheChangeActionButtons();
        this.backButtonHandler = () => this.undoLastChange();
        this.resetButtonHandler = () => this.resetChanges();
        this.backBtn?.addEventListener("click", this.backButtonHandler);
        this.resetBtn?.addEventListener("click", this.resetButtonHandler);
        this.undoShortcutHandler = (event: KeyboardEvent) => {
            const isUndoShortcut = (event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "z";
            if (!isUndoShortcut) return;
            if (this.pendingChanges.length === 0) return;

            event.preventDefault();
            event.stopPropagation();
            this.undoLastChange();
        };
        this.element.addEventListener("keydown", this.undoShortcutHandler, true);
        this.detailViewCellChangeHandler = (event: Event) => {
            const customEvent = event as CustomEvent<DetailViewCellChangeDetail>;
            const { cell, previousValue, value, target, previousSnapshot, snapshot } = customEvent.detail;
            this.pendingChanges.push({
                cell,
                previousValue: this.cloneValue(previousValue),
                value: this.cloneValue(value),
                target,
                previousSnapshot: this.cloneSnapshot(previousSnapshot),
                snapshot: this.cloneSnapshot(snapshot),
            });
            console.log("ObjectCRUDViewContainer registered change:", {
                cell,
                previousValue,
                value,
                target,
                previousSnapshot,
                snapshot,
                pendingChanges: this.pendingChanges,
            });
            this.syncChangeButtonsVisibility();
        };
        this.element.addEventListener(DetailViewCell.changeEventName, this.detailViewCellChangeHandler);

        this.focusInHandler = (event: FocusEvent) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;
            const itemEl = target.closest<HTMLElement>(this.getItemSelector());
            if (!itemEl) return;

            const component = this.getItemComponent(itemEl);
            if (component) {
                this.currentItem = component;
            }
        };
        this.element?.addEventListener("focusin", this.focusInHandler);
        this.setNonRequiredFieldsVisibility(this.nonRequiredFieldsVisible);
        this.syncChangeButtonsVisibility();

    }

    public override destroy(): void {
        if (this.focusInHandler && this.element) {
            this.element.removeEventListener("focusin", this.focusInHandler);
        }
        if (this.toggleVisibilityHandler) {
            this.toggleVisibilityBtn?.removeEventListener("click", this.toggleVisibilityHandler);
        }
        if (this.openFullFormHandler) {
            this.openFullFormBtn?.removeEventListener("click", this.openFullFormHandler);
        }
        if (this.detailViewCellChangeHandler && this.element) {
            this.element.removeEventListener(DetailViewCell.changeEventName, this.detailViewCellChangeHandler);
        }
        if (this.backButtonHandler) {
            this.backBtn?.removeEventListener("click", this.backButtonHandler);
        }
        if (this.resetButtonHandler) {
            this.resetBtn?.removeEventListener("click", this.resetButtonHandler);
        }
        if (this.undoShortcutHandler && this.element) {
            this.element.removeEventListener("keydown", this.undoShortcutHandler, true);
        }
        this.focusInHandler = null;
        this.toggleVisibilityHandler = null;
        this.openFullFormHandler = null;
        this.detailViewCellChangeHandler = null;
        this.backButtonHandler = null;
        this.resetButtonHandler = null;
        this.undoShortcutHandler = null;
        this.toggleVisibilityBtn = null;
        this.toggleVisibilityLabel = null;
        this.openFullFormBtn = null;
        this.btnContainer = null;
        this.backBtn = null;
        this.resetBtn = null;
    }

    public override onAfterSwap(): void {
        this.items.forEach((item) => {
            if (!item.element || item.element.hasAttribute("tabindex")) return;
            item.element.setAttribute("tabindex", "0");
        });
        this.cacheChangeActionButtons();
        this.syncChangeButtonsVisibility();
        this.syncToggleVisibility();
        this.setNonRequiredFieldsVisibility(this.nonRequiredFieldsVisible);
    }

    protected override toggleEditMode(): void {
        super.toggleEditMode();
        this.syncToggleVisibility();
        this.setNonRequiredFieldsVisibility(this.nonRequiredFieldsVisible);
    }

    protected async renderItem(itemId: number, rowIndex: number, position?: number): Promise<void> {
        if (!this.element) return;

        const rowEl = this.rowElements[rowIndex];
        const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        const contentTypeId = this.element.dataset.contentTypeId;
        const objectId = this.element.dataset.objectId;
        if (!targetGrid || !renderUrl || !contentTypeId) return;

        const values: Record<string, string | number> = {
            content_type_id: contentTypeId,
            field_id: itemId,
        };
        if (objectId) {
            values.object_id = objectId;
        }

        await htmx.ajax("get", renderUrl, {
            target: targetGrid,
            swap: "beforeend",
            values,
        });

        initComponents(targetGrid);
        if (typeof position === "number") {
            const renderedElements = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
            const renderedElement = renderedElements.find((element) => Number.parseInt(element.dataset.layoutItemId ?? "-1", 10) === itemId)
                ?? renderedElements[renderedElements.length - 1];
            const anchor = renderedElements[position] ?? null;
            if (renderedElement && anchor && anchor !== renderedElement) {
                targetGrid.insertBefore(renderedElement, anchor);
            }
        }

        this.reindexItems();
    }

    protected getSavePayload(): { layout: { rows: SectionedLayoutRowPayload[] }; content_type_id: number | null } {
        return {
            content_type_id: Number.parseInt(this.element?.dataset.contentTypeId ?? "", 10) || null,
            layout: {
                rows: this.serializeRows(),
            },
        };
    }

    protected override handleReadModeKeyDown(event: KeyboardEvent): void {
        const key = event.key;
        const isMeta = event.metaKey || event.ctrlKey;
        const isAlt = event.altKey;
        const isShift = event.shiftKey;

        if (isShift && this.isArrowKey(key)) {
            event.preventDefault();

            const allItems = this.getAllItems();
            if (allItems.length === 0) return;

            if (!this.currentItem || !allItems.includes(this.currentItem)) {
                this.currentItem = key === "ArrowLeft" || key === "ArrowUp"
                    ? allItems[allItems.length - 1]
                    : allItems[0];
            }

            const next = isMeta ? this.getEdgeItem(key) : this.findNextItem(key);
            if (!next) return;

            this.focusReadModeItem(next);
            this.currentItem = next;
            return;
        }

        if (isAlt && key === "ArrowDown") {
            event.preventDefault();
            this.openContextMenu();
        }
    }

    protected override onClick(event: MouseEvent): void {
        super.onClick(event);
        const target = event.target as HTMLElement | null;
        const itemEl = target?.closest<HTMLElement>(this.getItemSelector());
        if (!itemEl) return;

        const component = this.getItemComponent(itemEl);
        if (component) {
            this.currentItem = component;
        }
    }

    private getRows(): RowInfo[] {
        return this.rowElements.map((rowEl) => {
            const columns = Number.parseInt(rowEl.dataset.rowColumns ?? "1", 10) || 1;
            const items = Array.from(rowEl.querySelectorAll<HTMLElement>(this.getItemSelector()))
                .map((itemEl) => this.getItemComponent(itemEl))
                .filter((item): item is DetailViewCell => item instanceof DetailViewCell && !item.element?.classList.contains("hidden"));
            return {
                element: rowEl,
                columns,
                items,
            };
        });
    }

    private cacheChangeActionButtons(): void {
        this.btnContainer = this.element.querySelector<HTMLElement>("#object-crud-container-buttons");
        this.backBtn = this.element.querySelector<HTMLButtonElement>("#object-crud-container-back-button");
        this.resetBtn = this.element.querySelector<HTMLButtonElement>("#object-crud-container-reset-button");
    }

    private syncChangeButtonsVisibility(): void {
        this.btnContainer?.classList.toggle("hidden", this.pendingChanges.length === 0);
    }

    private undoLastChange(): void {
        const lastChange = this.pendingChanges.pop();
        if (!lastChange) return;

        lastChange.cell.restoreChange(lastChange.target, lastChange.previousValue, lastChange.previousSnapshot);
        console.log("ObjectCRUDViewContainer undo change:", {
            cell: lastChange.cell,
            restoredValue: lastChange.previousValue,
            target: lastChange.target,
            previousSnapshot: lastChange.previousSnapshot,
            pendingChanges: this.pendingChanges,
        });
        this.syncChangeButtonsVisibility();
    }

    private resetChanges(): void {
        if (this.pendingChanges.length === 0) return;

        const changesToReset = [...this.pendingChanges].reverse();
        this.pendingChanges = [];

        changesToReset.forEach((change) => {
            change.cell.restoreChange(change.target, change.previousValue, change.previousSnapshot);
        });

        console.log("ObjectCRUDViewContainer reset changes:", {
            resetCount: changesToReset.length,
            pendingChanges: this.pendingChanges,
        });
        this.syncChangeButtonsVisibility();
    }

    private cloneValue(value: DetailViewCellValue): DetailViewCellValue {
        return Array.isArray(value) ? [...value] : value;
    }

    private cloneSnapshot(snapshot: DetailViewCellSnapshot): DetailViewCellSnapshot {
        if (snapshot.kind === "widget") {
            return {
                kind: "widget",
                state: structuredClone(snapshot.state),
            };
        }

        return {
            kind: "native",
            fields: snapshot.fields.map((field) => ({
                value: field.value,
                checked: field.checked,
                selectedValues: field.selectedValues ? [...field.selectedValues] : undefined,
            })),
        };
    }

    private getAllItems(): DetailViewCell[] {
        return this.getRows().flatMap((row) => row.items);
    }

    private isArrowKey(key: string): boolean {
        return key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft" || key === "ArrowRight";
    }

    private focusReadModeItem(item: DetailViewCell): void {
        item.focusReadModeTarget();
        if (this.currentItem && this.currentItem !== item) {
            this.currentItem.unhighlight();
        }
    }

    private getCurrentPosition(): { row: RowInfo; index: number } | null {
        if (!this.currentItem) return null;

        for (const row of this.getRows()) {
            const index = row.items.indexOf(this.currentItem);
            if (index !== -1) {
                return { row, index };
            }
        }

        return null;
    }

    private findNextItem(key: string): DetailViewCell | null {
        const position = this.getCurrentPosition();
        if (!position) return null;

        const { row, index } = position;
        switch (key) {
            case "ArrowLeft":
                return this.moveLeft(row, index);
            case "ArrowRight":
                return this.moveRight(row, index);
            case "ArrowUp":
                return this.moveUp(row, index);
            case "ArrowDown":
                return this.moveDown(row, index);
            default:
                return null;
        }
    }

    private moveLeft(row: RowInfo, index: number): DetailViewCell | null {
        if (index > 0) return row.items[index - 1];
        const rows = this.getRows();
        const rowIndex = rows.findIndex((candidate) => candidate.element === row.element);
        if (rowIndex <= 0) return null;
        const previousRow = rows[rowIndex - 1];
        return previousRow.items[previousRow.items.length - 1] ?? null;
    }

    private moveRight(row: RowInfo, index: number): DetailViewCell | null {
        if (index < row.items.length - 1) return row.items[index + 1];
        const rows = this.getRows();
        const rowIndex = rows.findIndex((candidate) => candidate.element === row.element);
        if (rowIndex === -1 || rowIndex >= rows.length - 1) return null;
        return rows[rowIndex + 1].items[0] ?? null;
    }

    private moveUp(row: RowInfo, index: number): DetailViewCell | null {
        const rows = this.getRows();
        const rowIndex = rows.findIndex((candidate) => candidate.element === row.element);
        if (rowIndex <= 0) return null;

        const previousRow = rows[rowIndex - 1];
        return previousRow.items[Math.min(index, previousRow.items.length - 1)] ?? null;
    }

    private moveDown(row: RowInfo, index: number): DetailViewCell | null {
        const rows = this.getRows();
        const rowIndex = rows.findIndex((candidate) => candidate.element === row.element);
        if (rowIndex === -1 || rowIndex >= rows.length - 1) return null;

        const nextRow = rows[rowIndex + 1];
        return nextRow.items[Math.min(index, nextRow.items.length - 1)] ?? null;
    }

    private getEdgeItem(key: string): DetailViewCell | null {
        const rows = this.getRows();
        if (rows.length === 0) return null;

        switch (key) {
            case "ArrowLeft":
            case "ArrowUp":
                return rows[0].items[0] ?? null;
            case "ArrowRight":
            case "ArrowDown":
                return rows[rows.length - 1].items[rows[rows.length - 1].items.length - 1] ?? null;
            default:
                return null;
        }
    }

    private openContextMenu(): void {
        if (!this.currentItem?.element) return;
        const rect = this.currentItem.element.getBoundingClientRect();
        const items = this.currentItem.constructContextMenu();
        if (items.length === 0) return;

        getContextMenu().show(
            {
                preventDefault: () => undefined,
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2,
            } as MouseEvent,
            this.currentItem.element,
            items as ContextMenuItem[],
        );
    }

    /**
     * 
     * @param visible whether it is visible or not
     */
    public setNonRequiredFieldsVisibility(visible: boolean): void {
        this.nonRequiredFieldsVisible = visible;
        this.element?.setAttribute("data-non-required-fields-visible", String(visible));
        const shouldShowAllFields = this.editMode || visible;

        this.items.forEach((item) => {
            if (!item.element) return;

            const isRequired = item.element.dataset.isRequired === "true";
            const hasErrors = item.element.dataset.hasErrors === "true";
            const shouldShow = shouldShowAllFields || isRequired || hasErrors;
            item.element.classList.toggle("hidden", !shouldShow);
        });

        this.rowElements.forEach((rowElement) => {
            const visibleItems = rowElement.querySelectorAll(`${this.getItemSelector()}:not(.hidden)`).length;
            rowElement.classList.toggle("hidden", visibleItems === 0);
        });

        const visibleItems = this.getAllItems();
        if (!this.currentItem || !visibleItems.includes(this.currentItem)) {
            this.currentItem = visibleItems[0] ?? null;
        }

        this.toggleVisibilityBtn?.setAttribute("aria-pressed", String(!visible));
        if (this.toggleVisibilityLabel) {
            this.toggleVisibilityLabel.textContent = visible
                ? "Show Required Only"
                : "Show All Fields";
        }
    }

    /**
     * Toggles the visibility of the required fields.
     */
    public toggleNonRequiredFieldsVisibility(): void {
        this.setNonRequiredFieldsVisibility(!this.nonRequiredFieldsVisible);
    }

    private syncToggleVisibility(): void {
        this.toggleVisibilityBtn?.classList.toggle("hidden", this.editMode);
    }

    /**
     * Redirects the user to the full create view
     * TODO: This could be implemented more elegantly
     */
    private openFullForm(): void {
        const fullFormUrl = this.openFullFormBtn?.dataset.fullFormUrl;
        const form = this.element?.closest("form");
        if (!fullFormUrl || !form) return;

        const url = new URL(fullFormUrl, window.location.origin);
        const formData = new FormData(form);

        formData.forEach((value, key) => {
            if (key === "csrfmiddlewaretoken") return;
            if (value instanceof File) return;
            if (value === "") return;
            url.searchParams.append(key, value);
        });

        window.location.assign(url.toString());
    }

}
