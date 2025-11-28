/**
 * Bloomerp Main TypeScript Entry Point
 * 
 * This file serves as the main entry point for all TypeScript modules.
 * It sets up HTMX event listeners to handle dynamically loaded content
 * and initializes modules as needed.
 * 
 * HTMX Event Listeners:
 * - htmx:load: Fired when new content is loaded (initial page load or after swap)
 * - htmx:afterSwap: Fired after HTMX swaps content into the DOM
 * - htmx:configRequest: Fired before HTMX makes a request (for modification)
 * - htmx:afterSettle: Fired after HTMX settles animations
 */

import { initAllDataViews, DataView } from './modules/dataview';
import { Sidebar } from './modules/sidebar';
import type { DataViewConfig } from './types/bloomerp';
import { insertSkeleton } from './utils/animations';


/**
 * Application State
 */
class BloomerpApp {
    private dataViews: Map<string, DataView> = new Map();
    public sidebar: Sidebar | undefined;
    private initialized: boolean = false;

    constructor() {
        // Singleton pattern to prevent double initialization
        if ((window as any).BloomerpAppInstance) {
            return (window as any).BloomerpAppInstance;
        }
        (window as any).BloomerpAppInstance = this;

        this.setupHtmxEventListeners();
        this.init();
    }

    /**
     * Initialize the application
     */
    private init(): void {
        if (this.initialized) return;

        console.log('🌸 Bloomerp TypeScript initialized');

        // Initialize on DOM ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.initializeComponents();
            });
        } else {
            this.initializeComponents();
        }

        this.initialized = true;
    }

    /**
     * Initialize all components on the page
     */
    private initializeComponents(): void {
        this.initDataViews();
        this.initSidebar();
        // Add more component initializations here as needed
        // this.initForms();
        // this.initModals();
    }

    /**
     * Initialize sidebar
     */
    private initSidebar(): void {
        this.sidebar = new Sidebar();
    }

    /**
     * Initialize dataviews
     */
    private initDataViews(): void {
        this.dataViews = initAllDataViews();
        console.log(`Initialized ${this.dataViews.size} dataview(s)`);
    }

    /**
     * Setup HTMX event listeners for dynamic content
     */
    private setupHtmxEventListeners(): void {
        // Listen for when HTMX loads new content
        document.body.addEventListener('htmx:load', (event: CustomEvent) => {
            this.onHtmxLoad(event as CustomEvent);
        });

        // Listen for after HTMX swaps content
        document.body.addEventListener('htmx:afterSwap', (event: CustomEvent) => {
            this.onHtmxAfterSwap(event as CustomEvent);
        });

        // Listen for after HTMX settles (animations complete)
        document.body.addEventListener('htmx:afterSettle', (event: CustomEvent) => {
            this.onHtmxAfterSettle(event as CustomEvent);
        });

        // Listen for HTMX errors
        document.body.addEventListener('htmx:responseError', (event: CustomEvent) => {
            this.onHtmxError(event as CustomEvent);
        });

        document.body.addEventListener('htmx:beforeRequest', (event: CustomEvent) => {
            const triggeringElement = event.detail?.elt as HTMLElement;
            let target = event.detail?.target as HTMLElement;

            // Check for animation target override via hx-animation-target attribute
            const animationTargetSelector = triggeringElement?.getAttribute('hx-animation-target');
            if (animationTargetSelector) {
                const overrideTarget = document.querySelector(animationTargetSelector) as HTMLElement;
                if (overrideTarget) {
                    target = overrideTarget;
                }
            }
            
            // Insert skeleton loader before request
            if (target) {
                insertSkeleton(target);
            }
        });

        console.log('HTMX event listeners registered');
    }

    /**
     * Handle HTMX load event
     * Fired when content is loaded into the DOM
     */
    private onHtmxLoad(event: CustomEvent): void {
        const target = event.detail?.elt as HTMLElement;

        if (!target) return;

        // Reinitialize dataviews in the loaded content
        this.reinitializeDataViewsInElement(target);
    }

    /**
     * Handle HTMX after swap event
     * Fired after HTMX swaps content into the DOM
     */
    private onHtmxAfterSwap(event: CustomEvent): void {
        const target = event.detail?.target as HTMLElement;

        if (!target) return;

        console.log('HTMX content swapped man', target);
    }

    /**
     * Handle HTMX after settle event
     * Fired after animations complete
     */
    private onHtmxAfterSettle(event: CustomEvent): void {
        // Can be used for post-animation tasks
        // Currently not needed, but available for future use
    }

    /**
     * Handle HTMX error
     */
    private onHtmxError(event: CustomEvent): void {
        console.error('HTMX Error:', event.detail);

        // Show user-friendly error message if showMessage function exists
        if (typeof (window as any).showMessage === 'function') {
            (window as any).showMessage('An error occurred while loading content', 'error');
        }
    }

    /**
     * Reinitialize dataviews within a specific element
     */
    private reinitializeDataViewsInElement(element: HTMLElement): void {
        // Check if the element itself is a dataview or contains dataviews
        const views = element.querySelectorAll('[data-dataview]');
        
        // Also check if the element is inside a dataview (e.g. partial update)
        const parentView = element.closest('[data-dataview]');
        
        const allViews = new Set<Element>();
        views.forEach(v => allViews.add(v));
        if (parentView) allViews.add(parentView);

        allViews.forEach(view => {
            if (view.id) {
                // Debounce reinitialization to prevent multiple calls for the same view
                // (e.g. when multiple elements inside the view are swapped via OOB)
                if ((view as any)._reinitTimeout) {
                    clearTimeout((view as any)._reinitTimeout);
                }

                (view as any)._reinitTimeout = setTimeout(() => {
                    const existingView = this.dataViews.get(view.id);

                    console.log(`Initializing: ${view.id}`);

                    if (existingView) {
                        // Reinitialize existing dataview
                        existingView.reinitialize();
                    } else {
                        // Create new dataview instance
                        const newView = new DataView({ containerId: view.id });
                        this.dataViews.set(view.id, newView);
                    }
                    
                    delete (view as any)._reinitTimeout;
                }, 10); // Short debounce
            }
        });
    }

    /**
     * Get a specific dataview instance
     */
    public getDataView(viewId: string): DataView | undefined {
        return this.dataViews.get(viewId);
    }

    /**
     * Create a new dataview programmatically
     */
    public createDataView(config: DataViewConfig): DataView {
        const dataView = new DataView(config);
        this.dataViews.set(config.containerId, dataView);
        return dataView;
    }
}

/**
 * Create and export the app instance
 */
const app = new BloomerpApp();

/**
 * Export for use in other scripts or console debugging
 */
declare global {
    interface Window {
        BloomerpApp: BloomerpApp;
    }
}

window.BloomerpApp = app;

/**
 * Export utilities for backward compatibility with existing code
 */
export { app as default, BloomerpApp };
