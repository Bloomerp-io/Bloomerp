import BaseComponent, { getComponent } from "../BaseComponent";
import savePreference from "../../utils/preferences";
import { t } from "../../utils/i18n";
import type ForeignFieldWidget from "../widgets/ForeignFieldWidget";

/** Save alignment preferences and reload the standard calendar dataview. */
export default class InboxCalendarOverlay extends BaseComponent {
    private lifecycle = new AbortController();
    private saving = false;

    /** Bind one dropdown's apply button without intercepting the shared calendar's navigation. */
    public initialize(): void {
        this.element.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener("keydown", this.onKeyDown, { signal: this.lifecycle.signal });
        document.addEventListener("click", this.onOutsideClick, { signal: this.lifecycle.signal });
    }

    /** Keep owned FK portals inside the menu's interaction boundary while dismissing outside clicks. */
    private onOutsideClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Node) || this.element.contains(event.target)) return;
        for (const element of this.element.querySelectorAll<HTMLElement>('[bloomerp-component="foreign-field-widget"]')) {
            const widget = getComponent(element) as ForeignFieldWidget | null;
            if (widget?.ownsEvent(event)) return;
        }
        this.element.removeAttribute("open");
    };

    /** Let Escape dismiss this menu before it reaches an enclosing modal. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key !== "Escape" || !this.element.hasAttribute("open")) return;
        event.preventDefault();
        event.stopPropagation();
        this.element.removeAttribute("open");
        this.element.querySelector<HTMLElement>("summary")?.focus();
    };

    /** Handle the alignment preference apply button. */
    private onClick = (event: MouseEvent): void => {
        void this.apply(event);
    };

    /** Save alignment through the preference utility and let the returned loader refresh the calendar. */
    private async apply(event: MouseEvent): Promise<void> {
        if (!(event.target instanceof Element) || !event.target.closest("[data-apply-overlay]")) return;
        if (this.saving) return;
        const values = Array.from(this.element.querySelectorAll<HTMLInputElement>("[data-overlay-inbox]:checked"), this.inboxValue);
        const error = this.element.querySelector<HTMLElement>("[data-overlay-error]");
        const widgetElement = this.element.querySelector<HTMLElement>('[bloomerp-component="foreign-field-widget"]');
        const widget = widgetElement ? getComponent(widgetElement) as ForeignFieldWidget : null;
        let users = widget?.getValue() || [];
        users = Array.isArray(users) ? users : [users];
        if (error) error.hidden = values.length + users.length > 0;
        if (!values.length && !users.length) return;
        const container = this.element.closest<HTMLElement>('[bloomerp-component="dataview-container"]');
        const saveUrl = this.element.dataset.saveUrl;
        if (!container || !saveUrl) return;
        const currentUrl = new URL(container.dataset.url || window.location.href, window.location.origin);
        const queryParams: Record<string, string> = {};
        for (const key of ["q", "calendar_page"]) {
            const value = currentUrl.searchParams.get(key);
            if (value !== null) queryParams[key] = value;
        }
        const button = this.element.querySelector<HTMLButtonElement>("[data-apply-overlay]");
        this.saving = true;
        if (button) button.disabled = true;
        try {
            await savePreference(saveUrl, { selection: JSON.stringify({ inboxes: values, users }) }, {
                source: this.element,
                target: container,
                swap: "outerHTML",
                queryParams,
                headers: { "X-Bloomerp-Sync-Url": String(container.dataset.syncUrl === "true") },
            });
        } catch {
            if (error && !this.lifecycle.signal.aborted) {
                error.textContent = t("Calendar selections could not be saved. Please try again.");
                error.hidden = false;
            }
            return;
        } finally {
            this.saving = false;
            if (button) button.disabled = false;
        }
    }

    /** Extract a checkbox's effective source-inbox ID for the standard values-in lookup. */
    private inboxValue(input: HTMLInputElement): string {
        return input.value;
    }

    /** Release listeners when the dataview toolbar is replaced. */
    public destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
