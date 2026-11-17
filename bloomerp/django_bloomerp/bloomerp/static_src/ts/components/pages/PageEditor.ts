import BaseComponent, { getComponent } from '../BaseComponent';
import { BloomerpTextEditor } from '../text_editor/BloomerpTextEditor';
import ForeignFieldWidget from '../widgets/ForeignFieldWidget';
import { t as _ } from '@/utils/i18n';
import { $getRoot, $isElementNode, type LexicalNode } from 'lexical';
import { createModalInstance } from '@/utils/modals';
import type { Modal } from '../Modal';
import { addTooltip } from '@/utils/tooltip';

type PageData = { id: string; title: string; content: string; datetime_updated: string; shared_with_users?: Array<string | number>; shared_with_groups?: Array<string | number> };

/** Autosave the shared editor through generated CRUD; sockets only invalidate revisions. */
export default class PageEditor extends BaseComponent {
    private readonly lifecycle = new AbortController();
    private timer: ReturnType<typeof setTimeout> | null = null;
    private reconnect: ReturnType<typeof setTimeout> | null = null;
    private socket: WebSocket | null = null;
    private pending: Promise<boolean> | null = null;
    private dirty = false;
    private sharingDirty = false;
    private sharingEdited = false;
    private sharingRevision = 0;
    private revision = 0;
    private conflict = false;
    private uploads = 0;
    private remotePending = false;
    private deleteModal: Modal | null = null;
    private readonly tooltipCleanups: Array<() => void> = [];

    /** Bind autosave, file-upload state, teardown and browser navigation protection. */
    public initialize(): void {
        const options = { signal: this.lifecycle.signal };
        this.element.addEventListener('input', this.changed, options);
        this.element.addEventListener('change', this.changed, options);
        this.element.addEventListener('bloomerp:widget-change', this.changed, options);
        this.element.addEventListener('bloomerp:file-upload-state', this.uploadChanged, options);
        this.element.addEventListener('click', this.clicked, options);
        this.element.addEventListener('submit', this.submit, options);
        this.element.addEventListener('keydown', this.keydown, options);
        this.element.addEventListener('htmx:beforeCleanupElement', this.cleanup, options);
        document.addEventListener('htmx:confirm', this.confirmNavigation, options);
        window.addEventListener('beforeunload', this.beforeUnload, options);
        window.addEventListener('online', this.schedule, options);
        this.setupControls();
        this.connect();
    }

    /** Place formatting above the title and label the compact scratchpad actions. */
    private setupControls(): void {
        const toolbar = this.editor().element.querySelector<HTMLElement>('[data-text-editor-toolbar]');
        if (toolbar) this.element.querySelector('[data-page-formatting]')!.append(toolbar);
        if (this.element.closest('[data-pages-content]')) {
            for (const button of this.element.querySelectorAll<HTMLElement>('[data-page-controls] [data-page-delete], [data-page-controls] [data-page-share] button[aria-haspopup]')) {
                this.tooltipCleanups.push(addTooltip(button, { text: button.getAttribute('aria-label')!, position: 'bottom', portal: true }));
            }
        }
    }

    /** Move forward Tab from the page title directly into the document. */
    private keydown = (event: KeyboardEvent): void => {
        if (event.defaultPrevented || event.isComposing) return;
        if (event.key === 'Tab' && !event.shiftKey && (event.target as Element).matches('[name="title"]')) {
            event.preventDefault();
            this.editor().editor?.focus(undefined, { defaultSelection: 'rootStart' });
        }
    };

    /** Resolve this widget's rich-text editor without relying on initialization order. */
    private editor(): BloomerpTextEditor {
        return getComponent(this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]')!) as BloomerpTextEditor;
    }

    /** Queue local changes; remote programmatic value updates do not emit this event. */
    private changed = (event: Event): void => {
        const sharing = (event.target as Element).closest('[data-page-sharing]');
        if (sharing) { this.sharingEdited = true; this.sharingRevision += 1; return; }
        this.dirty = true;
        this.revision += 1;
        if (!this.conflict) this.status(_('Unsaved changes'));
        this.schedule();
    };

    /** Wait briefly after typing and serialize writes through one in-flight request. */
    private schedule = (): void => {
        if (this.timer) clearTimeout(this.timer);
        if (!this.conflict && !this.lifecycle.signal.aborted) this.timer = setTimeout(this.autosave, 700);
    };

    /** Start the debounced write without leaking rejected asynchronous promises. */
    private autosave = (): void => { void this.flush(); };

    /** Save pending content before page switches and full-size navigation. */
    public async flush(): Promise<boolean> {
        if (this.timer) clearTimeout(this.timer);
        if (this.pending) {
            const saved = await this.pending;
            return saved ? this.flush() : false;
        }
        if (this.conflict || this.uploads > 0) return false;
        if (!this.dirty && !this.sharingDirty) return true;
        this.pending = this.save();
        try { return await this.pending; }
        finally {
            this.pending = null;
            if (this.remotePending && !this.lifecycle.signal.aborted) {
                this.remotePending = false;
                void this.refresh();
            }
        }
    }

    /** Send only edited fields to the generated Page API, retaining drafts on failure. */
    private async save(): Promise<boolean> {
        const revision = this.revision;
        const savesSharing = this.sharingDirty;
        const sharingRevision = this.sharingRevision;
        const id = this.element.dataset.pageId;
        const title = this.element.querySelector<HTMLInputElement>('[name="title"]')!.value;
        const content = this.editor().getValue();
        if (!id && !title.trim() && !this.editor().editor?.getEditorState().read(this.hasContent)) {
            this.dirty = false;
            this.status(_('Start typing to create a page'));
            return true;
        }
        const payload: Record<string, unknown> = {};
        if (this.dirty || !id) Object.assign(payload, { title, content });
        if (this.sharingDirty) {
            payload.shared_with_users = this.sharingWidget('shared_with_users')?.getValue() ?? [];
            payload.shared_with_groups = this.sharingWidget('shared_with_groups')?.getValue() ?? [];
        }
        this.status(_('Saving…'));
        try {
            const response = await this.request(id ? 'PATCH' : 'POST', payload);
            if (!response.ok) {
                if (response.status === 409) { this.markConflict(); return false; }
                this.status(_('Could not save. Your changes are still here; edit again to retry.'), true);
                return false;
            }
            const page = await response.json() as PageData;
            this.element.dataset.pageId = page.id;
            this.element.dataset.version = page.datetime_updated;
            if (revision === this.revision) this.dirty = false;
            if (savesSharing) {
                if (sharingRevision === this.sharingRevision) this.sharingEdited = false;
                this.sharingDirty = false;
            }
            this.status(this.dirty || this.sharingDirty ? _('Unsaved changes') : _('All changes saved'));
            this.element.dispatchEvent(new CustomEvent('bloomerp:page-saved', { bubbles: true, detail: { page, created: !id } }));
            if (!id) {
                this.element.querySelector<HTMLButtonElement>('[data-page-delete]')?.removeAttribute('hidden');
                this.connect();
            }
            if (this.dirty || this.sharingDirty) this.schedule();
            return true;
        } catch {
            if (!this.lifecycle.signal.aborted) this.status(_('Could not save. Your changes are still here; edit again to retry.'), true);
            return false;
        }
    }

    /** Recognize real content, including images, without persisting untouched blank drafts. */
    private hasContent(): boolean {
        const root = $getRoot();
        return root.getTextContent().trim().length > 0 || root.getChildren().some(isNonemptyBlock);
    }

    /** Build the generated collection/detail URL from server-rendered route metadata. */
    private apiUrl(): string {
        const id = this.element.dataset.pageId;
        return this.element.dataset.apiUrl! + (id ? `${id}/` : '');
    }

    /** Resolve the standard multi-value relation widget for one sharing field. */
    private sharingWidget(field: string): ForeignFieldWidget | null {
        const node = this.element.querySelector<HTMLElement>(`[data-page-sharing-field="${field}"] [bloomerp-component="foreign-field-widget"]`);
        return node ? getComponent(node) as ForeignFieldWidget : null;
    }

    /** Send cookie-authenticated JSON and use the current revision for optimistic PATCHes. */
    private request(method: string, payload?: Record<string, unknown>): Promise<Response> {
        const csrf = this.element.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')!.value;
        const headers: Record<string, string> = { 'Content-Type': 'application/json', 'X-CSRFToken': csrf };
        if (method === 'PATCH') headers['If-Match'] = this.element.dataset.version!;
        return fetch(this.apiUrl(), { method, headers, body: payload ? JSON.stringify(payload) : undefined, signal: this.lifecycle.signal });
    }

    /** Subscribe to live invalidations using the existing authenticated Channels infrastructure. */
    private connect = (): void => {
        if (!this.element.dataset.pageId || this.lifecycle.signal.aborted) return;
        this.socket?.close();
        const url = new URL(`/ws/pages/${this.element.dataset.pageId}/`, window.location.origin);
        url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.socket = new WebSocket(url);
        this.socket.addEventListener('message', this.remoteChanged, { signal: this.lifecycle.signal });
        this.socket.addEventListener('open', this.opened, { signal: this.lifecycle.signal });
        this.socket.addEventListener('close', this.closed, { signal: this.lifecycle.signal });
    };

    /** Reconcile changes missed while disconnected before accepting more local writes. */
    private opened = (): void => { void this.refresh(); };

    /** Retry interrupted connections while stopping when the server revokes access. */
    private closed = (event: CloseEvent): void => {
        if (this.lifecycle.signal.aborted) return;
        if (event.code === 4403) {
            this.conflict = true;
            this.status(_('This page is no longer available to you.'), true);
            return;
        }
        this.reconnect = setTimeout(this.connect, 3000);
    };

    /** Read the authoritative API after a remote save, deferring our own in-flight acknowledgement. */
    private remoteChanged = (): void => {
        if (this.pending) this.remotePending = true;
        else void this.refresh();
    };

    /** Apply remote content only to a clean editor; conflicting drafts remain untouched. */
    private async refresh(): Promise<void> {
        if (this.pending) { this.remotePending = true; return; }
        const version = this.element.dataset.version;
        try {
            const response = await this.request('GET');
            if (!response.ok) return;
            const page = await response.json() as PageData;
            if (this.pending || version !== this.element.dataset.version) return;
            if (page.datetime_updated === this.element.dataset.version) return;
            if (this.dirty || this.sharingDirty) { this.markConflict(); return; }
            this.element.querySelector<HTMLInputElement>('[name="title"]')!.value = page.title;
            if (this.editor().getValue() !== page.content) this.editor().setValue(page.content, false);
            this.element.dataset.version = page.datetime_updated;
            for (const field of ['shared_with_users', 'shared_with_groups'] as const) {
                if (!this.sharingEdited && page[field]) this.sharingWidget(field)?.setValue(page[field], false);
            }
            this.status(_('Updated from another editor'));
            this.element.dispatchEvent(new CustomEvent('bloomerp:page-saved', { bubbles: true, detail: { page, created: false } }));
        } catch { /* Autosave errors retain local content; the socket will reconnect. */ }
    }

    /** Stop autosave on a stale revision without attempting automatic merging. */
    private markConflict(): void {
        this.conflict = true;
        if (this.timer) clearTimeout(this.timer);
        this.status(_('This page changed elsewhere. Your unsaved text is still here. Reload to continue.'), true);
    }

    /** Keep uploads inside the next autosave instead of saving an incomplete paste. */
    private uploadChanged = (event: Event): void => {
        this.uploads += (event as CustomEvent<{ delta: number }>).detail.delta;
        if (!this.uploads) this.schedule();
    };

    /** Save sharing only after explicit submission, while content continues to autosave. */
    private submit = async (event: SubmitEvent): Promise<void> => {
        event.preventDefault();
        if (!(event.target as Element).matches('[data-page-sharing]')) { await this.flush(); return; }
        if (!await this.flush()) return;
        if (!this.element.dataset.pageId) {
            this.status(_('Add a title or content before sharing this page.'), true);
            return;
        }
        this.sharingDirty = true;
        this.revision += 1;
        if (await this.flush()) {
            this.status(_('Sharing updated'));
            if (!this.sharingEdited) (event.target as Element).dispatchEvent(new CustomEvent('dropdown-dismiss', { bubbles: true }));
        }
    };

    /** Ask for deletion in the shared modal shell without a native browser confirmation. */
    private clicked = (event: MouseEvent): void => {
        const opener = (event.target as Element).closest<HTMLElement>('[data-page-delete]');
        if (!opener || !this.element.dataset.pageId) return;
        if (this.deleteModal) { this.deleteModal.focus(); return; }
        const modal = createModalInstance('bloomerp-general-use-modal', opener);
        this.deleteModal = modal;
        modal.setTitle(_('Delete page'));
        modal.setSize('sm');
        modal.setPadding('p-4');
        const template = this.element.querySelector<HTMLTemplateElement>('[data-page-delete-dialog]')!;
        const body = modal.getBodyElement()!;
        body.replaceChildren(template.content.cloneNode(true));
        const cancel = body.querySelector<HTMLButtonElement>('[data-page-delete-cancel]')!;
        const confirm = body.querySelector<HTMLButtonElement>('[data-page-delete-confirm]')!;
        /** Dismiss the confirmation without modifying the page. */
        function cancelDeletion(): void { modal.close(); }
        /** Submit the confirmed operation once and retain failures in the dialog. */
        const confirmDeletion = (): void => { void this.deletePage(modal, confirm); };
        /** Release the disposed dialog so the action can be opened again. */
        const releaseModal = (): void => { if (this.deleteModal === modal) this.deleteModal = null; };
        cancel.addEventListener('click', cancelDeletion, { signal: this.lifecycle.signal });
        confirm.addEventListener('click', confirmDeletion, { signal: this.lifecycle.signal });
        modal.element.addEventListener('bloomerp:modal-closed', releaseModal, { once: true, signal: this.lifecycle.signal });
        modal.open();
        cancel.focus();
    };

    /** Delete through the generated API only after the modal's explicit confirmation. */
    private async deletePage(modal: Modal, button: HTMLButtonElement): Promise<void> {
        if (button.disabled) return;
        button.disabled = true;
        const error = modal.getBodyElement()!.querySelector<HTMLElement>('[data-page-delete-error]')!;
        error.hidden = true;
        if (this.pending) await this.pending;
        if (this.lifecycle.signal.aborted) return;
        if (this.timer) clearTimeout(this.timer);
        try {
            const response = await this.request('DELETE');
            if (!response.ok) throw new Error('Page deletion failed');
            this.dirty = this.sharingDirty = false;
            modal.close();
            this.element.dispatchEvent(new CustomEvent('bloomerp:page-deleted', { bubbles: true }));
        } catch {
            if (!this.lifecycle.signal.aborted) {
                error.hidden = false;
                button.disabled = false;
            }
        }
    }

    /** Flush before HTMX replaces the full editor; leave failed drafts mounted. */
    private confirmNavigation = (event: Event): void => {
        const detail = (event as CustomEvent<{ target?: Element; issueRequest?: (skip: boolean) => void }>).detail;
        if (!detail?.target?.contains(this.element) || (!this.dirty && !this.sharingDirty && !this.pending)) return;
        event.preventDefault();
        void this.flush().then(this.resumeNavigation.bind(this, detail.issueRequest));
    };

    /** Resume a deferred HTMX navigation only after the draft has reached the server. */
    private resumeNavigation(issue: ((skip: boolean) => void) | undefined, saved: boolean): void { if (saved) issue?.(true); }

    /** Ask the browser to protect unsaved work during tab closes or hard navigation. */
    private beforeUnload = (event: BeforeUnloadEvent): void => {
        if (!this.dirty && !this.sharingDirty && !this.pending) return;
        event.preventDefault(); event.returnValue = '';
    };

    /** Announce save and conflict status without adding a custom resolution interface. */
    private status(message: string, error: boolean = false): void {
        const node = this.element.querySelector<HTMLElement>('[data-page-status]');
        if (node) {
            node.textContent = error ? message : '';
            node.hidden = !error;
            node.setAttribute('role', error ? 'alert' : 'status');
        }
    }

    /** Dispose only when HTMX removes this component's root element. */
    private cleanup = (event: Event): void => { if (event.target === this.element) this.destroy(); };

    /** Cancel timers, subscriptions and requests when either editor surface is removed. */
    public override destroy(): void {
        this.lifecycle.abort();
        if (this.timer) clearTimeout(this.timer);
        if (this.reconnect) clearTimeout(this.reconnect);
        this.socket?.close();
        this.deleteModal?.destroy();
        this.deleteModal = null;
        for (const cleanup of this.tooltipCleanups) cleanup();
        super.destroy();
    }
}

/** Distinguish an untouched paragraph from a block containing media or other content. */
function isNonemptyBlock(node: LexicalNode): boolean {
    return !$isElementNode(node) || node.getType() !== 'paragraph' || node.getChildrenSize() > 0;
}
