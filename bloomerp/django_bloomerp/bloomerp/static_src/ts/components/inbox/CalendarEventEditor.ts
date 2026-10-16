import ObjectCRUDViewContainer from "../detail_view_components/ObjectCRUDViewContainer";
import { EmailRecipients } from "./EmailRecipients";
import { getSdk } from "../../sdk/getSdk";
import { t } from "../../utils/i18n";

interface AvailabilityUser {
    id: string;
    label: string;
    available: boolean;
    busy: { start: string; end: string }[];
}

/** Coordinate shared recipient chips, date controls, and a compact availability calendar. */
export default class CalendarEventEditor extends ObjectCRUDViewContainer {
    private lifecycle = new AbortController();
    private recipients: EmailRecipients | null = null;
    private request: AbortController | null = null;
    private timer?: ReturnType<typeof setTimeout>;
    private timeFormatter: Intl.DateTimeFormat | null = null;

    /** Attach existing composer controls without owning the nested rich-text editor or splitter. */
    public override initialize(): void {
        super.initialize();
        const source = this.element.querySelector<HTMLInputElement>('[name="attendees"]');
        const users = this.element.querySelector<HTMLInputElement>('[name="attendee_users"]');
        if (source && users) {
            const searchUrl = new URL(this.element.dataset.recipientSearchUrl!, location.origin);
            const token = this.value("_permission_token");
            if (token) searchUrl.searchParams.set("_permission_token", token);
            this.recipients = new EmailRecipients(source, this.lifecycle.signal, searchUrl.toString(), users);
        }
        this.element.addEventListener("change", this.onChange, { signal: this.lifecycle.signal });
        this.element.addEventListener("input", this.onParticipantInput, { signal: this.lifecycle.signal });
        this.element.addEventListener("submit", this.onSubmit, { capture: true, signal: this.lifecycle.signal });
        this.element.addEventListener("click", this.onCalendarClick, { signal: this.lifecycle.signal });
        this.updateSubmitLabel();
        void this.refresh();
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

    /** Debounce availability updates while keeping local date controls responsive. */
    private onChange = (): void => {
        this.updateSubmitLabel();
        clearTimeout(this.timer);
        this.request?.abort();
        this.timer = setTimeout(this.refresh.bind(this), 150);
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

    /** Fetch free/busy intervals in the event's selected timezone and ignore stale responses. */
    private async refresh(): Promise<void> {
        const pane = this.element.querySelector<HTMLElement>("[data-availability-grid]");
        if (!pane) return;
        this.request?.abort();
        const controller = new AbortController();
        this.request = controller;
        pane.setAttribute("aria-busy", "true");
        try {
            const users = this.selectedUsers();
            const result = await getSdk().client.request<{ users: AvailabilityUser[] }>(this.element.dataset.availabilityUrl!, {
                query: {
                    action: "availability", day: this.value("start_date"), timezone: this.value("event_timezone"), users,
                    ...(this.value("_permission_token") ? { _permission_token: this.value("_permission_token") } : {}),
                }, signal: controller.signal,
            });
            if (controller.signal.aborted) return;
            this.render(pane, result.users);
        } catch {
            if (!controller.signal.aborted) pane.textContent = t("Availability could not be loaded.");
        } finally {
            if (!controller.signal.aborted) pane.removeAttribute("aria-busy");
        }
    }

    /** Render selectable half-hour rows with private busy blocks and explicit unknown states. */
    private render(pane: HTMLElement, users: AvailabilityUser[]): void {
        pane.replaceChildren();
        this.timeFormatter = new Intl.DateTimeFormat("sv-SE", {
            timeZone: this.value("event_timezone"), year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
        });
        const heading = this.element.querySelector<HTMLElement>("[data-availability-date]");
        if (heading) heading.textContent = this.value("start_date");
        if (!users.length) {
            pane.textContent = t("No readable attendee calendars.");
            return;
        }
        const table = document.createElement("table");
        table.className = "w-full table-fixed border-collapse text-xs";
        const header = table.createTHead().insertRow();
        const timeHeading = document.createElement("th");
        timeHeading.className = "w-14";
        timeHeading.textContent = t("Time");
        header.append(timeHeading);
        for (const user of users) {
            const cell = document.createElement("th");
            cell.scope = "col";
            cell.className = "sticky top-0 border-b border-gray-200 bg-white p-2 font-medium";
            cell.textContent = user.label;
            cell.title = user.available ? user.label : t("Availability unavailable");
            header.append(cell);
        }
        const body = table.createTBody();
        for (let slot = 0; slot < 48; slot += 1) {
            const hour = `${Math.floor(slot / 2)}`.padStart(2, "0");
            const minute = slot % 2 ? "30" : "00";
            const clock = `${hour}:${minute}`;
            const row = body.insertRow();
            const time = row.insertCell();
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.availabilityTime = clock;
            button.className = "w-full px-1 py-2 text-gray-500 hover:bg-primary-50 hover:text-primary";
            button.textContent = clock;
            const selected = this.isSelectedSlot(slot);
            if (selected) button.classList.add("bg-primary-50", "text-primary", "font-medium");
            button.setAttribute("aria-pressed", String(selected));
            button.setAttribute("aria-label", `${t("Start event at")} ${clock}`);
            time.append(button);
            for (const user of users) {
                const cell = row.insertCell();
                const busy = user.busy.some(this.overlaps.bind(this, slot));
                cell.className = "border border-gray-100 " + (!user.available ? "bg-gray-100" : busy ? "bg-primary-100" : "bg-white");
                cell.textContent = !user.available ? "?" : busy ? t("Busy") : "";
                cell.title = !user.available ? t("Availability unavailable") : busy ? t("Busy") : t("No visible conflicts");
            }
        }
        pane.append(table);
        const row = body.rows[Math.max(0, Number(this.value("start_time").slice(0, 2)) * 2 - 1)];
        if (row) pane.scrollTop = row.offsetTop - pane.offsetTop;
    }

    /** Mark the chosen event span independently of busy and unavailable attendee columns. */
    private isSelectedSlot(slot: number): boolean {
        if (this.element.querySelector<HTMLInputElement>('[name="all_day"]')?.checked) return true;
        const start = this.value("start_time").split(":").map(Number);
        const end = this.value("end_time").split(":").map(Number);
        const first = start[0] * 60 + start[1];
        const last = this.value("end_date") > this.value("start_date") ? 1440 : end[0] * 60 + end[1];
        return slot * 30 < last && (slot + 1) * 30 > first;
    }

    /** Compare an interval with a displayed slot using IANA-zone clock parts, including midnight. */
    private overlaps(slot: number, interval: { start: string; end: string }): boolean {
        const start = this.timeFormatter!.format(new Date(interval.start));
        const end = this.timeFormatter!.format(new Date(interval.end));
        const day = this.value("start_date");
        const from = `${day} ${String(Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
        const next = slot + 1;
        const until = next === 48 ? `${day} 24:00` : `${day} ${String(Math.floor(next / 2)).padStart(2, "0")}:${next % 2 ? "30" : "00"}`;
        return start < until && end > from;
    }

    /** Select an hour from the availability calendar without submitting the event. */
    private onCalendarClick = (event: MouseEvent): void => {
        const target = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-availability-time]") : null;
        if (!target) return;
        const start = this.element.querySelector<HTMLInputElement>('[name="start_time"]');
        const end = this.element.querySelector<HTMLInputElement>('[name="end_time"]');
        const endDate = this.element.querySelector<HTMLInputElement>('[name="end_date"]');
        const allDay = this.element.querySelector<HTMLInputElement>('[name="all_day"]');
        if (!start || !end || !endDate || (allDay?.disabled && allDay.checked)) return;
        if (allDay?.checked) { allDay.checked = false; allDay.dispatchEvent(new Event("change", { bubbles: true })); }
        start.value = target.dataset.availabilityTime!;
        const hour = Number(start.value.slice(0, 2));
        end.value = `${String((hour + 1) % 24).padStart(2, "0")}:${start.value.slice(3)}`;
        const day = new Date(`${this.value("start_date")}T12:00:00Z`);
        if (hour === 23) day.setUTCDate(day.getUTCDate() + 1);
        endDate.value = day.toISOString().slice(0, 10);
        this.onChange();
    };

    /** Abort component-owned work when the modal closes or validation replaces its form. */
    public destroy(): void {
        this.lifecycle.abort();
        this.request?.abort();
        clearTimeout(this.timer);
        super.destroy();
    }
}
