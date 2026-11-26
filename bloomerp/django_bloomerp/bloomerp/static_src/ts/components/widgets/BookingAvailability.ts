import { BaseWidget } from './BaseWidget';

type Hours = { start: string; end: string };
type DateOverride = { date: string; hours: Hours[] };
type Schedule = {
    start_date?: string | null;
    end_date?: string | null;
    days?: Record<string, Hours[]>;
    exceptions?: DateOverride[];
};

/** Edit recurring hours and date overrides as one JSON form value. */
export default class BookingAvailability extends BaseWidget {
    private lifecycle: AbortController | null = null;

    /** Restore the saved schedule and listen for changes inside this editor. */
    public initialize(): void {
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.setValue(this.getValue());
        this.element?.addEventListener('click', this.handleClick, { signal: this.lifecycle.signal });
        this.element?.addEventListener('input', this.handleInput, { signal: this.lifecycle.signal });
    }

    /** Read the actual Django form value, including untouched legacy data. */
    public getValue(): string {
        return this.input(this.element, 'value')?.value ?? '{}';
    }

    /** Restore controls from a stored value or from a form state snapshot. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        const output = this.input(this.element, 'value');
        if (!output) return;
        output.value = typeof value === 'string' ? value : JSON.stringify(value ?? {});
        const schedule = this.readSchedule(output.value);
        const warning = this.element?.querySelector<HTMLElement>('[data-availability-unrecognized]');
        if (warning) warning.hidden = schedule !== null;
        const start = this.input(this.element, 'start');
        const end = this.input(this.element, 'end');
        if (start) start.value = schedule?.start_date ?? '';
        if (end) end.value = schedule?.end_date ?? '';
        this.element?.querySelectorAll<HTMLElement>('[data-availability-day]').forEach((day) => {
            const key = day.dataset.availabilityDay ?? '';
            this.renderHours(day, schedule?.days?.[key]);
        });
        this.element?.querySelector('[data-availability-exceptions]')?.replaceChildren();
        for (const exception of schedule?.exceptions ?? []) this.addException(exception);
        if (emitChange) this.onChange();
    }

    /** Read structured JSON and recognize the older flat weekday map. */
    private readSchedule(value: string): Schedule | null {
        try {
            const parsed: unknown = JSON.parse(value || '{}');
            if (parsed === null) return {};
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
            const fields = Object.keys(parsed);
            const dayKeys = Array.from(this.element?.querySelectorAll<HTMLElement>('[data-availability-day]') ?? [],
                (day: HTMLElement): string | undefined => day.dataset.availabilityDay);
            if (fields.length && fields.every((field: string): boolean => dayKeys.includes(field))) {
                return { days: parsed as Record<string, Hours[]> };
            }
            const schedule = parsed as Schedule;
            if (fields.some((field: string): boolean => !['start_date', 'end_date', 'days', 'exceptions'].includes(field)) ||
                (schedule.exceptions !== undefined && !Array.isArray(schedule.exceptions))) return null;
            return schedule;
        } catch {
            return null;
        }
    }

    /** Resolve a native control within the appropriate day or schedule. */
    private input(parent: ParentNode | null, field: string): HTMLInputElement | null {
        return parent?.querySelector<HTMLInputElement>(`[data-availability-${field}]`) ?? null;
    }

    /** Clone a native row without introducing new form field names. */
    private cloneRow(template: string): HTMLElement | null {
        const source = this.element?.querySelector<HTMLTemplateElement>(`[data-availability-${template}-template]`);
        const row = source?.content.firstElementChild?.cloneNode(true);
        return row instanceof HTMLElement ? row : null;
    }

    /** Replace the visible intervals for one day and update its empty state. */
    private renderHours(day: HTMLElement, intervals?: Hours[]): void {
        day.querySelectorAll('[data-availability-interval]').forEach((row) => row.remove());
        if (Array.isArray(intervals)) {
            for (const interval of intervals) this.addHours(day, interval);
        }
        this.refreshUnavailable(day);
    }

    /** Append an editable interval to a weekday or date override. */
    private addHours(day: HTMLElement, interval?: Hours): HTMLElement | null {
        const row = this.cloneRow('interval');
        if (!row) return null;
        const from = this.input(row, 'from');
        const to = this.input(row, 'to');
        if (from) from.value = interval?.start ?? '';
        if (to) to.value = interval?.end ?? '';
        day.querySelector('[data-availability-hours]')?.append(row);
        this.refreshUnavailable(day);
        return row;
    }

    /** Append a date override, preserving an empty list for unavailable dates. */
    private addException(value?: DateOverride): HTMLElement | null {
        const row = this.cloneRow('exception');
        if (!row) return null;
        const date = this.input(row, 'date');
        if (date) date.value = value?.date ?? '';
        this.renderHours(row, value?.hours);
        this.element?.querySelector('[data-availability-exceptions]')?.append(row);
        return row;
    }

    /** Show the unavailable label when there are no intervals. */
    private refreshUnavailable(day: HTMLElement): void {
        const label = day.querySelector<HTMLElement>('[data-availability-unavailable]');
        if (label) label.hidden = day.querySelector('[data-availability-interval]') !== null;
    }

    /** Read visible local hours in display order. */
    private collectHours(day: HTMLElement): Hours[] {
        return Array.from(day.querySelectorAll('[data-availability-interval]'),
            (row: Element): Hours => ({ start: this.input(row, 'from')?.value ?? '', end: this.input(row, 'to')?.value ?? '' }));
    }

    /** Serialize the visible controls and notify the surrounding edit layout. */
    private updateValue(): void {
        const output = this.input(this.element, 'value');
        if (!output) return;
        const days: Record<string, Hours[]> = {};
        for (const day of this.element?.querySelectorAll<HTMLElement>('[data-availability-day]') ?? []) {
            const key = day.dataset.availabilityDay;
            const hours = this.collectHours(day);
            if (key && hours.length) days[key] = hours;
        }
        const exceptions = Array.from(this.element?.querySelectorAll<HTMLElement>('[data-availability-exception]') ?? [],
            (row: HTMLElement): DateOverride => ({ date: this.input(row, 'date')?.value ?? '', hours: this.collectHours(row) }));
        output.value = JSON.stringify({
            start_date: this.input(this.element, 'start')?.value || null,
            end_date: this.input(this.element, 'end')?.value || null,
            days,
            exceptions,
        });
        const warning = this.element?.querySelector<HTMLElement>('[data-availability-unrecognized]');
        if (warning) warning.hidden = true;
        this.onChange();
    }

    /** Update serialized hours after a native date or time change. */
    private handleInput = (event: Event): void => {
        if (event.target instanceof HTMLInputElement && event.target.type !== 'hidden') this.updateValue();
    };

    /** Add or remove a row and let the form track the resulting schedule. */
    private handleClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest('button');
        if (!button || button.matches(':disabled')) return;
        const day = button.closest<HTMLElement>('[data-availability-day], [data-availability-exception]');
        if (button.hasAttribute('data-availability-add-exception')) {
            this.input(this.addException(), 'date')?.focus();
        } else if (day && button.hasAttribute('data-availability-add-hours')) {
            const hours = this.collectHours(day);
            this.input(this.addHours(day, hours.length ? undefined : { start: '09:00', end: '17:00' }), 'from')?.focus();
        } else if (day && button.hasAttribute('data-availability-remove-hours')) {
            button.closest('[data-availability-interval]')?.remove();
            this.refreshUnavailable(day);
        } else if (button.hasAttribute('data-availability-remove-exception')) {
            day?.remove();
        } else {
            return;
        }
        this.updateValue();
    };

    /** Release the editor's listeners when the form is replaced. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
