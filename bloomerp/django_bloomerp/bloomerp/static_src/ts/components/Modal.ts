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
        this.modalBodyElement = this.backdropElement.querySelector(`#${this.modalId}-modal-body`) as HTMLElement | null;

        if (!this.containerElement || !this.modalBodyElement) {
            console.warn(`Modal structure not found for ID: ${this.modalId}`, {
                backdrop: this.backdropElement,
                container: this.containerElement,
                body: this.modalBodyElement
            });
            return;
        }

        // Setup event listeners
        this.setupBackdropClickHandler();
        this.setupEscapeKeyHandler();
        this.setupTabKeyHandler();
    }

    /**
     * Called after HTMX swaps new content
     * With event delegation, no need to re-bind - listeners work automatically
     */
    public onAfterSwap(): void {
        let openTriggers = document.querySelectorAll(`[${OPEN_MODAL_ATTRIBUTE}="${this.element.id}"]`);
        
        openTriggers.forEach((trigger)=>{
            trigger.addEventListener('click', (e) =>{
                this.open() 
            })
        })

        let closeTriggers = document.querySelectorAll(`[${CLOSE_MODAL_ATTRIBUTE}="${this.element.id}"]`);
        
        closeTriggers.forEach((trigger)=>{
            trigger.addEventListener('click', (e) =>{
                this.close() 
            })
        })

        let fullscreenTriggers = document.querySelectorAll(`[${TOGGLE_FULL_SCREEN_ATTRIBUTE}="${this.element.id}"]`);
        
        fullscreenTriggers.forEach((trigger)=>{
            trigger.addEventListener('click', (e) =>{
                this.toggleFullscreen() 
            })
        })

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
            if (e.key === 'Escape') {
                const openModals = document.querySelectorAll('[id$="-backdrop"]:not(.hidden)');
                if (openModals.length > 0) {
                    const lastModal = openModals[openModals.length - 1];
                    const modalId = lastModal.id.replace('-backdrop', '');
                    if (modalId === this.modalId) {
                        this.close();
                    }
                }
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
        const modalBody = this.modalBodyElement || (this.modalId ? document.getElementById(`${this.modalId}-modal-body`) : null);
        
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
        // Store original size in data attribute for reliable restoration
        const sizeClasses = ['max-w-sm', 'max-w-2xl', 'max-w-4xl', 'max-w-6xl'];
        let currentSize = 'md';

        // Detect current size before modifying classes
        for (const sizeClass of sizeClasses) {
            if (container.classList.contains(sizeClass)) {
                if (sizeClass === 'max-w-sm') currentSize = 'sm';
                else if (sizeClass === 'max-w-2xl') currentSize = 'md';
                else if (sizeClass === 'max-w-4xl') currentSize = 'lg';
                else if (sizeClass === 'max-w-6xl') currentSize = 'xl';
                break;
            }
        }

        // Store in both instance property and data attribute for reliability
        this.originalSize = currentSize;
        container.setAttribute('data-original-size', currentSize);

        // Remove all size classes
        sizeClasses.forEach((sizeClass) => {
            container.classList.remove(sizeClass);
        });

        // Set fullscreen
        container.classList.add('max-w-full', 'w-full', 'h-full', 'rounded-none');

        // Update modal body - keep overflow-y-auto for scrolling
        modalBody.classList.remove('max-h-96');
        modalBody.classList.add('flex-1', 'overflow-y-auto');

        this.isFullscreen = true;
    }

    private exitFullscreen(container: HTMLElement, modalBody: HTMLElement): void {
        // Remove fullscreen classes
        container.classList.remove('max-w-full', 'w-full', 'h-full', 'rounded-none');

        // Get original size from data attribute (more reliable) or instance property
        const storedSize = container.getAttribute('data-original-size') || this.originalSize;
        
        // Add back the original size class
        const sizeClassMap: Record<string, string> = {
            'sm': 'max-w-sm',
            'lg': 'max-w-4xl',
            'xl': 'max-w-6xl',
        };

        const sizeClass = sizeClassMap[storedSize] || 'max-w-2xl';
        container.classList.add(sizeClass);

        // Update modal body max height - keep overflow-y-auto for scrolling
        modalBody.classList.remove('flex-1');
        modalBody.classList.add('max-h-96', 'overflow-y-auto');

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
}

