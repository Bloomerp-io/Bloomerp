/** Exercise the Telnyx driver with an SDK double and real DOM audio ownership. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type { BrowserCall } from './definition';
import type { TelnyxDevice } from './telnyx';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/telnyx-test-entry.ts`;
const result = await build({ configFile: false, root, logLevel: 'silent', plugins: [{
    name: 'telnyx-sdk-double', enforce: 'pre',
    /** Replace only the SDK import, leaving the actual driver under test. */
    resolveId(id: string): string | null { if (id === entry) return entry; return id === '@telnyx/webrtc' ? 'virtual:telnyx.ts' : null; },
    /** Expose deterministic SDK calls, notifications and credential updates. */
    load(id: string): string | null {
        if (id === entry) return `export { TelnyxDevice } from '${root}/ts/communication/voip/telnyx';`;
        if (id !== 'virtual:telnyx.ts') return null;
        return `export class TelnyxRTC {
            /** Capture construction without initiating any media. */
            constructor(options: object) { this.options = options; this.handlers = new Map(); window.sdk = this; }
            /** Register a SDK event listener. */
            on(event: string, callback: Function): void { this.handlers.set(event, callback); }
            /** Remove a SDK event listener. */
            off(event: string): void { this.handlers.delete(event); }
            /** Simulate successful authenticated registration. */
            async connect(): Promise<void> { this.handlers.get('telnyx.ready')?.(); }
            /** Record disposal. */
            async disconnect(): Promise<void> { this.closed = true; }
            /** Capture renewal of an existing authenticated session. */
            async login(options: object): Promise<void> { this.renewed = options; }
            /** Return a call configured by the current test. */
            newCall(options: object): object { this.outgoing = options; return window.call; }
        }`;
    },
}], build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'TelnyxFixture' } } });
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Select the executable fixture chunk. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const code = script.code;
interface FakeCall { id: string; state: string; direction: string; options: Record<string, unknown>; answer(): Promise<void>; hangup(): Promise<void>; muteAudio(): void; unmuteAudio(): void }
interface FixtureWindow extends DOMWindow {
    sdk: { handlers: Map<string, (payload?: object) => void>; outgoing: { destinationNumber: string; video: boolean }; renewed: { creds: { login_token: string } }; closed: boolean };
    call: FakeCall;
    TelnyxFixture: { TelnyxDevice: typeof TelnyxDevice };
}

/** Normalize outgoing, incoming, mute and cleanup without provider-specific UI logic. */
test('Telnyx uses opaque routing and waits for incoming consent', async function (): Promise<void> {
    const dom = new JSDOM('', { runScripts: 'outside-only' });
    const w = dom.window as FixtureWindow;
    let accepted = 0;
    let hungup = 0;
    let muted = false;
    w.call = {
        id: 'outgoing', state: 'new', direction: 'outbound', options: {},
        /** Track explicit media acceptance. */
        async answer(): Promise<void> { accepted += 1; },
        /** Track local disposal. */
        async hangup(): Promise<void> { hungup += 1; },
        /** Track microphone muting. */
        muteAudio(): void { muted = true; },
        /** Track microphone unmuting. */
        unmuteAudio(): void { muted = false; },
    };
    w.eval(code);
    const device = new w.TelnyxFixture.TelnyxDevice(JSON.stringify({ token: 'jwt', domain: 'test.sip.telnyx.com' }));
    try {
        await device.register();
        const outgoing = await device.connect('signed.reservation');
        assert.equal(w.sdk.outgoing.destinationNumber, 'sip:signed.reservation@test.sip.telnyx.com');
        assert.equal(w.sdk.outgoing.video, false);
        outgoing.mute(true);
        assert.equal(muted, true);
        outgoing.disconnect();
        let invitation: BrowserCall | undefined;
        /** Capture an incoming session without accepting media. */
        device.onIncoming((call: BrowserCall): void => { invitation = call; });
        w.call = { ...w.call, id: 'incoming', state: 'ringing', direction: 'inbound', options: {} };
        w.sdk.handlers.get('telnyx.notification')!({ type: 'callUpdate', call: w.call });
        assert(invitation);
        assert.equal(accepted, 0);
        assert(invitation.isPending());
        invitation.accept();
        assert.equal(accepted, 1);
        invitation.mute(false);
        assert.equal(muted, false);
        invitation.disconnect();
        device.updateToken(JSON.stringify({ token: 'renewed-jwt', domain: 'test.sip.telnyx.com' }));
        await Promise.resolve();
        assert.equal(w.sdk.renewed.creds.login_token, 'renewed-jwt');
        assert(hungup >= 2);
        device.destroy();
        assert.equal(w.document.querySelectorAll('audio').length, 0);
        assert.equal(w.sdk.closed, true);
    } finally { device.destroy(); dom.window.close(); }
});
