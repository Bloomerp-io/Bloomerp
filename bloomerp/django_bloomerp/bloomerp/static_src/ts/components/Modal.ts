import htmx from 'htmx.org';
import BaseComponent from './BaseComponent';
import { activateModal, buildModalShell, deactivateModal, getTopModal, MODAL_SIZE_CLASSES } from '../utils/modals';

/** Manage one dialog while shared utilities own its shell and open-modal stack. */
export class Modal extends BaseComponent {
    private containerElement: HTMLElement | null = null;
    private modalBodyElement: HTMLElement | null = null;
    private lifecycle: AbortController | null = null;
    private closeAnimationTimeoutId: number | null = null;
    private openAnimationTimeoutId: number | null = null;
    private opener: HTMLElement | null = null;
    private parentModal: Modal | null = null;
    private isFullscreen = false;
    private opened = false;
    private destroyed = false;

    /** Materialize a declaration and bind lifecycle-safe modal controls. */
    public initialize(): void {
        if (!this.element?.id) return;
        buildModalShell(this.element);
        this.containerElement = this.element.querySelector('[data-modal-container]');
        this.modalBodyElement = this.element.querySelector('[data-modal-body]');
        this.element.dataset.defaultModalSize ??= this.element.dataset.modalSize || 'md';
        this.element.dataset.defaultModalPadding ??= this.element.dataset.modalPadding || 'p-3';
        this.element.dataset.defaultBackdropClickClose ??= this.element.dataset.backdropClickClose || 'true';
        this.setSize(this.element.dataset.modalSize || 'md');
        this.setPadding(this.element.dataset.modalPadding || 'p-3');
        if (!this.portalToDocumentBody()) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        const options = { signal: this.lifecycle.signal };
        document.addEventListener('click', this.handleTriggerClick, { ...options, capture: true });
        document.addEventListener('keydown', this.handleKeyDown, options);
        document.body.addEventListener('bloomerp:close-modal', this.handleCloseEvent, options);
        this.element.addEventListener('click', this.handleBackdropClick, options);
        this.element.addEventListener('htmx:beforeCleanupElement', this.handleCleanup, options);
    }

    /** Portal outside stacking contexts without deleting an active duplicate. */
    private portalToDocumentBody(): boolean {
        if (this.element.parentElement === document.body) return true;
        const existing = Array.from(document.querySelectorAll<HTMLElement>('[bloomerp-component="modal"]'))
            .find((element: HTMLElement): boolean => element !== this.element && element.id === this.element.id);
        if (existing) {
            const instance = (existing as HTMLElement & { __bloomerp_component?: Modal }).__bloomerp_component;
            if (instance?.opened) {
                this.element.remove();
                return false;
            }
            instance?.destroy();
            existing.remove();
        }
        document.body.appendChild(this.element);
        return true;
    }

    /** Handle legacy attributes once, including triggers inserted by HTMX. */
    private handleTriggerClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const trigger = event.target.closest<HTMLElement>(
            '[bloomerp-open-modal], [bloomerp-close-modal], [bloomerp-full-screen-modal], [bloomerp-set-modal-title-for]',
        );
        if (!trigger || trigger.hasAttribute('disabled')) return;
        const id = this.element.id;
        if (trigger.getAttribute('bloomerp-set-modal-title-for') === id) {
            const title = trigger.getAttribute('bloomerp-set-modal-title-to');
            const size = trigger.getAttribute('bloomerp-set-modal-size-to');
            if (title) this.setTitle(title);
            if (size) this.setSize(size);
        }
        if (trigger.getAttribute('bloomerp-open-modal') === id) {
            this.setOpener(trigger);
            this.open();
        }
        if (trigger.getAttribute('bloomerp-close-modal') === id) this.close();
        if (trigger.getAttribute('bloomerp-full-screen-modal') === id) this.toggleFullscreen();
    };

    /** Close only the active dialog when its backdrop is clicked. */
    private handleBackdropClick = (event: MouseEvent): void => {
        if (event.target === this.element && getTopModal() === this
            && this.element.dataset.backdropClickClose !== 'false'
            && this.element.dataset.modalClosable !== 'false') this.close();
    };

    /** Keep Escape and Tab scoped to the most recently opened dialog. */
    private handleKeyDown = (event: KeyboardEvent): void => {
        if (getTopModal() !== this || event.defaultPrevented) return;
        if (event.key === 'Escape' && this.element.dataset.modalClosable !== 'false') {
            event.preventDefault();
            this.close();
        }
        if (event.key !== 'Tab') return;
        const elements = Array.from(this.containerElement.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        )).filter((element: HTMLElement): boolean => !element.hasAttribute('disabled') && element.getClientRects().length > 0);
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (!first) {
            event.preventDefault();
            this.focus();
        } else if (!this.containerElement.contains(document.activeElement) || document.activeElement === this.containerElement) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
        } else if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };

    /** Preserve the existing server-emitted close event contract. */
    private handleCloseEvent = (event: Event): void => {
        if ((event as CustomEvent<{ modalId?: string }>).detail?.modalId === this.element.id) this.close();
    };

    /** Dispose initialized descendants before HTMX removes their DOM. */
    private handleCleanup = (event: Event): void => {
        const element = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (!element) return;
        const instance = (element as HTMLElement & { __bloomerp_component?: BaseComponent }).__bloomerp_component;
        instance?.destroy();
    };

    /** Wire swapped forms before their eagerly initialized Save shortcuts can run. */
    public onAfterSwap(): void {
        for (const child of Array.from(this.modalBodyElement?.children || [])) {
            htmx.process(child as HTMLElement);
        }
    }

    /** Remember the launching control and owning parent before content is loaded. */
    public setOpener(opener: HTMLElement): void {
        if (this.opened) return;
        this.opener = opener;
        const parent = opener.closest<HTMLElement>('[bloomerp-component="modal"]');
        this.parentModal = parent !== this.element
            ? (parent as HTMLElement & { __bloomerp_component?: Modal })?.__bloomerp_component || null
            : null;
    }

    /** Focus the dialog without scrolling its preserved form contents. */
    public focus(): void {
        this.containerElement?.focus({ preventScroll: true });
    }

    /** Open this instance without replacing any other dialog's contents. */
    public open(): void {
        if (this.destroyed || !this.element.isConnected) return;
        if (this.closeAnimationTimeoutId !== null) {
            window.clearTimeout(this.closeAnimationTimeoutId);
            this.closeAnimationTimeoutId = null;
            this.finishOpening();
        }
        if (this.opened) return;
        this.opened = true;
        if (!this.opener && document.activeElement instanceof HTMLElement) this.setOpener(document.activeElement);
        this.element.classList.remove('hidden');
        this.element.classList.add('flex');
        activateModal(this, this.opener);
        this.focus();
        this.openAnimationTimeoutId = window.setTimeout(this.finishOpening, 10);
        this.element.dispatchEvent(new CustomEvent('bloomerp:modal-opened', {
            bubbles: true, detail: { modalId: this.element.id },
        }));
    }

    /** Apply the enter animation only while this instance is still open. */
    private finishOpening = (): void => {
        this.openAnimationTimeoutId = null;
        if (!this.opened || this.destroyed || this.closeAnimationTimeoutId !== null) return;
        this.containerElement.classList.remove('scale-95', 'opacity-0');
        this.containerElement.classList.add('scale-100', 'opacity-100');
    };

    /** Close this dialog and its owned children, preserving any surviving parent. */
    public close(): void {
        if (!this.opened || this.closeAnimationTimeoutId !== null) return;
        this.closeChildren();
        this.containerElement.classList.remove('scale-100', 'opacity-100');
        this.containerElement.classList.add('scale-95', 'opacity-0');
        this.closeAnimationTimeoutId = window.setTimeout(this.finishClosing, 200);
    }

    /** Complete closure before notifying owners and disposing temporary form content. */
    private finishClosing = (): void => {
        this.closeAnimationTimeoutId = null;
        this.opened = false;
        this.element.classList.remove('flex');
        this.element.classList.add('hidden');
        this.element.inert = false;
        this.element.setAttribute('aria-hidden', 'true');
        deactivateModal(this);
        this.opener = null;
        this.element.dispatchEvent(new CustomEvent('bloomerp:modal-closed', {
            bubbles: true, detail: { modalId: this.element.id },
        }));
        if (this.element.dataset.modalDisposable === 'true') this.destroy();
        const callback = this.element.dataset.onClose;
        if (callback) new Function(callback)();
    };

    /** Dispose child dialogs when their owning form is no longer available. */
    private closeChildren(): void {
        for (const element of document.querySelectorAll<HTMLElement>('[bloomerp-component="modal"]')) {
            const child = (element as HTMLElement & { __bloomerp_component?: Modal }).__bloomerp_component;
            if (child !== this && child?.parentModal === this) {
                if (child.element.dataset.modalDisposable === 'true') child.destroy();
                else child.close();
            }
        }
    }

    /** Release listeners, requests and child components when an instance is removed. */
    public destroy(): void {
        if (this.destroyed) return;
        this.destroyed = true;
        this.closeChildren();
        this.lifecycle?.abort();
        if (this.closeAnimationTimeoutId !== null) window.clearTimeout(this.closeAnimationTimeoutId);
        if (this.openAnimationTimeoutId !== null) window.clearTimeout(this.openAnimationTimeoutId);
        for (const element of [this.element, ...this.element.querySelectorAll<HTMLElement>('*')]) {
            htmx.trigger(element, 'htmx:abort');
            if (element === this.element) continue;
            const instance = (element as HTMLElement & { __bloomerp_component?: BaseComponent }).__bloomerp_component;
            instance?.destroy();
        }
        deactivateModal(this);
        if (this.element.dataset.modalDisposable === 'true') this.element.remove();
        super.destroy();
    }

    /** Return the stable, instance-local HTMX content target. */
    public getBodyElement(): HTMLElement | null {
        return this.modalBodyElement;
    }

    /** Update the visible title and accessible dialog name using plain text. */
    public setTitle(title: string): void {
        const heading = this.containerElement?.querySelector('h3');
        if (heading) heading.textContent = title;
        this.containerElement?.setAttribute('aria-label', title);
    }

    /** Change the preferred size while respecting a temporary fullscreen state. */
    public setSize(size: string): void {
        this.element.dataset.modalSize = size in MODAL_SIZE_CLASSES ? size : 'md';
        this.applySize();
    }

    /** Apply either fullscreen geometry or the configured declaration size. */
    private applySize(): void {
        if (!this.containerElement || !this.modalBodyElement) return;
        const size = this.isFullscreen ? 'full' : this.element.dataset.modalSize || 'md';
        this.containerElement.classList.remove(...Object.values(MODAL_SIZE_CLASSES));
        this.containerElement.classList.add(MODAL_SIZE_CLASSES[size]);
        this.containerElement.classList.toggle('h-full', size === 'full');
        this.containerElement.classList.toggle('rounded-none', size === 'full');
        this.modalBodyElement.classList.toggle('flex-1', size === 'full');
        this.modalBodyElement.classList.toggle('max-h-96', size !== 'full');
    }

    /** Toggle fullscreen while retaining the configured size and body padding. */
    public toggleFullscreen(): void {
        this.isFullscreen = !this.isFullscreen;
        this.applySize();
    }

    /** Configure whether clicking this dialog's backdrop closes it. */
    public setBackdrop(enabled: boolean): void {
        this.element.dataset.backdropClickClose = String(enabled);
    }

    /** Replace only padding classes while retaining caller-supplied body styling. */
    public setPadding(padding: string): void {
        if (!this.modalBodyElement) return;
        for (const className of Array.from(this.modalBodyElement.classList)) {
            if (/^!?p(?:[trblxyse])?-.+$/.test(className)) this.modalBodyElement.classList.remove(className);
        }
        const normalized = padding.trim() || this.element.dataset.defaultModalPadding || 'p-3';
        this.element.dataset.modalPadding = normalized;
        this.modalBodyElement.classList.add(...normalized.split(/\s+/));
    }

    /** Restore declaration defaults for legacy callers that reuse one modal. */
    public resetToDefaults(): void {
        this.isFullscreen = false;
        this.setSize(this.element.dataset.defaultModalSize || 'md');
        this.setPadding(this.element.dataset.defaultModalPadding || 'p-3');
        this.setBackdrop(this.element.dataset.defaultBackdropClickClose !== 'false');
    }
}
