/** Carrier-neutral session controls consumed by the persistent phone component. */
export interface BrowserCall {
    /** Answer an incoming call. */
    accept(): void;
    /** Reject an unanswered incoming call. */
    reject(): void;
    /** End an established or outgoing call. */
    disconnect(): void;
    /** Set local microphone muting. */
    mute(muted: boolean): void;
    /** Indicate whether rejection is appropriate for this session. */
    isPending(): boolean;
    /** Subscribe to normalized session lifecycle events. */
    on(event: 'accept' | 'disconnect' | 'cancel' | 'reject' | 'error', callback: () => void): void;
}

/** Browser transport lifecycle implemented by each supported carrier SDK. */
export interface BrowserDevice {
    /** Establish incoming-call availability. */
    register(): Promise<void>;
    /** Dispose the registration and its resources. */
    destroy(): void;
    /** Replace short-lived browser credentials. */
    updateToken(token: string): void;
    /** Connect a server-authorized call reservation. */
    connect(callId: string): Promise<BrowserCall>;
    /** Deliver normalized incoming sessions. */
    onIncoming(callback: (call: BrowserCall) => void): void;
    /** Report transport failures without exposing SDK details. */
    onError(callback: () => void): void;
    /** Request refreshed credentials before expiration. */
    onTokenExpiry(callback: () => void): void;
}
