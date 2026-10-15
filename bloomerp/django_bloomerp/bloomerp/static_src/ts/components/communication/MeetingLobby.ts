import BaseComponent from '../BaseComponent';
import { t as _ } from '../../utils/i18n';

/** Keep link visitors in a browser-bound waiting room until the host admits them. */
export default class MeetingLobby extends BaseComponent {
    private lifecycle = new AbortController();
    private timer: number | null = null;
    private busy = false;

    /** Restore pending admission after reload without requesting capture or media credentials. */
    public initialize(): void {
        this.element.querySelector('form')!.addEventListener('submit', this.request, { signal: this.lifecycle.signal });
        this.timer = window.setInterval(this.poll, 2500);
        void this.poll();
    }

    /** Submit an anonymous name or server-derived account identity with CSRF protection. */
    private request = async (event: Event): Promise<void> => {
        event.preventDefault();
        if (this.busy) return;
        this.busy = true;
        const form = this.element.querySelector<HTMLFormElement>('form')!;
        try {
            const response = await fetch(form.action, { method: 'POST', body: new FormData(form), signal: this.lifecycle.signal });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || _('Unable to request admission.'));
            this.render(data.status);
        } catch (error: unknown) {
            if (!this.lifecycle.signal.aborted) this.message(error instanceof Error ? error.message : _('Unable to request admission.'));
        } finally { this.busy = false; }
    };

    /** Read only this browser's decision, with no media admission before explicit joining. */
    private poll = async (): Promise<void> => {
        if (this.busy) return;
        this.busy = true;
        try {
            const response = await fetch(this.element.dataset.statusUrl!, { signal: this.lifecycle.signal, cache: 'no-store' });
            if (response.status === 404 || response.status === 403) { this.render('ended'); return; }
            if (!response.ok) throw new Error();
            const data = await response.json();
            this.render(data.status);
        } catch {
            if (!this.lifecycle.signal.aborted) this.message(_('Connection interrupted. Retrying…'));
        } finally { this.busy = false; }
    };

    /** Present translated admission states without rendering guest input as HTML. */
    private render(status: string): void {
        this.element.querySelector<HTMLFormElement>('form')!.hidden = status !== 'new';
        this.element.querySelector<HTMLButtonElement>('[data-meeting-join]')!.hidden = status !== 'admitted';
        const labels: Record<string, string> = { new: '', waiting: _('Waiting for the host to admit you…'), admitted: _('You have been admitted. You can now join.'), rejected: _('The host did not admit you.'), ended: _('This meeting is no longer available.') };
        this.message(labels[status] || '');
        if (['ended', 'rejected'].includes(status) && this.timer !== null) { window.clearInterval(this.timer); this.timer = null; }
    }

    /** Announce waiting-room feedback through its accessible status region. */
    private message(text: string): void { this.element.querySelector('[data-meeting-status]')!.textContent = text; }

    /** Stop polling and abort outstanding requests when the lobby is removed. */
    public override destroy(): void {
        this.lifecycle.abort();
        if (this.timer !== null) window.clearInterval(this.timer);
        super.destroy();
    }
}
