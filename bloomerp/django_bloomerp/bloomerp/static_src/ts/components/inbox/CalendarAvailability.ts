import BaseComponent from "../BaseComponent";
import { getSdk } from "../../sdk/getSdk";
import { t } from "../../utils/i18n";

export interface AvailabilitySelection {
    users: string[];
    day: string;
    timezone: string;
    startTime: string;
    endTime: string;
    endDate: string;
    allDay: boolean;
    token?: string;
}

interface AvailabilityUser {
    id: string;
    label: string;
    available: boolean;
    busy: { start: string; end: string }[];
}

/** Own the availability request, free/busy display, and time selection independently of any form. */
export default class CalendarAvailability extends BaseComponent {
    private selection: AvailabilitySelection | null = null;
    private lifecycle = new AbortController();
    private request: AbortController | null = null;
    private timer?: ReturnType<typeof setTimeout>;
    private timeFormatter: Intl.DateTimeFormat | null = null;

    /** Bind local time selection without reading or mutating the surrounding form. */
    public initialize(): void {
        this.element.addEventListener("click", this.onTimeClick, { signal: this.lifecycle.signal });
    }

    /** Accept participant and timing inputs from the owning editor, cancelling obsolete requests. */
    public setSelection(selection: AvailabilitySelection): void {
        this.selection = selection;
        clearTimeout(this.timer);
        this.request?.abort();
        this.timer = setTimeout(this.refresh.bind(this), 150);
    }

    /** Fetch free/busy intervals in the event's selected timezone and ignore stale responses. */
    private async refresh(): Promise<void> {
        if (!this.selection) return;
        const pane = this.element.querySelector<HTMLElement>("[data-availability-grid]");
        if (!pane) return;
        this.request?.abort();
        const controller = new AbortController();
        this.request = controller;
        pane.setAttribute("aria-busy", "true");
        try {
            const users = this.selection.users;
            const result = await getSdk().client.request<{ users: AvailabilityUser[] }>(this.element.dataset.url!, {
                query: {
                    day: this.selection!.day, timezone: this.selection!.timezone, users,
                    ...(this.selection!.token ? { _permission_token: this.selection!.token } : {}),
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
            timeZone: this.selection!.timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
        });
        const heading = this.element.querySelector<HTMLElement>("[data-availability-date]");
        if (heading) heading.textContent = this.selection!.day;
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
        const row = body.rows[Math.max(0, Number(this.selection!.startTime.slice(0, 2)) * 2 - 1)];
        if (row) pane.scrollTop = row.offsetTop - pane.offsetTop;
    }

    /** Mark the chosen event span independently of busy and unavailable attendee columns. */
    private isSelectedSlot(slot: number): boolean {
        if (this.selection!.allDay) return true;
        const start = this.selection!.startTime.split(":").map(Number);
        const end = this.selection!.endTime.split(":").map(Number);
        const first = start[0] * 60 + start[1];
        const last = this.selection!.endDate > this.selection!.day ? 1440 : end[0] * 60 + end[1];
        return slot * 30 < last && (slot + 1) * 30 > first;
    }

    /** Compare an interval with a displayed slot using IANA-zone clock parts, including midnight. */
    private overlaps(slot: number, interval: { start: string; end: string }): boolean {
        const start = this.timeFormatter!.format(new Date(interval.start));
        const end = this.timeFormatter!.format(new Date(interval.end));
        const day = this.selection!.day;
        const from = `${day} ${String(Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
        const next = slot + 1;
        const until = next === 48 ? `${day} 24:00` : `${day} ${String(Math.floor(next / 2)).padStart(2, "0")}:${next % 2 ? "30" : "00"}`;
        return start < until && end > from;
    }

    /** Return a chosen one-hour range to the owner without changing any model fields. */
    private onTimeClick = (event: MouseEvent): void => {
        const target = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-availability-time]") : null;
        if (!target || !this.selection) return;
        const startTime = target.dataset.availabilityTime!;
        const hour = Number(startTime.slice(0, 2));
        const endTime = `${String((hour + 1) % 24).padStart(2, "0")}:${startTime.slice(3)}`;
        const end = new Date(`${this.selection.day}T12:00:00Z`);
        if (hour === 23) end.setUTCDate(end.getUTCDate() + 1);
        this.element.dispatchEvent(new CustomEvent("bloomerp:availability-time-selected", {
            bubbles: true, detail: { startTime, endTime, endDate: end.toISOString().slice(0, 10) },
        }));
    };

    /** Cancel outstanding requests and listeners when the sidebar is replaced. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.request?.abort();
        clearTimeout(this.timer);
        super.destroy();
    }
}
