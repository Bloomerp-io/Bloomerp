import { BaseWidget } from './BaseWidget';

/** Bind the manual location and meeting checkbox as one layout field. */
export default class BookingLocation extends BaseWidget {
    private lifecycle?: AbortController;

    /** Keep the manual input read-only while a generated meeting is selected. */
    public override initialize(): void {
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.syncInput();
        this.element?.addEventListener('change', this.handleChange, { signal: this.lifecycle.signal });
    }

    /** Serialize the location selected by the organizer. */
    public getValue(): string {
        return this.meeting?.checked ? this.element?.dataset.meetingValue ?? '' : this.input?.value ?? '';
    }

    /** Restore the controls from their saved single-field value. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        if (!this.input || !this.meeting) return;
        this.meeting.checked = value === this.element?.dataset.meetingValue;
        this.input.value = this.meeting.checked || typeof value !== 'string' ? '' : value;
        this.syncInput();
        if (emitChange) this.onChange();
    }

    /** Release listeners when the framework swaps out the form. */
    public override destroy(): void {
        this.lifecycle?.abort();
    }

    /** Find the location input used by the Django field. */
    private get input(): HTMLInputElement | null {
        return this.element?.querySelector<HTMLInputElement>('input[type="text"]') ?? null;
    }

    /** Find the option that selects a generated meeting. */
    private get meeting(): HTMLInputElement | null {
        return this.element?.querySelector<HTMLInputElement>('[data-booking-meeting]') ?? null;
    }

    /** Update the control state before notifying the containing layout. */
    private handleChange = (): void => {
        this.syncInput();
        this.onChange();
    };

    /** Preserve the manual text so unchecking the option restores it. */
    private syncInput(): void {
        if (this.input) this.input.readOnly = this.meeting?.checked ?? false;
    }
}
