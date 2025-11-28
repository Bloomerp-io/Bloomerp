
/**
 * Sidebar class to manage the behavior of the sidebar
 * in the Bloomerp application. The sidebar can be opened,
 * closed, and toggled, and its state can be queried.
 * 
 * The state of the sidebar is also stored in localStorage
 * to persist user preferences across sessions.
 */
export class Sidebar {
    private sidebarElement: HTMLElement | null;
    private overlayElement: HTMLElement | null;
    private mainElement: HTMLElement | null;
    private readonly storageKey = 'bloomerp_sidebar_state';
    private _isOpen: boolean = false;

    constructor() {
        this.sidebarElement = document.getElementById('sidebar');
        this.overlayElement = document.getElementById('sidebar-overlay');
        this.mainElement = document.getElementById('main');
        
        this.init();
    }

    private init(): void {
        // Restore state from local storage or default to open on large screens
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
    }

    private setupEventListeners(): void {
        // Close on overlay click
        if (this.overlayElement) {
            this.overlayElement.addEventListener('click', () => {
                this.close();
            });
        }

        // Listen for window resize to handle responsive behavior if needed
        // For now, we stick to the user's preference or initial state
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

    private updateUI(): void {
        if (!this.sidebarElement) return;

        if (this._isOpen) {
            // Open state: remove translate-x-full to show sidebar
            this.sidebarElement.classList.remove('-translate-x-full');
            
            // Show overlay on mobile
            if (this.overlayElement) {
                this.overlayElement.classList.remove('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.add('lg:ml-64');
                this.mainElement.classList.remove('ml-2');
            }
        } else {
            // Closed state: add translate-x-full to hide sidebar
            this.sidebarElement.classList.add('-translate-x-full');
            
            // Hide overlay
            if (this.overlayElement) {
                this.overlayElement.classList.add('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.remove('lg:ml-64');
                this.mainElement.classList.add('ml-2');
            }
        }
    }
}