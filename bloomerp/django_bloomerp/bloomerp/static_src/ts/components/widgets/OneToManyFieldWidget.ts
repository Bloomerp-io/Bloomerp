import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import { attachObjectPreviewTooltip } from "@/utils/objectPreviewTooltip";
import { BaseWidget, type BaseWidgetSerializableState } from "./BaseWidget";

export type OneToManyRowState = Record<string, string | string[]>;
export type OneToManyAggregation = "sum" | "average" | "count" | "min" | "max" | "first" | "last";
type EmbeddedWidgetState = {
    fieldName: string;
    componentName: string;
    componentIndex: number;
    state: BaseWidgetSerializableState;
};
type OneToManyFieldWidgetSerializableState = BaseWidgetSerializableState & {
    value: OneToManyRowState[];
    embeddedWidgetStates?: EmbeddedWidgetState[][];
};

export default class OneToManyFieldWidget extends BaseWidget {
    private addButton: HTMLButtonElement | null = null;
    private deleteButton: HTMLButtonElement | null = null;
    private tbody: HTMLTableSectionElement | null = null;
    private rowTemplate: HTMLTemplateElement | null = null;
    private addButtonHandler: (() => void) | null = null;
    private deleteButtonHandler: (() => void) | null = null;
    private inputHandler: ((event: Event) => void) | null = null;
    private checkboxHandler: ((event: Event) => void) | null = null;
    private selectAllHandler: ((event: Event) => void) | null = null;
    private actionHandler: ((event: Event) => void) | null = null;
    private selectAllCheckbox: HTMLInputElement | null = null;
    private previewCleanupFns: Array<() => void> = [];
    private currentPage = 1;
    private pageSize = 10;

    public initialize(): void {
        if (!this.element) return;

        this.addButton = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-add-row]");
        this.deleteButton = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-delete-rows]");
        this.tbody = this.element.querySelector<HTMLTableSectionElement>("[data-one-to-many-body]");
        this.rowTemplate = this.element.querySelector<HTMLTemplateElement>("[data-one-to-many-row-template]");
        this.selectAllCheckbox = this.element.querySelector<HTMLInputElement>("[data-one-to-many-select-all]");
        this.pageSize = this.parsePageSize(this.element.dataset.pageSize);

        this.addButtonHandler = () => this.addRow();
        this.deleteButtonHandler = () => this.deleteSelectedRows();
        this.inputHandler = (event: Event) => this.handleFieldChange(event);
        this.checkboxHandler = (event: Event) => this.handleCheckboxChange(event);
        this.selectAllHandler = (event: Event) => this.handleSelectAll(event);
        this.actionHandler = (event: Event) => this.handleAction(event);

        this.addButton?.addEventListener("click", this.addButtonHandler);
        this.deleteButton?.addEventListener("click", this.deleteButtonHandler);
        this.element.addEventListener("input", this.inputHandler);
        this.element.addEventListener("change", this.inputHandler);
        this.element.addEventListener("change", this.checkboxHandler);
        this.element.addEventListener("click", this.actionHandler);
        this.selectAllCheckbox?.addEventListener("change", this.selectAllHandler);
        this.refreshView();
        this.configureRowPreviewActions();
    }

    private parsePageSize(value: string | undefined): number {
        const pageSize = Number.parseInt(value ?? "", 10);
        if (!Number.isFinite(pageSize)) return 10;
        return Math.min(100, Math.max(1, pageSize));
    }

    public destroy(): void {
        if (this.addButton && this.addButtonHandler) {
            this.addButton.removeEventListener("click", this.addButtonHandler);
        }
        if (this.deleteButton && this.deleteButtonHandler) {
            this.deleteButton.removeEventListener("click", this.deleteButtonHandler);
        }
        if (this.element && this.inputHandler) {
            this.element.removeEventListener("input", this.inputHandler);
            this.element.removeEventListener("change", this.inputHandler);
            this.element.removeEventListener("change", this.checkboxHandler!);
        }
        if (this.element && this.actionHandler) {
            this.element.removeEventListener("click", this.actionHandler);
        }
        if (this.selectAllCheckbox && this.selectAllHandler) {
            this.selectAllCheckbox.removeEventListener("change", this.selectAllHandler);
        }
        this.addButtonHandler = null;
        this.deleteButtonHandler = null;
        this.inputHandler = null;
        this.checkboxHandler = null;
        this.selectAllHandler = null;
        this.actionHandler = null;
        this.selectAllCheckbox = null;
        this.cleanupRowPreviewActions();
    }

    public getValue(): string {
        return JSON.stringify(this.serializeRows());
    }

    public getRowCount(): number {
        return this.getActiveRows().length;
    }

    public getRows(): OneToManyRowState[] {
        return this.getActiveRows().map((row) => this.serializeRow(row));
    }

    public setRows(rows: OneToManyRowState[]): void {
        this.setValue(rows, true);
    }

    public getFirstColumnName(kind: "date" | "number" | "text"): string | null {
        return this.element?.querySelector<HTMLElement>(
            `[data-one-to-many-column][data-column-kind="${kind}"]`,
        )?.dataset.oneToManyColumn ?? null;
    }

    public aggregateColumn(
        fieldName: string,
        aggregation: OneToManyAggregation,
    ): string | number | null {
        if (aggregation === "count") return this.getRowCount();
        if (!fieldName) return null;

        const rows = this.getActiveRows();
        if (aggregation === "first" || aggregation === "last") {
            const row = aggregation === "first" ? rows[0] : rows.at(-1);
            return row ? this.getColumnValue(row, fieldName) : null;
        }

        const kind = this.getColumnKind(fieldName);
        const values = rows
            .map((row) => this.getColumnValue(row, fieldName))
            .filter((value) => value.trim() !== "");
        if (!values.length) return null;

        if (aggregation === "sum" || aggregation === "average") {
            if (kind !== "number") return null;
            const total = values.reduce((sum, value) => sum + this.toNumber(value), 0);
            return aggregation === "average" ? total / values.length : total;
        }

        if (kind === "number") {
            const numbers = values.map((value) => this.toNumber(value));
            return aggregation === "min" ? Math.min(...numbers) : Math.max(...numbers);
        }
        const sorted = [...values].sort((left, right) => (
            left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" })
        ));
        return aggregation === "min" ? sorted[0] : sorted.at(-1) ?? null;
    }


    public override getSerializableState(): OneToManyFieldWidgetSerializableState {
        const rows = this.getAllRows();
        return {
            value: rows.map((row) => this.serializeRow(row)),
            embeddedWidgetStates: rows.map((row) => this.captureEmbeddedWidgetStates(row)),
        };
    }

    public override setSerializableState(state: BaseWidgetSerializableState, emitChange: boolean = false): void {
        const oneToManyState = state as OneToManyFieldWidgetSerializableState;
        this.setValue(oneToManyState.value, false);

        const rows = this.getAllRows();
        const embeddedWidgetStates = oneToManyState.embeddedWidgetStates ?? [];
        rows.forEach((row, index) => {
            this.restoreEmbeddedWidgetStates(row, embeddedWidgetStates[index] ?? []);
        });
        this.refreshView();

        if (emitChange) {
            this.onChange();
        }
    }

    /** Patch existing rows in place when identities match, preserving unrelated widget state. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        if (!this.tbody || !this.rowTemplate) return;

        const rows = this.normalizeRows(value);
        const existing = Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]"));
        const previous = existing.map((row: HTMLElement): OneToManyRowState => this.serializeRow(row));
        if (rows.length === existing.length && rows.every((row: OneToManyRowState, index: number): boolean =>
            (row.id ?? "") === (previous[index].id ?? ""))) {
            rows.forEach((row: OneToManyRowState, index: number): void => {
                const changes = Object.fromEntries(Object.entries(row).filter(
                    ([key, next]: [string, string | string[]]): boolean => JSON.stringify(next) !== JSON.stringify(previous[index][key]),
                ));
                this.applyRowData(existing[index], changes);
            });
            this.refreshView();
            if (emitChange) this.onChange();
            return;
        }
        this.tbody.innerHTML = "";

        rows.forEach((rowData, rowIndex) => {
            const fragment = this.rowTemplate.content.cloneNode(true) as DocumentFragment;
            this.replacePrefix(fragment, rowIndex);
            const rowElement = fragment.querySelector<HTMLElement>("[data-one-to-many-row]");
            this.tbody?.appendChild(fragment);
            if (rowElement) {
                initComponents(rowElement);
                this.applyRowData(rowElement, {
                    ...this.getDefaultRowData(),
                    ...rowData,
                });
            }
        });

        if (rows.length === 0) {
            const emptyRow = this.element?.querySelector<HTMLTemplateElement>("[data-one-to-many-empty-row-template]");
            if (emptyRow) {
                this.tbody.appendChild(emptyRow.content.cloneNode(true));
            }
        }

        initComponents(this.tbody);
        this.currentPage = 1;
        this.refreshView();
        this.configureRowPreviewActions();

        if (emitChange) {
            this.onChange();
        }
    }

    private handleCheckboxChange(event: Event): void {
        const target = event.target as HTMLElement | null;
        if (!target || !target.matches("[data-one-to-many-row-checkbox]")) return;
        this.updateDeleteButtonVisibility();
    }

    private handleSelectAll(event: Event): void {
        const selectAll = event.target as HTMLInputElement | null;
        if (!selectAll || !this.tbody) return;
        const checked = selectAll.checked;
        this.getActiveRows()
            .filter((row) => !row.classList.contains("hidden"))
            .forEach((row) => {
                const cb = row.querySelector<HTMLInputElement>("[data-one-to-many-row-checkbox]");
                if (!cb) return;
                cb.checked = checked;
            });
        this.updateDeleteButtonVisibility();
    }

    private updateDeleteButtonVisibility(): void {
        if (!this.deleteButton || !this.tbody) return;
        const anyChecked = this.tbody.querySelector<HTMLInputElement>("[data-one-to-many-row-checkbox]:checked") !== null;
        this.deleteButton.classList.toggle("hidden", !anyChecked);
    }

    private deleteSelectedRows(): void {
        if (!this.tbody) return;

        const rows = this.getActiveRows().filter((row) => {
            const checkbox = row.querySelector<HTMLInputElement>("[data-one-to-many-row-checkbox]");
            return checkbox?.checked ?? false;
        });
        this.deleteRows(rows);
    }

    private addRow(
        rowData: OneToManyRowState = {},
        embeddedWidgetStates: EmbeddedWidgetState[] = [],
    ): HTMLElement | null {
        if (!this.tbody || !this.rowTemplate || this.addButton?.disabled) return null;

        const rowIndex = this.getNextRowIndex();
        const fragment = this.rowTemplate.content.cloneNode(true) as DocumentFragment;
        this.replacePrefix(fragment, rowIndex);
        this.tbody.querySelector("[data-one-to-many-empty-row]")?.remove();
        const rowElement = fragment.querySelector<HTMLElement>("[data-one-to-many-row]");
        if (rowElement) {
            this.applyRowData(rowElement, {
                ...this.getDefaultRowData(),
                ...rowData,
            });
        }
        const appendedNodes = Array.from(fragment.children);
        this.tbody.appendChild(fragment);
        appendedNodes.forEach((node) => {
            if (node instanceof HTMLElement) {
                initComponents(node);
            }
        });
        if (rowElement) {
            this.restoreEmbeddedWidgetStates(rowElement, embeddedWidgetStates);
        }
        this.currentPage = Math.max(1, Math.ceil(this.getActiveRows().length / this.pageSize));
        this.refreshView();
        this.configureRowPreviewActions();
        this.onChange();
        return rowElement;
    }

    private replacePrefix(root: ParentNode, rowIndex: number): void {
        const elements = root.querySelectorAll<HTMLElement>("*");
        elements.forEach((element) => {
            for (const attr of ["name", "id", "for"]) {
                const value = element.getAttribute(attr);
                if (value?.includes("__prefix__")) {
                    element.setAttribute(attr, value.replace(/__prefix__/g, String(rowIndex)));
                }
            }
            // Replace __prefix__ in all data-* attributes so that custom widgets
            // (e.g. ForeignFieldWidget) that read their field name from a data attribute
            // also get the correct row-indexed name after cloning the template row.
            for (const attr of element.getAttributeNames()) {
                if (!attr.startsWith("data-")) continue;
                const value = element.getAttribute(attr);
                if (value?.includes("__prefix__")) {
                    element.setAttribute(attr, value.replace(/__prefix__/g, String(rowIndex)));
                }
            }
        });
    }

    private handleFieldChange(event: Event): void {
        const target = event.target as HTMLElement | null;
        if (!target || !this.element?.contains(target)) return;
        if (!this.isTrackableField(target)) return;
        this.updateTotals();
        this.onChange();
    }

    private isTrackableField(target: HTMLElement): target is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
        if (
            !(target instanceof HTMLInputElement)
            && !(target instanceof HTMLTextAreaElement)
            && !(target instanceof HTMLSelectElement)
        ) {
            return false;
        }

        if (target instanceof HTMLInputElement && target.type === "hidden") {
            return false;
        }

        return true;
    }

    private serializeRows(): OneToManyRowState[] {
        if (!this.tbody) return [];

        return Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]"))
            .map((rowElement) => this.serializeRow(rowElement));
    }

    private serializeRow(rowElement: HTMLElement): OneToManyRowState {
        const rowData: OneToManyRowState = {};
        const fields = rowElement.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
            "input[name], textarea[name], select[name]",
        );
        fields.forEach((field) => {
            const fieldName = this.getFieldKey(field.name);
            if (!fieldName) return;

            if (field instanceof HTMLSelectElement && field.multiple) {
                rowData[fieldName] = Array.from(field.selectedOptions).map((option) => option.value);
                return;
            }

            if (field instanceof HTMLInputElement && field.type === "checkbox") {
                rowData[fieldName] = field.checked ? (field.value || "on") : "";
                return;
            }

            rowData[fieldName] = field.value ?? "";
        });
        return rowData;
    }

    private getFieldKey(name: string): string | null {
        const parts = name.split("__");
        if (parts.length < 3) return null;
        return parts.slice(2).join("__");
    }

    private normalizeRows(value: unknown): OneToManyRowState[] {
        if (typeof value === "string") {
            try {
                const parsed = JSON.parse(value);
                return this.normalizeRows(parsed);
            } catch {
                return [];
            }
        }

        if (!Array.isArray(value)) {
            return [];
        }

        return value.map((row) => {
            if (!row || typeof row !== "object" || Array.isArray(row)) {
                return {};
            }

            return Object.fromEntries(
                Object.entries(row).map(([key, fieldValue]) => {
                    if (Array.isArray(fieldValue)) {
                        return [key, fieldValue.map((item) => String(item))];
                    }
                    return [key, fieldValue == null ? "" : String(fieldValue)];
                }),
            );
        });
    }

    private getDefaultRowData(): OneToManyRowState {
        if (!this.element) return {};

        const defaults: OneToManyRowState = {};
        this.element.querySelectorAll<HTMLElement>("[data-one-to-many-column]").forEach((column) => {
            const fieldName = column.dataset.oneToManyColumn;
            const serializedValue = column.dataset.columnDefaultValue;
            if (!fieldName || !serializedValue) return;

            try {
                const value = JSON.parse(serializedValue) as unknown;
                if (Array.isArray(value)) {
                    defaults[fieldName] = value.map((item) => String(item));
                } else if (value && typeof value === "object") {
                    defaults[fieldName] = JSON.stringify(value);
                } else {
                    defaults[fieldName] = value == null ? "" : String(value);
                }
            } catch {
                defaults[fieldName] = serializedValue;
            }
        });
        return defaults;
    }

    /** Apply supplied columns through their widget contracts, leaving other columns untouched. */
    private applyRowData(rowElement: HTMLElement, rowData: OneToManyRowState): void {
        const handled = new Set<string>();
        for (const cell of rowElement.querySelectorAll<HTMLElement>("[data-one-to-many-cell]")) {
            const name = cell.dataset.oneToManyCell!;
            if (!(name in rowData)) continue;
            for (const root of cell.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`)) {
                const widget = getComponent(root);
                if (widget instanceof BaseWidget) {
                    widget.setValue(rowData[name], false);
                    handled.add(name);
                    break;
                }
            }
        }
        const fields = rowElement.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
            "input[name], textarea[name], select[name]",
        );
        fields.forEach((field) => {
            const fieldName = this.getFieldKey(field.name);
            if (!fieldName || handled.has(fieldName) || !(fieldName in rowData)) return;
            const value = rowData[fieldName];

            if (field instanceof HTMLSelectElement && field.multiple && Array.isArray(value)) {
                Array.from(field.options).forEach((option) => {
                    option.selected = value.includes(option.value);
                });
                return;
            }

            if (field instanceof HTMLInputElement && field.type === "checkbox") {
                field.checked = Array.isArray(value)
                    ? value.includes(field.value)
                    : value === "true"
                        || value === "1"
                        || value === (field.value || "on");
                return;
            }

            field.value = Array.isArray(value) ? value[0] ?? "" : value;
        });
    }

    private handleAction(event: Event): void {
        const target = event.target as HTMLElement | null;
        const action = target?.closest<HTMLElement>(
            "[data-one-to-many-delete-row], [data-one-to-many-clone-row], [data-one-to-many-sort], "
            + "[data-one-to-many-autofill], [data-one-to-many-previous-page], [data-one-to-many-next-page]",
        );
        if (!action || !this.element?.contains(action)) return;

        const row = action.closest<HTMLElement>("[data-one-to-many-row]");
        if (action.hasAttribute("data-one-to-many-delete-row") && row) {
            this.deleteRows([row]);
            return;
        }
        if (action.hasAttribute("data-one-to-many-clone-row") && row) {
            const rowData = this.serializeRow(row);
            const embeddedWidgetStates = this.captureEmbeddedWidgetStates(row);
            rowData.id = "";
            delete rowData.DELETE;
            this.addRow(rowData, embeddedWidgetStates);
            return;
        }
        if (action.hasAttribute("data-one-to-many-sort")) {
            this.sortRows(
                action.dataset.columnField ?? "",
                action.dataset.oneToManySort === "descending" ? "descending" : "ascending",
            );
            return;
        }
        if (action.hasAttribute("data-one-to-many-autofill")) {
            this.autofillColumn(
                action.dataset.columnField ?? "",
                action.dataset.oneToManyAutofill === "increment" ? "increment" : "copy",
            );
            return;
        }
        if (action.hasAttribute("data-one-to-many-previous-page")) {
            this.currentPage = Math.max(1, this.currentPage - 1);
            this.refreshView();
            return;
        }
        if (action.hasAttribute("data-one-to-many-next-page")) {
            const pageCount = Math.max(1, Math.ceil(this.getActiveRows().length / this.pageSize));
            this.currentPage = Math.min(pageCount, this.currentPage + 1);
            this.refreshView();
        }
    }

    private deleteRows(rows: HTMLElement[]): void {
        rows.forEach((row) => {
            const idInput = row.querySelector<HTMLInputElement>('input[type="hidden"][name$="__id"]');
            if (idInput?.value) {
                const prefix = idInput.name.replace(/__id$/, "");
                let deleteInput = row.querySelector<HTMLInputElement>('input[type="hidden"][name$="__DELETE"]');
                if (!deleteInput) {
                    deleteInput = document.createElement("input");
                    deleteInput.type = "hidden";
                    deleteInput.name = `${prefix}__DELETE`;
                    row.appendChild(deleteInput);
                }
                deleteInput.value = "1";
                row.dataset.oneToManyDeleted = "true";
                row.classList.add("hidden");
            } else {
                row.remove();
            }
        });

        if (this.selectAllCheckbox) this.selectAllCheckbox.checked = false;
        this.updateDeleteButtonVisibility();
        this.refreshView();
        this.configureRowPreviewActions();
        this.onChange();
    }

    private getActiveRows(): HTMLElement[] {
        if (!this.tbody) return [];
        return Array.from(
            this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]:not([data-one-to-many-deleted])"),
        );
    }

    private getAllRows(): HTMLElement[] {
        if (!this.tbody) return [];
        return Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]"));
    }

    private configureRowPreviewActions(): void {
        if (!this.element) return;

        this.cleanupRowPreviewActions();
        const contentTypeId = this.element.dataset.relatedContentTypeId ?? "";
        const detailUrlTemplate = this.element.dataset.detailUrlTemplate ?? "";

        this.getAllRows().forEach((row) => {
            const action = row.querySelector<HTMLAnchorElement>("[data-one-to-many-view-row]");
            const idInput = row.querySelector<HTMLInputElement>('input[type="hidden"][name$="__id"]');
            const objectId = idInput?.value.trim() ?? "";
            const isAvailable = Boolean(objectId) && !row.hasAttribute("data-one-to-many-deleted");

            if (!action || !isAvailable) {
                action?.classList.add("hidden");
                action?.classList.remove("inline-flex");
                action?.removeAttribute("href");
                return;
            }

            const detailUrl = action.dataset.detailUrl
                || detailUrlTemplate.replace("{object_id}", encodeURIComponent(objectId));
            action.dataset.objectId = objectId;
            action.classList.remove("hidden");
            action.classList.add("inline-flex", "items-center", "justify-center");
            if (detailUrl) {
                action.href = detailUrl;
            }

            if (contentTypeId) {
                this.previewCleanupFns.push(
                    attachObjectPreviewTooltip({
                        element: action,
                        objectId,
                        contentTypeId,
                    }),
                );
            }
        });
    }

    private cleanupRowPreviewActions(): void {
        this.previewCleanupFns.forEach((cleanup) => cleanup());
        this.previewCleanupFns = [];
    }

    private captureEmbeddedWidgetStates(row: HTMLElement): EmbeddedWidgetState[] {
        return Array.from(row.querySelectorAll<HTMLElement>("[data-one-to-many-cell]"))
            .flatMap((cell) => {
                const fieldName = cell.dataset.oneToManyCell;
                if (!fieldName) return [];
                return Array.from(cell.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`))
                    .map((element, componentIndex) => {
                        const component = getComponent(element);
                        const componentName = element.getAttribute(componentIdentifier);
                        if (!(component instanceof BaseWidget) || !componentName) return null;
                        return {
                            fieldName,
                            componentName,
                            componentIndex,
                            state: structuredClone(component.getSerializableState()),
                        };
                    })
                    .filter((state): state is EmbeddedWidgetState => state !== null);
            });
    }

    private restoreEmbeddedWidgetStates(row: HTMLElement, states: EmbeddedWidgetState[]): void {
        states.forEach(({ fieldName, componentName, componentIndex, state }) => {
            const cell = row.querySelector<HTMLElement>(
                `[data-one-to-many-cell="${CSS.escape(fieldName)}"]`,
            );
            const elements = cell?.querySelectorAll<HTMLElement>(
                `[${componentIdentifier}="${CSS.escape(componentName)}"]`,
            );
            const element = elements?.item(componentIndex) ?? null;
            const component = element ? getComponent(element) : null;
            if (component instanceof BaseWidget) {
                component.setSerializableState(structuredClone(state), false);
            }
        });
    }

    private getNextRowIndex(): number {
        if (!this.tbody) return 0;
        const indexes = Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]"))
            .flatMap((row) => Array.from(
                row.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("[name]"),
            ))
            .map((field) => Number(field.name.split("__")[1]))
            .filter(Number.isInteger);
        return indexes.length ? Math.max(...indexes) + 1 : 0;
    }


    private refreshView(): void {
        if (!this.tbody || !this.element) return;
        const rows = this.getActiveRows();
        const pageCount = Math.max(1, Math.ceil(rows.length / this.pageSize));
        this.currentPage = Math.min(Math.max(this.currentPage, 1), pageCount);
        const start = (this.currentPage - 1) * this.pageSize;

        rows.forEach((row, index) => {
            row.classList.toggle("hidden", index < start || index >= start + this.pageSize);
        });

        const emptyRow = this.tbody.querySelector<HTMLElement>("[data-one-to-many-empty-row]");
        if (rows.length === 0 && !emptyRow) {
            const template = this.element.querySelector<HTMLTemplateElement>("[data-one-to-many-empty-row-template]");
            if (template) this.tbody.appendChild(template.content.cloneNode(true));
        } else if (rows.length > 0) {
            emptyRow?.remove();
        }

        const pagination = this.element.querySelector<HTMLElement>("[data-one-to-many-pagination]");
        pagination?.classList.toggle("hidden", pageCount <= 1);
        pagination?.classList.toggle("flex", pageCount > 1);
        const status = this.element.querySelector<HTMLElement>("[data-one-to-many-page-status]");
        if (status) status.textContent = `${this.currentPage} / ${pageCount}`;
        const previous = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-previous-page]");
        const next = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-next-page]");
        if (previous) previous.disabled = this.currentPage === 1;
        if (next) next.disabled = this.currentPage === pageCount;
        this.updateTotals();
    }

    private sortRows(fieldName: string, direction: "ascending" | "descending"): void {
        if (!this.tbody || !fieldName) return;
        const kind = this.getColumnKind(fieldName);
        const multiplier = direction === "ascending" ? 1 : -1;
        const rows = this.getActiveRows();
        rows.sort((left, right) => {
            const leftValue = this.getColumnValue(left, fieldName);
            const rightValue = this.getColumnValue(right, fieldName);
            if (kind === "number") {
                return (this.toNumber(leftValue) - this.toNumber(rightValue)) * multiplier;
            }
            return leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" }) * multiplier;
        });
        rows.forEach((row) => this.tbody?.appendChild(row));
        this.currentPage = 1;
        this.refreshView();
    }

    private autofillColumn(fieldName: string, mode: "copy" | "increment"): void {
        if (!fieldName) return;
        const rows = this.getActiveRows();
        if (rows.length < 2) return;
        const firstValue = this.getColumnValue(rows[0], fieldName);
        const kind = this.getColumnKind(fieldName);

        rows.slice(1).forEach((row, index) => {
            let nextValue = firstValue;
            if (mode === "increment" && kind === "number") {
                nextValue = String(this.toNumber(firstValue) + index + 1);
            } else if (mode === "increment" && kind === "date") {
                nextValue = this.incrementDate(firstValue, index + 1);
            }
            this.setColumnValue(row, fieldName, nextValue);
        });
        this.updateTotals();
        this.onChange();
    }

    private getColumnControl(
        row: HTMLElement,
        fieldName: string,
    ): HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null {
        return row.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
            `[data-one-to-many-cell="${CSS.escape(fieldName)}"] input, `
            + `[data-one-to-many-cell="${CSS.escape(fieldName)}"] textarea, `
            + `[data-one-to-many-cell="${CSS.escape(fieldName)}"] select`,
        );
    }

    private getColumnValue(row: HTMLElement, fieldName: string): string {
        const control = this.getColumnControl(row, fieldName);
        if (control instanceof HTMLInputElement && control.type === "checkbox") {
            return control.checked ? "true" : "false";
        }
        return control?.value ?? "";
    }

    private getColumnKind(fieldName: string): string {
        return this.element?.querySelector<HTMLElement>(
            `[data-one-to-many-column="${CSS.escape(fieldName)}"]`,
        )?.dataset.columnKind ?? "text";
    }

    private setColumnValue(row: HTMLElement, fieldName: string, value: string): void {
        const control = this.getColumnControl(row, fieldName);
        if (!control) return;
        if (control instanceof HTMLInputElement && control.type === "checkbox") {
            control.checked = value === "true"
                || value === "1"
                || value === "on"
                || value === "yes";
            return;
        }
        control.value = value;
    }

    private toNumber(value: string): number {
        const number = Number(value);
        return Number.isFinite(number) ? number : 0;
    }

    private incrementDate(value: string, days: number): string {
        const date = new Date(`${value}T00:00:00Z`);
        if (Number.isNaN(date.getTime())) return value;
        date.setUTCDate(date.getUTCDate() + days);
        return date.toISOString().slice(0, 10);
    }

    private updateTotals(): void {
        if (!this.element) return;
        this.element.querySelectorAll<HTMLElement>("[data-one-to-many-total]").forEach((totalElement) => {
            const fieldName = totalElement.dataset.oneToManyTotal;
            if (!fieldName) return;
            totalElement.textContent = String(this.aggregateColumn(fieldName, "sum") ?? 0);
        });
    }
}
