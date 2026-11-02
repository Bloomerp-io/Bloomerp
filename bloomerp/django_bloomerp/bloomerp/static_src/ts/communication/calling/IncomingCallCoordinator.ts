/** Credential-free messages exchanged only between tabs of the same account and origin. */
export type CallTabMessage = { type: 'focus' } | { type: 'handled'; sessionId: string };

/** Elect one incoming-call owner while letting another tab take over after it closes. */
export default class IncomingCallCoordinator {
    private controller: AbortController | null = null;
    private release: (() => void) | null = null;
    private channel: BroadcastChannel | null = null;
    private timer: number | null = null;
    private readonly id = crypto.randomUUID();
    private enabled = false;
    public owner = false;

    /** Scope ownership and notifications to a single authenticated browser account. */
    public constructor(private readonly key: string, private readonly changed: (owner: boolean) => void, private readonly received: (message: CallTabMessage) => void) {
        if (typeof BroadcastChannel !== 'undefined') {
            this.channel = new BroadcastChannel(key);
            this.channel.addEventListener('message', this.onMessage);
        }
    }

    /** Wait for an exclusive browser lock without replacing a live calling tab. */
    public start(): void {
        if (this.enabled) return;
        this.enabled = true;
        if (navigator.locks) {
            this.controller = new AbortController();
            void navigator.locks.request(this.key, { signal: this.controller.signal }, this.hold).catch(this.lockFailed);
        } else {
            this.renewLease();
            this.timer = window.setInterval(this.renewLease, 2000);
        }
    }

    /** Hold ownership until availability is disabled or the owner shell is destroyed. */
    private hold = async (): Promise<void> => {
        if (!this.enabled) return;
        this.setOwner(true);
        /** Save the exclusive lock's release callback for explicit lifecycle cleanup. */
        const waitForRelease = (resolve: () => void): void => { this.release = resolve; };
        await new Promise<void>(waitForRelease);
        this.release = null;
    };

    /** Use a short renewable lease only on browsers without the Web Locks API. */
    private renewLease = (): void => {
        if (!this.enabled) return;
        try {
            const lease = JSON.parse(localStorage.getItem(`${this.key}.lease`) || 'null') as { id: string; until: number } | null;
            if (lease && lease.id !== this.id && lease.until > Date.now()) { this.setOwner(false); return; }
            localStorage.setItem(`${this.key}.lease`, JSON.stringify({ id: this.id, until: Date.now() + 7000 }));
            this.setOwner(true);
        } catch { this.setOwner(true); }
    };

    /** Notify the shell only when registration ownership changes. */
    private setOwner(owner: boolean): void {
        if (this.owner === owner) return;
        this.owner = owner;
        this.changed(owner);
    }

    /** Preserve incoming availability if a browser cannot supply an exclusive lock. */
    private lockFailed = (error: unknown): void => {
        if (!this.enabled || (error instanceof DOMException && error.name === 'AbortError')) return;
        this.renewLease();
        this.timer = window.setInterval(this.renewLease, 2000);
    };

    /** Broadcast invitation resolution without sending SDK objects or access tokens. */
    public send(message: CallTabMessage): void { this.channel?.postMessage(message); }

    /** Validate cross-tab messages before forwarding them to the calling shell. */
    private onMessage = (event: MessageEvent<unknown>): void => {
        const message = event.data as Partial<CallTabMessage> | null;
        if (message?.type === 'focus') this.received({ type: 'focus' });
        else if (message?.type === 'handled' && typeof message.sessionId === 'string') this.received({ type: 'handled', sessionId: message.sessionId });
    };

    /** Relinquish registration ownership while leaving the shared preference untouched. */
    public stop(): void {
        this.enabled = false;
        this.controller?.abort();
        this.controller = null;
        this.release?.();
        if (this.timer !== null) window.clearInterval(this.timer);
        this.timer = null;
        try {
            const lease = JSON.parse(localStorage.getItem(`${this.key}.lease`) || 'null') as { id: string } | null;
            if (lease?.id === this.id) localStorage.removeItem(`${this.key}.lease`);
        } catch { /* Storage is optional on browsers with an exclusive lock. */ }
        this.setOwner(false);
    }

    /** Close tab coordination after releasing any held lock or fallback lease. */
    public destroy(): void { this.stop(); this.channel?.close(); this.channel = null; }
}
