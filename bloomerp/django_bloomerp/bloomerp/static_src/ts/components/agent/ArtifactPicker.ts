import BaseComponent from '../BaseComponent';

export type ArtifactChoice = {token: string; key: string; title: string; summary: string; type: string; icon: string};
type ArtifactCategory = {key: string; label: string; icon: string; upload: boolean};

/** Select and upload attachments from the chat's plus menu. */
export default class ArtifactPicker extends BaseComponent {
    private lifecycle = new AbortController();
    private request: AbortController | null = null;
    private menu: HTMLElement | null = null;
    private input: HTMLElement | null = null;
    private search: HTMLInputElement | null = null;
    private list: HTMLElement | null = null;
    private categories: ArtifactCategory[] = [];
    private category: ArtifactCategory | null = null;
    private choices: ArtifactChoice[] = [];
    private selected: ArtifactChoice[] = [];
    private timer: number | null = null;
    private cursor: string | null = null;
    private index = 0;
    private uploading = false;
    private revision = 0;

    /** Restore validated draft selections and rebuild the visible attachment chips. */
    public restoreSelection(items: ArtifactChoice[]): void {
        this.selected = [...items];
        this.publish();
    }

    /** Bind the form-local menu and own all listeners and pending requests. */
    public initialize(): void {
        if (!this.element) return;
        this.menu = this.element.querySelector('[data-artifact-menu]');
        this.input = this.element.querySelector('[data-agent-composer] [contenteditable]');
        this.search = this.element.querySelector('[data-artifact-search]');
        this.list = this.element.querySelector('[data-artifact-options]');
        const signal = this.lifecycle.signal;
        this.element.addEventListener('click', this.onClick, {signal});
        this.element.addEventListener('input', this.onInput, {signal});
        this.element.addEventListener('change', this.onFile, {signal});
        this.element.addEventListener('keydown', this.onKey, {signal});
        this.element.addEventListener('agent:clear-attachments', this.clear, {signal});
        document.addEventListener('pointerdown', this.onOutside, {signal});
    }

    /** Translate menu status labels from server-rendered attributes. */
    private label(key: string): string { return this.element?.getAttribute(`data-picker-${key}`) ?? key; }

    /** Open the attachment picker and load its categories. */
    private open(): void {
        if (!this.menu || this.element?.dataset.attachmentsDisabled === 'true') return;
        this.menu.hidden = false;
        this.element?.querySelector('[data-artifact-plus]')?.setAttribute('aria-expanded', 'true');
        this.category = null;
        if (this.search) { this.search.value = ''; this.search.focus(); }
        void this.load(false);
    }

    /** Dismiss the menu without modifying the message text or attachment selection. */
    private close(): void {
        if (this.menu) this.menu.hidden = true;
        this.request?.abort();
        if (this.timer !== null) window.clearTimeout(this.timer);
        this.element?.querySelector('[data-artifact-plus]')?.setAttribute('aria-expanded', 'false');
    }

    /** Fetch a bounded category or candidate page, discarding stale searches. */
    private async load(more: boolean): Promise<void> {
        const endpoint = this.element?.getAttribute('data-artifact-search-url');
        if (!endpoint || !this.list) return;
        this.request?.abort();
        const request = new AbortController();
        this.request = request;
        const url = new URL(endpoint, window.location.origin);
        if (this.category) url.searchParams.set('type', this.category.key);
        url.searchParams.set('q', this.search?.value ?? '');
        if (more && this.cursor) url.searchParams.set('cursor', this.cursor);
        if (!more) this.list.replaceChildren();
        this.status(this.label('loading'));
        try {
            const response = await fetch(url, {signal: request.signal, credentials: 'same-origin'});
            if (!response.ok) throw new Error(this.label('error'));
            const data = await response.json();
            if (request.signal.aborted) return;
            if (!this.category) this.categories = data.types ?? [];
            else this.choices = more ? [...this.choices, ...data.items] : data.items;
            this.cursor = data.cursor ?? null;
            this.index = 0;
            this.render();
        } catch (error) {
            if (!request.signal.aborted) this.status(error instanceof Error ? error.message : this.label('error'));
        }
    }

    /** Render safe text rows, using the reference's rounded hover treatment. */
    private render(): void {
        if (!this.list) return;
        this.list.replaceChildren();
        if (this.category?.upload) this.addOption(this.label('upload'), 'fa-arrow-up-from-bracket', 'upload');
        const query = (this.search?.value ?? '').toLowerCase();
        if (this.category) {
            for (const [index, choice] of this.choices.entries()) this.addOption(choice.title, choice.icon, `choice:${index}`);
        } else {
            for (const category of this.categories) {
                if (category.label.toLowerCase().includes(query) || category.key.includes(query)) this.addOption(category.label, category.icon, `category:${category.key}`);
            }
        }
        this.status(this.list.childElementCount ? '' : this.label('empty'));
        const back = this.element?.querySelector<HTMLElement>('[data-artifact-back]');
        if (back) back.hidden = !this.category;
        const more = this.element?.querySelector<HTMLElement>('[data-artifact-more]');
        if (more) more.hidden = !this.cursor;
        this.highlight();
    }

    /** Append an option using trusted CSS and textContent for source labels. */
    private addOption(title: string, icon: string, action: string): void {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.artifactOption = action; button.setAttribute('role', 'option');
        button.className = 'flex w-full items-center gap-3 rounded-xl px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-base dark:text-zinc-100';
        const symbol = document.createElement('i'); symbol.className = `fa-solid ${icon}`; symbol.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span'); label.className = 'truncate'; label.textContent = title;
        button.append(symbol, label); this.list?.append(button);
    }

    /** Mark the keyboard-selected option without moving focus away from typing. */
    private highlight(): void {
        const options = this.options();
        options.forEach(this.unhighlight);
        const active = options[this.index];
        if (active) { active.classList.add('bg-base'); active.setAttribute('aria-selected', 'true'); active.scrollIntoView({block: 'nearest'}); }
    }

    /** Clear one option's visual keyboard-selection state. */
    private unhighlight(button: HTMLButtonElement): void { button.classList.remove('bg-base'); button.setAttribute('aria-selected', 'false'); }

    /** Read currently visible menu options in keyboard order. */
    private options(): HTMLButtonElement[] { return [...this.list?.querySelectorAll<HTMLButtonElement>('[data-artifact-option]') ?? []]; }

    /** Select a candidate once and publish draft metadata. */
    private select(choice: ArtifactChoice): void {
        if (this.selected.length >= 20) { this.status(this.label('limit')); return; }
        if (!this.selected.some(this.matchesChoice.bind(this, choice))) this.selected.push(choice);
        this.close(); this.publish(); this.input?.focus();
    }

    /** Compare candidate identities independently of timestamped selection tokens. */
    private matchesChoice(left: ArtifactChoice, right: ArtifactChoice): boolean { return left.key === right.key; }

    /** Render removable chips and notify the containing chat of the draft state. */
    private publish(): void {
        const chips = this.element?.querySelector('[data-artifact-chips]');
        chips?.replaceChildren();
        for (const [index, choice] of this.selected.entries()) {
            const chip = document.createElement('button'); chip.type = 'button'; chip.dataset.artifactRemove = String(index);
            chip.className = 'max-w-full truncate rounded-lg border border-gray-200 bg-gray-50 px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-700';
            chip.textContent = `${choice.title} ×`; chip.setAttribute('aria-label', `${this.label('remove')} ${choice.title}`); chips?.append(chip);
        }
        this.element?.dispatchEvent(new CustomEvent('agent:attachments-changed', {bubbles: true, detail: {items: this.selected, busy: this.uploading}}));
    }

    /** Show loading, empty, or actionable error text within the drop-up. */
    private status(text: string): void { const status = this.element?.querySelector<HTMLElement>('[data-artifact-status]'); if (status) status.textContent = text; }

    /** Route plus, category, upload, removal and pagination actions through one menu. */
    private onClick = (event: MouseEvent): void => {
        const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('button') : null;
        if (!button || this.element?.dataset.attachmentsDisabled === 'true') return;
        if (button.hasAttribute('data-artifact-plus')) { if (this.menu?.hidden) this.open(); else this.close(); }
        if (button.hasAttribute('data-artifact-back')) { this.category = null; if (this.search) this.search.value = ''; void this.load(false); }
        if (button.hasAttribute('data-artifact-more')) void this.load(true);
        if (button.dataset.artifactRemove !== undefined) { this.selected.splice(Number(button.dataset.artifactRemove), 1); this.publish(); }
        const action = button.dataset.artifactOption;
        if (action?.startsWith('category:')) {
            this.category = this.categories.find(this.matchesCategory.bind(this, action.slice(9))) ?? null;
            if (this.search) this.search.value = '';
            this.search?.focus(); void this.load(false);
        } else if (action?.startsWith('choice:')) this.select(this.choices[Number(action.slice(7))]);
        else if (action === 'upload' && !this.uploading) this.element?.querySelector<HTMLInputElement>('[data-artifact-file]')?.click();
    };

    /** Match the registry's stable category key. */
    private matchesCategory(key: string, category: ArtifactCategory): boolean { return category.key === key; }

    /** Debounce queries typed into the attachment search field. */
    private onInput = (event: Event): void => {
        if (event.target === this.search) {
            if (this.timer !== null) window.clearTimeout(this.timer);
            this.timer = window.setTimeout(this.refresh, 200);
        }
    };

    /** Execute the most recent debounced search. */
    private refresh = (): void => { void this.load(false); };

    /** Keep Enter/Escape within the attachment menu and support arrow-key selection. */
    private onKey = (event: KeyboardEvent): void => {
        if (this.menu?.hidden || event.isComposing) return;
        if (['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
            event.preventDefault(); event.stopPropagation();
            if (event.key === 'Escape') { this.close(); this.input?.focus(); return; }
            const options = this.options();
            if (event.key === 'Enter') {
                const target = event.target;
                if (target instanceof HTMLButtonElement) target.click();
                else options[this.index]?.click();
                return;
            }
            this.index = (this.index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % Math.max(options.length, 1); this.highlight();
        }
    };

    /** Dismiss when clicking outside the picker or back into the editor. */
    private onOutside = (event: PointerEvent): void => {
        if (event.target instanceof Node && (!this.element?.contains(event.target) || this.input?.contains(event.target))) this.close();
    };

    /** Send a native file-picker selection through the existing artifact endpoint. */
    private onFile = (event: Event): void => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.matches('[data-artifact-file]') || !input.files?.[0] || !this.category) return;
        void this.uploadFile(input.files[0], this.category.key);
        input.value = '';
    };

    /** Upload one selected file and ignore results for a replaced draft. */
    private async uploadFile(file: File, type: string): Promise<void> {
        const endpoint = this.element?.getAttribute('data-artifact-upload-url');
        const status = this.element?.querySelector<HTMLElement>('[data-artifact-upload-status]');
        if (!endpoint || !status || this.uploading) return;
        if (this.selected.length >= 20) { status.textContent = this.label('limit'); return; }
        const revision = this.revision;
        const csrf = this.element?.querySelector<HTMLInputElement>('[name=csrfmiddlewaretoken]')?.value ?? '';
        this.uploading = true; status.textContent = this.label('uploading'); this.publish();
        try {
            const form = new FormData(); form.set('type', type); form.set('file', file);
            const response = await fetch(endpoint, {method: 'POST', body: form, headers: {'X-CSRFToken': csrf}, credentials: 'same-origin', signal: this.lifecycle.signal});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error ?? this.label('error'));
            if (revision === this.revision) {
                this.select(data);
                status.textContent = '';
            }
        } catch (error) {
            if (revision === this.revision && !this.lifecycle.signal.aborted) status.textContent = error instanceof Error ? error.message : this.label('error');
        } finally { this.uploading = false; this.publish(); }
    }

    /** Clear the draft when sent or switched, ignoring uploads for an older draft. */
    private clear = (): void => {
        this.revision++;
        this.selected = [];
        const status = this.element?.querySelector('[data-artifact-upload-status]');
        if (status) status.textContent = '';
        this.close(); this.publish();
    };

    /** Abort requests and timers when the form leaves the document. */
    public override destroy(): void { this.lifecycle.abort(); this.request?.abort(); if (this.timer !== null) window.clearTimeout(this.timer); super.destroy(); }
}
