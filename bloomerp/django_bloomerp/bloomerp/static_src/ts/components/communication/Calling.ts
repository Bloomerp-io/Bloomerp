import BaseComponent from '../BaseComponent';
import CallWindow from '../../communication/calling/CallWindow';
import CallRingtone from '../../communication/calling/CallRingtone';
import IncomingCallCoordinator, { type CallTabMessage } from '../../communication/calling/IncomingCallCoordinator';
import { t as _ } from '../../utils/i18n';
import type { CallCredentials, CallingContext, CallingRegistration, IncomingCall, RegistrationOptions, BrowserCallTransport, TransportState, CallParticipant, CallActionContext } from '../../communication/calling/definition';
import { createBrowserCallTransport, registerCalling } from '../../communication/calling/registry';

type Session = Pick<CallCredentials, 'session_id' | 'join_url' | 'end_url' | 'media_mode'> & Partial<Pick<CallCredentials, 'caller_name' | 'caller_address' | 'call_kind' | 'decline_url' | 'recipient_status'>> & {
    can_end?: string; status?: string; cancel_url?: string; invitation_status?: string; created_by?: string; ring_expires_at?: string;
};

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
    private handledInvitations = new Set<string>();
    private closedSessions = new Set<string>();
    private admissionsUrl = '';
    private admissionsBusy = false;
    private admissionsTimer: number | null = null;
    private coordinator: IncomingCallCoordinator | null = null;
    private ringtone: CallRingtone | null = null;
    private incomingEnabled = false;
    private ringtoneMuted = false;
    private ringtoneBlocked = false;
    private registrationJob: number | null = null;
    private registrationReady = false;
    private registrationFailed = false;
    private registrationEpoch = 0;
    private registrationRetry: number | null = null;
    private retryDelay = 2000;
    private ringTimer: number | null = null;
    private outgoing = false;
    private ringbackTimer: number | null = null;
    private layoutObserver: ResizeObserver | null = null;

    /** Bind provider-rendered actions and authenticated incoming notifications. */
    public initialize(): void {
        if (this.lifecycle.signal.aborted) {
            this.lifecycle = new AbortController();
            this.session = null;
            this.pendingCall = null;
            this.busy = false;
            this.registrationJob = null;
            this.registrationReady = false;
            this.registrationFailed = false;
            for (const action of ['open', 'answer', 'decline', 'dismiss', 'microphone', 'camera', 'screen', 'share', 'audio', 'leave', 'end']) this.control(action, false);
            this.setCallState('idle');
            this.status(_('No active call'));
            this.setPanelOpen(false);
        }
        this.ringtone = new CallRingtone(this.onRingtoneBlocked);
        const workspace = document.getElementById('main');
        this.layoutObserver?.disconnect();
        if (workspace) {
            this.layoutObserver = new ResizeObserver(this.alignPanel);
            this.layoutObserver.observe(workspace);
            this.alignPanel();
        }
        this.coordinator = new IncomingCallCoordinator(this.preferenceKey('owner'), this.onOwnershipChanged, this.onTabMessage);
        this.admissionsTimer = window.setInterval(this.pollAdmissions, 2500);
        this.element.addEventListener('click', this.togglePanel, { signal: this.lifecycle.signal });
        document.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        document.addEventListener('im:call-changed', this.onChanged, { signal: this.lifecycle.signal });
        window.addEventListener('pagehide', this.ownerClosed, { signal: this.lifecycle.signal });
        window.addEventListener('beforeunload', this.beforeUnload, { signal: this.lifecycle.signal });
        this.element.addEventListener('htmx:beforeCleanupElement', this.cleanup, { signal: this.lifecycle.signal });
        document.addEventListener('htmx:afterSwap', this.renderAvailability, { signal: this.lifecycle.signal });
        document.addEventListener('bloomerp:calling-signaling', this.renderAvailability, { signal: this.lifecycle.signal });
        document.addEventListener('pointerdown', this.unlockRingtone, { signal: this.lifecycle.signal });
        document.addEventListener('click', this.unlockRingtone, { capture: true, signal: this.lifecycle.signal });
        document.addEventListener('keydown', this.unlockRingtone, { signal: this.lifecycle.signal });
        window.addEventListener('storage', this.onPreferenceChanged, { signal: this.lifecycle.signal });
        window.addEventListener('online', this.retryIncoming, { signal: this.lifecycle.signal });
        this.ringtoneMuted = this.readPreference('muted');
        this.ringtone.setMuted(this.ringtoneMuted);
        this.setIncomingEnabled(this.readPreference('incoming'), false);
    }

    /** Release media and listeners when the application shell is removed. */
    public override destroy(): void {
        if (this.lifecycle.signal.aborted) return;
        this.callWindow.destroy();
        if (this.admissionsTimer !== null) window.clearInterval(this.admissionsTimer);
        this.admissionsTimer = null;
        this.layoutObserver?.disconnect();
        this.layoutObserver = null;
        this.lifecycle.abort();
        this.registrationEpoch++;
        this.registrationJob = null;
        this.stopRinging();
        this.stopRingback();
        this.ringtone?.destroy();
        this.coordinator?.destroy();
        if (this.registrationRetry !== null) window.clearTimeout(this.registrationRetry);
        this.registrationRetry = null;
        void this.transport?.disconnect();
        void this.pendingCall?.transport.disconnect();
        for (const registration of this.registrations) registration.destroy();
        this.registrations.clear();
        this.transport = null;
        super.destroy();
    }

    /** Tear down media on navigation and restore availability if this document is cached. */
    private ownerClosed = (event: PageTransitionEvent): void => {
        this.destroy();
        if (event.persisted) window.addEventListener('pageshow', this.restoreCachedPage, { once: true });
    };

    /** Reconnect remembered incoming availability after a browser restores its cached page. */
    private restoreCachedPage = (): void => { if (this.element.isConnected) this.initialize(); };

    /** Preserve an active call against accidental full-page navigation. */
    private beforeUnload = (event: BeforeUnloadEvent): void => {
        if (this.transport || this.busy) { event.preventDefault(); event.returnValue = ''; }
    };

    /** Ignore child cleanup while releasing resources on shell removal. */
    private cleanup = (event: Event): void => { if (event.target === this.element) this.destroy(); };

    /** Retract the control panel into its footer button without changing the call. */
    private togglePanel = (event: MouseEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('[data-call-panel-toggle]') : null;
        if (!button) return;
        this.setPanelOpen(false);
        this.element.querySelector<HTMLElement>('[data-call-launcher]')?.focus();
    };

    /** Show or hide the shared panel while its footer launcher remains available. */
    private setPanelOpen(open: boolean): void {
        if (open) this.alignPanel();
        this.element.querySelector<HTMLElement>('[data-call-panel]')!.hidden = !open;
        this.element.querySelector('[data-call-launcher]')!.setAttribute('aria-expanded', String(open));
    }

    /** Follow the workspace border through sidebar transitions and viewport resizing. */
    private alignPanel = (): void => {
        const workspace = document.getElementById('main');
        const panel = this.element.querySelector<HTMLElement>('[data-call-panel]');
        if (workspace && panel) panel.style.setProperty('--call-panel-left', `${workspace.getBoundingClientRect().left}px`);
    };

    /** Scope availability and ringtone preferences to this user and browser origin. */
    private preferenceKey(name: string): string { return `bloomerp.calling.${this.element.dataset.callUser}.${name}`; }

    /** Restore an explicit opt-in without persisting registration tokens or media permissions. */
    private readPreference(name: string): boolean {
        try { return localStorage.getItem(this.preferenceKey(name)) === 'true'; }
        catch { return false; }
    }

    /** Remember device-local preferences without making storage a prerequisite for calling. */
    private savePreference(name: string, enabled: boolean): void {
        try { localStorage.setItem(this.preferenceKey(name), String(enabled)); }
        catch { /* Availability remains usable in this tab when storage is disabled. */ }
    }

    /** Automatically restore one incoming registration owner after navigation or refresh. */
    private setIncomingEnabled(enabled: boolean, persist: boolean = true): void {
        this.incomingEnabled = enabled;
        if (persist) this.savePreference('incoming', enabled);
        if (enabled) this.coordinator?.start();
        else {
            this.registrationEpoch++;
            this.coordinator?.stop();
            this.ringtone?.setEnabled(false);
            this.registrationReady = false;
            this.registrationFailed = false;
            if (this.registrationRetry !== null) window.clearTimeout(this.registrationRetry);
            this.registrationRetry = null;
            if (this.element.dataset.callState === 'ringing' && !this.busy) void this.leave(_('Incoming calls disabled')).catch(this.registrationError.bind(this));
            if (!this.transport && !this.session) this.releaseRegistrations();
        }
        this.renderAvailability();
    }

    /** Reflect preference changes made in another tab without modifying its stored value. */
    private onPreferenceChanged = (event: StorageEvent): void => {
        if (event.key === this.preferenceKey('incoming') || event.key === null) this.setIncomingEnabled(this.readPreference('incoming'), false);
        if (event.key === this.preferenceKey('muted') || event.key === null) {
            this.ringtoneMuted = this.readPreference('muted');
            this.ringtone?.setMuted(this.ringtoneMuted);
            this.renderAvailability();
        }
    };

    /** Register only in the elected tab and release idle devices when ownership ends. */
    private onOwnershipChanged = (owner: boolean): void => {
        if (this.lifecycle.signal.aborted) return;
        this.registrationEpoch++;
        this.registrationJob = null;
        this.registrationReady = false;
        this.ringtone?.setEnabled(owner && this.incomingEnabled);
        if (owner) void this.enable();
        else if (!this.transport && !this.session) this.releaseRegistrations();
        this.renderAvailability();
    };

    /** Reopen the owning panel or suppress invitations already handled in another tab. */
    private onTabMessage = (message: CallTabMessage): void => {
        if (message.type === 'focus' && this.coordinator?.owner) { this.setPanelOpen(true); window.focus(); }
        else if (message.type === 'handled') {
            this.handledInvitations.add(message.sessionId);
            if (this.session?.session_id === message.sessionId && !this.transport && !this.busy) void this.leave(_('Call handled in another tab')).catch(this.registrationError.bind(this));
        }
    };

    /** Retry restored availability after the network becomes reachable again. */
    private retryIncoming = (): void => {
        if (this.incomingEnabled && this.coordinator?.owner) void this.enable();
    };

    /** Prime the receiving tab's audio during an ordinary trusted interaction. */
    private unlockRingtone = (event: Event): void => {
        if (event.isTrusted && this.incomingEnabled && this.coordinator?.owner && !this.ringtoneMuted) this.ringtone?.unlock();
    };

    /** Surface blocked audio before calls arrive and keep the footer's readiness honest. */
    private onRingtoneBlocked = (blocked: boolean): void => {
        this.ringtoneBlocked = blocked;
        this.element.dataset.callSound = this.ringtoneMuted ? 'muted' : blocked ? 'blocked' : 'ready';
        this.control('ringtone-enable', blocked);
        this.renderAvailability();
    };

    /** Present availability consistently in the panel, footer and newly swapped chat menus. */
    private renderAvailability = (): void => {
        if (this.lifecycle.signal.aborted) return;
        const signaling = document.body.dataset.callSignalingState === 'connected';
        let label = _('Offline');
        let availability = 'offline';
        if (this.incomingEnabled) {
            if (!this.coordinator?.owner) { label = _('Available in another tab'); availability = 'elsewhere'; }
            else if (this.registrationFailed) label = _('Offline — reconnecting');
            else if (!this.registrationReady || !signaling) { label = _('Connecting…'); availability = 'connecting'; }
            else { label = this.ringtoneBlocked ? _('Available — enable ringtone sound') : _('Available'); availability = 'available'; }
        }
        this.element.dataset.callAvailability = availability;
        this.element.querySelector('[data-call-availability]')!.textContent = label;
        const state = this.element.dataset.callState;
        const description = state === 'ringing' ? (this.ringtoneBlocked ? _('Incoming call — enable ringtone sound') : _('Incoming call')) : state === 'connected' ? _('Call in progress') : label;
        this.element.querySelector('[data-call-launcher-description]')!.textContent = description;
        this.element.querySelector('[data-call-launcher]')!.setAttribute('title', `${_('Calls')} · ${description}`);
        for (const button of document.querySelectorAll<HTMLElement>('[data-call-action="availability"], [data-call-action="enable"]')) {
            button.setAttribute('aria-checked', String(this.incomingEnabled));
            const check = button.querySelector<HTMLElement>('[data-call-availability-check]');
            if (check) check.hidden = !this.incomingEnabled;
        }
        const mute = this.element.querySelector<HTMLElement>('[data-call-action="ringtone"]')!;
        mute.setAttribute('aria-pressed', String(this.ringtoneMuted));
        mute.setAttribute('aria-label', this.ringtoneMuted ? _('Unmute ringtone') : _('Mute ringtone'));
        mute.title = mute.getAttribute('aria-label')!;
        this.element.querySelector('[data-call-ringtone-icon]')!.className = `fa-solid ${this.ringtoneMuted ? 'fa-bell-slash' : 'fa-bell'}`;
        this.control('retry', this.incomingEnabled && Boolean(this.coordinator?.owner) && this.registrationFailed);
        this.control('ringtone-test', this.incomingEnabled && Boolean(this.coordinator?.owner) && !this.ringtoneMuted);
    };

    /** Synchronize the footer's visual state without changing call media. */
    private setCallState(state: 'idle' | 'ringing' | 'connecting' | 'connected'): void {
        this.element.dataset.callState = state;
        this.renderAvailability();
    }

    /** Present normalized caller information for either a phone or conference invitation. */
    private presentSession(session: Session): void {
        this.element.querySelector('[data-call-caller]')!.textContent = session.caller_name || session.caller_address || _('Call');
        const kind = session.call_kind === 'phone' ? _('Phone call') : session.media_mode === 'video' ? _('Video call') : _('Audio call');
        this.element.querySelector('[data-call-kind]')!.textContent = session.caller_address && session.caller_address !== session.caller_name ? `${kind} · ${session.caller_address}` : kind;
        this.element.querySelector('[data-call-kind-icon]')!.className = `fa-solid ${session.media_mode === 'video' ? 'fa-video' : 'fa-phone'}`;
    }

    /** Stop audio and the unanswered-call deadline before accepting, declining or closing. */
    private stopRinging(): void {
        this.ringtone?.setRinging(false);
        if (this.ringTimer !== null) window.clearTimeout(this.ringTimer);
        this.ringTimer = null;
    }

    /** Stop caller feedback permanently after an answer, timeout, failure or hangup. */
    private stopRingback(): void {
        this.outgoing = false;
        this.ringtone?.setRingback(false);
        if (this.ringbackTimer !== null) window.clearTimeout(this.ringbackTimer);
        this.ringbackTimer = null;
    }

    /** Bound unanswered feedback without ending a conference room other users may still join. */
    private expireRingback = (): void => {
        if (!this.outgoing) return;
        this.stopRingback();
        this.status(_('No answer'));
    };

    /** Expand one incoming invitation and ring until it is resolved or its deadline passes. */
    private offerInvitation(session: Session): void {
        const expires = session.ring_expires_at ? Date.parse(session.ring_expires_at) : Date.now() + 60000;
        if (Number.isFinite(expires) && expires <= Date.now()) return;
        this.session = session;
        this.presentSession(session);
        this.setPanelOpen(true);
        this.error('');
        this.status(_('Incoming call'));
        this.control('answer', true);
        this.control('decline', true);
        this.control('dismiss', false);
        this.setCallState('ringing');
        this.ringtone?.setRinging(true);
        this.ringTimer = window.setTimeout(this.expireInvitation, Math.min(60000, Number.isFinite(expires) ? expires - Date.now() : 60000));
    }

    /** Bound ringing when no transport or server cancellation notification arrives. */
    private expireInvitation = (): void => {
        if (!this.session || this.element.dataset.callState !== 'ringing' || this.busy) return;
        this.handledInvitations.add(this.session.session_id);
        this.coordinator?.send({ type: 'handled', sessionId: this.session.session_id });
        void this.leave(_('Missed call')).catch(this.registrationError.bind(this));
    };
    /** Dispatch declared controls without checking an IM provider key. */
    private onClick = (event: MouseEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-call-action]') : null;
        if (!button) return;
        event.preventDefault();
        const action = button.dataset.callAction;
        if (action === 'panel') {
            const panel = this.element.querySelector<HTMLElement>('[data-call-panel]')!;
            this.setPanelOpen(panel.hidden);
            if (this.incomingEnabled && !this.coordinator?.owner) this.coordinator?.send({ type: 'focus' });
            return;
        }
        if (action === 'availability' || action === 'enable') {
            this.setPanelOpen(true);
            this.setIncomingEnabled(action === 'enable' || !this.incomingEnabled);
            if (this.incomingEnabled) this.ringtone?.unlock();
            return;
        }
        if (action === 'ringtone') {
            this.ringtoneMuted = !this.ringtoneMuted;
            this.savePreference('muted', this.ringtoneMuted);
            this.ringtone?.setMuted(this.ringtoneMuted);
            if (!this.ringtoneMuted) this.ringtone?.unlock();
            this.renderAvailability();
            return;
        }
        if (action === 'ringtone-enable' || action === 'ringtone-test') { this.ringtone?.preview(); return; }
        if (action === 'retry') { this.retryIncoming(); return; }
        void this.perform(button);
    };

    /** Read the transport's normalized roster, with authorized credential identities as fallback. */
    private participants(): CallParticipant[] {
        this.pressed('screen', this.transport?.screenSharing?.() || false);
        return this.transport?.participants?.() || this.identities;
    }

    /** Route presentation-tab actions through the same serialized owner controls. */
    private async onWindowAction(button: HTMLElement, context: CallActionContext = {}): Promise<void> { await this.perform(button, context); }

    /** Open the presentation after capture settles, with inline controls if pop-ups are blocked. */
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
        this.setPanelOpen(true);
        this.error('');
        try {
            if (action === 'open') {
                this.openCallWindow();
            } else if (action === 'start') {
                if (this.transport || this.session) throw new Error(_('Leave or dismiss the current call first.'));
                // Prime caller audio within the click, before fetching the reservation or credentials.
                this.ringtone?.unlock();
                this.outgoing = true;
                const key = `${button.dataset.startUrl}:${button.dataset.mediaMode}`;
                const clientId = this.attempts.get(key) || crypto.randomUUID();
                this.attempts.set(key, clientId);
                this.status(_('Starting call…'));
                this.setCallState('connecting');
                this.session = await this.post<Session>(button.dataset.startUrl!, new URLSearchParams({ client_id: clientId, media_mode: button.dataset.mediaMode! }));
                const recipient = button.closest('[data-conversation-id]')?.querySelector('.im-identity-text strong')?.textContent;
                if (recipient) this.session.caller_name = recipient;
                this.presentSession(this.session);
                this.attempts.delete(key);
                this.control('answer', true);
                this.control('dismiss', true);
                this.control('end', this.session.can_end === 'true');
                await this.join(this.session.join_url);
            } else if (action === 'join' || action === 'answer') {
                if (this.transport) throw new Error(_('Leave the current call first.'));
                this.stopRinging();
                this.setCallState('connecting');
                if (this.pendingCall) await this.connect(this.pendingCall.credentials, this.pendingCall.transport);
                else await this.join(button.dataset.joinUrl || this.session!.join_url);
                if (this.session) this.coordinator?.send({ type: 'handled', sessionId: this.session.session_id });
            } else if (action === 'decline' && this.session && !this.transport) {
                this.stopRinging();
                const declining = this.session;
                if (declining.decline_url) await this.post(declining.decline_url);
                this.handledInvitations.add(declining.session_id);
                this.coordinator?.send({ type: 'handled', sessionId: declining.session_id });
                await this.leave(_('Call declined'));
            } else if (action === 'leave' || action === 'dismiss') {
                await this.leave();
                this.callWindow.destroy();
                this.setPanelOpen(false);
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
                if (!this.transport) {
                    this.stopRingback();
                    this.status(_('Call not connected'));
                }
                this.error(error instanceof Error ? error.message : _('Calling is unavailable.'));
                this.control('dismiss', !this.transport);
                if (!this.transport) this.setCallState(this.session ? 'ringing' : 'idle');
            }
        } finally { this.busy = false; }
    }

    /** Join with authorized credentials unless the server reports that the session closed. */
    private async join(url: string): Promise<void> {
        this.status(_('Joining call…'));
        const credentials = await this.post<CallCredentials>(url);
        if (this.closedSessions.has(credentials.session_id)) throw new Error(_('This call has ended.'));
        await this.connect(credentials);
    }

    /** Bind either a provider-issued reservation or an explicitly accepted invitation. */
    private async connect(credentials: CallCredentials, incoming?: BrowserCallTransport): Promise<void> {
        this.stopRinging();
        this.pendingCall = null;
        this.identities = credentials.participants || [];
        this.session = {
            session_id: credentials.session_id, join_url: credentials.join_url,
            end_url: credentials.end_url, media_mode: credentials.media_mode, can_end: credentials.can_end, cancel_url: credentials.cancel_url,
            caller_name: this.session?.caller_name || credentials.caller_name, caller_address: credentials.caller_address,
            call_kind: credentials.call_kind, decline_url: credentials.decline_url,
            recipient_status: credentials.recipient_status,
        };
        if (credentials.recipient_status && credentials.recipient_status !== 'invited') this.stopRingback();
        this.presentSession(this.session);
        const transport = incoming || createBrowserCallTransport(credentials.driver, this.element.querySelector<HTMLElement>('[data-call-media]')!, this.onState, this.context);
        transport.setStateListener?.(this.onState);
        this.transport = transport;
        let connected = false;
        try {
            await transport.connect(credentials);
            connected = true;
            if (this.transport !== transport || this.lifecycle.signal.aborted) { await transport.disconnect(); return; }
            this.controls(credentials);
            try { await transport.playAudio(); }
            catch (error: unknown) {
                // Playback can be retried with Enable sound; it must not bypass capture consent.
                this.error(error instanceof Error ? error.message : _('Enable sound to hear the call.'));
            }
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
        } finally {
            // Keep the permission prompt visible in its owning tab until it settles.
            if (this.transport === transport && !this.lifecycle.signal.aborted) this.openCallWindow();
        }
    }

    /** Apply control visibility from authorized join capabilities. */
    private controls(credentials: CallCredentials): void {
        this.admissionsUrl = credentials.admissions_url || '';
        const share = this.element.querySelector<HTMLElement>('[data-call-action="share"]')!;
        share.dataset.shareUrl = credentials.share_url || '';
        this.control('share', Boolean(credentials.share_url));
        void this.pollAdmissions();
        this.control('answer', false); this.control('decline', false); this.control('dismiss', false);
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
        this.stopRinging();
        this.stopRingback();
        const transport = this.transport;
        const pending = this.pendingCall;
        const cancelUrl = this.session?.cancel_url;
        this.transport = null;
        this.pendingCall = null;
        this.session = null;
        this.identities = [];
        this.admissionsUrl = '';
        this.setCallState('idle');
        const waiting = this.element.querySelector<HTMLElement>('[data-call-admissions]')!;
        waiting.replaceChildren();
        waiting.dataset.guests = '';
        await transport?.disconnect();
        await pending?.transport.disconnect();
        if (cancelUrl) await this.post(cancelUrl);
        for (const action of ['open', 'answer', 'decline', 'microphone', 'camera', 'screen', 'share', 'audio', 'leave', 'end']) this.control(action, false);
        this.control('dismiss', true);
        this.status(message);
        if (!this.incomingEnabled || !this.coordinator?.owner) this.releaseRegistrations();
        else if (!this.registrationReady) this.scheduleRegistrationRetry();
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

    /** Restore authorized accounts in the owning tab and retry temporary failures. */
    private async enable(): Promise<void> {
        if (!this.incomingEnabled || !this.coordinator?.owner || this.registrationJob !== null || this.lifecycle.signal.aborted) return;
        if (this.transport || this.session || this.busy) { this.scheduleRegistrationRetry(); return; }
        this.registrationFailed = false;
        this.registrationReady = false;
        const epoch = ++this.registrationEpoch;
        this.registrationJob = epoch;
        this.releaseRegistrations();
        this.renderAvailability();
        try {
            const response = await fetch(this.element.dataset.registrationsUrl!, { signal: this.lifecycle.signal, cache: 'no-store' });
            if (!response.ok) throw new Error(_('Incoming calling is unavailable.'));
            const data = await response.json() as { registrations: RegistrationOptions[] };
            const context: CallingContext = { ...this.context, registrationCreated: this.trackIncomingRegistration.bind(this, epoch) };
            for (const options of data.registrations) {
                if (!this.currentRegistration(epoch)) return;
                const registration = await registerCalling(options, context);
                this.trackIncomingRegistration(epoch, registration);
            }
            if (this.currentRegistration(epoch)) {
                this.registrationReady = true;
                this.retryDelay = 2000;
                if (this.registrationRetry !== null) window.clearTimeout(this.registrationRetry);
                this.registrationRetry = null;
                this.error('');
            }
        } catch {
            if (this.currentRegistration(epoch)) this.registrationError();
        } finally {
            if (this.registrationJob === epoch) this.registrationJob = null;
            this.renderAvailability();
            if (this.incomingEnabled && this.coordinator?.owner && !this.registrationReady) this.scheduleRegistrationRetry();
        }
    }

    /** Reject stale registration results after availability or tab ownership changes. */
    private currentRegistration(epoch: number): boolean {
        return epoch === this.registrationEpoch && this.incomingEnabled && Boolean(this.coordinator?.owner) && !this.lifecycle.signal.aborted;
    }

    /** Dispose devices created by requests that outlive their registration ownership. */
    private trackIncomingRegistration(epoch: number, registration: CallingRegistration): void {
        if (this.currentRegistration(epoch)) this.ownRegistration(registration);
        else registration.destroy();
    }

    /** Release idle SDK registrations without affecting an ongoing call. */
    private releaseRegistrations(): void {
        for (const registration of this.registrations) registration.destroy();
        this.registrations.clear();
    }

    /** Retry with bounded backoff instead of requiring another setup click. */
    private scheduleRegistrationRetry(): void {
        if (this.registrationRetry !== null || !this.incomingEnabled || !this.coordinator?.owner || this.lifecycle.signal.aborted) return;
        this.registrationRetry = window.setTimeout(this.onRegistrationRetry, this.retryDelay);
        this.retryDelay = Math.min(60000, this.retryDelay * 2);
    }

    /** Clear the retry token before making the next authorized registration request. */
    private onRegistrationRetry = (): void => { this.registrationRetry = null; void this.enable(); };

    /** Own each registration until the application shell is removed. */
    private ownRegistration(registration: CallingRegistration): void {
        if (this.lifecycle.signal.aborted) registration.destroy();
        else this.registrations.add(registration);
    }

    /** Present registration errors without SDK details or credentials. */
    private registrationError(): void {
        if (this.lifecycle.signal.aborted) return;
        this.registrationFailed = true;
        this.registrationReady = false;
        this.error(_('Incoming calling is unavailable. Check your connection and access.'));
        this.control('dismiss', !this.transport && !this.session);
        this.renderAvailability();
        this.scheduleRegistrationRetry();
    }

    /** Receive normalized driver invitations and enforce one active call across transports. */
    private incoming(call: IncomingCall): void {
        // An outgoing device in a secondary tab must not reject another tab's invitation.
        if (!this.incomingEnabled || !this.coordinator?.owner) return;
        if (this.lifecycle.signal.aborted || this.busy || this.transport || this.session) {
            void call.transport.disconnect();
            return;
        }
        this.pendingCall = call;
        this.offerInvitation(call.credentials);
        call.transport.setStateListener?.(this.onInvitationState.bind(this, call.credentials.session_id));
    }

    /** Ignore late carrier termination events belonging to a previously dismissed invitation. */
    private onInvitationState(sessionId: string, state: TransportState): void {
        if (this.session?.session_id === sessionId) this.onState(state);
    }

    /** Reconcile call closure independently of invitation responses and incoming ringing. */
    private onChanged = (event: Event): void => {
        const session = (event as CustomEvent<Session>).detail;
        if (!session?.session_id) return;
        if (this.outgoing && this.session?.session_id === session.session_id
            && session.recipient_status && session.recipient_status !== 'invited') {
            this.stopRingback();
            this.status(session.recipient_status === 'accepted' ? _('Connecting…') : _('No answer'));
        }
        const resolved = ['accepted', 'declined', 'missed', 'cancelled'].includes(session.invitation_status || '');
        const closed = ['ended', 'cancelled', 'failed'].includes(session.status || '');
        if (closed) this.closedSessions.add(session.session_id);
        if (closed || resolved) {
            if (resolved && !closed
                && this.session?.session_id === session.session_id && (this.transport || this.busy)) return;
            this.handledInvitations.add(session.session_id);
            if (this.session?.session_id === session.session_id && (!resolved || (!this.transport && !this.busy))) {
                void this.leave(session.invitation_status === 'accepted' ? _('Answered on another tab or device') : _('Call ended')).catch(this.registrationError.bind(this));
            }
        } else if (['ringing', 'active'].includes(session.status || '') && this.incomingEnabled && this.coordinator?.owner
            && session.created_by !== this.element.dataset.callUser && !this.handledInvitations.has(session.session_id)
            && !this.transport && !this.busy && !this.session) {
            this.offerInvitation(session);
        }
    };

    /** Reflect normalized transport lifecycle without depending on SDK events. */
    private onState = (state: TransportState): void => {
        if (state === 'disconnected') { void this.leave(_('Call disconnected')).catch(this.registrationError.bind(this)); }
        else {
            this.stopRinging();
            const awaitingAnswer = state === 'waiting' && this.outgoing;
            if (state === 'connected') this.stopRingback();
            this.ringtone?.setRingback(awaitingAnswer);
            if (awaitingAnswer && this.ringbackTimer === null) this.ringbackTimer = window.setTimeout(this.expireRingback, 60000);
            this.setCallState(state === 'connected' || state === 'waiting' && !awaitingAnswer ? 'connected' : 'connecting');
            this.status(awaitingAnswer ? _('Ringing…') : state === 'waiting' ? _('Waiting for participants…') : state === 'connected' ? _('Call in progress') : _('Reconnecting…'));
        }
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
