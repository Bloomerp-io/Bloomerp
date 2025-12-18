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
	private mainElement : HTMLElement;
	private overlayElement : HTMLElement;
	private sidebarButton : HTMLElement;
	private _isOpen : boolean;
	private readonly storageKey = 'bloomerp_sidebar_state';


	public initialize(): void {
		this.mainElement = document.getElementById('main');
		this.overlayElement = document.getElementById('sidebar-overlay');
		this.sidebarButton = document.getElementById('sidebar-toggle')

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

		// Add keyboard click -> command + b OR cntrl + b toggles the sidebar
		document.addEventListener('keydown', (event) => {
			if ((event.metaKey || event.ctrlKey) && event.key === 'b') {
				event.preventDefault();
				this.toggle();
			}
		});

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