import BaseComponent from "./BaseComponent";

/**
 * Sidebar component to manage the behavior of the sidebar
 * in the Bloomerp application. The sidebar can be opened,
 * closed, and toggled, and its state can be queried.
 * 
 * The state of the sidebar is also stored in localStorage
 * to persist user preferences across sessions.
 */
export class Sidebar extends BaseComponent {
    private mainElement : HTMLElement | null;
    private overlayElement : HTMLElement | null;
    private sidebarButton : HTMLElement | null;
    private floatingButton : HTMLElement | null;
	private _isOpen : boolean;
	private readonly storageKey = 'bloomerp_sidebar_state';
    private hoverTimer: number | null = null;


	public initialize(): void {
		this.mainElement = document.getElementById('main');
		this.overlayElement = document.getElementById('sidebar-overlay');
        this.sidebarButton = document.getElementById('sidebar-toggle')
        this.floatingButton = document.getElementById('sidebar-toggle-floating');

		// Get state
		const storedState = localStorage.getItem(this.storageKey);

		if (storedState !== null) {
            this._isOpen = storedState === 'true';
        } else {
            // Default: open on large screens (>= 1024px), closed on small
            this._isOpen = window.innerWidth >= 1024;
        }

		// Apply initial state
        this.updateUI();

        // Setup event listeners
        this.setupEventListeners();

        // Bind visibility handlers for the floating button (mouse/touch)
        this.bindFloatingVisibilityHandlers();

	}

	private updateUI(): void {
        if (!this.element) return;

        if (this._isOpen) {
            // Open state: remove translate-x-full to show sidebar
            this.element.classList.remove('-translate-x-full');
            
            // Show overlay on mobile
            if (this.overlayElement) {
                this.overlayElement.classList.remove('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.add('lg:ml-64');
                this.mainElement.classList.remove('ml-2');
            }

            if (this.floatingButton) {
                this.floatingButton.classList.add('hidden');
            }
        } else {
            // Closed state: add translate-x-full to hide sidebar
            this.element.classList.add('-translate-x-full');
            
            // Hide overlay
            if (this.overlayElement) {
                this.overlayElement.classList.add('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.remove('lg:ml-64');
                this.mainElement.classList.add('ml-2');
            }

            if (this.floatingButton) {
                // Keep the floating button hidden by default when sidebar is closed;
                // visibility will be controlled by pointer/touch handlers.
                this.floatingButton.classList.add('hidden');
            }
        }
    }

    private bindFloatingVisibilityHandlers(): void {
        const mouseHandler = (e: MouseEvent) => this.handlePointer(e.clientX, e.clientY);
        const touchHandler = () => this.toggleFloatingByTouch();

        window.addEventListener('mousemove', mouseHandler);
        window.addEventListener('touchstart', touchHandler, {passive:true});
    }

    private handlePointer(clientX: number, clientY: number): void {
        if (this._isOpen) return; // don't show floating when sidebar is open

        const nearLeft = clientX < 80 && clientY < 120;

        if (nearLeft) {
            if (this.hoverTimer) {
                window.clearTimeout(this.hoverTimer);
                this.hoverTimer = null;
            }
            this.showFloating();
        } else {
            if (!this.hoverTimer) {
                this.hoverTimer = window.setTimeout(() => {
                    this.hideFloating();
                    this.hoverTimer = null;
                }, 600);
            }
        }
    }

    private showFloating(): void {
        if (!this.floatingButton) return;
        this.floatingButton.classList.remove('hidden');
    }

    private hideFloating(): void {
        if (!this.floatingButton) return;
        this.floatingButton.classList.add('hidden');
    }

    private toggleFloatingByTouch(): void {
        if (!this.floatingButton) return;
        if (this.floatingButton.classList.contains('hidden')) {
            this.showFloating();
        } else {
            this.hideFloating();
        }
    }

	private setupEventListeners(): void {
        // Close on overlay click
        if (this.overlayElement) {
            this.overlayElement.addEventListener('click', () => {
                this.close();
            });
        }

        if (this.sidebarButton) {
			this.sidebarButton.addEventListener('click', () => {
				this.toggle()
			})
		}

        if (this.floatingButton) {
            this.floatingButton.addEventListener('click', () => {
                this.toggle()
            })
        }
    }

    public toggle(): void {
        this._isOpen = !this._isOpen;
        this.saveState();
        this.updateUI();
    }

    public open(): void {
        if (this._isOpen) return;
        this._isOpen = true;
        this.saveState();
        this.updateUI();
    }

    public close(): void {
        if (!this._isOpen) return;
        this._isOpen = false;
        this.saveState();
        this.updateUI();
    }

    public isOpen(): boolean {
        return this._isOpen;
    }

    private saveState(): void {
        localStorage.setItem(this.storageKey, String(this._isOpen));
    }
}