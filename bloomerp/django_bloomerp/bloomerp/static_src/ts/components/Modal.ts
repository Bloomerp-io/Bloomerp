import BaseComponent, { registerComponent, getComponent } from './BaseComponent';

// Define those attributes
const OPEN_MODAL_ATTRIBUTE = 'bloomerp-open-modal'
const CLOSE_MODAL_ATTRIBUTE = 'bloomerp-close-modal'
const TOGGLE_FULL_SCREEN_ATTRIBUTE = 'bloomerp-full-screen-modal'

/**
 * Modal Component
 * 
 * Manages modal behavior including:
 * - Opening/closing with animations
 * - Fullscreen toggle functionality
 * - Backdrop click-to-close
 * - Keyboard navigation (ESC to close, focus trapping)
 * - Accessibility features
 * 
 * Usage in HTML:
 * <div bloomerp-component="modal" id="my-modal">
 *   <!-- modal content -->
 * </div>
 * 
 */
export class Modal extends BaseComponent {
    private modalId: string = '';
    private backdropElement: HTMLElement | null = null;
    private containerElement: HTMLElement | null = null;
    private modalBodyElement: HTMLElement | null = null;
    private isFullscreen: boolean = false;
    private originalSize: string = 'md';
    
    // Event handler references for cleanup
    private backdropClickHandler: ((e: MouseEvent) => void) | null = null;
    private escapeKeyHandler: ((e: KeyboardEvent) => void) | null = null;
    private tabKeyHandler: ((e: KeyboardEvent) => void) | null = null;
    private readonly triggerBoundAttribute = 'data-modal-trigger-bound';

    public initialize(): void {
        if (!this.element) {
            console.warn('Modal component: element is null');
            return;
        }

        // Extract modal ID from element ID
        this.modalId = this.element.id;
        
        if (!this.modalId) {
            console.warn('Modal component requires an id attribute', this.element);
            return;
        }

        // The element itself is the backdrop
        this.backdropElement = this.element;
        
        // Cache element references for container and body (children of backdrop)
        this.containerElement = this.backdropElement.querySelector(`#${this.modalId}-container`) as HTMLElement | null;
        this.modalBodyElement = this.backdropElement.querySelector(`#${this.modalId}-body`) as HTMLElement | null;

        if (!this.containerElement || !this.modalBodyElement) {
            console.warn(`Modal structure not found for ID: ${this.modalId}`, {
                backdrop: this.backdropElement,
                container: this.containerElement,
                body: this.modalBodyElement
            });
            return;
        }

        this.captureOriginalState();

        // Setup event listeners
        this.setupBackdropClickHandler();
        this.setupEscapeKeyHandler();
        this.setupTabKeyHandler();
        this.setupTriggerButtons();
    }

    /**
     * Setup event listeners for trigger buttons (open, close, fullscreen)
     */
    private setupTriggerButtons(): void {
        if (!this.element) return;

        let openTriggers = document.querySelectorAll(`[${OPEN_MODAL_ATTRIBUTE}="${this.element.id}"]`);
        
        openTriggers.forEach((trigger)=>{
            if ((trigger as HTMLElement).getAttribute(this.triggerBoundAttribute) === `${this.modalId}:open`) {
                return;
            }

            trigger.addEventListener('click', (e) =>{
                this.open() 
            });
            (trigger as HTMLElement).setAttribute(this.triggerBoundAttribute, `${this.modalId}:open`);
        })

        let closeTriggers = document.querySelectorAll(`[${CLOSE_MODAL_ATTRIBUTE}="${this.element.id}"]`);
        
        closeTriggers.forEach((trigger)=>{
            if ((trigger as HTMLElement).getAttribute(this.triggerBoundAttribute) === `${this.modalId}:close`) {
                return;
            }

            trigger.addEventListener('click', (e) =>{
                this.close() 
            });
            (trigger as HTMLElement).setAttribute(this.triggerBoundAttribute, `${this.modalId}:close`);
        })

        let fullscreenTriggers = document.querySelectorAll(`[${TOGGLE_FULL_SCREEN_ATTRIBUTE}="${this.element.id}"]`);
        
        fullscreenTriggers.forEach((trigger)=>{
            if ((trigger as HTMLElement).getAttribute(this.triggerBoundAttribute) === `${this.modalId}:fullscreen`) {
                return;
            }

            trigger.addEventListener('click', (e) =>{
                this.toggleFullscreen() 
            });
            (trigger as HTMLElement).setAttribute(this.triggerBoundAttribute, `${this.modalId}:fullscreen`);
        })
    }

    /**
     * Called after HTMX swaps new content
     */
    public onAfterSwap(): void {
        // Re-setup trigger buttons after content swap
        this.setupTriggerButtons();
    }

    private setupBackdropClickHandler(): void {
        if (!this.backdropElement) return;

        // Check if backdrop click should close modal
        const backdropClickClose = this.element?.getAttribute('data-backdrop-click-close');
        const shouldClose = backdropClickClose !== 'false'; // Default to true

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

            // Find currently visible modal backdrops (our modal elements have
            // `bloomerp-component="modal"` and are hidden when closed)
            const openModals = document.querySelectorAll('[bloomerp-component="modal"]:not(.hidden)') as NodeListOf<HTMLElement>;
            if (openModals.length === 0) return;

            const lastModal = openModals[openModals.length - 1];
            const modalId = lastModal.id;
            if (modalId === this.modalId) {
                this.close();
            }
        };

        document.addEventListener('keydown', this.escapeKeyHandler);
    }

    private setupTabKeyHandler(): void {
        this.tabKeyHandler = (e: KeyboardEvent) => {
            if (e.key === 'Tab' && this.isOpen()) {
                const focusableElements = this.containerElement?.querySelectorAll(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                ) as NodeListOf<HTMLElement> | undefined;

                if (focusableElements && focusableElements.length > 0) {
                    const firstElement = focusableElements[0];
                    const lastElement = focusableElements[focusableElements.length - 1];

                    if (e.shiftKey && document.activeElement === firstElement) {
                        e.preventDefault();
                        lastElement.focus();
                    } else if (!e.shiftKey && document.activeElement === lastElement) {
                        e.preventDefault();
                        firstElement.focus();
                    }
                }
            }
        };

        document.addEventListener('keydown', this.tabKeyHandler);
    }

    /**
     * Open the modal with animation
     */
    public open(): void {
        // If modalId is empty, try to get it from this.element
        if (!this.modalId && this.element) {
            this.modalId = this.element.id;
        }
        
        // Get fresh references in case they weren't found during initialize
        const backdrop = this.backdropElement || (this.modalId ? document.getElementById(this.modalId) : null);
        const container = this.containerElement || (this.modalId ? document.getElementById(`${this.modalId}-container`) : null);
        
        if (!backdrop || !container) {
            console.warn(`Modal elements not found for ID: ${this.modalId}`, {
                element: this.element,
                modalId: this.modalId,
                backdrop: backdrop,
                container: container
            });
            return;
        }
        
        // Display the backdrop
        backdrop.classList.remove('hidden');
        backdrop.classList.add('flex');
        
        // Add animation with a slight delay to ensure the display change is processed
        setTimeout(() => {
            container.classList.remove('scale-95', 'opacity-0');
            container.classList.add('scale-100', 'opacity-100');
        }, 10);
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
        
        // Focus container
        container.focus();

        this.element?.dispatchEvent(new CustomEvent('bloomerp:modal-opened', {
            bubbles: true,
            detail: { modalId: this.modalId },
        }));
    }

    /**
     * Close the modal with animation
     */
    public close(): void {
        // Get fresh references in case they weren't found during initialize
        const backdrop = this.backdropElement || document.getElementById(this.modalId);
        const container = this.containerElement || document.getElementById(`${this.modalId}-container`);
        
        if (!backdrop || !container) {
            console.warn(`Modal elements not found for ID: ${this.modalId}`);
            return;
        }
        
        // Add closing animation
        container.classList.remove('scale-100', 'opacity-100');
        container.classList.add('scale-95', 'opacity-0');
        
        // Wait for animation to complete before hiding
        setTimeout(() => {
            backdrop.classList.remove('flex');
            backdrop.classList.add('hidden');
            
            // Restore body scroll
            document.body.style.overflow = '';

            this.element?.dispatchEvent(new CustomEvent('bloomerp:modal-closed', {
                bubbles: true,
                detail: { modalId: this.modalId },
            }));
        }, 200);
    }

    /**
     * Check if modal is currently open
     */
    private isOpen(): boolean {
        return this.backdropElement ? !this.backdropElement.classList.contains('hidden') : false;
    }

    /**
     * Toggle fullscreen mode
     */
    public toggleFullscreen(): void {
        // Get fresh references in case they weren't found during initialize
        if (!this.modalId && this.element) {
            this.modalId = this.element.id;
        }
        
        const container = this.containerElement || (this.modalId ? document.getElementById(`${this.modalId}-container`) : null);
        const modalBody = this.modalBodyElement || (this.modalId ? document.getElementById(`${this.modalId}-body`) : null);
        
        if (!container || !modalBody) {
            console.warn(`Modal elements not found for fullscreen toggle: ${this.modalId}`);
            return;
        }

        if (this.isFullscreen) {
            this.exitFullscreen(container, modalBody);
        } else {
            this.enterFullscreen(container, modalBody);
        }
    }

    private enterFullscreen(container: HTMLElement, modalBody: HTMLElement): void {
        this.captureOriginalState(container, modalBody);

        // Store original size and body classes in data attributes for reliable restoration
        const sizeClasses = ['max-w-sm', 'max-w-2xl', 'max-w-4xl', 'max-w-6xl'];
        let currentSize = container.getAttribute('data-original-size') || 'md';

        this.originalSize = currentSize;

        // Remove all size classes from container
        sizeClasses.forEach((sizeClass) => {
            container.classList.remove(sizeClass);
        });

        // Set fullscreen on container - make it flex column for proper layout
        container.classList.add('max-w-full', 'w-full', 'h-full', 'rounded-none', 'flex', 'flex-col');

        // Update modal body - remove max-h constraint and make it flex-1 to fill space
        modalBody.className = 'flex-1 overflow-y-auto p-6';

        this.isFullscreen = true;
    }

    private captureOriginalState(
        container: HTMLElement | null = this.containerElement,
        modalBody: HTMLElement | null = this.modalBodyElement
    ): void {
        if (!container || !modalBody) return;

        if (!container.getAttribute('data-original-size')) {
            container.setAttribute('data-original-size', this.detectCurrentSize(container));
        }

        if (!container.getAttribute('data-original-body-classes')) {
            container.setAttribute('data-original-body-classes', Array.from(modalBody.classList).join(' '));
        }
    }

    private detectCurrentSize(container: HTMLElement): string {
        const sizeClasses = ['max-w-sm', 'max-w-2xl', 'max-w-4xl', 'max-w-6xl', 'max-w-full'];

        for (const sizeClass of sizeClasses) {
            if (container.classList.contains(sizeClass)) {
                if (sizeClass === 'max-w-sm') return 'sm';
                if (sizeClass === 'max-w-2xl') return 'md';
                if (sizeClass === 'max-w-4xl') return 'lg';
                if (sizeClass === 'max-w-6xl') return 'xl';
                if (sizeClass === 'max-w-full') return 'full';
            }
        }

        return 'md';
    }

    private exitFullscreen(container: HTMLElement, modalBody: HTMLElement): void {
        // Remove fullscreen classes from container
        container.classList.remove('max-w-full', 'h-full', 'rounded-none', 'flex', 'flex-col');

        // Get original size from data attribute (more reliable) or instance property
        const storedSize = container.getAttribute('data-original-size') || this.originalSize;
        
        // Add back the original size class
        const sizeClassMap: Record<string, string> = {
            'sm': 'max-w-sm',
            'lg': 'max-w-4xl',
            'xl': 'max-w-6xl',
            'full': 'max-w-full',
        };

        const sizeClass = sizeClassMap[storedSize] || 'max-w-2xl';
        container.classList.add(sizeClass);

        if (storedSize === 'full') {
            container.classList.add('h-full', 'rounded-none');
        } else {
            container.classList.add('w-full');
        }

        // Restore original modal body classes
        const originalBodyClasses = container.getAttribute('data-original-body-classes');
        if (originalBodyClasses) {
            modalBody.className = originalBodyClasses;
        } else {
            // Fallback to default classes
            modalBody.className = 'max-h-96 overflow-y-auto p-6';
        }

        this.isFullscreen = false;
    }

    /**
     * Clean up event listeners
     */
    public destroy(): void {
        if (this.backdropElement && this.backdropClickHandler) {
            this.backdropElement.removeEventListener('click', this.backdropClickHandler);
        }

        if (this.escapeKeyHandler) {
            document.removeEventListener('keydown', this.escapeKeyHandler);
        }

        if (this.tabKeyHandler) {
            document.removeEventListener('keydown', this.tabKeyHandler);
        }
    }

    public getBodyElement(): HTMLElement | null {
        return this.modalBodyElement;
    }

    public setTitle(title: string): void {
        if (!this.element) return;

        const titleElement = this.element.querySelector(`#${this.element.id}-title`) as HTMLElement | null;
        if (titleElement) {
            titleElement.textContent = title;
        }
    }
}
