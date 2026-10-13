import BaseComponent from './BaseComponent';

/** Add keyboard navigation to shared dropdowns without changing their Alpine state. */
export default class DropdownKeyboard extends BaseComponent {
    private lifecycle: AbortController | null = null;
    private externalTrigger: HTMLElement | null = null;
    private previousFocus: HTMLElement | null = null;

    /** Bind navigation to this dropdown and any external search trigger. */
    public override initialize(): void {
        if (!this.element) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        const handler = this.handleKeydown.bind(this);
        const options = { signal: this.lifecycle.signal };
        this.element.addEventListener('keydown', handler, options);
        this.element.addEventListener('htmx:beforeCleanupElement', this.handleCleanup.bind(this), options);
        this.element.addEventListener('dropdown-dismissed', this.restorePreviousFocus.bind(this), options);
        const trigger = this.element.querySelector<HTMLElement>('[aria-haspopup="true"]');
        trigger?.addEventListener('pointerdown', this.rememberPreviousFocus.bind(this), options);
        trigger?.addEventListener('click', this.focusTrigger.bind(this), options);
        const selector = this.element.dataset.dropdownTriggerSelector;
        this.externalTrigger = selector ? document.querySelector<HTMLElement>(selector) : null;
        if (this.externalTrigger && !this.element.contains(this.externalTrigger)) {
            this.externalTrigger.addEventListener('keydown', handler, options);
        }
    }

    /** Focus the clicked trigger even when a keyboard shortcut invokes its click programmatically. */
    private focusTrigger(event: MouseEvent): void {
        this.rememberPreviousFocus();
        if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
    }

    /** Remember the field being edited before a pointer or shortcut moves focus into this dropdown. */
    private rememberPreviousFocus(): void {
        const active = document.activeElement;
        if (active instanceof HTMLElement && active !== document.body && !this.element?.contains(active)) {
            this.previousFocus = active;
        }
    }

    /** Return to the original field on dismissal without overriding a deliberate click elsewhere. */
    private restorePreviousFocus(event: Event): void {
        if (event.target !== this.element || !this.element) return;
        const previous = this.previousFocus;
        this.previousFocus = null;
        if (!this.element.contains(document.activeElement)) return;
        const target = previous ?? this.externalTrigger ?? this.element.querySelector<HTMLElement>('[aria-haspopup="true"]');
        if (!target?.isConnected || target.matches(':disabled, [aria-disabled="true"]') || target.closest('[inert]')) return;
        if (!target.getClientRects().length || window.getComputedStyle(target).visibility === 'hidden') return;
        target.focus({ preventScroll: true });
    }

    /** Rebind external triggers that may have been replaced by an HTMX swap. */
    public override onAfterSwap(): void {
        this.initialize();
    }

    /** Release external listeners before HTMX removes the dropdown root. */
    private handleCleanup(event: Event): void {
        if (event.target === this.element) this.destroy();
    }

    /** Release all listeners when the dropdown is destroyed. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        this.externalTrigger = null;
        this.previousFocus = null;
        super.destroy();
    }

    /** Navigate visible items or dismiss only the currently focused menu level with Escape. */
    private handleKeydown(event: KeyboardEvent): void {
        if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Escape') return;
        const target = event.target;
        if (!(target instanceof HTMLElement) || !this.element) return;
        const menu = this.element.querySelector<HTMLElement>('[data-dropdown-panel]');
        if (!menu || menu.getAttribute('aria-hidden') === 'true' || !menu.getClientRects().length || window.getComputedStyle(menu).visibility === 'hidden') return;
        const targetMenu = target.closest('[data-dropdown-panel]');
        const ownTrigger = this.element.querySelector<HTMLElement>('[aria-haspopup="true"]');
        if (target !== ownTrigger && target !== this.externalTrigger) {
            if (targetMenu !== menu) return;
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            this.element.dispatchEvent(new CustomEvent('dropdown-dismiss'));
            if (this.element.hasAttribute('data-dropdown-submenu')) ownTrigger?.focus({ preventScroll: true });
            return;
        }
        // Preserve native arrow navigation in select fields, editors, and numeric inputs.
        if (target.closest('select, textarea, [contenteditable]:not([contenteditable="false"])')) return;
        if (target instanceof HTMLInputElement && target.type !== 'search' && target.type !== 'text') return;
        const items: HTMLElement[] = [];
        for (const item of menu.querySelectorAll<HTMLElement>('[role="menuitem"], button, a[href], [tabindex="0"]')) {
            if (item.closest('[data-dropdown-panel]') !== menu) continue;
            if (item.matches(':disabled, [aria-disabled="true"]') || item.closest('[inert]')) continue;
            if (!item.getClientRects().length || window.getComputedStyle(item).visibility === 'hidden') continue;
            items.push(item);
        }
        if (!items.length) return;

        const currentIndex = items.indexOf(document.activeElement as HTMLElement);
        const step = event.key === 'ArrowDown' ? 1 : -1;
        const nextIndex = currentIndex < 0
            ? (step > 0 ? 0 : items.length - 1)
            : (currentIndex + step + items.length) % items.length;
        event.preventDefault();
        event.stopPropagation();
        items[nextIndex].focus();
        items[nextIndex].scrollIntoView({ block: 'nearest' });
    }
}
