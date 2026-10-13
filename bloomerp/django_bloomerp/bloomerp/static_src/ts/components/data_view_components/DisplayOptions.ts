import Sortable, { type SortableEvent } from "sortablejs";
import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import showMessage from "../../utils/messages";
import { MessageType } from "../UiMessage";
import { getCsrfToken } from "@/utils/cookies";

type DisplayOptionValue = string | string[];

export class DataViewDisplayOptions extends BaseComponent {
    public optionChangedCallback: (() => void) | null = null;
    private clickHandler: ((event: Event) => void) | null = null;
    private changeHandler: ((event: Event) => void) | null = null;
    private changeTimer: number | null = null;

    private fieldSortable: Sortable | null = null;
    private fieldOrderBeforeDrag: HTMLElement[] = [];
    private suppressFieldClickUntil: number = 0;

    /** Initialize option controls and dragging for visible field chips. */
    public initialize(): void {
        if (!this.element) return;

        this.clickHandler = this.handleClick.bind(this);
        this.changeHandler = this.handleChange.bind(this);

        this.element.addEventListener("click", this.clickHandler);
        this.element.addEventListener("change", this.changeHandler);
        this.initializeFieldSorting();
    }
    
    public setOptionChangedCallback(callback: () => void): void {
        this.optionChangedCallback = callback;
    }

    /** Toggle options while preventing a completed field drag from toggling visibility. */
    private handleClick(event: Event): void {
        const target = event.target as HTMLElement | null;
        const submitter = target?.closest<HTMLElement>("[data-display-options-submit]");
        if (!submitter) return;

        event.preventDefault();
        if (submitter.hasAttribute("data-field-id") && performance.now() < this.suppressFieldClickUntil) return;
        this.submitValues(this.parseValues(submitter.dataset.displayOptionsValues));
    }

    /** Restrict sorting to visible fields and keep hidden fields after the ordered chips. */
    private initializeFieldSorting(): void {
        const list = this.element?.querySelector<HTMLElement>('[data-field-order-list]');
        if (!list) return;
        this.fieldSortable = Sortable.create(list, {
            animation: 150,
            draggable: '[data-field-visible="true"]',
            handle: '[data-field-drag-handle]',
            ghostClass: 'opacity-50',
            onStart: this.handleFieldSortStart.bind(this),
            onMove: this.allowFieldSortMove.bind(this),
            onEnd: this.handleFieldSortEnd.bind(this),
        });
    }

    /** Snapshot the complete chip order so a failed save can restore the original layout. */
    private handleFieldSortStart(event: SortableEvent): void {
        this.fieldOrderBeforeDrag = Array.from(event.from.children) as HTMLElement[];
    }

    /** Prevent visible fields from being inserted amongst the hidden field chips. */
    private allowFieldSortMove(event: { related: HTMLElement }): boolean {
        return event.related.dataset.fieldVisible === 'true';
    }

    /** Save the new field order, restoring it if the server rejects the change. */
    private async handleFieldSortEnd(event: SortableEvent): Promise<void> {
        this.suppressFieldClickUntil = performance.now() + 250;
        if (event.oldDraggableIndex === event.newDraggableIndex) return;
        const sortable = this.fieldSortable;
        sortable?.option('disabled', true);
        const fieldOrder = this.getVisibleFieldOrder(event.from);
        try {
            const saved = await this.submitValues({
                reorder_view_type: this.element?.dataset.viewType ?? '',
                field_order: fieldOrder,
            });
            if (!saved) event.from.replaceChildren(...this.fieldOrderBeforeDrag);
        } catch (error) {
            event.from.replaceChildren(...this.fieldOrderBeforeDrag);
            showMessage('Unable to save field order. Please try again.', MessageType.ERROR);
            console.error('Failed to save field order', error);
        } finally {
            if (sortable && this.fieldSortable === sortable) sortable.option('disabled', false);
        }
    }

    /** Read visible field IDs from the chip list in their current visual order. */
    private getVisibleFieldOrder(list: HTMLElement): string[] {
        const fieldOrder: string[] = [];
        for (const chip of list.querySelectorAll<HTMLElement>('[data-field-visible="true"]')) {
            fieldOrder.push(chip.dataset.fieldId ?? '');
        }
        return fieldOrder;
    }

    private handleChange(event: Event): void {
        const target = event.target as HTMLElement | null;
        const form = target?.closest<HTMLFormElement>("[data-display-options-form]");
        if (!form) return;

        if (this.changeTimer !== null) {
            window.clearTimeout(this.changeTimer);
        }

        this.changeTimer = window.setTimeout(() => {
            const values = this.parseValues(form.dataset.displayOptionsValues);
            const formData = new FormData(form);
            formData.forEach((value, key) => {
                const stringValue = String(value);
                const existingValue = values[key];

                if (existingValue === undefined) {
                    values[key] = stringValue;
                } else if (Array.isArray(existingValue)) {
                    existingValue.push(stringValue);
                } else {
                    values[key] = [existingValue, stringValue];
                }
            });
            this.submitValues(values);
        }, 200);
    }

    private parseValues(rawValues: string | undefined): Record<string, DisplayOptionValue> {
        if (!rawValues) return {};

        try {
            const parsed = JSON.parse(rawValues);
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
            return Object.fromEntries(
                Object.entries(parsed).map(([key, value]) => [key, String(value)])
            );
        } catch (error) {
            console.error("Failed to parse display options values:", error);
            return {};
        }
    }

    /** Persist options and replace the panel while retaining its current scroll position. */
    private async submitValues(values: Record<string, DisplayOptionValue>): Promise<boolean> {
        if (!this.element) return false;

        const url = this.element.dataset.preferenceUrl;
        if (!url) return false;

        const csrfToken = getCsrfToken();
        const formData = new FormData();

        Object.entries(values).forEach(([key, value]) => {
            if (Array.isArray(value)) {
                value.forEach((item) => formData.append(key, item));
            } else {
                formData.set(key, value);
            }
        });

        if (csrfToken) {
            formData.set("csrfmiddlewaretoken", csrfToken);
        }

        const response = await fetch(url, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
            },
        });

        if (!response.ok) {
            showMessage(await response.text() || "Unable to save display options.", MessageType.ERROR);
            return false;
        }

        const html = await response.text();
        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const replacement = template.content.firstElementChild as HTMLElement | null;
        if (!replacement || !this.element.parentElement) return false;

        const parent = this.element.parentElement;
        const previousCallback = this.optionChangedCallback;
        const scrollStates: { element: HTMLElement; top: number; left: number }[] = [];
        for (let scroller: HTMLElement | null = this.element; scroller; scroller = scroller.parentElement) {
            if (scroller === this.element || scroller.scrollHeight > scroller.clientHeight || scroller.scrollWidth > scroller.clientWidth) {
                scrollStates.push({
                    element: scroller === this.element ? replacement : scroller,
                    top: scroller.scrollTop,
                    left: scroller.scrollLeft,
                });
            }
        }
        this.destroy();
        this.element.replaceWith(replacement);
        initComponents(parent);

        const newComponent = getComponent(replacement) as DataViewDisplayOptions | null;
        if (newComponent) newComponent.suppressFieldClickUntil = this.suppressFieldClickUntil;
        if (newComponent && previousCallback) {
            newComponent.setOptionChangedCallback(previousCallback);
        }

        previousCallback?.();
        for (const scrollState of scrollStates) {
            scrollState.element.scrollTop = scrollState.top;
            scrollState.element.scrollLeft = scrollState.left;
        }
        return true;
    }

    /** Destroy field sorting and release option listeners and pending submissions. */
    public destroy(): void {
        this.fieldSortable?.destroy();
        this.fieldSortable = null;
        if (this.clickHandler) {
            this.element?.removeEventListener("click", this.clickHandler);
        }
        if (this.changeHandler) {
            this.element?.removeEventListener("change", this.changeHandler);
        }
        if (this.changeTimer !== null) {
            window.clearTimeout(this.changeTimer);
        }
    }

    
}
