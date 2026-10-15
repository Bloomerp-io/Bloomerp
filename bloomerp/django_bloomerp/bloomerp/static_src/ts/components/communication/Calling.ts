import BaseComponent from '../BaseComponent';
import CallWindow from '../../communication/calling/CallWindow';
import { t as _ } from '../../utils/i18n';
import type { CallCredentials, CallingContext, CallingRegistration, IncomingCall, RegistrationOptions, BrowserCallTransport, TransportState, CallParticipant, CallActionContext } from '../../communication/calling/definition';
import { createBrowserCallTransport, registerCalling } from '../../communication/calling/registry';

type Session = Pick<CallCredentials, 'session_id' | 'join_url' | 'end_url' | 'media_mode'> & { can_end?: string; status?: string; cancel_url?: string };

/** Own one browser call independently of chat fragments and provider identities. */
export default class Calling extends BaseComponent {
    private callWindow = new CallWindow(this.element, this.onWindowAction.bind(this), this.participants.bind(this));
    private lifecycle = new AbortController();
    private identities: CallParticipant[] = [];
    private transport: BrowserCallTransport | null = null;
    private session: Session | null = null;
    private busy = false;
    private pendingCall: IncomingCall | null = null;
    private registrations = new Set<CallingRegistration>();
    private context: CallingContext = {
        post: this.post.bind(this), incoming: this.incoming.bind(this),
        registrationError: this.registrationError.bind(this),
        registrationCreated: this.ownRegistration.bind(this),
    };
    private microphone = false;
    private camera = false;
    private attempts = new Map<string, string>();
    private terminal = new Set<string>();
    private admissionsUrl = '';
    private admissionsBusy = false;
    private admissionsTimer: number | null = null;

    /** Bind provider-rendered actions and authenticated incoming notifications. */
    public initialize(): void {
        this.admissionsTimer = window.setInterval(this.pollAdmissions, 2500);
        this.element.addEventListener('click', this.togglePanel, { signal: this.lifecycle.signal });
        document.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        document.addEventListener('im:call-changed', this.onChanged, { signal: this.lifecycle.signal });
        window.addEventListener('pagehide', this.ownerClosed, { signal: this.lifecycle.signal });
        window.addEventListener('beforeunload', this.beforeUnload, { signal: this.lifecycle.signal });
        this.element.addEventListener('htmx:beforeCleanupElement', this.cleanup, { signal: this.lifecycle.signal });
    }

    /** Release media and listeners when the application shell is removed. */
    public override destroy(): void {
        this.callWindow.destroy();
        if (this.admissionsTimer !== null) window.clearInterval(this.admissionsTimer);
        this.lifecycle.abort();
        void this.transport?.disconnect();
        void this.pendingCall?.transport.disconnect();
        for (const registration of this.registrations) registration.destroy();
        this.registrations.clear();
        this.transport = null;
        super.destroy();
    }

    /** Tear down the companion view and transport when the owner page actually unloads. */
    private ownerClosed = (): void => { this.destroy(); };

    /** Preserve an active call against accidental full-page navigation. */
    private beforeUnload = (event: BeforeUnloadEvent): void => {
        if (this.transport || this.busy) { event.preventDefault(); event.returnValue = ''; }
    };

    /** Ignore child cleanup while releasing resources on shell removal. */
    private cleanup = (event: Event): void => { if (event.target === this.element) this.destroy(); };

    /** Resize the owner controls without changing media or the companion tab. */
    private togglePanel = (event: MouseEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('[data-call-panel-toggle]') : null;
        if (!button) return;
        const collapsed = this.element.dataset.collapsed !== 'true';
        this.element.dataset.collapsed = String(collapsed);
        button.setAttribute('aria-expanded', String(!collapsed));
        const label = collapsed ? _('Expand call controls') : _('Collapse call controls');
        button.setAttribute('aria-label', label);
        button.title = label;
        const icon = button.querySelector('i');
        if (icon) icon.className = `fa-solid fa-chevron-${collapsed ? 'up' : 'down'}`;
    };

    /** Dispatch declared controls without checking an IM provider key. */
    private onClick = (event: MouseEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-call-action]') : null;
        if (!button) return;
        event.preventDefault();
        void this.perform(button);
    };

    /** Read the transport's normalized roster, with authorized credential identities as fallback. */
    private participants(): CallParticipant[] {
        this.pressed('screen', this.transport?.screenSharing?.() || false);
        return this.transport?.participants?.() || this.identities;
    }

    /** Route presentation-tab actions through the same serialized owner controls. */
    private async onWindowAction(button: HTMLElement, context: CallActionContext = {}): Promise<void> { await this.perform(button, context); }

    /** Open the presentation before awaiting network requests to preserve browser activation. */
    private openCallWindow(): void {
        const opened = this.callWindow.open();
        this.element.querySelector<HTMLElement>('[data-call-media]')!.hidden = opened;
        this.control('open', true);
        if (!opened) this.error(_('Allow pop-ups to open the call tab. Your call controls are available here.'));
    }

    /** Serialize mutations and present recoverable failures in the call panel. */
    private async perform(button: HTMLElement, context: CallActionContext = {}): Promise<void> {
        if (this.busy) return;
        const action = button.dataset.callAction;
        this.busy = true;
        this.element.hidden = false;
        this.error('');
        try {
            if (action === 'open') {
                this.openCallWindow();
            } else if (action === 'enable') {
                await this.enable();
            } else if (action === 'start') {
                if (this.transport || this.session) throw new Error(_('Leave or dismiss the current call first.'));
                this.openCallWindow();
                const key = `${button.dataset.startUrl}:${button.dataset.mediaMode}`;
                const clientId = this.attempts.get(key) || crypto.randomUUID();
                this.attempts.set(key, clientId);
                this.status(_('Starting call…'));
                this.session = await this.post<Session>(button.dataset.startUrl!, new URLSearchParams({ client_id: clientId, media_mode: button.dataset.mediaMode! }));
                this.attempts.delete(key);
                this.control('answer', true);
                this.control('dismiss', true);
                this.control('end', this.session.can_end === 'true');
                await this.join(this.session.join_url);
            } else if (action === 'join' || action === 'answer') {
                if (this.transport) throw new Error(_('Leave the current call first.'));
                this.openCallWindow();
                if (this.pendingCall) await this.connect(this.pendingCall.credentials, this.pendingCall.transport);
                else await this.join(button.dataset.joinUrl || this.session!.join_url);
            } else if (action === 'leave' || action === 'dismiss') {
                await this.leave();
                this.callWindow.destroy();
                this.element.hidden = true;
            } else if (action === 'end' && this.session) {
                const ending = this.session;
                try { await this.post<Session>(ending.end_url); }
                catch (error: unknown) {
                    // A terminal notification may precede a failed remote cleanup response.
                    this.session = ending;
                    this.control('end', true);
                    throw error;
                }
                await this.leave();
                this.callWindow.destroy();
                this.status(_('Call ended'));
            } else if (action === 'microphone' && this.transport) {
                await this.transport.microphone(!this.microphone);
                this.microphone = !this.microphone;
                this.pressed('microphone', this.microphone);
            } else if (action === 'camera' && this.transport) {
                await this.transport.camera(!this.camera);
                this.camera = !this.camera;
                this.pressed('camera', this.camera);
            } else if (action === 'screen' && this.transport?.screenShare && !button.hidden) {
                const transport = this.transport;
                if (transport.screenSharing?.()) await transport.screenShare!(false);
                else {
                    // Capture is invoked before the first await, in the initiating document.
                    const stream = await (context.capture ? context.capture() : navigator.mediaDevices.getDisplayMedia({ video: true, audio: false }));
                    try {
                        if (this.transport !== transport || this.lifecycle.signal.aborted) {
                            for (const track of stream.getTracks()) track.stop();
                            return;
                        }
                        await transport.screenShare!(true, stream);
                    } catch (error: unknown) {
                        for (const track of stream.getTracks()) track.stop();
                        throw error;
                    }
                }
                this.pressed('screen', this.transport?.screenSharing?.() || false);
            } else if (action === 'share' && button.dataset.shareUrl && !button.hidden) {
                const url = new URL(button.dataset.shareUrl, location.origin).href;
                await (context.copy ? context.copy(url) : navigator.clipboard.writeText(url));
                this.status(_('Meeting link copied'));
            } else if (action === 'admit' && this.admissionsUrl) {
                await this.post(button.dataset.decisionUrl!, new URLSearchParams({ decision: button.dataset.decision! }));
                await this.pollAdmissions();
            } else if (action === 'audio') await this.transport?.playAudio();
        } catch (error: unknown) {
            if (!this.lifecycle.signal.aborted) {
                if (!this.transport) this.status(_('Call not connected'));
                this.error(error instanceof Error ? error.message : _('Calling is unavailable.'));
                this.control('dismiss', !this.transport);
            }
        } finally { this.busy = false; }
    }

    /** Accept a call explicitly and use only its server-selected browser driver. */
    private async join(url: string): Promise<void> {
        this.status(_('Joining call…'));
        const credentials = await this.post<CallCredentials>(url);
        if (this.terminal.has(credentials.session_id)) throw new Error(_('This call has ended.'));
        await this.connect(credentials);
    }

    /** Bind either a provider-issued reservation or an explicitly accepted invitation. */
    private async connect(credentials: CallCredentials, incoming?: BrowserCallTransport): Promise<void> {
        this.pendingCall = null;
        this.identities = credentials.participants || [];
        this.session = {
            session_id: credentials.session_id, join_url: credentials.join_url,
            end_url: credentials.end_url, media_mode: credentials.media_mode, can_end: credentials.can_end, cancel_url: credentials.cancel_url,
        };
        const transport = incoming || createBrowserCallTransport(credentials.driver, this.element.querySelector<HTMLElement>('[data-call-media]')!, this.onState, this.context);
        transport.setStateListener?.(this.onState);
        this.transport = transport;
        let connected = false;
        try {
            await transport.connect(credentials);
            connected = true;
            if (this.transport !== transport || this.lifecycle.signal.aborted) { await transport.disconnect(); return; }
            this.controls(credentials);
            await transport.playAudio();
            await transport.microphone(true);
            if (this.transport !== transport) return;
            this.microphone = true;
            this.pressed('microphone', true);
            if (credentials.media_mode === 'video' && credentials.can_video === 'true') {
                await transport.camera(true);
                this.camera = true;
                this.pressed('camera', true);
            }
        } catch (error: unknown) {
            if (!connected && this.transport === transport) {
                this.transport = null;
                await transport.disconnect();
                this.control('answer', Boolean(credentials.join_url));
                this.control('end', credentials.can_end === 'true');
            }
            // Preserve a connected session when capture permission fails, allowing retry.
            if (this.transport === transport) {
                this.control('leave', true);
                this.control('end', credentials.can_end === 'true');
            }
            throw error;
        }
    }

    /** Apply control visibility from authorized join capabilities. */
    private controls(credentials: CallCredentials): void {
        this.admissionsUrl = credentials.admissions_url || '';
        const share = this.element.querySelector<HTMLElement>('[data-call-action="share"]')!;
        share.dataset.shareUrl = credentials.share_url || '';
        this.control('share', Boolean(credentials.share_url));
        void this.pollAdmissions();
        this.control('answer', false); this.control('dismiss', false);
        this.control('microphone', true); this.control('camera', credentials.can_video === 'true');
        this.control('screen', credentials.can_screen_share === 'true' && Boolean(this.transport?.screenShare) && Boolean(navigator.mediaDevices?.getDisplayMedia));
        this.pressed('screen', false);
        this.control('audio', true); this.control('leave', true);
        this.control('end', credentials.can_end === 'true');
        this.microphone = false; this.camera = false;
        this.pressed('microphone', false); this.pressed('camera', false);
    }

    /** Stop local media without ending the room for other participants. */
    private async leave(message: string = _('You left the call')): Promise<void> {
        const transport = this.transport;
        const pending = this.pendingCall;
        const cancelUrl = this.session?.cancel_url;
        this.transport = null;
        this.pendingCall = null;
        this.session = null;
        this.identities = [];
        this.admissionsUrl = '';
        const waiting = this.element.querySelector<HTMLElement>('[data-call-admissions]')!;
        waiting.replaceChildren();
        waiting.dataset.guests = '';
        await transport?.disconnect();
        await pending?.transport.disconnect();
        if (cancelUrl) await this.post(cancelUrl);
        for (const action of ['open', 'answer', 'microphone', 'camera', 'screen', 'share', 'audio', 'leave', 'end']) this.control(action, false);
        this.control('dismiss', true);
        this.status(message);
    }

    /** Refresh the host's normalized waiting list without exposing provider-specific UI. */
    private pollAdmissions = async (): Promise<void> => {
        const url = this.admissionsUrl;
        if (!url || !this.transport || this.admissionsBusy) return;
        this.admissionsBusy = true;
        try {
            const endpoint = new URL(url, location.origin);
            if (endpoint.origin !== location.origin) return;
            const response = await fetch(endpoint, { signal: this.lifecycle.signal, cache: 'no-store' });
            if (!response.ok) return;
            const data = await response.json() as { guests: { id: string; name: string; url: string }[] };
            if (this.admissionsUrl !== url || !this.transport) return;
            const container = this.element.querySelector<HTMLElement>('[data-call-admissions]')!;
            const signature = JSON.stringify(data.guests);
            if (container.dataset.guests === signature) return;
            container.dataset.guests = signature;
            container.replaceChildren();
            const template = this.element.querySelector<HTMLTemplateElement>('[data-call-admission-template]')!;
            for (const guest of data.guests) {
                const row = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
                row.querySelector('[data-guest-name]')!.textContent = guest.name;
                for (const button of row.querySelectorAll<HTMLElement>('[data-call-action]')) button.dataset.decisionUrl = guest.url;
                container.append(row);
            }
        } catch { /* Keep the call connected and retry transient waiting-room failures. */ }
        finally { this.admissionsBusy = false; }
    };

    /** Register only the incoming accounts returned by IM provider hooks. */
    private async enable(): Promise<void> {
        const response = await fetch(this.element.dataset.registrationsUrl!, { signal: this.lifecycle.signal });
        if (!response.ok) throw new Error(_('Incoming calling is unavailable.'));
        const data = await response.json() as { registrations: RegistrationOptions[] };
        for (const options of data.registrations) {
            const registration = await registerCalling(options, this.context);
            this.ownRegistration(registration);
        }
        this.status(data.registrations.length ? _('Ready for incoming calls') : _('No incoming call accounts are available'));
        this.control('dismiss', !this.transport && !this.session);
    }

    /** Own each registration until the application shell is removed. */
    private ownRegistration(registration: CallingRegistration): void {
        if (this.lifecycle.signal.aborted) registration.destroy();
        else this.registrations.add(registration);
    }

    /** Present registration errors without SDK details or credentials. */
    private registrationError(): void {
        this.element.hidden = false;
        this.error(_('Incoming calling is unavailable. Check your connection and access.'));
        this.control('dismiss', !this.transport && !this.session);
    }

    /** Receive normalized driver invitations and enforce one active call across transports. */
    private incoming(call: IncomingCall): void {
        if (this.lifecycle.signal.aborted || this.busy || this.transport || this.session) {
            void call.transport.disconnect();
            return;
        }
        this.pendingCall = call;
        this.session = call.credentials;
        call.transport.setStateListener?.(this.onState);
        this.element.hidden = false;
        this.error('');
        this.status(_('Incoming call'));
        this.control('answer', true);
        this.control('dismiss', true);
    }

    /** Surface an invitation without enabling camera or microphone automatically. */
    private onChanged = (event: Event): void => {
        const session = (event as CustomEvent<Session>).detail;
        if (!session?.session_id) return;
        if (['ended', 'cancelled', 'failed'].includes(session.status || '')) {
            this.terminal.add(session.session_id);
            if (this.session?.session_id === session.session_id) {
                void this.leave(_('Call ended')).catch(this.registrationError.bind(this));
            }
        } else if (session.status === 'ringing' && !this.transport && !this.busy && !this.session) {
            this.session = session;
            this.element.hidden = false;
            this.status(_('Incoming call'));
            this.control('answer', true); this.control('dismiss', true);
        }
    };

    /** Reflect normalized transport lifecycle without depending on SDK events. */
    private onState = (state: TransportState): void => {
        if (state === 'disconnected') { void this.leave(_('Call disconnected')).catch(this.registrationError.bind(this)); }
        else this.status(state === 'connected' ? _('Call in progress') : _('Reconnecting…'));
    };

    /** Send same-origin, CSRF-protected requests without logging credentials. */
    private async post<T>(url: string, body: URLSearchParams = new URLSearchParams()): Promise<T> {
        const endpoint = new URL(url, location.origin);
        if (endpoint.origin !== location.origin) throw new Error(_('Invalid call endpoint.'));
        const token = this.element.querySelector<HTMLInputElement>('[name=csrfmiddlewaretoken]')?.value || '';
        const response = await fetch(endpoint, { method: 'POST', headers: { 'X-CSRFToken': token }, body, signal: this.lifecycle.signal });
        if (!response.ok) {
            let message = _('Calling failed. Check your connection and access, then try again.');
            if (response.headers.get('Content-Type')?.includes('application/json')) {
                const problem: unknown = await response.json();
                if (typeof problem === 'object' && problem !== null && 'error' in problem && typeof problem.error === 'string') message = problem.error;
            }
            throw new Error(message);
        }
        return await response.json() as T;
    }

    /** Set the visible pressed state after a successful media operation. */
    private pressed(action: string, enabled: boolean): void {
        this.element.querySelector(`[data-call-action="${action}"]`)?.setAttribute('aria-pressed', String(enabled));
    }

    /** Show only controls supported by the current authorized state. */
    private control(action: string, visible: boolean): void {
        const button = this.element.querySelector<HTMLElement>(`[data-call-action="${action}"]`);
        if (button) button.hidden = !visible;
    }

    /** Announce lifecycle changes to assistive technology. */
    private status(message: string): void { this.element.querySelector<HTMLElement>('[data-call-status]')!.textContent = message; }

    /** Present failures separately so lifecycle events do not erase them. */
    private error(message: string): void {
        const region = this.element.querySelector<HTMLElement>('[data-call-error]')!;
        region.textContent = message; region.hidden = !message;
    }
}
