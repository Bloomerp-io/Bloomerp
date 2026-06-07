import htmx from "htmx.org";

import BaseComponent, { getComponent } from "../BaseComponent";

type WidgetChangeEvent = CustomEvent<{ value: unknown }>;

export default class ListFilterWidget extends BaseComponent {
    private form: HTMLFormElement | null = null;
    private currentContentTypeId: string | null = null;
    private widgetChangeHandler: ((event: Event) => void) | null = null;
    private inputChangeHandler: ((event: Event) => void) | null = null;

    public initialize(): void {
        if (!this.element) {
            return;
        }

        this.form = this.element.closest("form");
        this.currentContentTypeId = this.normalizeContentTypeId(this.element.dataset.contentTypeId);

        this.widgetChangeHandler = () => this.syncWithContentType(true);
        this.inputChangeHandler = () => this.syncWithContentType(true);

        this.form?.addEventListener("bloomerp:widget-change", this.widgetChangeHandler);
        this.form?.addEventListener("change", this.inputChangeHandler);

        this.syncWithContentType(false);
    }

    public destroy(): void {
        if (this.form && this.widgetChangeHandler) {
            this.form.removeEventListener("bloomerp:widget-change", this.widgetChangeHandler);
        }
        if (this.form && this.inputChangeHandler) {
            this.form.removeEventListener("change", this.inputChangeHandler);
        }
        this.widgetChangeHandler = null;
        this.inputChangeHandler = null;
    }

    private syncWithContentType(reloadOnChange: boolean): void {
        if (!this.element) {
            return;
        }

        const nextContentTypeId = this.getCurrentContentTypeId();
        const previousContentTypeId = this.currentContentTypeId;
        this.currentContentTypeId = nextContentTypeId;

        if (!nextContentTypeId) {
            this.element.removeAttribute("hx-get");
            this.element.removeAttribute("hx-trigger");
            this.element.dataset.contentTypeId = "";
            this.element.innerHTML = "";
            return;
        }

        const nextUrl = this.buildUrl(nextContentTypeId);
        const currentUrl = this.element.getAttribute("hx-get") || "";
        this.element.dataset.contentTypeId = nextContentTypeId;
        this.element.setAttribute("hx-get", nextUrl);
        this.element.setAttribute("hx-trigger", "load");

        const contentTypeChanged = previousContentTypeId !== null && previousContentTypeId !== nextContentTypeId;
        const shouldLoadInitialContent = !currentUrl && this.element.innerHTML.trim() === "";

        if ((reloadOnChange && contentTypeChanged) || shouldLoadInitialContent) {
            this.element.innerHTML = "";
            void htmx.ajax("get", nextUrl, {
                target: this.element,
                swap: "innerHTML",
            });
        }
    }

    private getCurrentContentTypeId(): string | null {
        if (!this.form) {
            return this.normalizeContentTypeId(this.element?.dataset.contentTypeId);
        }

        const customWidgetElement = this.form.querySelector<HTMLElement>(
            '[bloomerp-component="foreign-field-widget"][data-field-name="content_type_id"]'
        );
        if (customWidgetElement) {
            const widget = getComponent(customWidgetElement) as { getValue?: () => unknown } | null;
            const widgetValue = widget?.getValue?.();
            const normalizedWidgetValue = this.normalizeContentTypeId(widgetValue);
            if (normalizedWidgetValue) {
                return normalizedWidgetValue;
            }
        }

        const input = this.form.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('[name="content_type_id"]');
        return this.normalizeContentTypeId(input?.value);
    }

    private normalizeContentTypeId(value: unknown): string | null {
        if (Array.isArray(value)) {
            return this.normalizeContentTypeId(value[0]);
        }

        if (value === null || value === undefined) {
            return null;
        }

        const normalizedValue = String(value).trim();
        return normalizedValue ? normalizedValue : null;
    }

    private buildUrl(contentTypeId: string): string {
        const template = this.element?.dataset.urlTemplate || "/components/filters/__CONTENT_TYPE_ID__/init/";
        return template.replace("__CONTENT_TYPE_ID__", encodeURIComponent(contentTypeId));
    }
}