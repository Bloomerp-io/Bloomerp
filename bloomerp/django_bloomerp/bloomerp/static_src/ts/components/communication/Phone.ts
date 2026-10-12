import { Call, Device } from '@twilio/voice-sdk';
import BaseComponent from '../BaseComponent';
import { t as _ } from '../../utils/i18n';

interface Connection { id: string; token_url: string; }

/** Keep browser audio sessions outside conversation fragments so chat navigation preserves calls. */
export default class Phone extends BaseComponent {
    private lifecycle = new AbortController();
    private devices = new Map<string, Device>();
    private call: Call | null = null;
    private busy = false;
    private muted = false;

    /** Bind delegated call controls and explicit incoming-call registration. */
    public initialize(): void {
        document.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        window.addEventListener('beforeunload', this.onBeforeUnload, { signal: this.lifecycle.signal });
        this.element?.addEventListener('htmx:beforeCleanupElement', this.onCleanup, { signal: this.lifecycle.signal });
    }

    /** Release microphone, registrations and listeners when the application shell is removed. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.call?.disconnect();
        this.devices.forEach(this.destroyDevice);
        this.devices.clear();
        super.destroy();
    }

    /** Dispose one carrier device without retaining active registrations. */
    private destroyDevice(device: Device): void { device.destroy(); }

    /** Clean up only when this persistent shell is actually removed. */
    private onCleanup = (event: Event): void => { if (event.target === this.element) this.destroy(); };

    /** Ask the browser to protect an active call during full-page navigation. */
    private onBeforeUnload = (event: BeforeUnloadEvent): void => {
        if (this.call) { event.preventDefault(); event.returnValue = ''; }
    };

    /** Dispatch call controls without coupling them to a particular conversation component. */
    private onClick = (event: MouseEvent): void => {
        const button = (event.target as Element)?.closest<HTMLElement>('[data-phone-action]');
        if (!button) return;
        const action = button.dataset.phoneAction;
        if (action === 'enable') void this.enable();
        if (action === 'call') void this.start(button);
        if (action === 'answer') this.call?.accept();
        if (action === 'hangup') { if (this.call?.status() === Call.State.Pending) this.call.reject(); else this.call?.disconnect(); }
        if (action === 'mute' && this.call) { this.muted = !this.muted; this.call.mute(this.muted); this.status(this.muted ? _('Microphone muted') : _('Call in progress')); }
    };

    /** Send CSRF-protected session requests and never expose server exception details. */
    private async post(url: string, data: URLSearchParams = new URLSearchParams()): Promise<Record<string, string>> {
        const token = this.element?.querySelector<HTMLInputElement>('[name=csrfmiddlewaretoken]')?.value || '';
        const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': token }, body: data, signal: this.lifecycle.signal });
        if (!response.ok) throw new Error(_('Calling is unavailable. Check your connection and line access.'));
        return await response.json() as Record<string, string>;
    }

    /** Create an authorized carrier registration and refresh its short-lived token. */
    private async device(connection: Connection): Promise<Device> {
        const existing = this.devices.get(connection.id);
        if (existing) return existing;
        const credentials = await this.post(connection.token_url);
        const device = new Device(credentials.token, { tokenRefreshMs: 60000 });
        this.devices.set(connection.id, device);
        device.on('incoming', this.incoming);
        device.on('error', this.error);
        device.on('tokenWillExpire', this.refreshToken.bind(this, connection, device));
        try { await device.register(); }
        catch (error) { device.destroy(); this.devices.delete(connection.id); throw error; }
        return device;
    }

    /** Refresh authorization and drop registrations immediately when line access is revoked. */
    private async refreshToken(connection: Connection, device: Device): Promise<void> {
        try { const refreshed = await this.post(connection.token_url); device.updateToken(refreshed.token); }
        catch { device.destroy(); this.devices.delete(connection.id); this.error(); }
    }

    /** Register assigned lines after an explicit user gesture enables browser telephony. */
    private async enable(): Promise<void> {
        if (this.busy) return;
        this.busy = true;
        try {
            const response = await fetch(this.element!.dataset.connectionsUrl!, { signal: this.lifecycle.signal });
            if (!response.ok) throw new Error();
            const data = await response.json() as { connections: Connection[] };
            for (const connection of data.connections) await this.device(connection);
            this.status(data.connections.length ? _('Ready for incoming calls') : _('No authorized voice lines are available'));
        } catch { this.error(); }
        finally { this.busy = false; }
    }

    /** Reserve a server-authorized call and pass only its opaque ID to Twilio. */
    private async start(button: HTMLElement): Promise<void> {
        if (this.call || this.busy) return;
        this.busy = true;
        let reservationId = '';
        try {
            const device = await this.device({ id: button.dataset.connectionId!, token_url: button.dataset.tokenUrl! });
            const reserved = await this.post(button.dataset.callUrl!, new URLSearchParams({ client_id: crypto.randomUUID() }));
            reservationId = reserved.call_id;
            this.bindCall(await device.connect({ params: { CallId: reserved.call_id } }));
            this.status(_('Calling…'));
        } catch {
            if (reservationId) {
                try { await this.post(button.dataset.callUrl!, new URLSearchParams({ action: 'cancel', call_id: reservationId })); }
                catch { /* A carrier callback or later synchronization can still reconcile the attempt. */ }
            }
            this.error();
        }
        finally { this.busy = false; }
    }

    /** Present an incoming call without automatically opening the microphone. */
    private incoming = (call: Call): void => {
        if (this.call || this.busy) { call.reject(); return; }
        this.bindCall(call);
        this.status(_('Incoming call'));
        this.element?.dispatchEvent(new CustomEvent('voip:incoming', { bubbles: true }));
        this.control('answer', false);
    };

    /** Bind one session and keep the global controls synchronized with SDK state. */
    private bindCall(call: Call): void {
        this.call = call;
        this.muted = false;
        this.control('hangup', false);
        this.control('mute', false);
        call.on('accept', this.accepted);
        call.on('disconnect', this.ended);
        call.on('cancel', this.ended);
        call.on('reject', this.ended);
        call.on('error', this.callError);
    }

    /** Display the connected session state after local or remote acceptance. */
    private accepted = (): void => { this.control('answer', true); this.status(_('Call in progress')); };

    /** Clear session controls after a carrier or local termination. */
    private ended = (): void => {
        this.call = null;
        this.control('answer', true); this.control('hangup', true); this.control('mute', true);
        this.status(_('Call ended'));
    };

    /** Reset session controls when call establishment fails. */
    private callError = (): void => { this.ended(); this.error(); };

    /** Show a translated operational error without leaking SDK diagnostics. */
    private error = (): void => { this.status(_('Calling failed. Check microphone permission, connection settings and line access.')); };

    /** Toggle a persistent session control. */
    private control(action: string, hidden: boolean): void {
        const element = this.element?.querySelector<HTMLElement>(`[data-phone-action="${action}"]`);
        if (element) element.hidden = hidden;
    }

    /** Update the live region for incoming, active and failed calls. */
    private status(message: string): void {
        const region = this.element?.querySelector<HTMLElement>('[data-phone-status]');
        if (region) region.textContent = message;
    }
}
