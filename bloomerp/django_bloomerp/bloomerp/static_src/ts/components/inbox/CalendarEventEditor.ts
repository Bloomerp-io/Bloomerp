import ObjectCRUDViewContainer from "../detail_view_components/ObjectCRUDViewContainer";
import { EmailRecipients } from "./EmailRecipients";
import { getComponent } from "../BaseComponent";
import type CalendarAvailability from "./CalendarAvailability";
import { t } from "../../utils/i18n";

/** Coordinate event form controls with recipient chips and the independent availability sidebar. */
export default class CalendarEventEditor extends ObjectCRUDViewContainer {
    private lifecycle = new AbortController();
    private recipients: EmailRecipients | null = null;

    /** Attach existing composer controls without owning the nested rich-text editor or splitter. */
    public override initialize(): void {
        super.initialize();
        const source = this.element.querySelector<HTMLInputElement>('[name="attendees"]');
        const users = this.element.querySelector<HTMLInputElement>('[name="attendee_users"]');
        if (source && users) {
            const searchUrl = new URL(this.element.dataset.recipientSearchUrl!, location.origin);
            const token = this.value("_permission_token");
            if (token) searchUrl.searchParams.set("_permission_token", token);
            this.recipients = new EmailRecipients(source, this.lifecycle.signal, searchUrl.pathname + searchUrl.search, users);
        }
        this.element.addEventListener("change", this.onChange, { signal: this.lifecycle.signal });
        this.element.addEventListener("input", this.onParticipantInput, { signal: this.lifecycle.signal });
        this.element.addEventListener("submit", this.onSubmit, { capture: true, signal: this.lifecycle.signal });
        this.element.addEventListener("bloomerp:availability-time-selected", this.onTimeSelected, { signal: this.lifecycle.signal });
        this.updateSubmitLabel();
        this.updateAvailability();
    }

    /** Refresh shared layout state and participant-dependent controls after child swaps. */
    public override onAfterSwap(): void {
        super.onAfterSwap();
        this.updateSubmitLabel();
    }

    /** Choose Save or Send from committed recipients and unfinished participant input. */
    private updateSubmitLabel(): void {
        const label = this.element.querySelector<HTMLElement>("[data-calendar-submit-label]");
        if (!label) return;
        const hasParticipants = Boolean(
            this.value("attendees").trim()
            || this.selectedUsers().length
            || this.element.querySelector<HTMLInputElement>('[role="combobox"]')?.value.trim(),
        );
        label.textContent = hasParticipants ? t("Send") : t("Save");
    }

    /** Flush unfinished guest input before HTMX serializes the form. */
    private onSubmit = (event: Event): void => {
        if (event.defaultPrevented) return;
        if (this.recipients && !this.recipients.validate()) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    };

    /** Forward form changes to the sidebar and update the participant-dependent submit label. */
    private onChange = (): void => {
        this.updateSubmitLabel();
        this.updateAvailability();
    };

    /** Update the action while a participant address is being typed, before committing its chip. */
    private onParticipantInput = (event: Event): void => {
        if (event.target instanceof HTMLInputElement && (
            event.target.name === "attendees" || event.target.getAttribute("role") === "combobox"
        )) this.updateSubmitLabel();
    };

    /** Read named form values without selecting fields from neighboring modals. */
    private value(name: string): string {
        return this.element.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${name}"]`)?.value ?? "";
    }

    /** Read internal participant IDs safely when a validation response retains malformed input. */
    private selectedUsers(): string[] {
        const selected: string[] = [];
        try {
            const values: unknown = JSON.parse(this.value("attendee_users") || "[]");
            if (Array.isArray(values)) {
                for (const value of values) if (typeof value === "string") selected.push(value);
            }
        } catch { /* Field validation reports invalid input; keep the rest of the form interactive. */ }
        return selected;
    }

    /** Pass explicit participant and timing inputs to the independent availability sidebar. */
    private updateAvailability(): void {
        const element = this.element.querySelector<HTMLElement>('[bloomerp-component="calendar-availability"]');
        if (!element) return;
        const sidebar = getComponent(element) as CalendarAvailability;
        sidebar?.setSelection({
            users: this.selectedUsers(), day: this.value("start_date"), timezone: this.value("event_timezone"),
            startTime: this.value("start_time"), endTime: this.value("end_time"), endDate: this.value("end_date"),
            allDay: Boolean(this.element.querySelector<HTMLInputElement>('[name="all_day"]')?.checked),
            token: this.value("_permission_token"),
        });
    }

    /** Apply the sidebar's chosen time range using the form's own date and all-day controls. */
    private onTimeSelected = (event: Event): void => {
        const detail = (event as CustomEvent<{ startTime: string; endTime: string; endDate: string }>).detail;
        const allDay = this.element.querySelector<HTMLInputElement>('[name="all_day"]');
        if (allDay?.disabled && allDay.checked) return;
        if (allDay?.checked) { allDay.checked = false; allDay.dispatchEvent(new Event("change", { bubbles: true })); }
        for (const [name, value] of Object.entries({ start_time: detail.startTime, end_time: detail.endTime, end_date: detail.endDate })) {
            const field = this.element.querySelector<HTMLInputElement>(`[name="${name}"]`);
            if (field) field.value = value;
        }
        this.onChange();
    };

    /** Abort component-owned work when the modal closes or validation replaces its form. */
    public destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
