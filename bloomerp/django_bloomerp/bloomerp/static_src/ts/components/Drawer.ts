import BaseComponent from './BaseComponent';

const OPEN_DRAWER_ATTRIBUTE = 'bloomerp-open-drawer';
const CLOSE_DRAWER_ATTRIBUTE = 'bloomerp-close-drawer';

type DrawerSide = 'left' | 'right';

/**
 * Drawer Component
 *
 * Manages drawer behavior including:
 * - Opening/closing with animations
 * - Optional backdrop click-to-close
 * - Keyboard navigation (ESC to close)
 *
 * Usage in HTML:
 * <div bloomerp-component="drawer" id="my-drawer">
 *   <!-- drawer content -->
 * </div>
 */
export class Drawer extends BaseComponent {
    private drawerId: string = '';
    private backdropElement: HTMLElement | null = null;
    private panelElement: HTMLElement | null = null;
    private side: DrawerSide = 'right';
    private placeholder: Comment | null = null;
    private animationTimer: ReturnType<typeof setTimeout> | null = null;
    private previousBodyOverflow: string | null = null;
    private returnFocus: HTMLElement | null = null;


    private backdropClickHandler: ((e: MouseEvent) => void) | null = null;
    private escapeKeyHandler: ((e: KeyboardEvent) => void) | null = null;

    private triggerHandlers: Array<{ element: EventTarget; handler: EventListener }> = [];

    /** Bind drawer controls and release them when its owning view is replaced. */
    public initialize(): void {
        if (!this.element) {
            console.warn('Drawer component: element is null');
            return;
        }

        this.drawerId = this.element.id;
        if (!this.drawerId) {
            console.warn('Drawer component requires an id attribute', this.element);
            return;
        }

        this.element.addEventListener('htmx:beforeCleanupElement', this.onCleanup);
        this.syncElements();

        if (!this.panelElement) {
            console.warn(`Drawer structure not found for ID: ${this.drawerId}`, {
                backdrop: this.backdropElement,
                panel: this.panelElement,
            });
            return;
        }

        this.setupBackdropClickHandler();
        this.setupEscapeKeyHandler();
        this.setupTriggerButtons();
    }

    public onAfterSwap(): void {
        this.setupTriggerButtons();
    }

    private syncElements(): void {
        if (!this.element) return;

        this.backdropElement = this.element;
        this.panelElement = this.backdropElement.querySelector(
            `#${this.drawerId}-panel`
        ) as HTMLElement | null;

        if (!this.panelElement) {
            this.panelElement = this.backdropElement.querySelector(
                '[data-drawer-panel]'
            ) as HTMLElement | null;
        }

        const sideAttribute = this.element.getAttribute('data-side');
        this.side = sideAttribute === 'left' ? 'left' : 'right';
    }

    /** Handle drawer triggers, including buttons inserted by later HTMX swaps. */
    private setupTriggerButtons(): void {
        if (!this.element) return;

        this.clearTriggerHandlers();

        const drawer = this;
        /** Route clicks from a trigger or its children to this drawer instance. */
        function handleDrawerTrigger(event: Event): void {
            if (!(event.target instanceof Element)) return;
            const trigger = event.target.closest(
                `[${OPEN_DRAWER_ATTRIBUTE}], [${CLOSE_DRAWER_ATTRIBUTE}]`
            );
            if (trigger?.getAttribute(OPEN_DRAWER_ATTRIBUTE) === drawer.drawerId) {
                drawer.open();
            } else if (trigger?.getAttribute(CLOSE_DRAWER_ATTRIBUTE) === drawer.drawerId) {
                drawer.close();
            }
        }
        document.addEventListener('click', handleDrawerTrigger);
        this.triggerHandlers.push({ element: document, handler: handleDrawerTrigger });
    }

    private clearTriggerHandlers(): void {
        this.triggerHandlers.forEach(({ element, handler }) => {
            element.removeEventListener('click', handler);
        });
        this.triggerHandlers = [];
    }

    private setupBackdropClickHandler(): void {
        if (!this.backdropElement) return;

        const backdropClickClose = this.element?.getAttribute(
            'data-backdrop-click-close'
        );
        const shouldClose = backdropClickClose !== 'false';

        if (shouldClose) {
            this.backdropClickHandler = (e: MouseEvent) => {
                if (e.target === this.backdropElement) {
                    this.close();
                }
            };
            this.backdropElement.addEventListener('click', this.backdropClickHandler);
        }
    }

    private setupEscapeKeyHandler(): void {
        this.escapeKeyHandler = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;

            const openDrawers = document.querySelectorAll(
                '[bloomerp-component="drawer"]:not(.hidden)'
            ) as NodeListOf<HTMLElement>;
            if (openDrawers.length === 0) return;

            const lastDrawer = openDrawers[openDrawers.length - 1];
            if (lastDrawer.id === this.drawerId) {
                this.close();
            }
        };

        document.addEventListener('keydown', this.escapeKeyHandler);
    }

    private getClosedTranslateClass(): string {
        return this.side === 'left' ? '-translate-x-full' : 'translate-x-full';
    }

    /** Open the panel and remember the originating cell or control for focus restoration. */
    public open(returnFocus?: HTMLElement): void {
        if (!this.element) return;
        this.syncElements();

        if (!this.backdropElement || !this.panelElement) {
            console.warn(`Drawer elements not found for ID: ${this.drawerId}`);
            return;
        }

        if (this.backdropElement.classList.contains('hidden')) {
            this.returnFocus = returnFocus ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
        }
        if (this.animationTimer) clearTimeout(this.animationTimer);
        // Escape the main content's stacking context so the backdrop covers navigation.
        if (this.element.dataset.portalToBody === 'true' && !this.placeholder && this.element.parentElement !== document.body) {
            this.placeholder = document.createComment('drawer');
            this.element.before(this.placeholder);
            this.placeholder.parentElement?.addEventListener('htmx:beforeCleanupElement', this.onCleanup);
            document.body.appendChild(this.element);
        }
        if (this.element.dataset.lockScroll !== 'false') {
            this.previousBodyOverflow ??= document.body.style.overflow;
            document.body.style.overflow = 'hidden';
        }
        this.backdropElement.classList.remove('hidden');
        this.backdropElement.classList.add('flex');

        const closedClass = this.getClosedTranslateClass();
        this.panelElement.classList.remove('translate-x-0');
        this.panelElement.classList.add(closedClass);

        this.animationTimer = setTimeout(() => {
            this.panelElement?.classList.remove(closedClass);
            this.panelElement?.classList.add('translate-x-0');
        }, 10);

    }

    /** Close the panel and return keyboard focus to its connected originating control. */
    public close(): void {
        this.syncElements();

        if (!this.backdropElement || !this.panelElement) {
            console.warn(`Drawer elements not found for ID: ${this.drawerId}`);
            return;
        }

        if (this.animationTimer) clearTimeout(this.animationTimer);
        const closedClass = this.getClosedTranslateClass();
        this.panelElement.classList.remove('translate-x-0');
        this.panelElement.classList.add(closedClass);

        this.animationTimer = setTimeout(() => {
            this.backdropElement?.classList.remove('flex');
            this.backdropElement?.classList.add('hidden');
            this.restorePosition();
            if (this.returnFocus?.isConnected) this.returnFocus.focus({ preventScroll: true });
            this.returnFocus = null;
        }, 200);
    }

    /** Return a portaled drawer to its owner and restore the prior scrolling state. */
    private restorePosition(): void {
        if (this.placeholder) {
            this.placeholder.parentElement?.removeEventListener('htmx:beforeCleanupElement', this.onCleanup);
            if (this.placeholder.isConnected) this.placeholder.replaceWith(this.element);
            else this.element.remove();
            this.placeholder = null;
        }
        if (this.previousBodyOverflow !== null) {
            document.body.style.overflow = this.previousBodyOverflow;
            this.previousBodyOverflow = null;
        }
    }

    /** Release the drawer when HTMX removes it or the view owning its portal. */
    private onCleanup = (event: Event): void => {
        if (event.target === this.element || event.target === this.placeholder?.parentElement) this.destroy();
    };

    /** Release timers, global controls, and any portal created by this drawer. */
    public override destroy(): void {
        this.returnFocus = null;
        this.element?.removeEventListener('htmx:beforeCleanupElement', this.onCleanup);
        if (this.animationTimer) clearTimeout(this.animationTimer);
        this.backdropElement?.classList.remove('flex');
        this.backdropElement?.classList.add('hidden');
        this.restorePosition();
        if (this.backdropElement && this.backdropClickHandler) {
            this.backdropElement.removeEventListener('click', this.backdropClickHandler);
        }

        if (this.escapeKeyHandler) {
            document.removeEventListener('keydown', this.escapeKeyHandler);
        }

        this.clearTriggerHandlers();
        super.destroy();
    }
}
