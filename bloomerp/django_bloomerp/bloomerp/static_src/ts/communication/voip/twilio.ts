import { Call, Device } from '@twilio/voice-sdk';
import type { BrowserCall, BrowserDevice } from './definition';

/** Adapt Twilio session state and events to the shared phone controls. */
class TwilioCall implements BrowserCall {
    /** Retain the SDK session behind a carrier-neutral interface. */
    constructor(private readonly call: Call) {}
    /** Answer this incoming session. */
    public accept(): void { this.call.accept(); }
    /** Decline this incoming session. */
    public reject(): void { this.call.reject(); }
    /** End this session. */
    public disconnect(): void { this.call.disconnect(); }
    /** Change local microphone muting. */
    public mute(muted: boolean): void { this.call.mute(muted); }
    /** Identify Twilio's unanswered incoming state. */
    public isPending(): boolean { return this.call.status() === Call.State.Pending; }
    /** Forward supported normalized lifecycle events. */
    public on(event: 'accept' | 'disconnect' | 'cancel' | 'reject' | 'error', callback: () => void): void { this.call.on(event, callback); }
}

/** Own Twilio SDK configuration and its carrier-specific outgoing parameters. */
export class TwilioDevice implements BrowserDevice {
    private readonly device: Device;
    /** Build a device with bounded token-refresh lead time. */
    constructor(token: string) { this.device = new Device(token, { tokenRefreshMs: 60000 }); }
    /** Register with Twilio for incoming calls. */
    public async register(): Promise<void> { await this.device.register(); }
    /** Release Twilio registration and audio resources. */
    public destroy(): void { this.device.destroy(); }
    /** Replace the Twilio access token. */
    public updateToken(token: string): void { this.device.updateToken(token); }
    /** Pass only the opaque authorized reservation to TwiML dispatch. */
    public async connect(callId: string): Promise<BrowserCall> { return new TwilioCall(await this.device.connect({ params: { CallId: callId } })); }
    /** Wrap incoming SDK sessions before exposing them to shared UI. */
    public onIncoming(callback: (call: BrowserCall) => void): void { this.device.on('incoming', (call: Call): void => { callback(new TwilioCall(call)); }); }
    /** Subscribe to SDK transport failures. */
    public onError(callback: () => void): void { this.device.on('error', callback); }
    /** Subscribe to Twilio token expiration notices. */
    public onTokenExpiry(callback: () => void): void { this.device.on('tokenWillExpire', callback); }
}
