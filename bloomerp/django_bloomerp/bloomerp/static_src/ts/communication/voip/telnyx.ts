import { TelnyxRTC } from '@telnyx/webrtc';
import type { BrowserCall, BrowserDevice } from './definition';

type SDKCall = ReturnType<TelnyxRTC['newCall']>;
type CallEvent = Parameters<BrowserCall['on']>[0];
type Credentials = { token: string; domain: string };

/** Translate Telnyx notifications into the shared session lifecycle. */
class TelnyxCall implements BrowserCall {
    private listeners = new Map<CallEvent, Set<() => void>>();
    private emitted = new Set<CallEvent>();
    private audio = document.createElement('audio');

    /** Keep audio ownership per call so rejected invitations cannot replace active audio. */
    public constructor(private readonly call: SDKCall) {
        this.audio.autoplay = true;
        this.audio.hidden = true;
        document.body.append(this.audio);
        call.options.remoteElement = this.audio;
    }
    /** Accept capture only after the shared UI receives explicit consent. */
    public accept(): void { void this.call.answer({ remoteElement: this.audio }).catch(this.failed); }
    /** Reject a pending session without requesting capture. */
    public reject(): void { this.disconnect(); }
    /** Stop the SDK session and release its media element. */
    public disconnect(): void { void this.call.hangup().catch(this.failed); this.release(); }
    /** Translate shared microphone muting to the SDK. */
    public mute(muted: boolean): void { if (muted) this.call.muteAudio(); else this.call.unmuteAudio(); }
    /** Resume the per-call audio element after an autoplay restriction. */
    public async playAudio(): Promise<void> { if (this.audio.srcObject) await this.audio.play(); }
    /** Distinguish unanswered incoming calls from outgoing sessions. */
    public isPending(): boolean { return this.call.direction === 'inbound' && this.call.state === 'ringing'; }
    /** Replay state reached before the caller could attach its event listeners. */
    public on(event: CallEvent, callback: () => void): void {
        if (!this.listeners.has(event)) this.listeners.set(event, new Set());
        this.listeners.get(event)!.add(callback);
        if (this.emitted.has(event)) callback();
    }
    /** Emit each normalized lifecycle event at most once. */
    private emit(event: CallEvent): void {
        if (this.emitted.has(event)) return;
        this.emitted.add(event);
        for (const callback of this.listeners.get(event) || []) callback();
    }
    /** Map active and terminal states without leaking SDK state into the UI. */
    public changed(): void {
        if (this.call.state === 'active') this.emit('accept');
        if (['hangup', 'destroy', 'purge'].includes(this.call.state)) { this.release(); this.emit('disconnect'); }
    }
    /** Release audio after remote termination or local cleanup. */
    private release(): void { this.audio.srcObject = null; this.audio.remove(); }
    /** Surface SDK operation failures through the session's terminal event. */
    private failed = (): void => { this.release(); this.emit('error'); };
}

/** Own Telnyx credentials, registration and SIP routing behind the carrier interface. */
export class TelnyxDevice implements BrowserDevice {
    private readonly client: TelnyxRTC;
    private credentials: Credentials;
    private calls = new Map<string, TelnyxCall>();
    private disposed = false;
    private refreshTimer: ReturnType<typeof setTimeout> | undefined;
    private incoming: ((call: BrowserCall) => void) | undefined;
    private error: (() => void) | undefined;
    private expiry: (() => void) | undefined;
    private rejectRegistration: ((error: Error) => void) | undefined;

    /** Accept only a server-issued JWT envelope; never expose account API keys. */
    public constructor(token: string) {
        this.credentials = this.decode(token);
        this.client = new TelnyxRTC({ login_token: this.credentials.token, enableCallReports: false, enableCallRecording: false });
        this.client.on('telnyx.notification', this.notification);
        this.client.on('telnyx.error', this.failed);
    }
    /** Validate the provider envelope before using its domain in SIP routing. */
    private decode(token: string): Credentials {
        const value = JSON.parse(token) as Credentials;
        if (!value.token || !/^[a-z0-9-]+\.sip\.telnyx\.com$/.test(value.domain)) throw new Error('Invalid calling credentials');
        return value;
    }
    /** Wait for authenticated registration with a bounded readiness timeout. */
    public async register(): Promise<void> {
        if (this.disposed) throw new Error('Calling registration was closed');
        await new Promise<void>((resolve, reject): void => {
            const timeout = setTimeout((): void => { failed(new Error('Calling registration timed out')); }, 15000);
            /** Remove temporary registration listeners on either outcome. */
            const cleanup = (): void => { clearTimeout(timeout); this.client.off('telnyx.ready', ready); this.rejectRegistration = undefined; };
            /** Resolve only once Telnyx has authenticated the device. */
            const ready = (): void => { cleanup(); this.scheduleRefresh(); resolve(); };
            /** Reject waiting callers without exposing SDK error payloads. */
            const failed = (error: Error): void => { cleanup(); reject(error); };
            this.rejectRegistration = failed;
            this.client.on('telnyx.ready', ready);
            void this.client.connect().catch((): void => { failed(new Error('Calling registration failed')); });
        });
    }
    /** Release registration, timers and all owned media. */
    public destroy(): void {
        if (this.disposed) return;
        this.disposed = true;
        this.rejectRegistration?.(new Error('Calling registration was closed'));
        clearTimeout(this.refreshTimer);
        for (const call of this.calls.values()) call.disconnect();
        this.calls.clear();
        this.client.off('telnyx.notification', this.notification);
        this.client.off('telnyx.error', this.failed);
        void this.client.disconnect().catch(this.ignoreClosedError);
    }
    /** Ignore socket-close failures after all local media has already been released. */
    private ignoreClosedError(): void {}
    /** Renew authentication on the existing SDK session without dropping active media. */
    public updateToken(token: string): void {
        if (this.disposed) return;
        this.credentials = this.decode(token);
        this.client.options.login_token = this.credentials.token;
        void this.client.login({ creds: { login_token: this.credentials.token } }).then(this.scheduleRefresh).catch(this.failed);
    }
    /** Dial only a signed reservation at the configured application SIP domain. */
    public async connect(callId: string): Promise<BrowserCall> {
        if (this.disposed || !/^[A-Za-z0-9_.-]+$/.test(callId)) throw new Error('Invalid call reservation');
        const call = this.client.newCall({ destinationNumber: `sip:${callId}@${this.credentials.domain}`, audio: true, video: false });
        return this.wrap(call);
    }
    /** Subscribe the common shell to incoming invitations. */
    public onIncoming(callback: (call: BrowserCall) => void): void { this.incoming = callback; }
    /** Subscribe the common shell to sanitized device failures. */
    public onError(callback: () => void): void { this.error = callback; }
    /** Request renewed server authorization before credentials expire. */
    public onTokenExpiry(callback: () => void): void { this.expiry = callback; }
    /** Bound credentials to server renewal rather than relying on persistent SDK login. */
    private scheduleRefresh = (): void => {
        clearTimeout(this.refreshTimer);
        if (!this.disposed) this.refreshTimer = setTimeout((): void => { this.expiry?.(); }, 8 * 60 * 1000);
    };
    /** Normalize SDK errors without leaking tokens or carrier payloads. */
    private failed = (): void => { if (!this.disposed) { this.rejectRegistration?.(new Error('Calling registration failed')); this.error?.(); } };
    /** Reuse one session wrapper across repeated SDK notifications. */
    private wrap(call: SDKCall): TelnyxCall {
        let wrapped = this.calls.get(call.id);
        if (!wrapped) { wrapped = new TelnyxCall(call); this.calls.set(call.id, wrapped); }
        wrapped.changed();
        return wrapped;
    }
    /** Offer incoming sessions once and translate subsequent state changes. */
    private notification = (notification: { type: string; call?: SDKCall }): void => {
        const call = notification.call;
        if (this.disposed || notification.type !== 'callUpdate' || !call) return;
        const known = this.calls.has(call.id);
        const wrapped = this.wrap(call);
        if (!known && call.direction === 'inbound' && call.state === 'ringing') {
            if (this.incoming) this.incoming(wrapped); else wrapped.reject();
        }
        if (['hangup', 'destroy', 'purge'].includes(call.state)) this.calls.delete(call.id);
    };
}
