import { visibleConversationReadMarker } from "../../utils/conversationReadMarker";
import { bindReferencePreviews } from "../../utils/referencePreviews";
import htmx from 'htmx.org';
import { BloomerpHttpClient } from '../../sdk/sdk';
import BaseComponent, { getComponent } from '../BaseComponent';
import { BloomerpTextEditor } from '../text_editor/BloomerpTextEditor';

/** Own the reusable message timeline and editor, independently of its host. */
export default class Conversation extends BaseComponent {
    private lifecycle = new AbortController();
    private socket: WebSocket | null = null;
    private pending = false;
    private reacting = false;
    private readPending = false;
    private acknowledgedMessage = '';
    private acknowledgedActivity = '';
    private visibilityObserver: MutationObserver | null = null;
    private referencePreviewCleanup: (() => void) | null = null;
    private clientId = crypto.randomUUID();
    private attemptedContent = '';

    /** Bind composer events and authorized live timeline invalidations. */
    public initialize(): void {
        this.element.addEventListener('htmx:beforeCleanupElement', this.onCleanup, { signal: this.lifecycle.signal });
        this.element.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener('focusout', this.onGroupNameChange, { signal: this.lifecycle.signal });
        this.element.addEventListener('submit', this.onSubmit, { signal: this.lifecycle.signal });
        this.element.addEventListener('keydown', this.onKeyDown, { signal: this.lifecycle.signal });
        this.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/communication/conversation/${this.element.dataset.conversationId}/`);
        this.socket.addEventListener('message', this.onNotification);
        this.socket.addEventListener('close', this.onSocketClosed, { signal: this.lifecycle.signal });
        document.addEventListener('visibilitychange', this.scheduleRead, { signal: this.lifecycle.signal });
        window.addEventListener('focus', this.scheduleRead, { signal: this.lifecycle.signal });
        this.visibilityObserver = new MutationObserver(this.scheduleRead);
        for (let parent: HTMLElement | null = this.element; parent; parent = parent.parentElement) {
            this.visibilityObserver.observe(parent, { attributes: true, attributeFilter: ['hidden', 'class', 'style'] });
        }
        this.onAfterSwap();
        this.scrollMessages();
    }

    /** Resolve the existing editor instance after child components initialize. */
    private getEditor(): BloomerpTextEditor | null {
        const node = this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]');
        return node ? getComponent(node) as BloomerpTextEditor : null;
    }

    /** Handle group-name keyboard edits independently from composer submission. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Enter' && event.target instanceof HTMLInputElement && event.target.matches('[data-group-name]')) {
            event.preventDefault();
            void this.onGroupNameChange(event);
            event.target.blur();
            return;
        }
    };

    /** Save changed group names on blur or Enter through the SDK's session-authenticated client. */
    private onGroupNameChange = async (event: Event): Promise<void> => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.matches('[data-group-name]')) return;
        const error = input.parentElement?.querySelector<HTMLElement>('[data-group-name-error]');
        const url = this.element.dataset.groupUrl;
        if (!url || input.disabled || input.value === input.defaultValue) return;
        if (error) error.hidden = true;
        input.removeAttribute('aria-invalid');
        input.disabled = true;
        const token = this.element.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')?.value;
        const client = new BloomerpHttpClient({
            baseUrl: window.location.origin,
            auth: { type: 'session', csrf: { token } },
        });
        try {
            const result = await client.request<{ id: string; name: string }>(url, {
                method: 'PATCH', body: JSON.stringify({ name: input.value }), signal: this.lifecycle.signal,
            });
            input.value = result.name;
            input.defaultValue = result.name;
            const label = this.element.querySelector('.im-chat-header .im-identity-text strong');
            if (label) label.textContent = result.name;
            document.body.dispatchEvent(new CustomEvent('im:unread-changed', { bubbles: true }));
        } catch (cause: unknown) {
            if (this.lifecycle.signal.aborted) return;
            input.setAttribute('aria-invalid', 'true');
            if (error) {
                error.textContent = cause instanceof Error ? cause.message : 'Unable to save group name.';
                error.hidden = false;
            }
        } finally {
            input.disabled = false;
        }
    };

    /** Send sanitized editor content through the conversation controller endpoint. */
    private onSubmit = async (event: SubmitEvent): Promise<void> => {
        if (!(event.target instanceof HTMLFormElement) || !event.target.matches('[data-send-form]')) return;
        event.preventDefault();
        const editor = this.getEditor();
        if (this.pending || !editor) return;
        const form = event.target;
        const html = editor.getValue();
        const quote = this.element.querySelector<HTMLElement>('[data-quote-preview]');
        const signature = JSON.stringify([html, quote?.dataset.replyTo]);
        if (this.attemptedContent && this.attemptedContent !== signature) this.clientId = crypto.randomUUID();
        this.attemptedContent = signature;
        const data = new FormData(form);
        data.set('body_html', html);
        data.set('client_id', this.clientId);
        data.set('reply_to', quote?.dataset.replyTo || '');
        data.set('thread_root', this.element.dataset.threadId || '');
        const button = form.querySelector<HTMLButtonElement>('.im-send')!;
        const error = form.querySelector<HTMLElement>('[data-send-error]')!;
        error.hidden = true;
        this.pending = true;
        button.disabled = true;
        editor.editor?.setEditable(false);
        try {
            const response = await fetch(form.action, { method: 'POST', body: data, signal: this.lifecycle.signal });
            if (!response.ok) {
                const result = await response.json().catch((): { error: string } => ({ error: 'Unable to send this message.' }));
                throw new Error(result.error || 'Unable to send this message.');
            }
            const acknowledgement = await response.json();
            if (!acknowledgement.message_id) throw new Error('Unable to confirm message delivery.');
            editor.setValue('');
            if (quote) { quote.hidden = true; delete quote.dataset.replyTo; }
            this.clientId = crypto.randomUUID();
            this.attemptedContent = '';
            this.element.dispatchEvent(new CustomEvent('im:message-sent', { bubbles: true }));
            await this.refreshMessages();
        } catch (reason: unknown) {
            if (!this.lifecycle.signal.aborted) {
                error.textContent = reason instanceof Error ? reason.message : 'Unable to send this message.';
                error.hidden = false;
            }
        } finally {
            this.pending = false;
            button.disabled = false;
            editor.editor?.setEditable(true);
        }
    };

    /** Refresh content via the authorized endpoint without replacing the draft editor. */
    private async refreshMessages(): Promise<void> {
        if (!this.element.isConnected) return;
        const url = new URL(this.element.dataset.loadUrl!, location.origin);
        url.searchParams.set('messages_only', '1');
        if (this.element.dataset.threadId) url.searchParams.set('thread', this.element.dataset.threadId);
        await htmx.ajax('get', url.toString(), { target: this.element.querySelector('.im-messages')!, swap: 'outerHTML' });
        this.scrollMessages();
    }

    /** React only to the consumer's content-free refresh event. */
    private onNotification = (event: MessageEvent<string>): void => {
        const payload = JSON.parse(event.data) as { action: string; name?: string };
        if (payload.action === 'refresh') void this.refreshMessages();
        if (payload.action === 'group-updated') {
            const label = this.element.querySelector('.im-chat-header .im-identity-text strong');
            if (label && payload.name) label.textContent = payload.name;
            const members = this.element.querySelector<HTMLElement>('[data-group-members]');
            if (members) void htmx.ajax('get', this.element.dataset.groupUrl!, { target: members, swap: 'outerHTML' });
        }
    };

    /** Clear private content immediately when the server revokes membership. */
    private onSocketClosed = (event: CloseEvent): void => {
        if (event.code !== 4403) return;
        this.getEditor()?.destroy();
        this.destroy();
        this.element.textContent = 'This conversation is no longer available.';
    };

    /** Keep the latest message visible after loading the timeline. */
    private scrollMessages(): void {
        const messages = this.element.querySelector<HTMLElement>('.im-messages');
        if (messages) messages.scrollTop = messages.scrollHeight;
    }

    /** Preview a quoted reply and focus the text editor. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement;
        const reaction = target.closest<HTMLButtonElement>('[data-reaction-emoji]');
        if (reaction) { void this.setReaction(reaction); return; }
        const button = target.closest<HTMLElement>('[data-quote-message]');
        const preview = this.element.querySelector<HTMLElement>('[data-quote-preview]')!;
        if (button) {
            preview.hidden = false;
            preview.dataset.replyTo = button.dataset.quoteMessage;
            this.element.querySelector('[data-quote-text]')!.textContent = button.closest('.im-message')?.querySelector('[data-message-body]')?.textContent || '';
            this.element.querySelector<HTMLElement>('[contenteditable]:not([contenteditable="false"])')?.focus();
        } else if (target.closest('[data-cancel-quote]')) {
            preview.hidden = true;
            delete preview.dataset.replyTo;
        }
    };

    /** Close subscriptions before HTMX removes this conversation instance. */
    private onCleanup = (event: Event): void => {
        if ((event as CustomEvent<{ elt: HTMLElement }>).detail.elt === this.element) this.destroy();
    };

    /** Set a participant's desired reaction state without risking double-toggle retries. */
    private async setReaction(button: HTMLButtonElement): Promise<void> {
        if (this.reacting || button.disabled) return;
        const message = button.closest<HTMLElement>('[data-reaction-url]');
        if (!message) return;
        const error = this.element.querySelector<HTMLElement>('[data-send-error]')!;
        const token = this.element.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')!;
        const data = new FormData();
        data.set('csrfmiddlewaretoken', token.value);
        data.set('emoji', button.dataset.reactionEmoji!);
        data.set('active', button.dataset.reactionActive!);
        this.reacting = true;
        button.disabled = true;
        error.hidden = true;
        try {
            const response = await fetch(message.dataset.reactionUrl!, { method: 'POST', body: data, signal: this.lifecycle.signal });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to update reaction.');
            button.closest('[bloomerp-component="dropdown-keyboard"]')?.dispatchEvent(new CustomEvent('dropdown-dismiss', { bubbles: true }));
            await this.refreshMessages();
        } catch (reason: unknown) {
            if (!this.lifecycle.signal.aborted) {
                error.textContent = reason instanceof Error ? reason.message : 'Unable to update reaction.';
                error.hidden = false;
            }
        } finally {
            this.reacting = false;
            button.disabled = false;
        }
    }

    /** Wait for HTMX and shell visibility changes to finish before acknowledging content. */
    private scheduleRead = (): void => {
        requestAnimationFrame(this.markVisibleMessagesRead);
    };

    /** Mark only the latest rendered message, preserving unseen arrivals and hidden panels. */
    private markVisibleMessagesRead = async (): Promise<void> => {
        if (this.lifecycle.signal.aborted || this.readPending) return;
        const messageId = visibleConversationReadMarker(this.element, document.visibilityState);
        const activity = this.element.querySelector<HTMLElement>('.im-messages')?.dataset.activityToken || '';
        const visible = document.visibilityState === 'visible' && this.element.getClientRects().length > 0;
        if (!visible || ((!messageId || messageId === this.acknowledgedMessage) && (!activity || activity === this.acknowledgedActivity))) return;
        const token = this.element.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]');
        if (!token) return;
        const data = new FormData();
        data.set('csrfmiddlewaretoken', token.value);
        if (messageId) data.set('message_id', messageId);
        if (activity) data.set('activity_token', activity);
        data.set('thread_root', this.element.dataset.threadId || '');
        this.readPending = true;
        try {
            const response = await fetch(this.element.dataset.readUrl!, { method: 'POST', body: data, signal: this.lifecycle.signal });
            if (!response.ok || !(await response.json()).ok) return;
            this.acknowledgedMessage = messageId || '';
            this.acknowledgedActivity = activity;
            document.body.dispatchEvent(new CustomEvent('im:unread-changed', { bubbles: true }));
        } catch {
            // Keep the marker unacknowledged so the next visibility/update event retries it.
        } finally {
            this.readPending = false;
            const latest = this.element.querySelector('.im-messages [data-message-id]:last-child') as HTMLElement | null;
            if (latest?.dataset.messageId && latest.dataset.messageId !== messageId) this.scheduleRead();
        }
    };

    /** Bind shared object previews whenever the message timeline is replaced. */
    public override onAfterSwap(): void {
        this.referencePreviewCleanup?.();
        const messages = this.element.querySelector<HTMLElement>('.im-messages');
        this.referencePreviewCleanup = messages ? bindReferencePreviews(messages) : null;
        this.scheduleRead();
    }

    /** Release socket subscriptions and instance-owned listeners. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.socket?.close();
        this.visibilityObserver?.disconnect();
        this.referencePreviewCleanup?.();
        super.destroy();
    }
}
