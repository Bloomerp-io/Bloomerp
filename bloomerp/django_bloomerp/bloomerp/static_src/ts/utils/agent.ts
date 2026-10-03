/**
 * One browser bridge per authenticated base page, started by the main bundle.
 * Components supply item handlers; a chat UI listens for `chat.event` events.
 * Live tab discovery and navigation use the Channels layer; chat remains a seam.
 */

export type AgentAction = 'get_current_page' | 'highlight_item' | 'click_item';

export type AgentCommand = {
    type: 'command';
    command_id: string;
    page_id: string;
    action: AgentAction | 'navigate';
    arguments: Record<string, unknown>;
};

/** Handle a page command and return a JSON-serializable result. */
export type AgentCommandHandler = (
    arguments_: Record<string, unknown>,
) => Promise<Record<string, unknown>>;

type PageState = {
    page_id: string;
    url: string;
    title: string;
    visible: boolean;
    focused: boolean;
};

/** Connect this tab to the backend without owning component or chat rendering. */
export default class BloomerpAgent extends EventTarget {
    readonly tabId: string = this.resolveTabId();
    private pageId: string = crypto.randomUUID();
    private socket: WebSocket | null = null;
    private heartbeat: number | null = null;
    private reconnectTimer: number | null = null;
    private reconnectDelay: number = 1000;
    private handlers = new Map<AgentAction, AgentCommandHandler>();
    private readonly opened = this.handleOpen.bind(this);
    private readonly received = this.handleMessage.bind(this);
    private readonly closed = this.handleClose.bind(this);
    private readonly stateChanged = this.reportState.bind(this);
    private readonly pageChanged = this.handlePageChange.bind(this);

    /** Open the authenticated tab socket; repeated calls are safe. */
    connect(): void {
        if (this.socket && this.socket.readyState < WebSocket.CLOSING) return;
        if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
        const url = new URL(`/ws/agents/${this.tabId}/`, window.location.origin);
        url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.socket = new WebSocket(url);
        this.socket.addEventListener('open', this.opened);
        this.socket.addEventListener('message', this.received);
        this.socket.addEventListener('close', this.closed);
    }

    /** Stop the connection and release tab listeners and timers. */
    disconnect(): void {
        this.stopReporting();
        if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
        this.socket?.close(1000, 'Browser bridge stopped');
        this.dispatchEvent(new Event('disconnected'));
        this.socket = null;
    }

    /** Install a component-aware handler for page discovery, highlight, or click. */
    registerHandler(action: AgentAction, handler: AgentCommandHandler): void {
        this.handlers.set(action, handler);
    }

    /** Remove a handler when its owning integration is torn down. */
    unregisterHandler(action: AgentAction): void {
        this.handlers.delete(action);
    }

    /** Report whether this tab can currently send chat commands. */
    get connected(): boolean {
        return this.socket?.readyState === WebSocket.OPEN;
    }

    /** Request cancellation of one run without closing the shared browser bridge. */
    cancelChat(runId: string): void {
        this.send({ type: 'chat.cancel', run_id: runId });
    }

    /** Request a bounded page of committed run events after reconnect or delivery loss. */
    replayChat(conversationId: string, runId: string, afterSequence: number = 0): void {
        this.send({type: 'chat.replay', conversation_id: conversationId, run_id: runId,
            after_sequence: afterSequence, limit: 100});
    }

    /** Request an owner-scoped page of conversation metadata. */
    listConversations(requestId: string, search: string, archived: boolean, cursor: string | null): void {
        this.send({type: 'chat.history', request_id: requestId, search, archived, cursor});
    }

    /** Load persisted messages and the active run's replay boundary. */
    loadConversation(requestId: string, conversationId: string, beforeSequence: number | null = null): void {
        this.send({type: 'chat.conversation', request_id: requestId, conversation_id: conversationId,
            before_sequence: beforeSequence});
    }

    /** Rename, archive or restore a conversation without changing execution state. */
    editConversation(requestId: string, conversationId: string, changes: {title?: string; archived?: boolean}): void {
        this.send({type: 'chat.edit_conversation', request_id: requestId, conversation_id: conversationId, ...changes});
    }

    /** Submit a decision for an exact server-persisted approval proposal. */
    decideApproval(approvalId: string, decision: 'approved' | 'rejected'): void {
        this.send({type: 'chat.approval', approval_id: approvalId, decision});
    }

    /** Send correlated chat input to the persisted agent controller. */
    sendChat(message: string, conversationId: string | null = null,
        clientMessageId: string = crypto.randomUUID(), attachments: string[] = []): void {
        this.send({
            type: 'chat.message',
            ...(attachments.length ? {attachments} : {}),
            message,
            conversation_id: conversationId,
            client_message_id: clientMessageId,
            page: this.getPageState(),
        });
    }

    /** Reuse this tab's identity across full page loads and manual reconnects. */
    private resolveTabId(): string {
        const key = 'bloomerp.agent.tab_id';
        const stored = sessionStorage.getItem(key);
        if (stored && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(stored)) {
            return stored;
        }
        const id = crypto.randomUUID();
        sessionStorage.setItem(key, id);
        return id;
    }

    /** Describe the current page without coupling the bridge to a DOM registry. */
    private getPageState(): PageState {
        return {
            page_id: this.pageId,
            url: window.location.href,
            title: document.title,
            visible: document.visibilityState === 'visible',
            focused: document.hasFocus(),
        };
    }

    /** Register page state and start presence updates after connection. */
    private handleOpen(event: Event): void {
        if (event.target !== this.socket) return;
        this.reconnectDelay = 1000;
        this.stopReporting();
        this.reportState();
        window.addEventListener('focus', this.stateChanged);
        window.addEventListener('blur', this.stateChanged);
        window.addEventListener('popstate', this.pageChanged);
        document.addEventListener('visibilitychange', this.stateChanged);
        document.addEventListener('htmx:afterSettle', this.pageChanged);
        this.heartbeat = window.setInterval(this.stateChanged, 30_000);
        this.dispatchEvent(new Event('connected'));
    }

    /** Reconnect after transient failure, stopping for authentication/origin rejection. */
    private handleClose(event: CloseEvent): void {
        if (event.target !== this.socket) return;
        this.stopReporting();
        this.dispatchEvent(new Event('disconnected'));
        if (![1000, 4401, 4403].includes(event.code)) {
            this.reconnectTimer = window.setTimeout(this.connect.bind(this), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30_000);
        }
    }

    /** Remove presence listeners and the heartbeat timer. */
    private stopReporting(): void {
        if (this.heartbeat !== null) window.clearInterval(this.heartbeat);
        this.heartbeat = null;
        window.removeEventListener('focus', this.stateChanged);
        window.removeEventListener('blur', this.stateChanged);
        window.removeEventListener('popstate', this.pageChanged);
        document.removeEventListener('visibilitychange', this.stateChanged);
        document.removeEventListener('htmx:afterSettle', this.pageChanged);
    }

    /** Invalidate old item references when navigation or HTMX changes the page. */
    private handlePageChange(): void {
        this.pageId = crypto.randomUUID();
        this.reportState();
    }

    /** Send page metadata as both registration and a presence heartbeat. */
    private reportState(): void {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.send({ type: 'tab.state', page: this.getPageState() });
        }
    }

    /** Decode backend messages and expose chat/connection events to the app. */
    private async handleMessage(event: MessageEvent<string>): Promise<void> {
        try {
            const message: unknown = JSON.parse(event.data);
            if (!isRecord(message) || typeof message.type !== 'string') {
                throw new Error('Invalid agent message');
            }
            if (message.type === 'command') {
                if (!isCommand(message)) throw new Error('Invalid browser command');
                await this.executeCommand(message);
            } else {
                this.dispatchEvent(new CustomEvent(message.type, { detail: message }));
            }
        } catch (error: unknown) {
            this.dispatchEvent(new CustomEvent('bridge.error', { detail: error }));
        }
    }

    /** Execute a command against this page and report a correlated result. */
    private async executeCommand(command: AgentCommand): Promise<void> {
        try {
            if (command.page_id !== this.pageId) throw new Error('Page has changed');
            if (command.action === 'navigate') {
                const value = command.arguments.url;
                if (typeof value !== 'string') throw new Error('URL is required');
                const url = new URL(value, window.location.href);
                if (url.origin !== window.location.origin) {
                    throw new Error('Navigation must stay within this instance');
                }
                // Acceptance precedes unloading; it does not confirm destination loading.
                this.sendResult(command.command_id, 'accepted', { url: url.href });
                window.location.assign(url.href);
                return;
            }
            const handler = this.handlers.get(command.action);
            if (!handler) throw new Error(`No handler for ${command.action}`);
            const result = await handler(command.arguments);
            this.sendResult(command.command_id, 'completed', result);
        } catch (error: unknown) {
            this.sendResult(command.command_id, 'failed', {
                message: error instanceof Error ? error.message : 'Command failed',
            });
        }
    }

    /** Send an acknowledgement that backend MCP calls can correlate. */
    private sendResult(
        commandId: string,
        status: 'accepted' | 'completed' | 'failed',
        result: Record<string, unknown>,
    ): void {
        this.send({ type: 'command.result', command_id: commandId, status, result });
    }

    /** Send a JSON message, failing clearly when the connection is unavailable. */
    private send(message: Record<string, unknown>): void {
        if (this.socket?.readyState !== WebSocket.OPEN) {
            throw new Error('Agent connection is unavailable');
        }
        this.socket.send(JSON.stringify(message));
    }
}

/** Narrow decoded JSON to a record before inspecting protocol fields. */
function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Validate the command envelope before allowing browser actions. */
function isCommand(value: Record<string, unknown>): value is AgentCommand {
    return value.type === 'command'
        && typeof value.command_id === 'string'
        && typeof value.page_id === 'string'
        && ['navigate', 'get_current_page', 'highlight_item', 'click_item'].includes(String(value.action))
        && isRecord(value.arguments);
}

let browserAgent: BloomerpAgent | null = null;

/** Initialize once on authenticated base pages; expose the bridge to future chat UI. */
export function initBrowserAgent(): void {
    if (document.body?.dataset.bloomerpAgent !== 'enabled' || browserAgent) return;
    browserAgent = new BloomerpAgent();
    Object.assign(window, { bloomerpAgent: browserAgent });
    window.addEventListener('pagehide', browserAgent.disconnect.bind(browserAgent));
    window.addEventListener('pageshow', browserAgent.connect.bind(browserAgent));
    browserAgent.connect();
}

/** Return the shared authenticated bridge without opening a component-owned socket. */
export function getBrowserAgent(): BloomerpAgent | null {
    return browserAgent;
}
