/** Exercise the production shell with a provider-selected transport double. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { JSDOM, type DOMWindow } from 'jsdom';
import type { OutputAsset, OutputChunk } from 'rollup';
import type Calling from './Calling';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/conference-test-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent',
    plugins: [{
        name: 'conference-fixture', enforce: 'pre',
        /** Replace only the external media adapter boundary. */
        resolveId(id: string): string | null {
            if (id === entry) return entry;
            return id.endsWith('calling/registry') ? 'virtual:media.ts' : null;
        },
        /** Bundle the real component and registry around an observable media double. */
        load(id: string): string | null {
            if (id === 'virtual:media.ts') return `
                /** Expose an incoming callback without hard-coding a carrier in the shell. */
                export async function registerCalling(options: object, context: object): Promise<object> {
                    window.callContext = context;
                    return { /** Observe registration cleanup. */ destroy(): void { window.calls.push(['registration-destroy']); } };
                }
                /** Record provider selection and media operations without hardware. */
                export function createBrowserCallTransport(driver: string, container: HTMLElement, onState: (state: string) => void): object {
                    window.calls.push(['driver', driver]);
                    return {
                        /** Report membership independently of camera publications. */
                        participants(): object[] { return window.roster || []; },
                        /** Report connection through the normalized callback. */
                        async connect(): Promise<void> { if (window.failConnect) throw new Error('offline'); onState('connected'); },
                        /** Observe hardware cleanup. */
                        async disconnect(): Promise<void> { window.calls.push(['disconnect']); },
                        /** Observe microphone consent. */
                        async microphone(value: boolean): Promise<void> { window.calls.push(['microphone', value]); await window.microphonePermission; },
                        /** Reflect browser-native sharing state. */
                        screenSharing(): boolean { return Boolean(window.sharing); },
                        /** Observe screen capture consent. */
                        async screenShare(value: boolean): Promise<void> { if (window.cancelScreen) throw new Error('Screen selection cancelled'); window.sharing = value; window.calls.push(['screen', value]); },
                        /** Observe camera consent. */
                        async camera(value: boolean): Promise<void> { window.calls.push(['camera', value]); await window.cameraPermission; },
                        /** Observe explicit audio playback. */
                        async playAudio(): Promise<void> { window.calls.push(['audio']); if (window.failPlayback) throw new Error('Audio playback blocked'); }
                    };
                }
            `;
            return id === entry ? `
                import Calling from '${root}/ts/components/communication/Calling';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('bloomerp:calling', Calling);
                export { initComponents, getComponent };
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'CallingFixture' } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Select the emitted test bundle. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;
const template = readFileSync(`${root}/../templates/components/communication/calling/controls.html`, 'utf8').replace(/{%.*?%}/g, '');
interface FixtureWindow extends DOMWindow {
    calls: unknown[][];
    failConnect: boolean;
    failPlayback: boolean;
    microphonePermission?: Promise<void>;
    cameraPermission?: Promise<void>;
    sharing: boolean;
    cancelScreen: boolean;
    roster: { id: string; displayName: string; avatar?: string; initials?: string; local?: boolean; video?: HTMLVideoElement; screenVideo?: HTMLVideoElement }[];
    callContext: { incoming(call: unknown): void };
    CallingFixture: { initComponents(element: HTMLElement): void; getComponent(element: HTMLElement): Calling };
}
interface Fixture { dom: JSDOM; w: FixtureWindow; shell: HTMLElement; requests: { url: string; body: string }[]; component: Calling; children: JSDOM[] }
const session = { session_id: 'session-1', join_url: '/join', end_url: '/end', media_mode: 'video', can_end: 'true' };

/** Instantiate real controls and CSRF-protected request behavior with deterministic responses. */
function fixture(video: boolean = true, sharing: boolean = false): Fixture {
    const dom = new JSDOM(`<body>${template}<button data-call-action="enable">Enable</button><div id="chat"><button data-call-action="start" data-start-url="/start" data-media-mode="video">Call</button></div></body>`, { runScripts: 'outside-only', url: 'https://app.example/' });
    const w = dom.window as FixtureWindow;
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser default result type required by jsdom. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, result?: XPathResult | null): XPathResult {
        return evaluate.call(this, context, type ?? 0, result ?? null);
    };
    w.calls = [];
    /** Model focusing the media owner for the screen chooser. */
    w.focus = function focus(): void {};
    /** Model a document-bound chooser and observable capture cleanup. */
    async function capture(origin: string): Promise<MediaStream> {
        w.calls.push(['capture', origin]);
        if (w.cancelScreen) throw new Error('Screen selection cancelled');
        const track = { /** Observe release of a selected display. */ stop(): void { w.calls.push(['screen-stop']); } };
        return { /** Return the selected display tracks. */ getTracks(): object[] { return [track]; } } as unknown as MediaStream;
    }
    Object.defineProperty(w.navigator, 'mediaDevices', { value: { /** Capture from the main application button. */ getDisplayMedia(): Promise<MediaStream> { return capture('owner'); } } });
    const children: JSDOM[] = [];
    /** Model independently closable presentation tabs without acquiring a second transport. */
    w.open = function open(): Window {
        const child = new JSDOM('<html><head></head><body></body></html>', { url: 'https://app.example/' });
        Object.defineProperty(child.window.navigator, 'mediaDevices', { value: { /** Capture from the presentation button. */ getDisplayMedia(): Promise<MediaStream> { return capture('child'); } } });
        Object.defineProperty(child.window.navigator, 'clipboard', { value: { /** Record copying from the focused call tab. */ async writeText(text: string): Promise<void> { w.calls.push(['copy', text]); } } });
        const originalClose = child.window.close.bind(child.window);
        Object.defineProperty(child.window, 'closed', { value: false, writable: true });
        /** Expose tab closure to the owner without unloading it. */
        child.window.close = function close(): void { Object.defineProperty(child.window, 'closed', { value: true }); originalClose(); };
        /** Avoid jsdom's unimplemented window focus. */
        child.window.focus = function focus(): void {};
        /** Simulate muted video playback without hardware. */
        child.window.HTMLMediaElement.prototype.play = async function play(): Promise<void> {};
        children.push(child);
        return child.window as unknown as Window;
    };
    const requests: Fixture['requests'] = [];
    /** Record application requests while leaving the real shell asynchronous. */
    w.fetch = async function fetch(input: URL | string, init: RequestInit): Promise<Response> {
        const url = new URL(String(input), 'https://app.example').pathname;
        requests.push({ url, body: String(init.body) });
        const data = url === '/waiting' ? { guests: [{ id: 'guest', name: '<Visitor>', url: '/admit/guest' }] } : url === '/registrations' ? { registrations: [{ id: 'line', driver: 'alternate-driver', token_url: '/token' }] } : url === '/join' ? { ...session, driver: 'alternate-driver', can_video: String(video), can_screen_share: String(video), share_url: sharing ? '/meeting/token/' : '', admissions_url: sharing ? '/waiting' : '', url: 'wss://media.example', token: 'private-token' } : session;
        return { ok: true, json: async function json(): Promise<object> { return data; } } as Response;
    } as typeof fetch;
    w.eval(scriptCode);
    w.CallingFixture.initComponents(w.document.body);
    const shell = w.document.querySelector<HTMLElement>('[bloomerp-component="bloomerp:calling"]')!;
    shell.dataset.registrationsUrl = '/registrations';
    return { dom, w, shell, requests, children, component: w.CallingFixture.getComponent(shell) };
}

/** Allow promise-based request and media transitions to complete. */
async function click(f: Fixture, action: string): Promise<void> {
    f.w.document.querySelector<HTMLButtonElement>(`[data-call-action="${action}"]`)!.click();
    await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
}

/** Deliver session state and invitation progress through the real notification listener. */
function notify(f: Fixture, status: string, invitationStatus?: string): void {
    f.w.document.dispatchEvent(new f.w.CustomEvent('im:call-changed', { detail: { ...session, status, invitation_status: invitationStatus } }));
}

/** Add the explicit join action rendered on a shared calendar or ad hoc meeting page. */
function addMeetingJoin(f: Fixture): void {
    const button = f.w.document.createElement('button');
    button.dataset.callAction = 'join';
    button.dataset.joinUrl = '/join';
    f.w.document.body.append(button);
}

/** Reproduce a notification arriving before the corresponding join response is processed. */
function notifyDuringJoin(f: Fixture, status: string, invitationStatus: string): void {
    const fetchResponse = f.w.fetch;
    /** Publish the socket event after server authorization but before returning credentials. */
    f.w.fetch = async function fetch(input: URL | string, init: RequestInit): Promise<Response> {
        const response = await fetchResponse(input, init);
        if (new URL(String(input), 'https://app.example').pathname === '/join') notify(f, status, invitationStatus);
        return response;
    } as typeof fetch;
}

/** A host acceptance notification must not turn a successful direct join into an ended call. */
test('direct meeting join survives acceptance arriving before its credentials', async function (): Promise<void> {
    const f = fixture();
    try {
        addMeetingJoin(f);
        notifyDuringJoin(f, 'ringing', 'accepted');
        await click(f, 'join');
        assert.equal(f.shell.dataset.callState, 'connected');
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="leave"]')!.hidden, false);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="end"]')!.hidden, false);
        assert.equal(f.children.length, 1);
        assert.equal(f.shell.querySelector('[data-call-error]')!.textContent, '');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Previously resolved invitations suppress ringing without blocking an explicitly authorized join. */
test('direct meeting join ignores earlier invitation resolution', async function (): Promise<void> {
    for (const status of ['accepted', 'declined', 'missed']) {
        const f = fixture();
        try {
            addMeetingJoin(f);
            notify(f, 'active', status);
            await click(f, 'join');
            assert.equal(f.shell.dataset.callState, 'connected', status);
            assert.equal(f.children.length, 1, status);
        } finally { f.component.destroy(); f.dom.window.close(); }
    }
});

/** A real terminal session notification must still win over an in-flight credential response. */
test('closed meeting notification prevents connecting with in-flight credentials', async function (): Promise<void> {
    for (const status of ['ended', 'cancelled', 'failed']) {
        const f = fixture();
        try {
            addMeetingJoin(f);
            notifyDuringJoin(f, status, 'accepted');
            await click(f, 'join');
            assert.match(f.shell.querySelector('[data-call-error]')!.textContent!, /This call has ended/);
            assert.equal(f.children.length, 0, status);
            assert.equal(f.w.calls.length, 0, status);
        } finally { f.component.destroy(); f.dom.window.close(); }
    }
});

/** Leaving locally must allow the host to reuse an open meeting's explicit join action. */
test('host can leave and rejoin after an accepted invitation notification', async function (): Promise<void> {
    const f = fixture();
    try {
        addMeetingJoin(f);
        await click(f, 'join');
        await click(f, 'leave');
        assert.equal(f.children[0].window.closed, true);
        notify(f, 'active', 'accepted');
        await click(f, 'join');
        assert.equal(f.shell.dataset.callState, 'connected');
        assert.equal(f.children.length, 2);
        assert.equal(f.requests.length, 2);
        assert.equal(f.requests[0].url, '/join');
        assert.equal(f.requests[1].url, '/join');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify provider dispatch, navigation survival and host termination. */
test('provider driver controls media; chat replacement preserves call; host can end', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        assert.deepEqual(f.requests.map(function url(request: { url: string }): string { return request.url; }), ['/start', '/join']);
        assert.ok(f.w.calls.some(function selected(call: unknown[]): boolean { return call[0] === 'driver' && call[1] === 'alternate-driver'; }));
        assert.ok(f.w.calls.some(function camera(call: unknown[]): boolean { return call[0] === 'camera' && call[1] === true; }));
        f.w.document.getElementById('chat')!.remove();
        assert.equal(f.w.calls.filter(function disconnected(call: unknown[]): boolean { return call[0] === 'disconnect'; }).length, 0);
        await click(f, 'microphone');
        assert.equal(f.shell.querySelector('[data-call-action="microphone"]')!.getAttribute('aria-pressed'), 'false');
        await click(f, 'end');
        assert.equal(f.requests.at(-1)!.url, '/end');
        assert.equal(f.children[0].window.closed, true);
        assert.ok(!f.shell.innerHTML.includes('private-token'));
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify incoming calls never capture media without acceptance. */
test('incoming invitation requires consent and dismiss makes no request', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'enable');
        f.requests.length = 0;
        notify(f, 'ringing');
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-panel]')!.hidden, false);
        assert.equal(f.w.calls.length, 0);
        await click(f, 'dismiss');
        assert.equal(f.requests.length, 0);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-panel]')!.hidden, true);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify media controls follow the authorized join response. */
test('audio-only capabilities hide camera and leaving does not end for everyone', async function (): Promise<void> {
    const f = fixture(false);
    try {
        await click(f, 'enable');
        f.requests.length = 0;
        notify(f, 'ringing');
        await click(f, 'answer');
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="camera"]')!.hidden, true);
        assert.equal(f.w.calls.some(function camera(call: unknown[]): boolean { return call[0] === 'camera'; }), false);
        await click(f, 'leave');
        assert.equal(f.children[0].window.closed, true);
        assert.equal(f.requests.length, 1);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Handled invitations must remain silent while allowing an explicit join of the open meeting. */
test('accepted invitation stops incoming ringing without closing the meeting', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'enable');
        notify(f, 'ringing', 'invited');
        assert.equal(f.shell.dataset.callState, 'ringing');
        notify(f, 'active', 'accepted');
        /** Allow the asynchronous invitation dismissal to update the controls. */
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
        assert.equal(f.shell.dataset.callState, 'idle');
        notify(f, 'active', 'invited');
        assert.equal(f.shell.dataset.callState, 'idle');
        assert.equal(f.children.length, 0);
        addMeetingJoin(f);
        await click(f, 'join');
        assert.equal(f.shell.dataset.callState, 'connected');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify a failed transport does not duplicate the application call. */
test('connection failure can retry the reserved call without starting another', async function (): Promise<void> {
    const f = fixture();
    try {
        f.w.failConnect = true;
        await click(f, 'start');
        f.w.failConnect = false;
        await click(f, 'answer');
        assert.deepEqual(f.requests.map(function url(request: { url: string }): string { return request.url; }), ['/start', '/join', '/join']);
        notify(f, 'ended');
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="leave"]')!.hidden, true);
    } finally { f.component.destroy(); f.dom.window.close(); }
});


/** Preserve actionable server errors and never join after a rejected start. */
test('existing call conflict explains how to join and clears starting status', async function (): Promise<void> {
    const f = fixture();
    try {
        /** Return the provider-neutral error response from the start endpoint. */
        f.w.fetch = async function fetch(): Promise<Response> {
            return {
                ok: false,
                headers: new Headers({ 'Content-Type': 'application/json' }),
                /** Provide an actionable error rather than an SDK exception. */
                json: async function json(): Promise<object> { return { error: 'A call is already open. Use Join call in the conversation.' }; },
            } as Response;
        };
        await click(f, 'start');
        assert.match(f.shell.querySelector('[data-call-error]')!.textContent!, /Use Join call/);
        assert.equal(f.shell.querySelector('[data-call-status]')!.textContent, 'Call not connected');
        assert.equal(f.w.calls.length, 0);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Build a normalized carrier invitation without placing SDK types in the shell. */
function offerIncoming(f: Fixture): { accepted: number; disconnected: number } {
    const observed = { accepted: 0, disconnected: 0 };
    f.w.callContext.incoming({
        credentials: { ...session, session_id: 'carrier-incoming', driver: 'alternate-driver', join_url: '', end_url: '', media_mode: 'audio', can_video: 'false', can_end: 'false' },
        transport: {
            /** Record explicit acceptance. */
            async connect(): Promise<void> { observed.accepted += 1; },
            /** Record rejection or local hangup. */
            async disconnect(): Promise<void> { observed.disconnected += 1; },
            /** Accept the normalized microphone operation. */
            async microphone(_enabled: boolean): Promise<void> {},
            /** Fail if unavailable camera controls ever trigger video. */
            async camera(_enabled: boolean): Promise<void> { throw new Error('Unexpected camera'); },
            /** Model SDK-owned audio playback. */
            async playAudio(): Promise<void> {},
        },
    });
    return observed;
}

/** Verify incoming carrier calls use the same consent, controls and cleanup as rooms. */
test('provider registrations offer incoming audio through the common controls', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'enable');
        const incoming = offerIncoming(f);
        assert.equal(incoming.accepted, 0);
        await click(f, 'answer');
        assert.equal(incoming.accepted, 1);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="camera"]')!.hidden, true);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="end"]')!.hidden, true);
        const busy = offerIncoming(f);
        assert.equal(busy.disconnected, 1);
        await click(f, 'leave');
        assert.equal(incoming.disconnected, 1);
        assert.equal(f.requests.filter(function joins(request: { url: string }): boolean { return request.url === '/join'; }).length, 0);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify declining an incoming carrier invitation never answers it. */
test('dismissing a driver invitation rejects it without accepting media', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'enable');
        const incoming = offerIncoming(f);
        await click(f, 'dismiss');
        assert.equal(incoming.accepted, 0);
        assert.equal(incoming.disconnected, 1);
    } finally { f.component.destroy(); f.dom.window.close(); }
});


/** Verify tab closure never affects the owner transport and reopening never rejoins. */
test('call tab closes and reopens while original tab keeps the transport', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        assert.equal(f.children.length, 1);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-media]')!.hidden, true);
        const stream = { id: 'owner-stream' } as MediaStream;
        const video = f.w.document.createElement('video');
        video.srcObject = stream;
        video.setAttribute('aria-label', 'Other participant');
        f.shell.querySelector('[data-call-media]')!.append(video);
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        const view = f.children[0].window.document;
        assert.equal(view.querySelector('video')!.srcObject, stream);
        assert.equal(view.querySelector('video')!.muted, true);
        assert.equal(view.body.innerHTML.includes('private-token'), false);
        assert.equal(view.querySelector('[data-call-action="camera"]')!.hasAttribute('hidden'), false);
        f.children[0].window.close();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(f.w.calls.filter(function disconnected(call: unknown[]): boolean { return call[0] === 'disconnect'; }).length, 0);
        await click(f, 'open');
        assert.equal(f.children.length, 2);
        assert.equal(f.requests.length, 2);
        assert.equal(f.w.calls.filter(function disconnected(call: unknown[]): boolean { return call[0] === 'disconnect'; }).length, 0);
        f.children[1].window.document.querySelector<HTMLButtonElement>('[data-call-action="microphone"]')!.click();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
        assert.equal(f.shell.querySelector('[data-call-action="microphone"]')!.getAttribute('aria-pressed'), 'false');
        f.children[1].window.document.querySelector<HTMLButtonElement>('[data-call-action="leave"]')!.click();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
        assert.equal(f.w.calls.filter(function disconnected(call: unknown[]): boolean { return call[0] === 'disconnect'; }).length, 1);
        assert.equal(f.requests.length, 2);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Verify delayed popup blocking never prevents an otherwise connected call. */
test('blocked delayed tabs have an inline fallback', async function (): Promise<void> {
    const f = fixture(false);
    try {
        /** Assert opening occurs after requests and microphone permission have settled. */
        f.w.open = function blocked(): null { assert.equal(f.requests.length, 2); assert.ok(f.w.calls.some(function microphone(call: unknown[]): boolean { return call[0] === 'microphone'; })); return null; };
        await click(f, 'start');
        assert.match(f.shell.querySelector('[data-call-error]')!.textContent!, /Allow pop-ups/);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-media]')!.hidden, false);
        assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="leave"]')!.hidden, false);
        await click(f, 'leave');
    } finally { f.component.destroy(); f.dom.window.close(); }
});


/** Verify owner teardown closes the companion tab and releases the transport. */
test('unloading the original page ends local participation and closes its call view', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        f.w.dispatchEvent(new f.w.Event('pagehide'));
        assert.equal(f.children[0].window.closed, true);
        assert.equal(f.w.calls.filter(function disconnected(call: unknown[]): boolean { return call[0] === 'disconnect'; }).length, 1);
    } finally { f.component.destroy(); f.dom.window.close(); }
});


/** Keep provider identity visible across camera toggles and remove departed participants. */
test('participant tiles reuse identities and swap avatars for camera video', async function (): Promise<void> {
    const f = fixture();
    try {
        f.w.roster = [{ id: 'alice', displayName: 'Alice Example', initials: 'AE', local: true }, { id: 'bob', displayName: 'Bob Example', avatar: '/media/bob.png', initials: 'BE' }];
        await click(f, 'start');
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        const doc = f.children[0].window.document;
        const tile = doc.querySelector<HTMLElement>('.call-participant')!;
        assert.equal(doc.querySelectorAll('.call-participant').length, 2);
        assert.equal(tile.querySelector('[data-participant-name]')!.textContent, 'Alice Example');
        assert.equal(tile.querySelector<HTMLElement>('[data-participant-avatar]')!.hidden, false);
        assert.equal(doc.querySelectorAll('img')[1].src, 'https://app.example/media/bob.png');
        const video = f.w.document.createElement('video');
        video.srcObject = { id: 'camera' } as MediaStream;
        f.w.roster[0].video = video;
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(doc.querySelector('.call-participant'), tile);
        assert.equal(tile.querySelector('video')!.srcObject, video.srcObject);
        assert.equal(tile.querySelector<HTMLElement>('[data-participant-avatar]')!.hidden, true);
        delete f.w.roster[0].video;
        f.w.roster.pop();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(tile.querySelector('video')!.srcObject, null);
        assert.equal(tile.querySelector<HTMLElement>('[data-participant-avatar]')!.hidden, false);
        assert.equal(doc.querySelectorAll('.call-participant').length, 1);
    } finally { f.component.destroy(); f.dom.window.close(); }
});


/** A remote host ending a call must not close another participant's presentation tab. */
test('remote termination leaves the participant call tab open with ended status', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        notify(f, 'ended');
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(f.children[0].window.closed, false);
        assert.equal(f.children[0].window.document.querySelector('[data-call-status]')!.textContent, 'Call ended');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Screen controls follow capabilities and browser-native capture state. */
test('screen sharing captures directly in the call tab and retains participant cameras', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        const child = f.children[0].window.document;
        const button = child.querySelector<HTMLButtonElement>('[data-call-action="screen"]')!;
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(button.hidden, false);
        button.click();
        assert.deepEqual(f.w.calls.filter((call: unknown[]): boolean => call[0] === 'capture').map((call: unknown[]): unknown => call[1]), ['child']);
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(f.w.sharing, true);
        assert.equal(button.getAttribute('aria-pressed'), 'true');
        const camera = f.w.document.createElement('video');
        const screen = f.w.document.createElement('video');
        camera.srcObject = {} as MediaStream;
        screen.srcObject = {} as MediaStream;
        f.w.roster = [{ id: 'alice', displayName: 'Alice', video: camera, screenVideo: screen }];
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        assert.equal(child.querySelectorAll('[data-screen]').length, 2);
        assert.equal(child.querySelector('[data-call-count]')!.textContent, '1');
        assert.equal(child.querySelector<HTMLVideoElement>('[data-screen="true"] video')!.srcObject, screen.srcObject);
        f.w.sharing = false;
        f.w.roster[0].screenVideo = undefined;
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 600); });
        assert.equal(button.getAttribute('aria-pressed'), 'false');
        assert.equal(child.querySelectorAll('[data-screen="true"]').length, 0);
        button.click();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        f.children[0].window.close();
        await click(f, 'open');
        assert.equal(f.w.calls.some((call: unknown[]): boolean => call[0] === 'disconnect'), false);
        assert.equal(f.requests.filter((request: { url: string }): boolean => request.url === '/join').length, 1);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Providers without screen capability never expose capture controls. */
test('screen sharing is hidden for unsupported calling providers', async function (): Promise<void> {
    const f = fixture(false);
    try {
        await click(f, 'start');
        assert.equal(f.shell.querySelector<HTMLButtonElement>('[data-call-action="screen"]')!.hidden, true);
        assert.equal(f.w.calls.some((call: unknown[]): boolean => call[0] === 'screen'), false);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Cancelling capture must preserve the active call and allow another attempt. */
test('cancelled screen chooser keeps the call connected', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        f.w.cancelScreen = true;
        await click(f, 'screen');
        assert.equal(f.w.calls.some((call: unknown[]): boolean => call[0] === 'disconnect'), false);
        assert.equal(f.shell.querySelector<HTMLButtonElement>('[data-call-action="leave"]')!.hidden, false);
        f.w.cancelScreen = false;
        await click(f, 'screen');
        assert.equal(f.w.sharing, true);
        f.children[0].window.close();
        await click(f, 'open');
        assert.equal(f.w.sharing, true);
        assert.equal(f.requests.filter((request: { url: string }): boolean => request.url === '/join').length, 1);
        await click(f, 'screen');
        assert.equal(f.w.sharing, false);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Late screen selections cannot publish into a call that ended while the picker was open. */
test('screen picker resolution after call termination releases capture', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        let resolveCapture!: (stream: MediaStream) => void;
        let stopped = false;
        f.children[0].window.navigator.mediaDevices.getDisplayMedia = function select(): Promise<MediaStream> {
            return new Promise<MediaStream>(function defer(resolve: (stream: MediaStream) => void): void { resolveCapture = resolve; });
        };
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        f.children[0].window.document.querySelector<HTMLButtonElement>('[data-call-action="screen"]')!.click();
        notify(f, 'ended');
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 20); });
        const track = { /** Observe release of the unused selected display. */ stop(): void { stopped = true; } };
        resolveCapture({ /** Supply a late capture result without hardware. */ getTracks(): object[] { return [track]; } } as unknown as MediaStream);
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 20); });
        assert.equal(stopped, true);
        assert.equal(f.w.calls.some((call: unknown[]): boolean => call[0] === 'screen'), false);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Host moderation and copying use the shared capabilities in the presentation tab. */
test('meeting controls copy links and admit guests without provider branches', async function (): Promise<void> {
    const f = fixture(true, true);
    try {
        await click(f, 'start');
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        const doc = f.children[0].window.document;
        const share = doc.querySelector<HTMLButtonElement>('[data-call-action="share"]')!;
        assert.equal(share.hidden, false);
        share.click();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 20); });
        assert.equal(f.w.calls.find((call: unknown[]): boolean => call[0] === 'copy')?.[1], 'https://app.example/meeting/token/');
        const waiting = doc.querySelector<HTMLElement>('[data-call-admissions]')!;
        assert.equal(waiting.querySelector('[data-guest-name]')!.textContent, '<Visitor>');
        assert.equal(waiting.querySelector('visitor'), null);
        waiting.querySelector<HTMLButtonElement>('[data-decision="admit"]')!.click();
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 20); });
        assert.equal(f.requests.find((request: { url: string }): boolean => request.url === '/admit/guest')?.body, 'decision=admit');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Resizing the owner panel preserves the active transport and full companion controls. */
test('owner controls minimize and reopen independently of the call tab', async function (): Promise<void> {
    const f = fixture();
    try {
        await click(f, 'start');
        const toggle = f.shell.querySelector<HTMLButtonElement>('[data-call-panel-toggle]')!;
        const panel = f.shell.querySelector<HTMLElement>('[data-call-panel]')!;
        const launcher = f.shell.querySelector<HTMLButtonElement>('[data-call-launcher]')!;
        const requestCount = f.requests.length;
        const operationCount = f.w.calls.length;
        toggle.click();
        assert.equal(panel.hidden, true);
        assert.equal(launcher.getAttribute('aria-expanded'), 'false');
        assert.equal(f.w.document.activeElement, launcher);
        await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 300); });
        const doc = f.children[0].window.document;
        assert.equal(doc.querySelector('[data-call-panel-toggle]'), null);
        assert.equal(doc.querySelector<HTMLButtonElement>('[data-call-action="camera"]')!.hidden, false);
        assert.equal(f.children[0].window.closed, false);
        launcher.click();
        assert.equal(panel.hidden, false);
        assert.equal(launcher.getAttribute('aria-expanded'), 'true');
        assert.equal(f.requests.length, requestCount);
        assert.equal(f.w.calls.length, operationCount);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

/** Keep the permission owner visible until acceptance or rejection settles capture. */
test('start, join and answer delay the call tab until media permissions settle', async function (): Promise<void> {
    for (const action of ['start', 'join', 'answer']) {
        for (const denied of [false, true]) {
            const f = fixture();
            // An autoplay rejection must not bypass the initial capture prompts.
            f.w.failPlayback = !denied;
            let allowMicrophone!: () => void;
            let settleCamera!: () => void;
            f.w.microphonePermission = new Promise<void>(function pending(resolve: () => void): void { allowMicrophone = resolve; });
            f.w.cameraPermission = new Promise<void>(function pending(resolve: () => void, reject: (error: Error) => void): void {
                /** Resolve the simulated browser prompt only when the test supplies consent. */
                settleCamera = (): void => { if (denied) reject(new f.w.Error('Camera permission denied')); else resolve(); };
            });
            try {
                if (action === 'answer') {
                    await click(f, 'enable');
                    notify(f, 'ringing');
                }
                if (action === 'join') addMeetingJoin(f);
                await click(f, action);
                assert.equal(f.children.length, 0);
                allowMicrophone();
                await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
                assert.equal(f.children.length, 0);
                settleCamera();
                await new Promise<void>(function settle(resolve: () => void): void { setTimeout(resolve, 0); });
                assert.equal(f.children.length, 1);
                assert.equal(f.shell.querySelector<HTMLElement>('[data-call-action="leave"]')!.hidden, false);
                if (denied) assert.match(f.shell.querySelector('[data-call-error]')!.textContent!, /Camera permission denied/);
                else assert.match(f.shell.querySelector('[data-call-error]')!.textContent!, /Audio playback blocked/);
            } finally { f.component.destroy(); f.dom.window.close(); }
        }
    }
});
