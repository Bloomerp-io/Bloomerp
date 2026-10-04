import htmx from 'htmx.org';
import ArtifactPicker, { type ArtifactChoice } from './ArtifactPicker';
import BaseComponent, { getComponent } from '../BaseComponent';
import BloomerpAgent, { getBrowserAgent, type ConversationApprovalRules } from '../../utils/agent';
import { parseAgentEditorState } from '../../utils/agentEditorState';
import { renderAgentMessage } from '../../utils/agentMarkdown';
import { updateAgentProgress, renderAgentProgress, type AgentProgressState } from '../../utils/agentProgress';
import '../../../styles/agentMarkdown.css';

type HistoryConversation = {id: string; title: string; status: string; updated_at: string; selected_agent_id?: string | null; run_status?: string; approval_rules?: ConversationApprovalRules};
type ConversationSnapshot = {
    conversation: HistoryConversation;
    messages: {id: string; role: string; status: string; content: Record<string, unknown>[]; artifacts?: {id: string; position: number}[]; sequence: number; created_at: string}[];
    approvals: (Record<string, unknown> & {id: string; run_id: string; created_at: string})[];
    before_sequence: number | null;
    run: {id: string; status: string; client_message_id: string; cursor: number; cancel_requested: boolean; progress?: Record<string, unknown> | null} | null;
};

/** Present streamed chat through the shared authenticated browser bridge. */
export default class AgentChat extends BaseComponent {
    private attachments: ArtifactChoice[] = [];
    private attachmentBusy = false;
    private approvalRules: ConversationApprovalRules = {default: 'writes', tools: {}};
    private approvalRequestId: string | null = null;
    private selectedAgentId: string | null = null;
    private agentsLoaded: boolean = false;
    private agentRequestId: string | null = null;
    private agentSelectionRequired: boolean = false;
    private availableAgents: {id: string; name: string}[] = [];
    private lifecycle: AbortController | null = null;
    private panel: HTMLElement | null = null;
    private input: HTMLTextAreaElement | null = null;
    private messages: HTMLElement | null = null;
    private previousFocus: HTMLElement | null = null;

    private bridge: BloomerpAgent | null = null;
    private conversationId: string | null = null;
    private clientMessageId: string | null = null;
    private runId: string | null = null;
    private response: HTMLElement | null = null;
    private cancellationRequested: boolean = false;
    private responseTimer: number | null = null;
    private markdownFrame: number | null = null;
    private progress: AgentProgressState = {sequence: 0, key: null, toolTitle: ''};
    private artifactCards = new Map<string, HTMLElement>();
    private approvalCards = new Map<string, {element: HTMLElement; sequence: number}>();
    private paused: boolean = false;
    private stateSequence: number = 0;
    private deltas = new Map<number, {messageId: string; text: string}>();
    private messageRows = new Map<string, {element: HTMLElement; baseline: string}>();
    private snapshotCursor: number = 0;
    private historyRows = new Map<string, HistoryConversation>();
    private historyRequestId: string | null = null;
    private historyCursor: string | null = null;
    private historyVisible: boolean = false;
    private historySearchTimer: number | null = null;
    private conversationArchived: boolean = false;
    private conversationTitle: string = '';
    private beforeMessageSequence: number | null = null;
    private selectionRequest: {id: string; conversationId: string; beforeSequence: number | null} | null = null;
    private editRequestId: string | null = null;
    private bufferedEvents: Record<string, unknown>[] = [];
    private unreadConversations = new Set<string>();
    private replaying: boolean = false;
    private replayCursor: number = 0;
    private terminalStatus: string | null = null;

    /** Bind the panel controls through the standard component lifecycle. */
    public override initialize(): void {
        if (!this.element) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.panel = this.element.querySelector('[data-agent-panel]');
        this.input = this.element.querySelector('[data-agent-input]');
        this.messages = this.element.querySelector('[data-agent-messages]');
        const signal = this.lifecycle.signal;
        this.element.addEventListener('click', this.onClick, { signal });
        this.element.addEventListener('submit', this.onSubmit, { signal });
        this.element.addEventListener('agent:attachments-changed', this.onAttachments, { signal });
        this.element.addEventListener('input', this.onInput, { signal });
        this.element.addEventListener('change', this.onHistoryFilter, { signal });
        this.element.addEventListener('change', this.onAgentChanged, { signal });
        this.element.addEventListener('change', this.onApprovalChanged, { signal });
        this.element.addEventListener('keydown', this.onKeyDown, { signal });
        document.addEventListener('keydown', this.onDocumentKeyDown, { signal });
        this.bridge = getBrowserAgent();
        this.bridge?.addEventListener('connected', this.onConnectionChanged, { signal });
        this.bridge?.addEventListener('disconnected', this.onConnectionChanged, { signal });
        this.bridge?.addEventListener('chat.event', this.onChatEvent, { signal });
        this.bridge?.addEventListener('protocol.error', this.onProtocolError, { signal });
        this.bridge?.addEventListener('bridge.error', this.onProtocolError, { signal });
        document.addEventListener('htmx:beforeCleanupElement', this.onCleanup, { signal });
        window.addEventListener('pagehide', this.saveEditorState, { signal });
        if (!this.restoreEditorState()) this.restoreActiveRun();
        this.onConnectionChanged();
    }

    /** Show conversation history without cancelling or detaching the selected run. */
    private showHistory(show: boolean): void {
        const history = this.element?.querySelector<HTMLElement>('[data-agent-history]');
        const scroll = this.element?.querySelector<HTMLElement>('[data-agent-scroll]');
        const footer = this.element?.querySelector<HTMLElement>('[data-agent-footer]');
        if (history) history.hidden = !show;
        if (scroll) scroll.hidden = show;
        if (footer) footer.hidden = show;
        this.historyVisible = show;
        this.saveEditorState();
        this.updateConversationTitle(this.conversationTitle);
        if (show) this.toggleRename(false);
        if (show) {
            this.loadHistory();
            this.element?.querySelector<HTMLInputElement>('[data-agent-search]')?.focus();
        }
    }

    /** Validate safe picker metadata received from the server. */
    private isAgentChoice(item: unknown): item is {id: string; name: string} {
        return !!item && typeof item === 'object' && typeof (item as {id?: unknown}).id === 'string' && typeof (item as {name?: unknown}).name === 'string';
    }

    /** Reconcile the picker with server-authorized model records and explain unavailable choices. */
    private renderAgentPicker(): void {
        const picker = this.element?.querySelector<HTMLSelectElement>('[data-agent-choice]');
        const empty = this.element?.querySelector<HTMLElement>('[data-agent-choice-empty]');
        if (!picker || !this.agentsLoaded) return;
        picker.replaceChildren();
        const unavailable = !!this.selectedAgentId && !this.availableAgents.some((model: {id: string; name: string}): boolean => model.id === this.selectedAgentId);
        if (!this.selectedAgentId && !this.agentSelectionRequired && this.availableAgents.length) this.selectedAgentId = this.availableAgents[0].id;
        if (unavailable || this.agentSelectionRequired) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = this.label('agent-unavailable');
            picker.append(option);
            this.selectedAgentId = null;
            this.agentSelectionRequired = true;
        }
        for (const model of this.availableAgents) {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            picker.append(option);
        }
        picker.value = this.selectedAgentId ?? '';
        picker.disabled = !this.availableAgents.length;
        if (empty) {
            empty.hidden = !!this.availableAgents.length && !this.agentSelectionRequired;
            empty.textContent = this.label(this.agentSelectionRequired && this.availableAgents.length ? 'agent-unavailable' : 'no-agents');
        }
        const welcome = this.element?.querySelector<HTMLElement>('[data-agent-welcome]');
        if (welcome && !this.availableAgents.length) welcome.hidden = true;
        this.syncComposer();
    }

    /** Save the next-run choice without changing a running or paused response. */
    private onAgentChanged = (event: Event): void => {
        if (!(event.target instanceof HTMLSelectElement) || !event.target.matches('[data-agent-choice]')) return;
        this.selectedAgentId = event.target.value || null;
        this.agentSelectionRequired = false;
        const empty = this.element?.querySelector<HTMLElement>('[data-agent-choice-empty]');
        if (empty) empty.hidden = true;
        if (this.conversationId && this.selectedAgentId && this.bridge?.connected) {
            this.agentRequestId = crypto.randomUUID();
            this.bridge.editConversation(this.agentRequestId, this.conversationId, {agent_id: this.selectedAgentId});
        }
        this.syncComposer();
    };

    /** Reflect the selected conversation's approval policy in the composer. */
    private renderApprovalPicker(): void {
        const picker = this.element?.querySelector<HTMLSelectElement>('[data-agent-approval-mode]');
        if (picker) {
            picker.value = this.approvalRules.default;
            picker.disabled = this.approvalRequestId !== null || !!this.selectionRequest || (!this.conversationId && this.clientMessageId !== null);
        }
    }

    /** Persist changes immediately for new tool calls, including during an active response. */
    private onApprovalChanged = (event: Event): void => {
        if (!(event.target instanceof HTMLSelectElement) || !event.target.matches('[data-agent-approval-mode]')) return;
        const mode = event.target.value;
        if (mode !== 'writes' && mode !== 'always' && mode !== 'never') return;
        if (this.conversationId && !this.bridge?.connected) {
            this.renderApprovalPicker();
            this.showError(this.label('disconnected'));
            return;
        }
        this.approvalRules = {...this.approvalRules, default: mode};
        if (this.conversationId && this.bridge?.connected) {
            this.approvalRequestId = crypto.randomUUID();
            this.bridge.editConversation(this.approvalRequestId, this.conversationId, {approval_rules: this.approvalRules});
        }
        this.renderApprovalPicker();
    };

    /** Fetch a bounded search page, discarding stale search responses by request identity. */
    private loadHistory(more: boolean = false): void {
        if (!this.bridge?.connected) { this.showError(this.label('disconnected')); return; }
        this.historyRequestId = crypto.randomUUID();
        if (!more) {
            this.historyRows.clear();
            this.historyCursor = null;
        }
        const search = this.element?.querySelector<HTMLInputElement>('[data-agent-search]')?.value ?? '';
        const archived = this.element?.querySelector<HTMLInputElement>('[data-agent-archived]')?.checked ?? false;
        const status = this.element?.querySelector<HTMLElement>('[data-agent-history-status]');
        if (status) status.textContent = this.label('history-loading');
        this.bridge.listConversations(this.historyRequestId, search, archived, more ? this.historyCursor : null);
    }

    /** Reload history after changing the archived filter. */
    private onHistoryFilter = (event: Event): void => {
        if (event.target instanceof Element && event.target.matches('[data-agent-archived]')) this.loadHistory();
    };

    /** Group a conversation date using the browser's local calendar. */
    private historyGroup(date: Date): string {
        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(today.getDate() - 1);
        if (date.toDateString() === today.toDateString()) return this.label('today');
        if (date.toDateString() === yesterday.toDateString()) return this.label('yesterday');
        return this.label('earlier');
    }

    /** Render owned titles as text and expose active/unread state without HTML interpolation. */
    private renderHistory(): void {
        const list = this.element?.querySelector<HTMLElement>('[data-agent-history-list]');
        if (!list) return;
        list.replaceChildren();
        let previousGroup = '';
        for (const conversation of this.historyRows.values()) {
            const date = new Date(conversation.updated_at);
            const group = this.historyGroup(date);
            if (group !== previousGroup) {
                const heading = document.createElement('h4');
                heading.className = 'pb-1 pt-4 text-xs font-medium text-gray-400';
                heading.textContent = group;
                list.append(heading);
                previousGroup = group;
            }
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.agentAction = 'select-conversation';
            button.dataset.conversationId = conversation.id;
            button.className = 'block w-full rounded-lg px-3 py-2 text-left hover:bg-primary-50 dark:hover:bg-zinc-800';
            button.setAttribute('aria-current', String(conversation.id === this.conversationId));
            const title = document.createElement('span');
            title.className = 'block truncate text-sm font-medium';
            title.textContent = conversation.title;
            const meta = document.createElement('span');
            meta.className = 'block text-xs text-gray-500';
            const active = ['queued', 'running', 'waiting'].includes(conversation.run_status ?? '');
            meta.textContent = active ? this.label(conversation.run_status!) : date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
            if (this.unreadConversations.has(conversation.id)) meta.textContent += ` · ${this.label('unread')}`;
            button.append(title, meta);
            list.append(button);
        }
        const status = this.element?.querySelector<HTMLElement>('[data-agent-history-status]');
        if (status) status.textContent = this.historyRows.size ? '' : this.label('history-empty');
        const more = this.element?.querySelector<HTMLButtonElement>('[data-agent-action="history-more"]');
        if (more) more.hidden = !this.historyCursor;
    }

    /** Detach only presentation state; server-side runs continue independently. */
    private detachConversation(): void {
        this.cancelMarkdownFrame();
        this.setProgress(null);
        this.progress.sequence = 0;
        if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
        this.responseTimer = null;
        this.selectionRequest = null;
        this.bufferedEvents = [];
        this.clientMessageId = null;
        this.runId = null;
        this.response = null;
        this.replaying = false;
        this.terminalStatus = null;
        this.cancellationRequested = false;
        this.paused = false;
        this.stateSequence = 0;
        this.snapshotCursor = 0;
        this.replayCursor = 0;
        this.deltas.clear();
        this.messageRows.clear();
        this.approvalCards.clear();
        this.artifactCards.clear();
    }

    /** Select a persisted transcript; buffer live events until its snapshot arrives. */
    private selectConversation(id: string, beforeSequence: number | null = null, preserveComposer: boolean = false): void {
        if (!this.bridge?.connected || !this.isUuid(id)) return;
        if (beforeSequence === null) {
            if (!preserveComposer) this.clearAttachments();
            this.detachConversation();
            this.conversationId = id;
            this.messages?.replaceChildren();
            this.showHistory(false);
            this.showError('');
            if (this.input && !preserveComposer) this.input.value = '';
            const welcome = this.element?.querySelector<HTMLElement>('[data-agent-welcome]');
            if (welcome) welcome.hidden = true;
        }
        const requestId = crypto.randomUUID();
        this.selectionRequest = {id: requestId, conversationId: id, beforeSequence};
        this.bridge.loadConversation(requestId, id, beforeSequence);
        this.syncComposer();
    }

    /** Apply owner-scoped history responses before handling live run events. */
    private handleHistoryEvent(message: Record<string, unknown>): boolean {
        const action = String(message.action ?? '');
        if (!['chat.history', 'chat.conversation', 'chat.edit_conversation'].includes(action)) return false;
        const failed = ['failed', 'forbidden', 'unavailable'].includes(String(message.status));
        if (action === 'chat.history' && message.request_id === this.historyRequestId) {
            if (failed) this.showError(String(message.message ?? this.label('failed')));
            else {
                for (const row of message.conversations as HistoryConversation[] ?? []) this.historyRows.set(row.id, row);
                this.historyCursor = typeof message.cursor === 'string' ? message.cursor : null;
                this.renderHistory();
            }
        }
        if (action === 'chat.conversation' && message.request_id === this.selectionRequest?.id) {
            const selection = this.selectionRequest!;
            this.selectionRequest = null;
            if (failed) { this.showError(String(message.message ?? this.label('failed'))); this.syncComposer(); }
            else this.renderTranscript(message as unknown as ConversationSnapshot, selection.beforeSequence !== null);
        }
        if (action === 'chat.edit_conversation' && message.request_id === this.editRequestId) {
            this.editRequestId = null;
            if (failed) this.showError(String(message.message ?? this.label('failed')));
            else {
                const conversation = message.conversation as HistoryConversation;
                if (conversation.id === this.conversationId) {
                    this.conversationArchived = conversation.status === 'archived';
                    this.updateConversationTitle(conversation.title);
                    this.toggleRename(false);
                    this.syncComposer();
                }
                if (this.historyVisible) this.loadHistory();
            }
        }
        return true;
    }

    /** Restore persisted messages and approval cards, then replay only events newer than the snapshot. */
    private renderTranscript(snapshot: ConversationSnapshot, older: boolean): void {
        const scroll = this.element?.querySelector<HTMLElement>('[data-agent-scroll]');
        const height = scroll?.scrollHeight ?? 0;
        const existing = older ? [...this.messages?.children ?? []] : [];
        this.approvalRules = snapshot.conversation.approval_rules ?? {default: 'writes', tools: {}};
        this.approvalRequestId = null;
        this.renderApprovalPicker();
        this.selectedAgentId = snapshot.conversation.selected_agent_id ?? null;
        this.agentSelectionRequired = false;
        this.renderAgentPicker();
        this.conversationArchived = snapshot.conversation.status === 'archived';
        this.updateConversationTitle(snapshot.conversation.title);
        for (const message of snapshot.messages) {
            if (this.messageRows.has(message.id)) continue;
            const content = message.content.filter(this.isTextBlock).map(this.blockText).join('\n\n');
            const text = content ? this.appendMessage(content, message.role === 'user') : null;
            for (const artifact of message.artifacts ?? []) {
                this.renderArtifact(artifact.id, message.created_at);
            }
            if (text) {
                text.parentElement!.dataset.createdAt = message.created_at;
                text.parentElement!.dataset.messageId = message.id;
                this.messageRows.set(message.id, {element: text, baseline: content});
                if (message.status === 'interrupted') text.setAttribute('aria-label', this.label('interrupted'));
            }
        }
        for (const approval of snapshot.approvals) {
            this.renderApproval(approval, snapshot.run?.id === approval.run_id ? snapshot.run.cursor : 0);
            const card = this.approvalCards.get(approval.id)?.element;
            if (card) card.dataset.createdAt = approval.created_at;
        }
        if (this.messages) {
            const rows = [...this.messages.children] as HTMLElement[];
            rows.sort(this.compareCreatedAt);
            this.messages.replaceChildren(...rows);
        }
        this.beforeMessageSequence = snapshot.before_sequence;
        const more = this.element?.querySelector<HTMLButtonElement>('[data-agent-action="older"]');
        if (more) more.hidden = this.beforeMessageSequence === null;
        if (!older) {
            const active = snapshot.run && ['queued', 'running', 'waiting'].includes(snapshot.run.status);
            if (active && snapshot.run) {
                this.runId = snapshot.run.id;
                this.clientMessageId = snapshot.run.client_message_id;
                this.snapshotCursor = snapshot.run.cursor;
                this.replayCursor = snapshot.run.cursor;
                this.stateSequence = snapshot.run.cursor;
                this.paused = snapshot.run.status === 'waiting';
                this.progress = {sequence: 0, key: this.paused ? 'paused' : 'waiting', toolTitle: ''};
                if (snapshot.run.progress) this.progress = updateAgentProgress(this.progress, snapshot.run.progress);
                this.displayProgress();
                this.cancellationRequested = snapshot.run.cancel_requested;
                this.setStatus(this.cancellationRequested ? 'stopping' : this.paused ? 'waiting' : 'responding');
                this.saveActiveRun();
                this.requestReplay();
            } else {
                this.clearSavedRun();
                this.setStatus('ready');
            }
            this.unreadConversations.delete(snapshot.conversation.id);
            this.updateUnreadBadge();
            const events = this.bufferedEvents;
            this.bufferedEvents = [];
            for (const event of events) this.receiveChatMessage(event);
            this.scrollToLatest();
        } else if (scroll && existing.length) scroll.scrollTop += scroll.scrollHeight - height;
        this.syncComposer();
    }

    /** Narrow transcript blocks to visible text; rich artifacts remain separate work. */
    private isTextBlock(block: Record<string, unknown>): block is Record<string, unknown> & {text: string} {
        return block.type === 'text' && typeof block.text === 'string';
    }

    /** Extract persisted visible text without interpreting HTML. */
    private blockText(block: Record<string, unknown> & {text: string}): string { return block.text; }

    /** Keep text and approval records ordered by their persisted creation time. */
    private compareCreatedAt(left: HTMLElement, right: HTMLElement): number {
        return (left.dataset.createdAt ?? '').localeCompare(right.dataset.createdAt ?? '');
    }

    /** Show or hide the inline rename form rather than opening a browser prompt. */
    private toggleRename(show: boolean): void {
        const form = this.element?.querySelector<HTMLFormElement>('[data-agent-rename-form]');
        const input = this.element?.querySelector<HTMLInputElement>('[data-agent-name]');
        if (form) form.hidden = !show;
        if (show && input) { input.value = this.conversationTitle; input.focus(); input.select(); }
    }

    /** Submit reversible metadata changes for the selected conversation. */
    private editConversation(changes: {title?: string; archived?: boolean}): void {
        if (!this.conversationId || !this.bridge?.connected) return;
        this.editRequestId = crypto.randomUUID();
        this.bridge.editConversation(this.editRequestId, this.conversationId, changes);
    }

    /** Update title and archive controls from authoritative conversation metadata. */
    private updateConversationTitle(title: string): void {
        this.conversationTitle = title;
        const label = this.element?.querySelector<HTMLElement>('[data-agent-title]');
        if (label) { label.textContent = title; label.title = title; }
        const tools = this.element?.querySelector<HTMLElement>('[data-agent-conversation-tools]');
        if (tools) tools.hidden = !this.conversationId || this.historyVisible;
        const archive = this.element?.querySelector<HTMLElement>('[data-agent-action="archive"]');
        const restore = this.element?.querySelector<HTMLElement>('[data-agent-action="restore"]');
        if (archive) archive.hidden = this.conversationArchived;
        if (restore) restore.hidden = !this.conversationArchived;
        const notice = this.element?.querySelector<HTMLElement>('[data-agent-archived-notice]');
        if (notice) notice.hidden = !this.conversationArchived;
    }

    /** Expose recoverable history/metadata errors without replacing the conversation. */
    private showError(message: string): void {
        const error = this.element?.querySelector<HTMLElement>('[data-agent-error]');
        if (error) { error.textContent = message; error.hidden = !message; }
    }

    /** Indicate background activity while keeping all off-screen runs independent. */
    private updateUnreadBadge(): void {
        const badge = this.element?.querySelector<HTMLElement>('[data-agent-unread]');
        if (badge) badge.hidden = !this.unreadConversations.size;
    }

    /** Scope the active-run pointer to this authenticated account and browser tab. */
    private storageKey(): string {
        return `bloomerp.agent.active.${this.element?.getAttribute('data-agent-user') ?? ''}`;
    }

    /** Save the selected chat and unsent editor state independently of run completion. */
    private saveEditorState = (): void => {
        try {
            sessionStorage.setItem(`${this.storageKey()}.editor`, JSON.stringify({
                conversationId: this.conversationId,
                draft: this.input?.value ?? '',
                attachments: this.attachments,
                open: this.panel ? !this.panel.hidden : false,
                historyVisible: this.historyVisible,
            }));
        } catch { /* Storage can be unavailable without disabling the editor. */ }
    };

    /** Restore drafts and panel visibility, then fetch the selected transcript on connection. */
    private restoreEditorState(): boolean {
        try {
            const saved = parseAgentEditorState(sessionStorage.getItem(`${this.storageKey()}.editor`));
            if (!saved) return false;
            this.conversationId = saved.conversationId;
            if (this.input) this.input.value = saved.draft;
            this.attachments = saved.attachments;
            const form = this.element?.querySelector<HTMLElement>('[data-artifact-search-url]');
            const picker = form ? getComponent(form) : null;
            if (picker instanceof ArtifactPicker) picker.restoreSelection(saved.attachments);
            if (saved.open) this.open();
            this.historyVisible = saved.historyVisible;
            return true;
        } catch { return false; }
    }

    /** Keep only run identifiers across tool-triggered full-page navigation. */
    private saveActiveRun(): void {
        this.saveEditorState();
        try {
            sessionStorage.setItem(this.storageKey(), JSON.stringify({runId: this.runId,
                conversationId: this.conversationId, clientMessageId: this.clientMessageId}));
        } catch { /* Chat still works when browser storage is disabled. */ }
    }

    /** Reattach to durable events after navigation without repeating user input or tools. */
    private restoreActiveRun(): void {
        try {
            const saved = JSON.parse(sessionStorage.getItem(this.storageKey()) ?? 'null');
            if (!saved || ![saved.runId, saved.conversationId, saved.clientMessageId].every(this.isUuid)) return;
            this.runId = saved.runId;
            this.conversationId = saved.conversationId;
            this.clientMessageId = saved.clientMessageId;
            this.open();
        } catch { this.clearSavedRun(); }
    }

    /** Validate stored identifiers before requesting an owner-authorized replay. */
    private isUuid(value: unknown): value is string {
        return typeof value === 'string' && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
    }

    /** Forget completed or explicitly reset work without deleting persisted history. */
    private clearSavedRun(): void {
        try { sessionStorage.removeItem(this.storageKey()); } catch { /* Storage is optional. */ }
    }

    /** Open the nonmodal assistant and focus its composer. */
    private open(): void {
        if (!this.panel) return;
        this.previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        this.panel.hidden = false;
        const launcher = this.element?.querySelector<HTMLElement>('[data-agent-action="open"]');
        if (launcher) {
            launcher.hidden = true;
            launcher.setAttribute('aria-expanded', 'true');
        }
        this.input?.focus();
        this.saveEditorState();
    }

    /** Close the assistant without discarding the current conversation. */
    private close(): void {
        if (!this.panel) return;
        this.panel.hidden = true;
        const launcher = this.element?.querySelector<HTMLElement>('[data-agent-action="open"]');
        if (launcher) {
            launcher.hidden = false;
            launcher.setAttribute('aria-expanded', 'false');
        }
        this.previousFocus?.focus();
        this.saveEditorState();
    }

    /** Clear the draft transcript and restore the suggested prompts. */
    private reset(): void {
        this.detachConversation();
        this.clearSavedRun();
        this.conversationId = null;
        this.approvalRules = {default: 'writes', tools: {}};
        this.approvalRequestId = null;
        this.renderApprovalPicker();
        this.conversationArchived = false;
        this.beforeMessageSequence = null;
        this.updateConversationTitle('');
        this.showHistory(false);
        this.toggleRename(false);
        this.showError('');
        const older = this.element?.querySelector<HTMLElement>('[data-agent-action="older"]');
        if (older) older.hidden = true;
        this.deltas.clear();
        this.snapshotCursor = 0;
        this.messageRows.clear();
        this.approvalCards.clear();
        this.artifactCards.clear();
        this.paused = false;
        this.stateSequence = 0;
        this.clearAttachments();
        this.messages?.replaceChildren();
        const welcome = this.element?.querySelector<HTMLElement>('[data-agent-welcome]');
        if (welcome) welcome.hidden = false;
        if (this.input) this.input.value = '';
        this.setStatus(this.bridge?.connected ? 'ready' : 'disconnected');
        this.syncComposer();
        this.input?.focus();
    }

    /** Handle panel actions and suggested chat prompts. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target instanceof Element ? event.target.closest<HTMLElement>('button') : null;
        if (!target) return;
        const action = target.dataset.agentAction;
        if (action === 'approve' || action === 'reject') {
            const id = target.dataset.approvalId;
            if (id && this.bridge?.connected) {
                try {
                    this.bridge.decideApproval(id, action === 'approve' ? 'approved' : 'rejected');
                    for (const button of this.approvalCards.get(id)?.element.querySelectorAll('button') ?? []) button.disabled = true;
                } catch { this.setStatus('disconnected'); }
            }
            return;
        }
        if (action === 'history') { this.showHistory(true); return; }
        if (action === 'history-back') { this.showHistory(false); return; }
        if (action === 'history-more') { this.loadHistory(true); return; }
        if (action === 'select-conversation' && target.dataset.conversationId) { this.selectConversation(target.dataset.conversationId); return; }
        if (action === 'older' && this.conversationId && this.beforeMessageSequence && !this.selectionRequest) { this.selectConversation(this.conversationId, this.beforeMessageSequence); return; }
        if (action === 'rename') { this.toggleRename(true); return; }
        if (action === 'cancel-rename') { this.toggleRename(false); return; }
        if (action === 'archive' || action === 'restore') { this.editConversation({archived: action === 'archive'}); return; }
        if (action === 'open') this.open();
        else if (action === 'close') this.close();
        else if (action === 'reset') this.reset();
        else if (action === 'stop') this.stop();
        else if (target.dataset.agentPrompt) {
            this.submit(target.innerText.trim());
            this.input?.focus();
        }
    };

    /** Submit the composer without navigating or replacing the page. */
    private onSubmit = (event: SubmitEvent): void => {
        event.preventDefault();
        if (event.target instanceof Element && event.target.matches('[data-agent-rename-form]')) {
            const title = this.element?.querySelector<HTMLInputElement>('[data-agent-name]')?.value.trim();
            if (title) this.editConversation({title});
            return;
        }
        this.submit(this.input?.value.trim() ?? '');
    };

    /** Send one correlated message and retain the draft if transport fails. */
    private submit(content: string): void {
        if (!this.selectedAgentId || (!content && !this.attachments.length) || this.attachmentBusy || this.clientMessageId || this.selectionRequest || this.conversationArchived || !this.bridge?.connected) return;
        const messageId = crypto.randomUUID();
        try {
            this.bridge.sendChat(content, this.conversationId, messageId, this.attachments.map(this.attachmentToken), this.selectedAgentId, this.conversationId ? undefined : this.approvalRules);
        } catch {
            this.setStatus('disconnected');
            return;
        }
        this.deltas.clear();
        this.snapshotCursor = 0;
        this.messageRows.clear();
        this.approvalCards.clear();
        this.artifactCards.clear();
        this.paused = false;
        this.stateSequence = 0;
        this.replayCursor = 0;
        this.terminalStatus = null;
        this.replaying = false;
        this.clientMessageId = messageId;
        this.runId = null;
        this.cancellationRequested = false;
        if (!this.conversationId) this.conversationTitle = content.slice(0, 255) || this.attachments[0]?.title || '';
        if (content) this.appendMessage(content, true);
        this.response = this.appendMessage('', false);
        this.progress = {sequence: 0, key: 'waiting', toolTitle: ''};
        this.displayProgress();
        this.showThinking();
        if (this.input) this.input.value = '';
        this.setStatus('responding');
        this.watchResponse();
        this.syncComposer();
        this.scrollToLatest();
        this.input?.focus();
    }

    /** Queue Stop until acceptance provides a run ID, then send cancellation. */
    private stop(): void {
        if (!this.clientMessageId || this.cancellationRequested) return;
        this.cancellationRequested = true;
        this.setStatus('stopping');
        this.sendCancellation();
        this.syncComposer();
    }

    /** Cancel the accepted run while preserving the shared browser connection. */
    private sendCancellation(): void {
        if (!this.runId) return;
        try {
            this.bridge?.cancelChat(this.runId);
        } catch {
            this.finish('interrupted');
        }
    }

    /** Apply only events belonging to this component's current submission. */
    private onChatEvent = (event: Event): void => {
        const data: unknown = (event as CustomEvent<unknown>).detail;
        if (!data || typeof data !== 'object' || Array.isArray(data)) return;
        this.receiveChatMessage(data as Record<string, unknown>);
    };

    /** Route history replies and selected-run events without consuming another conversation's output. */
    private receiveChatMessage(message: Record<string, unknown>): void {
        if (message.action === 'chat.agents' && Array.isArray(message.agents)) {
            this.agentsLoaded = true;
            this.availableAgents = message.agents.filter(this.isAgentChoice);
            this.renderAgentPicker();
            return;
        }
        if (message.action === 'chat.edit_conversation' && message.request_id === this.approvalRequestId) {
            this.approvalRequestId = null;
            if (message.status !== 'updated') {
                this.showError(String(message.message ?? this.label('failed')));
                if (this.conversationId && this.bridge?.connected) this.selectConversation(this.conversationId, null, true);
            } else {
                const conversation = message.conversation as HistoryConversation;
                if (conversation.id === this.conversationId && conversation.approval_rules) this.approvalRules = conversation.approval_rules;
            }
            this.renderApprovalPicker();
            return;
        }
        if (message.action === 'chat.edit_conversation' && message.request_id === this.agentRequestId) {
            this.agentRequestId = null;
            if (message.status !== 'updated') {
                this.showError(String(message.message ?? this.label('agent-unavailable')));
                if (this.bridge?.connected) this.bridge.listAgents();
            }
            return;
        }
        if (message.action === 'chat.message' && message.status === 'forbidden') {
            this.showError(String(message.message ?? this.label('agent-unavailable')));
            this.bridge?.listAgents();
        }
        if (this.handleHistoryEvent(message)) return;
        if (typeof message.conversation_id === 'string' && message.conversation_id !== this.conversationId
            && message.client_message_id !== this.clientMessageId) {
            if (typeof message.sequence === 'number') {
                this.unreadConversations.add(message.conversation_id);
                this.updateUnreadBadge();
                if (this.historyVisible && ['run.completed', 'run.failed', 'run.cancelled', 'run.paused'].includes(String(message.event_type))) this.loadHistory();
            }
            return;
        }
        if (this.selectionRequest?.beforeSequence === null && message.conversation_id === this.conversationId) {
            this.bufferedEvents.push(message);
            return;
        }
        if (!this.clientMessageId) return;
        if (message.action === 'chat.approval' && typeof message.approval_id === 'string') {
            if (message.status !== 'accepted') {
                const card = this.approvalCards.get(message.approval_id)?.element;
                if (card) {
                    for (const button of card.querySelectorAll('button')) button.disabled = false;
                    const status = card.querySelector('[data-approval-status]');
                    if (status) status.textContent = String(message.message ?? this.label('failed'));
                }
            }
            this.requestReplay();
            return;
        }
        if (message.run_id === this.runId && ['chat.replay', 'chat.cancel'].includes(String(message.action))
            && ['failed', 'forbidden', 'unavailable'].includes(String(message.status))) {
            this.finish('failed');
            return;
        }
        if (message.status === 'replay' && message.run_id === this.runId) {
            this.receiveReplay(message);
            return;
        }
        if (message.client_message_id !== this.clientMessageId) {
            // Action-level errors may omit message correlation.
            if (!message.client_message_id && message.action === 'chat.message'
                && ['failed', 'unavailable', 'forbidden'].includes(String(message.status))) this.finish('failed');
            return;
        }
        if (this.runId && message.run_id && message.run_id !== this.runId) return;
        this.applyActionEvent(message);
        this.watchResponse();
        if (message.status === 'accepted' && typeof message.run_id === 'string'
            && typeof message.conversation_id === 'string') {
            this.clearAttachments();
            for (const id of Array.isArray(message.artifact_ids) ? message.artifact_ids : []) {
                if (typeof id === 'string') {
                    this.renderArtifact(id, new Date().toISOString());
                    const card = this.artifactCards.get(id);
                    const row = this.response?.parentElement;
                    if (card && row?.parentElement === this.messages) this.messages?.insertBefore(card, row);
                }
            }
            this.runId = message.run_id;
            this.conversationId = message.conversation_id;
            this.updateConversationTitle(this.conversationTitle);
            this.saveActiveRun();
            if (this.cancellationRequested) this.sendCancellation();
            this.requestReplay();
        } else if (message.status === 'streaming' && typeof message.delta === 'string') {
            if (typeof message.sequence === 'number') {
                this.rememberDelta(message.sequence, String(message.message_id ?? ''), message.delta);
                this.scheduleMarkdownRender();
            }
        } else if (['completed', 'cancelled', 'failed'].includes(String(message.status))
            && typeof message.sequence === 'number') {
            this.terminalStatus = message.status === 'completed' ? 'ready' : String(message.status);
            this.requestReplay();
        }
        else if (['failed', 'busy', 'forbidden', 'unavailable'].includes(String(message.status))) this.finish('failed');
        this.scrollToLatest();
    }

    /** Apply public progress, approval cards and pause state in order during live delivery or replay. */
    private applyActionEvent(event: Record<string, unknown>): void {
        if (typeof event.sequence === 'number' && event.sequence <= this.snapshotCursor) return;
        this.progress = updateAgentProgress(this.progress, event);
        this.displayProgress();
        const sequence = typeof event.sequence === 'number' ? event.sequence : 0;
        const payload = event.payload as Record<string, unknown> | undefined;
        const data = payload?.data as Record<string, unknown> | undefined;
        if (event.event_type === 'tool.outcome' && Array.isArray(data?.artifacts)) {
            for (const artifact of data.artifacts) {
                if (artifact && typeof artifact.id === 'string') this.renderArtifact(artifact.id, String(artifact.created_at ?? ''));
            }
        }
        if (event.event_type === 'tool.outcome' && Array.isArray(data?.approvals)) {
            for (const value of data.approvals) {
                if (value && typeof value === 'object') this.renderApproval(value as Record<string, unknown>, sequence);
            }
        }
        if (event.event_type === 'approval.decided' && typeof payload?.approval_id === 'string') {
            this.renderApproval({id: payload.approval_id, status: data?.status}, sequence);
        }
        if (sequence >= this.stateSequence) {
            if (event.event_type === 'run.paused') this.paused = true;
            else if (['text.delta', 'approval.decided', 'run.completed', 'run.failed', 'run.cancelled'].includes(String(event.event_type))) this.paused = false;
            this.stateSequence = sequence;
        }
    }

    /** Load an authorized server-rendered artifact without type-specific chat branches. */
    private renderArtifact(id: string, createdAt: string): void {
        if (!this.messages || !this.isUuid(id) || this.artifactCards.has(id)) return;
        const template = this.element?.getAttribute('data-artifact-url-template');
        if (!template) return;
        const card = document.createElement('div');
        card.dataset.createdAt = createdAt;
        card.dataset.artifactId = id;
        card.textContent = this.label('history-loading');
        card.setAttribute('hx-get', template.replace('00000000-0000-0000-0000-000000000000', id));
        card.setAttribute('hx-trigger', 'intersect once');
        card.setAttribute('hx-swap', 'innerHTML');
        this.artifactCards.set(id, card);
        this.messages.append(card);
        htmx.process(card);
    }

    /** Show the MCP tool title and reveal its exact arguments on request. */
    private renderApproval(approval: Record<string, unknown>, sequence: number): void {
        if (typeof approval.id !== 'string' || !this.messages) return;
        const old = this.approvalCards.get(approval.id);
        if (old && old.sequence >= sequence) return;
        const card = old?.element ?? document.createElement('div');
        if (!old) {
            card.className = 'rounded-xl border border-gray-200 bg-white p-3 text-sm dark:border-zinc-700 dark:bg-zinc-900';
            const details = document.createElement('details');
            details.className = 'group';
            const summary = document.createElement('summary');
            summary.className = 'flex cursor-pointer list-none items-center justify-between gap-2 font-semibold [&::-webkit-details-marker]:hidden';
            const title = document.createElement('span');
            title.textContent = String(approval.tool_title ?? approval.tool_identifier ?? this.label('approval'));
            const chevron = document.createElement('i');
            chevron.className = 'fa-solid fa-chevron-down shrink-0 text-xs text-gray-400 transition-transform group-open:rotate-180';
            chevron.setAttribute('aria-hidden', 'true');
            summary.append(title, chevron);
            const args = document.createElement('pre');
            args.className = 'mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs';
            args.textContent = JSON.stringify(approval.arguments ?? {}, null, 2);
            details.append(summary, args);
            const status = document.createElement('p');
            status.dataset.approvalStatus = '';
            status.className = 'mt-2 text-xs text-gray-500';
            const actions = document.createElement('div');
            actions.dataset.approvalActions = '';
            actions.className = 'max-h-10 overflow-hidden opacity-100 transition-[max-height,opacity] duration-300 ease-in-out motion-reduce:transition-none';
            card.append(details, status, actions);
            for (const action of ['approve', 'reject']) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-secondary btn-xs mr-2 mt-2';
                button.dataset.agentAction = action;
                button.dataset.approvalId = approval.id;
                button.textContent = this.label(action);
                actions.append(button);
            }
            this.messages.append(card);
        }
        const status = String(approval.status ?? 'pending');
        const label = card.querySelector('[data-approval-status]');
        if (label) label.textContent = status === 'pending' ? '' : this.label(status);
        const actions = card.querySelector<HTMLElement>('[data-approval-actions]');
        if (actions) {
            const decided = status !== 'pending';
            actions.classList.toggle('max-h-0', decided);
            actions.classList.toggle('max-h-10', !decided);
            actions.classList.toggle('opacity-0', decided);
            actions.classList.toggle('opacity-100', !decided);
            actions.inert = decided;
            actions.setAttribute('aria-hidden', String(decided));
        }
        for (const button of card.querySelectorAll('button')) button.disabled = status !== 'pending' || !this.bridge?.connected;
        this.approvalCards.set(approval.id, {element: card, sequence});
    }

    /** Deduplicate deltas against the initial snapshot and stable provider message identity. */
    private rememberDelta(sequence: number, messageId: string, text: string): void {
        if (sequence <= this.snapshotCursor || !messageId) return;
        this.deltas.set(sequence, {messageId, text});
    }

    /** Batch live Markdown parsing until the next frame without changing raw delta storage. */
    private scheduleMarkdownRender(): void {
        if (this.markdownFrame === null) this.markdownFrame = window.requestAnimationFrame(this.onMarkdownFrame);
    }

    /** Render accumulated streamed text and scroll once for each scheduled frame. */
    private onMarkdownFrame = (): void => {
        this.markdownFrame = null;
        this.renderDeltas();
        this.scrollToLatest();
    };

    /** Release a pending render when switching conversations or flushing final text. */
    private cancelMarkdownFrame(): void {
        if (this.markdownFrame !== null) window.cancelAnimationFrame(this.markdownFrame);
        this.markdownFrame = null;
    }

    /** Reconstruct and sanitize Markdown from the persisted baseline plus ordered committed deltas. */
    private renderDeltas(): void {
        this.cancelMarkdownFrame();
        const texts = new Map<string, string>();
        for (const [, delta] of [...this.deltas.entries()].sort(this.compareDeltaSequence)) {
            texts.set(delta.messageId, (texts.get(delta.messageId) ?? '') + delta.text);
        }
        for (const [id, content] of texts) {
            let row = this.messageRows.get(id);
            if (!row) {
                const text = this.response ?? this.appendMessage('', false);
                if (!text) continue;
                this.response = null;
                row = {element: text, baseline: ''};
                this.messageRows.set(id, row);
            }
            renderAgentMessage(row.element, row.baseline + content, false);
        }
    }

    /** Show waving dots until the first visible response text arrives. */
    private showThinking(): void {
        if (!this.response) return;
        const indicator = document.createElement('span');
        indicator.className = 'bloomerp-agent-thinking';
        indicator.setAttribute('aria-hidden', 'true');
        for (let index = 0; index < 3; index++) {
            indicator.append(document.createElement('span'));
        }
        this.response.replaceChildren(indicator);
    }

    /** Sort received fragments by committed event order. */
    private compareDeltaSequence(left: [number, {messageId: string; text: string}], right: [number, {messageId: string; text: string}]): number {
        return left[0] - right[0];
    }

    /** Fetch committed events without resending the user's message. */
    private requestReplay(afterSequence?: number): void {
        if (!this.bridge?.connected || !this.runId || !this.conversationId) return;
        if (this.replaying && afterSequence === undefined) return;
        try {
            this.replaying = true;
            this.bridge.replayChat(this.conversationId, this.runId, afterSequence ?? this.replayCursor);
        } catch {
            this.replaying = false;
            this.setStatus('disconnected');
        }
    }

    /** Merge replay pages and finalize only after all committed output is available. */
    private receiveReplay(message: Record<string, unknown>): void {
        if (!Array.isArray(message.events)) return;
        for (const item of message.events) {
            if (!item || typeof item !== 'object') continue;
            const event = item as Record<string, unknown>;
            this.applyActionEvent(event);
            const payload = event.payload as Record<string, unknown> | undefined;
            if (event.event_type === 'text.delta' && typeof event.sequence === 'number' && typeof payload?.text === 'string') {
                this.rememberDelta(event.sequence, String(payload.message_id ?? ''), payload.text);
            }
            if (event.event_type === 'run.completed') this.terminalStatus = 'ready';
            else if (event.event_type === 'run.cancelled') this.terminalStatus = 'cancelled';
            else if (event.event_type === 'run.failed') this.terminalStatus = 'failed';
        }
        this.renderDeltas();
        if (typeof message.next_sequence === 'number') this.replayCursor = Math.max(this.replayCursor, message.next_sequence);
        if (message.has_more === true && typeof message.next_sequence === 'number') {
            this.requestReplay(message.next_sequence);
        } else {
            this.replaying = false;
            if (this.terminalStatus) this.finish(this.terminalStatus);
            else this.watchResponse();
        }
        this.scrollToLatest();
    }

    /** Keep real executions attached across reconnects and replay missed committed events. */
    private onConnectionChanged = (): void => {
        if (this.bridge?.connected) this.bridge.listAgents();
        this.replaying = false;
        if (!this.bridge?.connected) {
            if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
            this.responseTimer = null;
            if (this.clientMessageId && !this.runId) {
                this.finish('interrupted');
            }
            this.setStatus('disconnected');
            if (this.runId) this.setProgress('disconnected');
        } else if (this.conversationId) {
            const historyWasVisible = this.historyVisible;
            this.selectConversation(this.conversationId, null, true);
            if (historyWasVisible) this.showHistory(true);
            this.setStatus(this.cancellationRequested ? 'stopping' : 'responding');
            if (this.cancellationRequested) this.sendCancellation();
        } else {
            this.setStatus('ready');
            if (this.historyVisible) this.showHistory(true);
        }
        if (this.bridge?.connected && this.historyVisible) this.loadHistory();
        this.syncComposer();
    };

    /** Surface malformed transport responses instead of leaving a pending composer. */
    private onProtocolError = (_event: Event): void => {
        if (this.clientMessageId) this.finish('failed');
    };

    /** Bound silent transport failures so the composer cannot remain locked forever. */
    private watchResponse(): void {
        if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
        this.responseTimer = null;
        if (this.paused) return;
        this.responseTimer = window.setTimeout(this.onResponseTimeout, !this.runId ? 30_000 : 5000);
    }

    /** Mark a stalled response as interrupted without resubmitting its input. */
    private onResponseTimeout = (): void => {
        if (!this.runId) this.finish('interrupted');
        else {
            this.replaying = false;
            this.requestReplay();
            this.watchResponse();
        }
    };

    /** Complete the local response lifecycle while retaining partial assistant text. */
    private finish(status: string): void {
        this.renderDeltas();
        this.setProgress(null);
        if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
        this.responseTimer = null;
        this.response?.querySelector('.bloomerp-agent-thinking')?.remove();
        if (status !== 'ready') {
            if (this.response && !this.response.textContent) this.response.textContent = this.label(status);
            else this.appendMessage(this.label(status), false);
        }
        this.replaying = false;
        this.terminalStatus = null;
        this.clearSavedRun();
        this.clientMessageId = null;
        this.runId = null;
        this.response = null;
        this.cancellationRequested = false;
        this.setStatus(status);
        for (const card of this.approvalCards.values()) {
            for (const button of card.element.querySelectorAll('button')) button.disabled = true;
        }
        this.syncComposer();
    }

    /** Read translated presentation strings supplied by the server template. */
    private label(key: string): string {
        return this.element?.getAttribute(`data-status-${key}`) ?? key;
    }

    /** Set an initial or terminal presentation stage without adding transcript content. */
    private setProgress(key: string | null): void {
        this.progress = {...this.progress, key, toolTitle: ''};
        this.displayProgress();
    }

    /** Display factual run activity in the chat's dedicated, translated live region. */
    private displayProgress(): void {
        const target = this.element?.querySelector<HTMLElement>('[data-agent-progress]');
        if (target) renderAgentProgress(target, this.progress, this.progress.key ? this.label(`progress-${this.progress.key}`) : '');
    }

    /** Announce connection and response progress without changing the transcript. */
    private setStatus(key: string): void {
        const status = this.element?.querySelector<HTMLElement>('[data-agent-status]');
        if (status) status.textContent = this.label(key);
    }

    /** Release subscriptions before HTMX removes this component or its ancestor. */
    private onCleanup = (event: Event): void => {
        const removed = (event as CustomEvent<{ elt?: Element }>).detail?.elt;
        if (removed && this.element && removed.contains(this.element)) this.destroy();
    };

    /** Update the send button and composer size after text changes. */
    private onInput = (event: Event): void => {
        if (event.target instanceof Element && event.target.matches('[data-agent-search]')) {
            if (this.historySearchTimer !== null) window.clearTimeout(this.historySearchTimer);
            this.historySearchTimer = window.setTimeout(this.refreshHistory, 250);
            return;
        }
        this.syncComposer();
    };

    /** Debounce conversation-title searches without delaying composer input. */
    private refreshHistory = (): void => { this.loadHistory(); };

    /** Send on Enter while preserving Shift+Enter and input-method composition. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.target === this.input && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            this.element?.querySelector<HTMLFormElement>('[data-agent-form]')?.requestSubmit();
        }
    };

    /** Allow keyboard users to dismiss the open panel with Escape. */
    private onDocumentKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape' && this.panel && !this.panel.hidden) this.close();
    };

    /** Receive the registry-backed composer's selected candidates and upload state. */
    private onAttachments = (event: Event): void => {
        const detail = (event as CustomEvent<{items: ArtifactChoice[]; busy: boolean}>).detail;
        this.attachments = [...detail.items];
        this.attachmentBusy = detail.busy;
        this.syncComposer();
    };

    /** Extract a signed candidate token without sending display metadata as authority. */
    private attachmentToken(choice: ArtifactChoice): string { return choice.token; }

    /** Clear composer attachments after acceptance or when changing conversations. */
    private clearAttachments(): void {
        this.element?.querySelector('[data-artifact-search-url]')?.dispatchEvent(new CustomEvent('agent:clear-attachments'));
    }

    /** Keep the draft composer height and send availability in sync. */
    private syncComposer(): void {
        this.renderApprovalPicker();
        this.saveEditorState();
        const send = this.element?.querySelector<HTMLButtonElement>('[data-agent-send]');
        const busy = this.clientMessageId !== null;
        const form = this.element?.querySelector<HTMLElement>('[data-artifact-search-url]');
        if (form) form.dataset.attachmentsDisabled = String(busy || !!this.selectionRequest || this.conversationArchived);
        for (const button of form?.querySelectorAll<HTMLButtonElement>('[data-artifact-plus], [data-artifact-remove]') ?? []) button.disabled = busy || !!this.selectionRequest || this.conversationArchived;
        if (send) {
            send.disabled = !this.selectedAgentId || (!this.input?.value.trim() && !this.attachments.length) || this.attachmentBusy || busy || !!this.selectionRequest || this.conversationArchived || !this.bridge?.connected;
            send.hidden = busy;
        }
        const stop = this.element?.querySelector<HTMLButtonElement>('[data-agent-action="stop"]');
        if (stop) {
            stop.hidden = !busy;
            stop.disabled = this.cancellationRequested || !this.bridge?.connected;
        }
        const reset = this.element?.querySelector<HTMLButtonElement>('[data-agent-action="reset"]');
        if (reset) reset.disabled = busy && !this.runId;
        for (const prompt of this.element?.querySelectorAll<HTMLButtonElement>('[data-agent-prompt]') ?? []) {
            prompt.disabled = busy || !!this.selectionRequest || this.conversationArchived || !this.bridge?.connected;
        }
        if (this.input) {
            this.input.disabled = !!this.selectionRequest || this.conversationArchived;
            this.input.style.height = 'auto';
            this.input.style.height = `${Math.min(144, Math.max(48, this.input.scrollHeight))}px`;
        }
    }

    /** Append literal user text or sanitized assistant Markdown in a block-capable bubble. */
    private appendMessage(content: string, user: boolean): HTMLElement | null {
        if (!this.messages) return null;
        const welcome = this.element?.querySelector<HTMLElement>('[data-agent-welcome]');
        if (welcome) welcome.hidden = true;
        const row = document.createElement('div');
        row.dataset.createdAt = new Date().toISOString();
        row.className = user ? 'flex justify-end' : 'flex';
        const text = document.createElement(user ? 'p' : 'div');
        text.className = user
            ? 'max-w-[90%] whitespace-pre-wrap break-words rounded-xl bg-primary px-3.5 py-2.5 text-sm leading-6 text-white'
            : 'agent-markdown min-w-0 w-full break-words text-sm leading-6 text-gray-600 dark:text-zinc-300';
        renderAgentMessage(text, content, user);
        row.append(text);
        this.messages.append(row);
        return text;
    }

    /** Keep newly added conversation content visible inside the panel. */
    private scrollToLatest(): void {
        const viewport = this.element?.querySelector<HTMLElement>('[data-agent-scroll]');
        if (viewport) viewport.scrollTop = viewport.scrollHeight;
    }

    /** Release component-owned listeners when the chat is destroyed. */
    public override destroy(): void {
        this.cancelMarkdownFrame();
        this.setProgress(null);
        this.lifecycle?.abort();
        this.lifecycle = null;
        if (this.historySearchTimer !== null) window.clearTimeout(this.historySearchTimer);
        if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
        this.responseTimer = null;
        this.bridge = null;
        super.destroy();
    }
}
