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

    private backdropClickHandler: ((e: MouseEvent) => void) | null = null;
    private escapeKeyHandler: ((e: KeyboardEvent) => void) | null = null;

    private triggerHandlers: Array<{ element: Element; handler: EventListener }> = [];

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

    private setupTriggerButtons(): void {
        if (!this.element) return;

        this.clearTriggerHandlers();

        const openTriggers = document.querySelectorAll(
            `[${OPEN_DRAWER_ATTRIBUTE}="${this.element.id}"]`
        );
        openTriggers.forEach((trigger) => {
            const handler = () => this.open();
            trigger.addEventListener('click', handler);
            this.triggerHandlers.push({ element: trigger, handler });
        });

        const closeTriggers = document.querySelectorAll(
            `[${CLOSE_DRAWER_ATTRIBUTE}="${this.element.id}"]`
        );
        closeTriggers.forEach((trigger) => {
            const handler = () => this.close();
            trigger.addEventListener('click', handler);
            this.triggerHandlers.push({ element: trigger, handler });
        });
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

    public open(): void {
        if (!this.element) return;
        this.syncElements();

        if (!this.backdropElement || !this.panelElement) {
            console.warn(`Drawer elements not found for ID: ${this.drawerId}`);
            return;
        }

        this.backdropElement.classList.remove('hidden');
        this.backdropElement.classList.add('flex');

        const closedClass = this.getClosedTranslateClass();
        this.panelElement.classList.remove('translate-x-0');
        this.panelElement.classList.add(closedClass);

        setTimeout(() => {
            this.panelElement?.classList.remove(closedClass);
            this.panelElement?.classList.add('translate-x-0');
        }, 10);

        document.body.style.overflow = 'hidden';
    }

    public close(): void {
        this.syncElements();

        if (!this.backdropElement || !this.panelElement) {
            console.warn(`Drawer elements not found for ID: ${this.drawerId}`);
            return;
        }

        const closedClass = this.getClosedTranslateClass();
        this.panelElement.classList.remove('translate-x-0');
        this.panelElement.classList.add(closedClass);

        setTimeout(() => {
            this.backdropElement?.classList.remove('flex');
            this.backdropElement?.classList.add('hidden');
            document.body.style.overflow = '';
        }, 200);
    }

    public destroy(): void {
        if (this.backdropElement && this.backdropClickHandler) {
            this.backdropElement.removeEventListener('click', this.backdropClickHandler);
        }

        if (this.escapeKeyHandler) {
            document.removeEventListener('keydown', this.escapeKeyHandler);
        }

        this.clearTriggerHandlers();
    }
}
