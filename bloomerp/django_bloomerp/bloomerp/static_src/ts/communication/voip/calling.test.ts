/** Verify the carrier adapter against an SDK double, independently of the UI. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type { CallingContext, CallingRegistration, IncomingCall, TransportState } from '../calling/definition';
import type { CarrierTransport } from './calling';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/carrier-test-entry.ts`;
const result = await build({ configFile: false, root, logLevel: 'silent', plugins: [{
    name: 'carrier-sdk-double', enforce: 'pre',
    /** Isolate only the carrier SDK factory; execute the actual adapter. */
    resolveId(id: string, importer?: string): string | null {
        if (id === entry) return entry;
        if (id === './registry' && importer?.endsWith('/voip/calling.ts')) return 'virtual:carrier.ts';
        return null;
    },
    /** Export an observable SDK boundary and the production adapter. */
    load(id: string): string | null {
        if (id === entry) return `export { CarrierTransport, registerCarrier } from '${root}/ts/communication/voip/calling';`;
        if (id !== 'virtual:carrier.ts') return null;
        return `
            /** Provide the SDK double configured by the current test. */
            export function createBrowserDevice(driver: string, token: string): object {
                window.selected = [driver, token];
                return window.device;
            }
        `;
    },
}], build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'CarrierFixture' } } });
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Locate the bundled adapter code. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const code = script.code;
interface AdapterWindow extends DOMWindow {
    selected: string[];
    device: object;
    CarrierFixture: { CarrierTransport: typeof CarrierTransport; registerCarrier(options: object, context: CallingContext): Promise<CallingRegistration> };
}

/** Carrier sessions reuse registrations and revoke them when token refresh loses access. */
test('outgoing and incoming carrier lifecycle stays behind the common contract', async function (): Promise<void> {
    const dom = new JSDOM('', { runScripts: 'outside-only' });
    const w = dom.window as AdapterWindow;
    let connectedId = '';
    let destroyed = 0;
    let accepted = 0;
    let rejected = 0;
    let muted = false;
    let pending = false;
    let revoked = false;
    let incomingHandler: (call: object) => void;
    let expiryHandler: () => Promise<void>;
    let invitation: IncomingCall;
    const callbacks = new Map<string, () => void>();
    const owned: CallingRegistration[] = [];
    const states: TransportState[] = [];
    const call = {
        /** Simulate carrier acceptance. */
        accept(): void { accepted += 1; pending = false; callbacks.get('accept')?.(); },
        /** Observe rejection without media acceptance. */
        reject(): void { rejected += 1; },
        /** Observe a local hangup. */
        disconnect(): void {},
        /** Record microphone control. */
        mute(value: boolean): void { muted = value; },
        /** Distinguish an unanswered invitation. */
        isPending(): boolean { return pending; },
        /** Record normalized SDK callbacks. */
        on(event: string, handler: () => void): void { callbacks.set(event, handler); },
    };
    w.device = {
        /** Register the authorized browser device. */
        async register(): Promise<void> {},
        /** Record registration disposal. */
        destroy(): void { destroyed += 1; },
        /** Receive a refreshed credential. */
        updateToken(_token: string): void {},
        /** Connect only the application's opaque reservation ID. */
        async connect(id: string): Promise<object> { connectedId = id; return call; },
        /** Register carrier invitation delivery. */
        onIncoming(handler: (incoming: object) => void): void { incomingHandler = handler; },
        /** Bind registration error handling. */
        onError(_handler: () => void): void {},
        /** Bind token expiry to authorization refresh. */
        onTokenExpiry(handler: () => Promise<void>): void { expiryHandler = handler; },
    };
    const context: CallingContext = {
        /** Return a provider-selected carrier driver or simulate revoked authorization. */
        async post<T>(_url: string): Promise<T> { if (revoked) throw new Error('revoked'); return { driver: 'alternate-carrier', token: 'short-token' } as T; },
        /** Record an invitation without accepting it. */
        incoming(value: IncomingCall): void { invitation = value; },
        /** Keep registration errors separate from SDK data. */
        registrationError(): void {},
        /** Own registrations for cleanup. */
        registrationCreated(value: CallingRegistration): void { owned.push(value); },
    };
    /** Capture transport-neutral session state. */
    function state(value: TransportState): void { states.push(value); }
    w.eval(code);
    try {
        const transport = new w.CarrierFixture.CarrierTransport(state, context);
        await transport.connect({ session_id: 'call', call_id: 'opaque-reservation', registration_id: 'account', token_url: '/token', driver: 'voip', media_mode: 'audio', join_url: '/join', end_url: '', token: '', url: '', can_video: 'false', can_end: 'false' });
        assert.equal(connectedId, 'opaque-reservation');
        assert.deepEqual(Array.from(w.selected), ['alternate-carrier', 'short-token']);
        callbacks.get('accept')!();
        assert.equal(states[0], 'connected');
        await transport.microphone(false);
        assert.equal(muted, true);
        await transport.disconnect();
        pending = true;
        incomingHandler!(call);
        assert.equal(accepted, 0);
        await invitation!.transport.disconnect();
        assert.equal(rejected, 1);
        revoked = true;
        await expiryHandler!();
        assert.equal(destroyed, 1);
    } finally { for (const registration of owned) registration.destroy(); dom.window.close(); }
});
