import { componentIdentifier, getComponent } from "../BaseComponent";
import { BaseWidget, type BaseWidgetChangeDetail, type BaseWidgetSerializableState } from "../widgets/BaseWidget";
import { type ContextMenuItem, getContextMenu } from "../../utils/contextMenu";
import BaseSectionedLayoutItem from "../layouts/BaseSectionedLayoutItem";

export type DetailViewCellValue = string | string[] | null;

export type DetailViewCellChangeDetail = {
    cell: DetailViewCell;
    previousValue: DetailViewCellValue;
    value: DetailViewCellValue;
    target: HTMLElement | null;
    previousSnapshot: DetailViewCellSnapshot;
    snapshot: DetailViewCellSnapshot;
};

type DetailViewCellNativeFieldSnapshot = {
    value: string;
    checked: boolean;
    selectedValues?: string[];
};

export type DetailViewCellSnapshot =
    | {
        kind: "widget";
        state: BaseWidgetSerializableState;
    }
    | {
        kind: "native";
        fields: DetailViewCellNativeFieldSnapshot[];
    };

export class DetailViewCell extends BaseSectionedLayoutItem {
    public static readonly changeEventName = "bloomerp:detail-view-cell-change";

    public value: DetailViewCellValue = null;
    public label: string | null = null;
    public applicationFieldId: string | null = null;
    private nativeFieldChangeHandler: ((event: Event) => void) | null = null;
    private widgetFieldChangeHandler: ((event: Event) => void) | null = null;
    private suppressChangeTracking = false;
    private lastSnapshot: DetailViewCellSnapshot | null = null;

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        this.value = this.element.getAttribute("data-value") ?? null;
        this.label = this.element.getAttribute("data-label") ?? null;
        this.applicationFieldId = this.element.getAttribute("data-application-field-id") ?? null;

        if (this.applicationFieldId) {
            this.itemId = this.applicationFieldId;
        }

        this.setupContextMenu();
        
        this.setUpOnChangeHandler();
        this.value = this.readCurrentValue();
        this.lastSnapshot = this.captureSnapshot();
    }

    /**
     * Subscribes to widget and native field changes so the cell always knows its current value.
     */
    private setUpOnChangeHandler(): void {
        if (!this.element) return;

        this.widgetFieldChangeHandler = (event: Event): void => {
            const customEvent = event as CustomEvent<BaseWidgetChangeDetail>;
            const target = event.target as HTMLElement | null;
            if (!target || !this.element?.contains(target)) return;
            if (target === this.element) return;

            const previousSnapshot = this.cloneSnapshot(this.lastSnapshot ?? this.captureSnapshot());
            const nextValue = this.readCurrentValue();
            const previousValue = this.cloneValue(this.value);
            this.value = nextValue;
            const nextSnapshot = this.captureSnapshot();
            this.lastSnapshot = this.cloneSnapshot(nextSnapshot);
            
            this.emitCellChange(previousValue, nextValue, target, previousSnapshot, nextSnapshot);
        };

        this.nativeFieldChangeHandler = (event: Event): void => {
            const target = event.target as HTMLElement | null;
            if (!this.isTrackableField(target)) return;
            if (!this.element?.contains(target)) return;
            if (this.isInsideCustomWidget(target)) return;

            const previousSnapshot = this.cloneSnapshot(this.lastSnapshot ?? this.captureSnapshot());
            const nextValue = this.readCurrentValue();
            const previousValue = this.cloneValue(this.value);
            this.value = nextValue;
            const nextSnapshot = this.captureSnapshot();
            this.lastSnapshot = this.cloneSnapshot(nextSnapshot);
            this.emitCellChange(previousValue, nextValue, target, previousSnapshot, nextSnapshot);
        };

        this.element.addEventListener(BaseWidget.changeEventName, this.widgetFieldChangeHandler);
        this.element.addEventListener("input", this.nativeFieldChangeHandler);
        this.element.addEventListener("change", this.nativeFieldChangeHandler);
    }

    public destroy(): void {
        if (!this.element) return;
        if (this.widgetFieldChangeHandler) {
            this.element.removeEventListener(BaseWidget.changeEventName, this.widgetFieldChangeHandler);
        }
        if (this.nativeFieldChangeHandler) {
            this.element.removeEventListener("input", this.nativeFieldChangeHandler);
            this.element.removeEventListener("change", this.nativeFieldChangeHandler);
        }
        this.widgetFieldChangeHandler = null;
        this.nativeFieldChangeHandler = null;
        this.element.removeEventListener("contextmenu", this.onContextMenu, true);
    }

    public override setEditMode(isEditMode?: boolean): void {
        super.setEditMode(isEditMode);
        if (!this.element) return;

        this.element.classList.toggle("detail-layout-item--editing", this.isEditMode);
        const focusableElements = this.element.querySelectorAll<HTMLElement>(
            ".detail-layout-item__body input, .detail-layout-item__body textarea, .detail-layout-item__body select, .detail-layout-item__body button",
        );
        focusableElements.forEach((element) => {
            if (this.isEditMode) {
                element.setAttribute("tabindex", "-1");
            } else {
                element.removeAttribute("tabindex");
            }
        });
    }

    public override focusPrimaryTarget(): void {
        this.focusReadModeTarget();
    }

    public override focusReadModeTarget(): void {
        if (!this.element) return;

        const focusTarget = this.getFirstFocusableElement([
            "#editor", // TODO: this is for the text editor
            ".detail-layout-item__body [contenteditable=\"true\"]",
            ".detail-layout-item__body input:not([type=\"hidden\"])",
            ".detail-layout-item__body textarea",
            ".detail-layout-item__body select",
            ".detail-layout-item__body button:not([tabindex=\"-1\"])",
            ".detail-layout-item__body [tabindex]:not([tabindex=\"-1\"])",
        ]);
        console.log(focusTarget)

        if (focusTarget) {
            focusTarget.focus();
            return;
        }
        this.element.focus();
    }

    private getFirstFocusableElement(selectors: string[]): HTMLElement | null {
        for (const selector of selectors) {
            const element = this.element?.querySelector<HTMLElement>(selector);
            if (element) {
                return element;
            }
        }

        return null;
    }

    public override focusEditModeTarget(): void {
        this.element?.focus();
    }

    public restoreValue(value: DetailViewCellValue): void {
        this.suppressChangeTracking = true;

        try {
            const widget = this.getWidgetComponent();
            if (widget) {
                widget.setValue(this.cloneValue(value), false);
            } else {
                this.setNativeFieldValue(value);
            }
            this.value = this.cloneValue(value);
            this.lastSnapshot = this.captureSnapshot();
        } finally {
            this.suppressChangeTracking = false;
        }
    }

    public restoreChange(target: HTMLElement | null, value: DetailViewCellValue, snapshot: DetailViewCellSnapshot): void {
        this.suppressChangeTracking = true;

        try {
            if (this.restoreSnapshot(snapshot)) {
                this.value = this.readCurrentValue();
                this.lastSnapshot = this.captureSnapshot();
                return;
            }

            if (target && this.element?.contains(target) && this.restoreTargetValue(target, value)) {
                this.value = this.readCurrentValue();
                this.lastSnapshot = this.captureSnapshot();
                return;
            }

            this.restoreValue(value);
        } finally {
            this.suppressChangeTracking = false;
        }
    }

    /**
     * Context menu stuff
     */
    private onContextMenu = (event: MouseEvent): void => {
        event.preventDefault();
        this.showContextMenu(event);
    };

    private setupContextMenu(): void {
        if (!this.element) return;
        this.element.addEventListener("contextmenu", this.onContextMenu, true);
    }

    private showContextMenu(event: MouseEvent): void {
        if (!this.element) return;

        const items = this.constructContextMenu();
        if (items.length === 0) return;

        getContextMenu().show(event, this.element, items);
    }

    public constructContextMenu(): ContextMenuItem[] {
        const items: ContextMenuItem[] = [];
        if (this.value) {
            items.push({
                label: "Copy Value",
                icon: "fa-solid fa-copy",
                onClick: (context) => {
                    this.copyValue();
                    context.hide();
                },
            });
        }
        return items;
    }

    public highlight(): void {
        this.element?.classList.add("cell-focused");
    }

    public unhighlight(): void {
        this.element?.classList.remove("cell-focused");
    }

    private copyValue(): void {
        if (!this.value) return;
        const textValue = Array.isArray(this.value) ? this.value.join(", ") : this.value;
        navigator.clipboard.writeText(textValue).catch((error) => {
            console.error("Failed to copy value:", error);
        });
    }

    private isTrackableField(target: HTMLElement | null): target is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
        return target instanceof HTMLInputElement
            || target instanceof HTMLTextAreaElement
            || target instanceof HTMLSelectElement;
    }

    private getFieldValue(target: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): string | string[] {
        if (target instanceof HTMLSelectElement && target.multiple) {
            return Array.from(target.selectedOptions).map((option) => option.value);
        }

        if (target instanceof HTMLInputElement && target.type === "checkbox") {
            return target.checked ? "true" : "false";
        }
        return target.value ?? "";
    }

    private normalizeValue(value: unknown): DetailViewCellValue {
        if (Array.isArray(value)) {
            return value.map((item) => String(item));
        }

        if (typeof value === "string") {
            return value;
        }

        if (value === null || typeof value === "undefined") {
            return "";
        }

        return String(value);
    }

    private isInsideCustomWidget(target: HTMLElement): boolean {
        const widgetRoot = target.closest<HTMLElement>(`[${componentIdentifier}]`);
        if (!widgetRoot || widgetRoot === this.element) return false;

        const component = getComponent(widgetRoot);
        return component instanceof BaseWidget;
    }

    private emitCellChange(
        previousValue: DetailViewCellValue,
        nextValue: DetailViewCellValue,
        target: HTMLElement | null,
        previousSnapshot: DetailViewCellSnapshot,
        snapshot: DetailViewCellSnapshot,
    ): void {
        if (!this.element || this.suppressChangeTracking || this.valuesEqual(previousValue, nextValue)) {
            return;
        }

        this.element.dispatchEvent(new CustomEvent<DetailViewCellChangeDetail>(DetailViewCell.changeEventName, {
            bubbles: true,
            detail: {
                cell: this,
                previousValue,
                value: nextValue,
                target,
                previousSnapshot,
                snapshot,
            },
        }));
    }

    private getWidgetComponent(): BaseWidget | null {
        if (!this.element) return null;

        const componentElements = this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`);
        for (const componentElement of componentElements) {
            const component = getComponent(componentElement);
            if (component instanceof BaseWidget) {
                return component;
            }
        }

        return null;
    }

    private restoreTargetValue(target: HTMLElement, value: DetailViewCellValue): boolean {
        if (target.hasAttribute(componentIdentifier)) {
            const component = getComponent(target);
            if (component instanceof BaseWidget) {
                component.setValue(this.cloneValue(value), false);
                return true;
            }
        }

        if (!this.isTrackableField(target)) {
            return false;
        }

        this.setFieldElementValue(target, value);
        return true;
    }

    private restoreSnapshot(snapshot: DetailViewCellSnapshot): boolean {
        const widget = this.getWidgetComponent();
        if (snapshot.kind === "widget") {
            if (!widget) {
                return false;
            }

            widget.setSerializableState(structuredClone(snapshot.state), false);
            return true;
        }

        const fields = this.getNativeFields();
        if (fields.length !== snapshot.fields.length) {
            return false;
        }

        fields.forEach((field, index) => {
            const fieldSnapshot = snapshot.fields[index];
            this.setFieldElementSnapshot(field, fieldSnapshot);
        });
        return true;
    }

    private setNativeFieldValue(value: DetailViewCellValue): void {
        const fields = this.getNativeFields();
        if (fields.length === 0) return;

        const firstField = fields[0];
        if (firstField instanceof HTMLSelectElement && firstField.multiple) {
            const selectedValues = new Set(Array.isArray(value) ? value : []);
            fields.forEach((field) => {
                if (!(field instanceof HTMLSelectElement)) return;
                Array.from(field.options).forEach((option) => {
                    option.selected = selectedValues.has(option.value);
                });
            });
            return;
        }

        if (firstField instanceof HTMLInputElement && firstField.type === "radio") {
            fields.forEach((field) => {
                if (field instanceof HTMLInputElement && field.type === "radio") {
                    field.checked = field.value === value;
                }
            });
            return;
        }

        if (firstField instanceof HTMLInputElement && firstField.type === "checkbox") {
            if (fields.length === 1) {
                firstField.checked = value === "true";
                return;
            }

            const selectedValues = new Set(Array.isArray(value) ? value : (typeof value === "string" && value ? [value] : []));
            fields.forEach((field) => {
                if (field instanceof HTMLInputElement && field.type === "checkbox") {
                    field.checked = selectedValues.has(field.value);
                }
            });
            return;
        }

        const normalizedValue = Array.isArray(value) ? value.join(", ") : (value ?? "");
        fields.forEach((field, index) => {
            if (index > 0) return;
            field.value = normalizedValue;
        });
    }

    private setFieldElementValue(field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: DetailViewCellValue): void {
        if (!this.element) return;

        if (field instanceof HTMLSelectElement && field.multiple) {
            const selectedValues = new Set(Array.isArray(value) ? value : []);
            Array.from(field.options).forEach((option) => {
                option.selected = selectedValues.has(option.value);
            });
            this.dispatchRestoreEvents(field, ["input", "change"]);
            return;
        }

        if (field instanceof HTMLInputElement && field.type === "radio") {
            const name = field.name;
            const radioFields = this.getNativeFields().filter(
                (nativeField): nativeField is HTMLInputElement => nativeField instanceof HTMLInputElement && nativeField.type === "radio" && nativeField.name === name,
            );
            radioFields.forEach((radioField) => {
                radioField.checked = radioField.value === value;
                if (radioField.checked) {
                    this.dispatchRestoreEvents(radioField, ["input", "change"]);
                }
            });
            return;
        }

        if (field instanceof HTMLInputElement && field.type === "checkbox") {
            const name = field.name;
            const checkboxFields = this.getNativeFields().filter(
                (nativeField): nativeField is HTMLInputElement => nativeField instanceof HTMLInputElement && nativeField.type === "checkbox" && nativeField.name === name,
            );

            if (checkboxFields.length <= 1) {
                field.checked = value === "true";
                this.dispatchRestoreEvents(field, ["input", "change"]);
                return;
            }

            const selectedValues = new Set(Array.isArray(value) ? value : (typeof value === "string" && value ? [value] : []));
            checkboxFields.forEach((checkboxField) => {
                checkboxField.checked = selectedValues.has(checkboxField.value);
                this.dispatchRestoreEvents(checkboxField, ["input", "change"]);
            });
            return;
        }

        field.value = Array.isArray(value) ? value.join(", ") : (value ?? "");
        this.dispatchRestoreEvents(field, ["input", "change"]);
    }

    private setFieldElementSnapshot(
        field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
        snapshot: DetailViewCellNativeFieldSnapshot,
    ): void {
        if (field instanceof HTMLSelectElement && field.multiple) {
            const selectedValues = new Set(snapshot.selectedValues ?? []);
            Array.from(field.options).forEach((option) => {
                option.selected = selectedValues.has(option.value);
            });
            this.dispatchRestoreEvents(field, ["input", "change"]);
            return;
        }

        if (field instanceof HTMLInputElement && (field.type === "checkbox" || field.type === "radio")) {
            field.checked = snapshot.checked;
            this.dispatchRestoreEvents(field, ["input", "change"]);
            return;
        }

        field.value = snapshot.value;
        this.dispatchRestoreEvents(field, ["input", "change"]);
    }

    private dispatchRestoreEvents(field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, eventNames: Array<"input" | "change">): void {
        eventNames.forEach((eventName) => {
            field.dispatchEvent(new Event(eventName, { bubbles: true }));
        });
    }

    private readCurrentValue(): DetailViewCellValue {
        const widget = this.getWidgetComponent();
        if (widget) {
            return this.normalizeValue(widget.getValue());
        }

        const fields = this.getNativeFields();
        const field = fields[0];
        if (!field) {
            return this.normalizeValue(this.value);
        }

        if (field instanceof HTMLSelectElement && field.multiple) {
            return this.normalizeValue(Array.from(field.selectedOptions).map((option) => option.value));
        }

        if (field instanceof HTMLInputElement && field.type === "radio") {
            const checkedField = fields.find((nativeField) => nativeField instanceof HTMLInputElement && nativeField.type === "radio" && nativeField.checked);
            return this.normalizeValue(checkedField instanceof HTMLInputElement ? checkedField.value : "");
        }

        if (field instanceof HTMLInputElement && field.type === "checkbox" && fields.length > 1) {
            return this.normalizeValue(
                fields
                    .filter((nativeField): nativeField is HTMLInputElement => nativeField instanceof HTMLInputElement && nativeField.type === "checkbox" && nativeField.checked)
                    .map((nativeField) => nativeField.value),
            );
        }

        return this.normalizeValue(this.getFieldValue(field));
    }

    private captureSnapshot(): DetailViewCellSnapshot {
        const widget = this.getWidgetComponent();
        if (widget) {
            return {
                kind: "widget",
                state: widget.getSerializableState(),
            };
        }

        return {
            kind: "native",
            fields: this.getNativeFields().map((field) => this.captureFieldSnapshot(field)),
        };
    }

    private captureFieldSnapshot(field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): DetailViewCellNativeFieldSnapshot {
        if (field instanceof HTMLSelectElement && field.multiple) {
            return {
                value: field.value,
                checked: false,
                selectedValues: Array.from(field.selectedOptions).map((option) => option.value),
            };
        }

        return {
            value: field.value,
            checked: field instanceof HTMLInputElement ? field.checked : false,
        };
    }

    private getNativeFields(): Array<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement> {
        if (!this.element) return [];

        const fields = Array.from(
            this.element.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
                ".detail-layout-item__body input, .detail-layout-item__body textarea, .detail-layout-item__body select",
            ),
        );
        return fields.filter((field) => {
            if (!this.isTrackableField(field)) {
                return false;
            }

            return !(field instanceof HTMLInputElement && field.type === "hidden");
        });
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

    private valuesEqual(left: DetailViewCellValue, right: DetailViewCellValue): boolean {
        if (Array.isArray(left) || Array.isArray(right)) {
            if (!Array.isArray(left) || !Array.isArray(right)) {
                return false;
            }

            if (left.length !== right.length) {
                return false;
            }

            return left.every((value, index) => value === right[index]);
        }

        return left === right;
    }
}
