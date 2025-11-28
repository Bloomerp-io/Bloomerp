/**
 * Base View Module
 * 
 * Provides the abstract base class and interface for all view types.
 * Each view type (Table, Kanban, Calendar) extends this base.
 */

// Navigation key constants - shared across all views
export const NAVIGATION_KEYS = {
    // Global navigation
    ENTER_NAVIGATION: 'ArrowDown',
    EXIT_NAVIGATION: 'Escape',
    
    // Movement keys
    MOVE_UP: 'ArrowUp',
    MOVE_DOWN: 'ArrowDown',
    MOVE_LEFT: 'ArrowLeft',
    MOVE_RIGHT: 'ArrowRight',
    
    // Action keys
    SELECT: 'Enter',
    
    // Modifier keys
    CONTEXT_MENU_MODIFIER: 'shiftKey',
    MOVE_ITEM_MODIFIER: 'shiftKey',
} as const;

/**
 * Configuration for initializing a view
 */
export interface ViewConfig {
    container: HTMLElement;
    contentTypeId: string;
    abortController: AbortController;
    onContextMenuRequest: (element: HTMLElement, openedViaKeyboard: boolean) => void;
    onMessage: (message: string, type: 'success' | 'info' | 'warning' | 'error') => void;
}

/**
 * Interface that all view types must implement
 */
export interface IView {
    /** The type identifier for this view */
    readonly viewType: string;
    
    /** The main navigable element for this view */
    getNavigableElement(): HTMLElement | null;
    
    /** Initialize the view */
    initialize(): void;
    
    /** Cleanup the view (remove event listeners, reset state) */
    cleanup(): void;
    
    /** Handle navigation key press */
    handleNavigation(key: string, hasModifier: boolean): void;
    
    /** Handle the Enter/Select key */
    handleSelect(): void;
    
    /** Exit navigation mode */
    exitNavigationMode(): void;
    
    /** Open context menu on the currently selected element */
    openContextMenuOnSelected(): void;
    
    /** Enter navigation mode - initialize selection if needed */
    enterNavigationMode(): void;
    
    /** Refresh element references (e.g., after HTMX swap) */
    refreshElements(): void;
}

/**
 * Abstract base class for all view types
 * Provides common functionality and enforces the interface
 */
export abstract class BaseView implements IView {
    abstract readonly viewType: string;
    
    protected container: HTMLElement;
    protected contentTypeId: string;
    protected abortController: AbortController;
    protected navigationMode: boolean = false;
    
    // Callbacks to parent DataView
    protected onContextMenuRequest: (element: HTMLElement, openedViaKeyboard: boolean) => void;
    protected onMessage: (message: string, type: 'success' | 'info' | 'warning' | 'error') => void;
    
    constructor(config: ViewConfig) {
        this.container = config.container;
        this.contentTypeId = config.contentTypeId;
        this.abortController = config.abortController;
        this.onContextMenuRequest = config.onContextMenuRequest;
        this.onMessage = config.onMessage;
    }
    
    abstract getNavigableElement(): HTMLElement | null;
    abstract initialize(): void;
    abstract cleanup(): void;
    abstract handleNavigation(key: string, hasModifier: boolean): void;
    abstract handleSelect(): void;
    abstract exitNavigationMode(): void;
    abstract openContextMenuOnSelected(): void;
    abstract enterNavigationMode(): void;
    abstract refreshElements(): void;
    
    /**
     * Check if a navigation key should be handled
     */
    protected isNavigationKey(key: string): boolean {
        return [
            NAVIGATION_KEYS.MOVE_UP,
            NAVIGATION_KEYS.MOVE_DOWN,
            NAVIGATION_KEYS.MOVE_LEFT,
            NAVIGATION_KEYS.MOVE_RIGHT,
            NAVIGATION_KEYS.SELECT,
            NAVIGATION_KEYS.EXIT_NAVIGATION
        ].includes(key as any);
    }
    
    /**
     * Show a message to the user
     */
    protected showMessage(message: string, type: 'success' | 'info' | 'warning' | 'error'): void {
        this.onMessage(message, type);
    }
}
