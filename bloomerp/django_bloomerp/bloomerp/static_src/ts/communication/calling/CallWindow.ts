import type { CallParticipant, CallActionContext } from './definition';

/** Present owner-tab identities, media and controls without owning credentials or a transport. */
export default class CallWindow {
    private child: Window | null = null;
    private timer: number | null = null;
    private tiles = new Map<string, HTMLElement>();

    /** Bind the owner controls and normalized participant presentation supplied by any transport. */
    public constructor(private owner: HTMLElement, private action: (button: HTMLElement, context?: CallActionContext) => Promise<void>, private participants: () => CallParticipant[]) {}

    /** Open during the initiating gesture, or focus the existing presentation tab. */
    public open(): boolean {
        if (!this.child || this.child.closed) {
            this.child = window.open('about:blank', '_blank');
            this.tiles.clear();
        }
        if (!this.child) return false;
        this.render();
        this.child.focus();
        if (this.timer === null) this.timer = window.setInterval(this.sync, 250);
        this.sync();
        return true;
    }

    /** Reuse translated Django markup, stylesheets, icons and the current Bloomerp theme. */
    private render(): void {
        const doc = this.child!.document;
        if (doc.querySelector('[data-call-view]')) return;
        this.tiles.clear();
        doc.documentElement.lang = document.documentElement.lang;
        doc.documentElement.className = document.documentElement.className;
        const base = doc.createElement('base');
        base.href = document.baseURI;
        doc.head.replaceChildren(base);
        for (const asset of document.head.querySelectorAll('link[rel="stylesheet"], style')) {
            doc.head.append(doc.importNode(asset, true));
        }
        const template = this.owner.querySelector<HTMLTemplateElement>('[data-call-view-template]')!;
        doc.body.replaceChildren(doc.importNode(template.content, true));
        doc.body.className = 'bg-base text-gray-800 font-sans';
        doc.title = `${doc.querySelector('h1')!.textContent} · Bloomerp`;
        const controls = doc.querySelector<HTMLElement>('[data-call-toolbar]')!;
        for (const source of this.owner.querySelectorAll<HTMLButtonElement>('[data-call-action]')) {
            if (['open', 'admit'].includes(source.dataset.callAction || '')) continue;
            const button = doc.importNode(source, true);
            button.title = source.textContent?.trim() || '';
            button.setAttribute('aria-label', button.title);
            /** Dispatch to the original authorized control; the child never makes requests. */
            button.addEventListener('click', async (): Promise<void> => {
                if (source.hidden || source.disabled) return;
                const view = doc.defaultView!;
                /** Invoke capture on the clicked document while its user activation is live. */
                async function capture(): Promise<MediaStream> {
                    const stream = await view.navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
                    if (view.closed) {
                        for (const track of stream.getTracks()) track.stop();
                        throw new DOMException('Call tab closed during screen selection', 'AbortError');
                    }
                    return stream;
                }
                await this.action(source, {
                    capture,
                    /** Copy in the focused call tab rather than its inactive opener. */
                    copy(text: string): Promise<void> { return view.navigator.clipboard.writeText(text); },
                });
            });
            controls.append(button);
        }
    }

    /** Mirror state and roster without acquiring capture devices or duplicating audio playback. */
    private sync = (): void => {
        if (!this.child || this.child.closed) { this.release(); return; }
        try {
            this.render();
            const doc = this.child.document;
            doc.documentElement.className = document.documentElement.className;
            for (const attribute of ['data-call-status', 'data-call-error']) {
                const source = this.owner.querySelector<HTMLElement>(`[${attribute}]`)!;
                const target = doc.querySelector<HTMLElement>(`[${attribute}]`)!;
                target.textContent = source.textContent;
                target.hidden = source.hidden;
            }
            for (const target of doc.querySelectorAll<HTMLButtonElement>('[data-call-toolbar] [data-call-action]')) {
                const source = this.owner.querySelector<HTMLButtonElement>(`[data-call-action="${target.dataset.callAction}"]`)!;
                target.hidden = source.hidden;
                target.disabled = source.disabled;
                const pressed = source.getAttribute('aria-pressed');
                if (pressed !== null) target.setAttribute('aria-pressed', pressed);
                if (target.dataset.callAction === 'screen') {
                    target.querySelector<HTMLElement>('[data-share-start]')!.hidden = pressed === 'true';
                    target.querySelector<HTMLElement>('[data-share-stop]')!.hidden = pressed !== 'true';
                    target.title = target.querySelector<HTMLElement>(pressed === 'true' ? '[data-share-stop]' : '[data-share-start]')!.textContent || '';
                    target.setAttribute('aria-label', target.title);
                }
                const icon = target.querySelector('i');
                if (icon && target.dataset.callAction === 'microphone') icon.className = `fa-solid ${pressed === 'true' ? 'fa-microphone' : 'fa-microphone-slash'}`;
                if (icon && target.dataset.callAction === 'camera') icon.className = `fa-solid ${pressed === 'true' ? 'fa-video' : 'fa-video-slash'}`;
            }
            const waiting = this.owner.querySelector<HTMLElement>('[data-call-admissions]')!;
            const targetWaiting = doc.querySelector<HTMLElement>('[data-call-admissions]')!;
            if (targetWaiting.dataset.source !== waiting.innerHTML) {
                targetWaiting.dataset.source = waiting.innerHTML;
                targetWaiting.replaceChildren();
                for (const row of waiting.children) {
                    const clone = doc.importNode(row, true);
                    const sources = row.querySelectorAll<HTMLElement>('[data-call-action]');
                    clone.querySelectorAll<HTMLElement>('[data-call-action]').forEach((button: HTMLElement, index: number): void => {
                        /** Delegate host decisions to the original authorized request handler. */
                        button.addEventListener('click', (): void => { void this.action(sources[index]); });
                    });
                    targetWaiting.append(clone);
                }
            }
            this.renderParticipants(doc);
        } catch {
            // A user can navigate the presentation tab away from the application's origin.
            this.release();
        }
    };

    /** Keep stable participant tiles across camera toggles, joins and departures. */
    private renderParticipants(doc: Document): void {
        let participants = this.participants();
        // Older transports can still present their media without any provider-specific UI branch.
        if (!participants.length) {
            participants = Array.from(this.owner.querySelectorAll<HTMLVideoElement>('[data-call-media] video')).map((video: HTMLVideoElement, index: number): CallParticipant => ({ id: String(index), displayName: video.getAttribute('aria-label') || '', video }));
        }
        const count = participants.length;
        const screens = participants.filter((person: CallParticipant): boolean => Boolean(person.screenVideo)).map((person: CallParticipant): CallParticipant => ({ ...person, id: `${person.id}:screen`, video: person.screenVideo }));
        participants = [...screens, ...participants];
        const screenIds = new Set(screens.map((person: CallParticipant): string => person.id));
        const ids = new Set(participants.map((person: CallParticipant): string => person.id));
        for (const [id, tile] of this.tiles) {
            if (!ids.has(id)) { tile.querySelector('video')!.srcObject = null; tile.remove(); this.tiles.delete(id); }
        }
        const grid = doc.querySelector<HTMLElement>('[data-call-participants]')!;
        grid.dataset.count = String(participants.length);
        doc.querySelector('[data-call-count]')!.textContent = String(count);
        doc.querySelector<HTMLElement>('[data-call-empty]')!.hidden = participants.length > 0;
        for (const person of participants) {
            let tile = this.tiles.get(person.id);
            if (!tile) {
                const template = doc.querySelector<HTMLTemplateElement>('[data-call-participant-template]')!;
                tile = doc.importNode(template.content.firstElementChild!, true) as HTMLElement;
                grid.append(tile);
                this.tiles.set(person.id, tile);
            }
            tile.dataset.screen = String(screenIds.has(person.id));
            tile.querySelector('[data-participant-name]')!.textContent = person.displayName;
            tile.querySelector<HTMLElement>('[data-participant-local]')!.hidden = !person.local;
            tile.querySelector('[data-participant-initials]')!.textContent = person.initials || person.displayName.split(/\s+/).slice(0, 2).map((part: string): string => part[0] || '').join('').toUpperCase() || '?';
            const avatar = tile.querySelector<HTMLElement>('[data-participant-avatar]')!;
            const image = avatar.querySelector('img')!;
            const url = this.avatarUrl(person.avatar);
            if (image.dataset.avatar !== url) {
                image.dataset.avatar = url;
                image.hidden = !url;
                /** Fall back to the provider initials if an avatar cannot be loaded. */
                image.onerror = (): void => { image.hidden = true; };
                if (url) image.src = url;
                else image.removeAttribute('src');
            }
            const initials = avatar.querySelector<HTMLElement>('[data-participant-initials]')!;
            initials.hidden = Boolean(url) && !image.hidden;
            const video = tile.querySelector('video')!;
            video.muted = true;
            const stream = person.video?.srcObject || null;
            if (video.srcObject !== stream) {
                video.srcObject = stream;
                if (stream) void video.play().catch((): void => { /* Muted playback can resume after a gesture. */ });
            }
            video.hidden = !stream;
            avatar.hidden = Boolean(stream);
            tile.querySelector<HTMLElement>('[data-participant-camera-off]')!.hidden = Boolean(stream);
        }
    }

    /** Permit only normal image URLs and resolve relative uploads against the owner page. */
    private avatarUrl(value?: string): string {
        if (!value) return '';
        try { const url = new URL(value, document.baseURI); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; }
        catch { return ''; }
    }

    /** Forget a closed view without stopping any owner media tracks. */
    private release(): void {
        if (this.timer !== null) window.clearInterval(this.timer);
        this.timer = null;
        this.child = null;
        this.tiles.clear();
    }

    /** Close the presentation only when its original application is destroyed. */
    public destroy(): void { this.child?.close(); this.release(); }
}
