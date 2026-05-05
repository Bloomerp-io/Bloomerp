import { initComponents } from "../BaseComponent";
import { BaseWidget } from "./BaseWidget";

type OneToManyRowState = Record<string, string | string[]>;

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

    public initialize(): void {
        if (!this.element) return;

        this.addButton = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-add-row]");
        this.deleteButton = this.element.querySelector<HTMLButtonElement>("[data-one-to-many-delete-rows]");
        this.tbody = this.element.querySelector<HTMLTableSectionElement>("[data-one-to-many-body]");
        this.rowTemplate = this.element.querySelector<HTMLTemplateElement>("[data-one-to-many-row-template]");

        this.addButtonHandler = () => this.addRow();
        this.deleteButtonHandler = () => this.deleteSelectedRows();
        this.inputHandler = (event: Event) => this.handleFieldChange(event);
        this.checkboxHandler = (event: Event) => this.handleCheckboxChange(event);
        this.selectAllHandler = (event: Event) => this.handleSelectAll(event);

        this.addButton?.addEventListener("click", this.addButtonHandler);
        this.deleteButton?.addEventListener("click", this.deleteButtonHandler);
        this.element.addEventListener("input", this.inputHandler);
        this.element.addEventListener("change", this.inputHandler);
        this.element.addEventListener("change", this.checkboxHandler);
        this.element.querySelector<HTMLInputElement>("[data-one-to-many-select-all]")?.addEventListener("change", this.selectAllHandler);
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
        this.addButtonHandler = null;
        this.deleteButtonHandler = null;
        this.inputHandler = null;
        this.checkboxHandler = null;
        this.selectAllHandler = null;
    }

    public getValue(): string {
        return JSON.stringify(this.serializeRows());
    }

    public override getSerializableState(): { value: OneToManyRowState[] } {
        return {
            value: this.serializeRows(),
        };
    }

    public setValue(value: unknown, emitChange: boolean = false): void {
        if (!this.tbody || !this.rowTemplate) return;

        const rows = this.normalizeRows(value);
        this.tbody.innerHTML = "";

        rows.forEach((rowData, rowIndex) => {
            const fragment = this.rowTemplate.content.cloneNode(true) as DocumentFragment;
            this.replacePrefix(fragment, rowIndex);
            const rowElement = fragment.querySelector<HTMLElement>("[data-one-to-many-row]");
            if (rowElement) {
                this.applyRowData(rowElement, rowData);
            }
            this.tbody?.appendChild(fragment);
        });

        if (rows.length === 0) {
            const emptyRow = this.element?.querySelector<HTMLTemplateElement>("[data-one-to-many-empty-row-template]");
            if (emptyRow) {
                this.tbody.appendChild(emptyRow.content.cloneNode(true));
            }
        }

        initComponents(this.tbody);

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
        this.tbody.querySelectorAll<HTMLInputElement>("[data-one-to-many-row-checkbox]").forEach((cb) => {
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

        const rows = Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]"));
        rows.forEach((row) => {
            const checkbox = row.querySelector<HTMLInputElement>("[data-one-to-many-row-checkbox]");
            if (!checkbox?.checked) return;

            const idInput = row.querySelector<HTMLInputElement>("input[type=hidden][name]");
            if (idInput?.value) {
                // Saved row: inject DELETE marker and visually strike through
                const prefix = idInput.name.replace(/__id$/, "");
                const deleteInput = document.createElement("input");
                deleteInput.type = "hidden";
                deleteInput.name = `${prefix}__DELETE`;
                deleteInput.value = "1";
                row.appendChild(deleteInput);
                row.setAttribute("data-one-to-many-deleted", "true");
                row.style.opacity = "0.4";
                row.style.textDecoration = "line-through";
                row.style.pointerEvents = "none";
                checkbox.checked = false;
            } else {
                // Unsaved new row: remove from DOM
                row.remove();
            }
        });

        // Show empty-state row if nothing visible remains
        const visibleRows = this.tbody.querySelectorAll("[data-one-to-many-row]:not([data-one-to-many-deleted])").length;
        if (visibleRows === 0 && !this.tbody.querySelector("[data-one-to-many-empty-row]")) {
            const emptyRowTemplate = this.element?.querySelector<HTMLTemplateElement>("[data-one-to-many-empty-row-template]");
            if (emptyRowTemplate) {
                this.tbody.appendChild(emptyRowTemplate.content.cloneNode(true));
            }
        }

        // Reset select-all checkbox
        const selectAll = this.element?.querySelector<HTMLInputElement>("[data-one-to-many-select-all]");
        if (selectAll) selectAll.checked = false;

        this.updateDeleteButtonVisibility();
        this.onChange();
    }

    private addRow(): void {
        if (!this.tbody || !this.rowTemplate || this.addButton?.disabled) return;

        const rowIndex = this.tbody.querySelectorAll("[data-one-to-many-row]").length;
        const fragment = this.rowTemplate.content.cloneNode(true) as DocumentFragment;
        this.replacePrefix(fragment, rowIndex);
        this.tbody.querySelector("[data-one-to-many-empty-row]")?.remove();
        const appendedNodes = Array.from(fragment.children);
        this.tbody.appendChild(fragment);
        appendedNodes.forEach((node) => {
            if (node instanceof HTMLElement) {
                initComponents(node);
            }
        });
        this.onChange();
    }

    private replacePrefix(root: ParentNode, rowIndex: number): void {
        const elements = root.querySelectorAll<HTMLElement>("[name], [id], [for], [data-field-name]");
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

        return Array.from(this.tbody.querySelectorAll<HTMLElement>("[data-one-to-many-row]")).map((rowElement) => {
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
        });
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

    private applyRowData(rowElement: HTMLElement, rowData: OneToManyRowState): void {
        const fields = rowElement.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
            "input[name], textarea[name], select[name]",
        );
        fields.forEach((field) => {
            const fieldName = this.getFieldKey(field.name);
            if (!fieldName || !(fieldName in rowData)) return;
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
                    : value === (field.value || "on");
                return;
            }

            field.value = Array.isArray(value) ? value[0] ?? "" : value;
        });
    }
}
