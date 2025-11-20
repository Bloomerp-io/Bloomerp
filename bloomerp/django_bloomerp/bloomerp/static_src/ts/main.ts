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

import { initAllDataTables, DataTable } from './modules/datatable';
import type { DataTableConfig } from './types/bloomerp';

/**
 * Application State
 */
class BloomerpApp {
    private dataTables: Map<string, DataTable> = new Map();
    private initialized: boolean = false;

    constructor() {
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
        this.initDataTables();
        // Add more component initializations here as needed
        // this.initForms();
        // this.initModals();
    }

    /**
     * Initialize datatables
     */
    private initDataTables(): void {
        this.dataTables = initAllDataTables();
        console.log(`Initialized ${this.dataTables.size} datatable(s)`);
    }

    /**
     * Setup HTMX event listeners for dynamic content
     */
    private setupHtmxEventListeners(): void {
        // Listen for when HTMX loads new content
        document.body.addEventListener('htmx:load', (event) => {
            this.onHtmxLoad(event as CustomEvent);
        });

        // Listen for after HTMX swaps content
        document.body.addEventListener('htmx:afterSwap', (event) => {
            this.onHtmxAfterSwap(event as CustomEvent);
        });

        // Listen for after HTMX settles (animations complete)
        document.body.addEventListener('htmx:afterSettle', (event) => {
            this.onHtmxAfterSettle(event as CustomEvent);
        });

        // Listen for HTMX errors
        document.body.addEventListener('htmx:responseError', (event) => {
            this.onHtmxError(event as CustomEvent);
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

        // Reinitialize datatables in the loaded content
        this.reinitializeDataTablesInElement(target);
    }

    /**
     * Handle HTMX after swap event
     * Fired after HTMX swaps content into the DOM
     */
    private onHtmxAfterSwap(event: CustomEvent): void {
        const target = event.detail?.target as HTMLElement;

        if (!target) return;

        console.log('HTMX content swapped man', target);

        // Reinitialize components in swapped content
        this.reinitializeDataTablesInElement(target);
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
     * Reinitialize datatables within a specific element
     */
    private reinitializeDataTablesInElement(element: HTMLElement): void {
        console.log('Hello');
        const tables = element.querySelectorAll('[data-datatable]');

        tables.forEach(table => {
            if (table.id) {
                const existingTable = this.dataTables.get(table.id);

                if (existingTable) {
                    // Reinitialize existing datatable
                    existingTable.reinitialize();
                } else {
                    // Create new datatable instance
                    const newTable = new DataTable({ tableId: table.id });
                    this.dataTables.set(table.id, newTable);
                }
            }
        });
    }

    /**
     * Get a specific datatable instance
     */
    public getDataTable(tableId: string): DataTable | undefined {
        return this.dataTables.get(tableId);
    }

    /**
     * Create a new datatable programmatically
     */
    public createDataTable(config: DataTableConfig): DataTable {
        const dataTable = new DataTable(config);
        this.dataTables.set(config.tableId, dataTable);
        return dataTable;
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
