import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import { getCsrfToken } from "@/utils/cookies";

export class DataViewDisplayOptions extends BaseComponent {
    public optionChangedCallback: (() => void) | null = null;
    private clickHandler: ((event: Event) => void) | null = null;
    private changeHandler: ((event: Event) => void) | null = null;
    private changeTimer: number | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.clickHandler = (event: Event) => this.handleClick(event);
        this.changeHandler = (event: Event) => this.handleChange(event);

        this.element.addEventListener("click", this.clickHandler);
        this.element.addEventListener("change", this.changeHandler);
    }
    
    public setOptionChangedCallback(callback: () => void): void {
        this.optionChangedCallback = callback;
    }

    private handleClick(event: Event): void {
        const target = event.target as HTMLElement | null;
        const submitter = target?.closest<HTMLElement>("[data-display-options-submit]");
        if (!submitter) return;

        event.preventDefault();
        this.submitValues(this.parseValues(submitter.dataset.displayOptionsValues));
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
                values[key] = String(value);
            });
            this.submitValues(values);
        }, 200);
    }

    private parseValues(rawValues: string | undefined): Record<string, string> {
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

    private async submitValues(values: Record<string, string>): Promise<void> {
        if (!this.element) return;

        const url = this.element.dataset.preferenceUrl;
        if (!url) return;

        const csrfToken = getCsrfToken();
        const formData = new FormData();

        Object.entries(values).forEach(([key, value]) => {
            formData.set(key, value);
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
            console.error("Failed to update data view display options:", response.statusText);
            return;
        }

        const html = await response.text();
        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const replacement = template.content.firstElementChild as HTMLElement | null;
        if (!replacement || !this.element.parentElement) return;

        const parent = this.element.parentElement;
        const previousCallback = this.optionChangedCallback;
        this.element.replaceWith(replacement);
        initComponents(parent);

        const newComponent = getComponent(replacement) as DataViewDisplayOptions | null;
        if (newComponent && previousCallback) {
            newComponent.setOptionChangedCallback(previousCallback);
        }

        previousCallback?.();
    }

    public destroy(): void {
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
