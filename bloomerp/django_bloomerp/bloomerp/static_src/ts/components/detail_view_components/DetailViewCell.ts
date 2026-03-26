import { type ContextMenuItem, getContextMenu } from "../../utils/contextMenu";
import BaseSectionedLayoutItem from "../layouts/BaseSectionedLayoutItem";

export class DetailViewCell extends BaseSectionedLayoutItem {
    public value: string | null = null;
    public label: string | null = null;
    public applicationFieldId: string | null = null;
    private focusInHandler: ((event: FocusEvent) => void) | null = null;
    private focusOutHandler: ((event: FocusEvent) => void) | null = null;

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        this.value = this.element.getAttribute("data-value") ?? null;
        this.label = this.element.getAttribute("data-label") ?? null;
        this.applicationFieldId = this.element.getAttribute("data-application-field-id") ?? null;

        const applicationFieldId = Number.parseInt(this.applicationFieldId ?? "-1", 10);
        if (Number.isFinite(applicationFieldId)) {
            this.itemId = applicationFieldId;
        }

        this.setupContextMenu();
        this.setupDetailFieldChangeLogging();
    }

    public destroy(): void {
        if (!this.element) return;
        this.element.removeEventListener("contextmenu", this.onContextMenu, true);
        if (this.focusInHandler) {
            this.element.removeEventListener("focusin", this.focusInHandler, true);
        }
        if (this.focusOutHandler) {
            this.element.removeEventListener("focusout", this.focusOutHandler, true);
        }
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

        const focusTarget = this.element.querySelector<HTMLElement>(
            ".detail-layout-item__body input, .detail-layout-item__body textarea, .detail-layout-item__body select, .detail-layout-item__body button, .detail-layout-item__body [contenteditable=\"true\"], .detail-layout-item__body [tabindex]:not([tabindex=\"-1\"])",
        );
        if (focusTarget) {
            focusTarget.focus();
            return;
        }
        this.element.focus();
    }

    public override focusEditModeTarget(): void {
        this.element?.focus();
    }

    private onContextMenu = (event: MouseEvent): void => {
        event.preventDefault();
        this.showContextMenu(event);
    };

    private setupContextMenu(): void {
        if (!this.element) return;
        this.element.addEventListener("contextmenu", this.onContextMenu, true);
    }

    private setupDetailFieldChangeLogging(): void {
        if (!this.element) return;

        const layoutContainer = this.element.closest<HTMLElement>("[data-layout-kind]");
        if (layoutContainer?.dataset.layoutKind !== "detail") return;

        this.focusInHandler = (event: FocusEvent) => {
            const target = event.target as HTMLElement | null;
            if (!this.isTrackableField(target)) return;
            target.dataset.initialValue = this.getFieldValue(target);
        };

        this.focusOutHandler = (event: FocusEvent) => {
            const target = event.target as HTMLElement | null;
            if (!this.isTrackableField(target)) return;

            const initialValue = target.dataset.initialValue ?? "";
            const nextValue = this.getFieldValue(target);
            delete target.dataset.initialValue;

            if (initialValue === nextValue) return;

            this.value = nextValue;
            console.log("Detail overview field changed", {
                fieldId: this.applicationFieldId,
                label: this.label,
                value: nextValue,
            });
        };

        this.element.addEventListener("focusin", this.focusInHandler, true);
        this.element.addEventListener("focusout", this.focusOutHandler, true);
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
        navigator.clipboard.writeText(this.value).catch((error) => {
            console.error("Failed to copy value:", error);
        });
    }

    private isTrackableField(target: HTMLElement | null): target is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
        return target instanceof HTMLInputElement
            || target instanceof HTMLTextAreaElement
            || target instanceof HTMLSelectElement;
    }

    private getFieldValue(target: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): string {
        if (target instanceof HTMLInputElement && target.type === "checkbox") {
            return target.checked ? "true" : "false";
        }
        return target.value ?? "";
    }
}
