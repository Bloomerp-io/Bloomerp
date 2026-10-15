import type { BrowserCall, BrowserDevice } from './definition';
import { createBrowserDevice } from './registry';
import type { CallCredentials, CallingContext, CallingRegistration, BrowserCallTransport, RegistrationOptions, TransportState } from '../calling/definition';

/** Own carrier registrations separately from UI and conference rooms. */
class CarrierRegistration implements CallingRegistration {
    public device: BrowserDevice;
    private disposed = false;

    /** Bind incoming delivery and credential refresh to one authorized account. */
    public constructor(private options: RegistrationOptions, credentials: { driver: string; token: string }, private context: CallingContext) {
        this.device = createBrowserDevice(credentials.driver, credentials.token);
        this.device.onIncoming(this.incoming);
        this.device.onTokenExpiry(this.refresh);
        this.device.onError(this.failed);
    }

    /** Offer an incoming carrier session through the common invitation contract. */
    private incoming = (call: BrowserCall): void => {
        const transport = new CarrierTransport(null, this.context, call);
        const credentials: CallCredentials = {
            session_id: crypto.randomUUID(), driver: this.options.driver, media_mode: 'audio',
            join_url: '', end_url: '', url: '', token: '', can_video: 'false', can_end: 'false',
        };
        this.context.incoming({ credentials, transport });
    };

    /** Refresh current authorization; revoked access disposes the registration. */
    private refresh = async (): Promise<void> => {
        try {
            const credentials = await this.context.post<{ token: string }>(this.options.token_url);
            if (!this.disposed) this.device.updateToken(credentials.token);
        } catch { this.destroy(); this.context.registrationError(); }
    };

    /** Report registration problems through an application-owned message. */
    private failed = (): void => { if (!this.disposed) this.context.registrationError(); };

    /** Release SDK listeners and remove the shared account registration. */
    public destroy(): void {
        if (this.disposed) return;
        this.disposed = true;
        this.device.destroy();
        registrations.delete(this.options.id);
    }
}

const registrations = new Map<string, CarrierRegistration>();

/** Obtain one carrier registration and avoid double registration of an account. */
export async function registerCarrier(options: RegistrationOptions, context: CallingContext): Promise<CallingRegistration> {
    return await registration(options, context);
}

/** Reuse an account device or establish it using fresh server authorization. */
async function registration(options: RegistrationOptions, context: CallingContext): Promise<CarrierRegistration> {
    const existing = registrations.get(options.id);
    if (existing) return existing;
    const credentials = await context.post<{ driver: string; token: string }>(options.token_url);
    const registered = new CarrierRegistration(options, credentials, context);
    registrations.set(options.id, registered);
    context.registrationCreated(registered);
    try { await registered.device.register(); }
    catch (error: unknown) { registered.destroy(); throw error; }
    return registered;
}

/** Adapt a carrier call to the same media lifecycle as a conference session. */
export class CarrierTransport implements BrowserCallTransport {
    private call: BrowserCall | null;
    private disposed = false;
    private onState: (state: TransportState) => void;

    /** Keep incoming or outgoing carrier state behind the shared media interface. */
    public constructor(onState: ((state: TransportState) => void) | null, private context: CallingContext, incoming: BrowserCall | null = null) {
        this.onState = onState || this.ignoreState;
        this.call = incoming;
        if (incoming) this.bind(incoming);
    }

    /** Bind the invitation to the active shell before the user accepts it. */
    public setStateListener(listener: (state: TransportState) => void): void { this.onState = listener; }

    /** Accept an offered call or connect only the opaque server-authorized reservation. */
    public async connect(credentials: CallCredentials): Promise<void> {
        if (this.disposed) throw new Error('Call is no longer available');
        if (this.call) { this.call.accept(); return; }
        const registered = await registration({ id: credentials.registration_id!, driver: credentials.driver, token_url: credentials.token_url! }, this.context);
        if (this.disposed) return;
        const call = await registered.device.connect(credentials.call_id!);
        if (this.disposed) { call.disconnect(); return; }
        this.call = call;
        this.bind(call);
    }

    /** Normalize all terminal carrier states and remote acceptance. */
    private bind(call: BrowserCall): void {
        call.on('accept', this.accepted);
        call.on('disconnect', this.ended);
        call.on('cancel', this.ended);
        call.on('reject', this.ended);
        call.on('error', this.ended);
    }

    /** Reject an unanswered invitation or hang up an established call. */
    public async disconnect(): Promise<void> {
        this.disposed = true;
        if (this.call?.isPending()) this.call.reject();
        else this.call?.disconnect();
        this.call = null;
    }

    /** Translate microphone enablement to the carrier's mute operation. */
    public async microphone(enabled: boolean): Promise<void> { this.call?.mute(!enabled); }
    /** Reject unsupported video even if invoked outside the capability-driven UI. */
    public async camera(_enabled: boolean): Promise<void> { throw new Error('Video is unavailable for this call'); }
    /** Let drivers resume remote audio when their browser playback requires consent. */
    public async playAudio(): Promise<void> { await this.call?.playAudio?.(); }
    /** Report carrier acceptance. */
    private accepted = (): void => { if (!this.disposed) this.onState('connected'); };
    /** Report remote termination or cancellation, including unanswered invitations. */
    private ended = (): void => { if (!this.disposed) this.onState('disconnected'); };
    /** Ignore state only before an incoming invitation has a shell listener. */
    private ignoreState(_state: TransportState): void {}
}

/** Construct the carrier transport without exposing SDK types to the UI. */
export function createCarrierTransport(_container: HTMLElement, onState: (state: TransportState) => void, context: CallingContext): BrowserCallTransport {
    return new CarrierTransport(onState, context);
}
