/** Verify base-page startup and browser navigation without opening a real socket. */
import assert from 'node:assert/strict';
import test from 'node:test';
import BloomerpAgent, { initBrowserAgent } from './agent.ts';

class BrowserLocation {
    origin: string = 'https://erp.test';
    protocol: string = 'https:';
    href: string = 'https://erp.test/example/';
    assigned: string | null = null;

    /** Record navigation while keeping this test document alive. */
    assign(url: string): void {
        this.assigned = url;
    }
}

class BrowserWindow extends EventTarget {
    location: BrowserLocation = new BrowserLocation();
    bloomerpAgent?: BloomerpAgent;

    /** Reserve a heartbeat timer without keeping the Node process alive. */
    setInterval(handler: TimerHandler, timeout: number): number {
        return 1;
    }

    /** Discard a heartbeat timer in this synchronous browser fixture. */
    clearInterval(timer: number): void {}

    /** Reserve a reconnect timer without opening another fixture connection. */
    setTimeout(handler: TimerHandler, timeout: number): number {
        return 2;
    }

    /** Discard a reconnect timer in this synchronous browser fixture. */
    clearTimeout(timer: number): void {}
}

class BrowserDocument extends EventTarget {
    title: string = 'Example';
    visibilityState: string = 'visible';
    body: { dataset: { bloomerpAgent?: string } } = { dataset: {} };

    /** Report this fixture tab as focused for discovery metadata. */
    hasFocus(): boolean {
        return true;
    }
}

class BrowserStorage {
    private values = new Map<string, string>();

    /** Retrieve tab identity across connection initialization. */
    getItem(key: string): string | null {
        return this.values.get(key) ?? null;
    }

    /** Persist the generated tab identity in this fixture. */
    setItem(key: string, value: string): void {
        this.values.set(key, value);
    }
}

class BrowserSocket extends EventTarget {
    static OPEN: number = 1;
    static CLOSING: number = 2;
    static sockets: BrowserSocket[] = [];
    readyState: number = 0;
    sent: Record<string, unknown>[] = [];
    url: string;

    /** Capture the websocket address selected by the browser bridge. */
    constructor(url: URL) {
        super();
        this.url = url.toString();
        BrowserSocket.sockets.push(this);
    }

    /** Record outgoing protocol messages as decoded JSON. */
    send(message: string): void {
        this.sent.push(JSON.parse(message));
    }

    /** Stop this fixture connection without scheduling asynchronous close events. */
    close(code: number, reason: string): void {
        this.readyState = 3;
    }

    /** Deliver a backend command through the bridge's real message listener. */
    receive(message: Record<string, unknown>): void {
        this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }));
    }
}

/** Exercise the actual startup, stale-page guard, same-origin guard, and navigation ack. */
function verifyBrowserBridge(): void {
    const browserWindow = new BrowserWindow();
    const browserDocument = new BrowserDocument();
    Object.assign(globalThis, {
        window: browserWindow, document: browserDocument,
        sessionStorage: new BrowserStorage(), WebSocket: BrowserSocket,
    });
    initBrowserAgent();
    assert.equal(BrowserSocket.sockets.length, 0, 'Anonymous pages do not connect');
    browserDocument.body.dataset.bloomerpAgent = 'enabled';
    initBrowserAgent();
    initBrowserAgent();
    assert.equal(BrowserSocket.sockets.length, 1, 'Startup opens exactly one connection');
    const socket = BrowserSocket.sockets[0];
    assert.match(socket.url, /^wss:\/\/erp\.test\/ws\/agents\/[0-9a-f-]+\/$/);
    socket.readyState = BrowserSocket.OPEN;
    socket.dispatchEvent(new Event('open'));
    const page = socket.sent[0].page as Record<string, unknown>;
    assert.equal(page.url, browserWindow.location.href);
    const command = {
        type: 'command', command_id: 'one', page_id: page.page_id,
        action: 'navigate', arguments: { url: 'https://other.test/' },
    };
    socket.receive(command);
    assert.equal(socket.sent.at(-1)?.status, 'failed');
    assert.equal(browserWindow.location.assigned, null);
    socket.receive({ ...command, page_id: 'stale', arguments: { url: '/customers/' } });
    assert.equal(socket.sent.at(-1)?.status, 'failed');
    assert.equal(browserWindow.location.assigned, null);
    socket.receive({ ...command, arguments: { url: '/customers/?q=one#card' } });
    assert.equal(socket.sent.at(-1)?.status, 'accepted');
    assert.equal(browserWindow.location.assigned, 'https://erp.test/customers/?q=one#card');
    browserDocument.dispatchEvent(new Event('htmx:afterSettle'));
    const nextPage = socket.sent.at(-1)?.page as Record<string, unknown>;
    assert.notEqual(nextPage.page_id, page.page_id);
    const bridge = browserWindow.bloomerpAgent!;
    assert.equal(bridge.connected, true);
    const messageId = crypto.randomUUID();
    bridge.sendChat('Chat request', null, messageId);
    assert.equal(socket.sent.at(-1)?.client_message_id, messageId);
    bridge.sendChat('', null, messageId, ['signed-file-selection']);
    assert.deepEqual(socket.sent.at(-1)?.attachments, ['signed-file-selection']);
    assert.equal(socket.sent.at(-1)?.message, '');
    bridge.cancelChat('sample-run');
    assert.deepEqual(socket.sent.at(-1), { type: 'chat.cancel', run_id: 'sample-run' });
    bridge.replayChat('conversation', 'run', 7);
    assert.deepEqual(socket.sent.at(-1), {type: 'chat.replay', conversation_id: 'conversation', run_id: 'run', after_sequence: 7, limit: 100});
    bridge.decideApproval('approval-id', 'approved');
    assert.deepEqual(socket.sent.at(-1), {type: 'chat.approval', approval_id: 'approval-id', decision: 'approved'});
    bridge.listConversations('request', 'title', false, null);
    assert.deepEqual(socket.sent.at(-1), {type: 'chat.history', request_id: 'request', search: 'title', archived: false, cursor: null});
    bridge.loadConversation('request', 'conversation', 20);
    assert.equal(socket.sent.at(-1)?.before_sequence, 20);
    bridge.editConversation('request', 'conversation', {archived: true});
    assert.equal(socket.sent.at(-1)?.type, 'chat.edit_conversation');
    bridge.sendChat('Real request');
    bridge.disconnect();
    assert.equal(bridge.connected, false);
    assert.throws(bridge.sendChat.bind(bridge, 'Offline'), /unavailable/);
}

test('authenticated base pages connect and execute guarded navigation', verifyBrowserBridge);
