/**
 * DataView Module with HTMX Integration
 * 
 * This module serves as the main orchestrator for data views.
 * It delegates view-specific logic to the appropriate view class
 * (TableView, KanbanView, CalendarView) while handling common
 * functionality like context menus and HTMX integration.
 */

import htmx from 'htmx.org';
import type { DataViewConfig, DataViewContextTrigger, ContextMenuPosition } from '../types/bloomerp';
import { IView, ViewConfig, NAVIGATION_KEYS, TableView, KanbanView, CalendarView } from './views';


/**
 * DataView class orchestrates view interactions and delegates to specific view implementations
 */
export class DataView {
    private containerId: string;
    private container: HTMLElement | null = null;
    private viewType: string = 'table';
    private contentTypeId: string | null = null;
    
    // Initialization tracking
    private currentRenderId: string | null = null;
    private abortController: AbortController | null = null;
    
    // The active view implementation
    private activeView: IView | null = null;
    
    // Context menu properties
    private contextMenu: HTMLElement | null = null;
    private currentTrigger: DataViewContextTrigger | null = null;
    private contextMenuOpen: boolean = false;
    private contextMenuItemIndex: number = -1;
    private contextMenuAbortController: AbortController | null = null;
    private contextMenuOpenedViaKeyboard: boolean = false;

    constructor(config: DataViewConfig) {
        this.containerId = config.containerId;
        this.initialize();
    }

    /**
     * Initialize the dataview
     */
    private initialize(): void {
        this.container = document.getElementById(this.containerId);

        if (!this.container) {
            console.warn(`DataView: Container with ID "${this.containerId}" not found`);
            return;
        }

        // Check if this is a new render or the same one
        const newRenderId = this.container.dataset.renderId || null;
        if (newRenderId && newRenderId === this.currentRenderId) {
            console.log(`DataView: Already initialized for render ${newRenderId}, skipping`);
            return;
        }
        
        // Cleanup previous initialization if any
        this.cleanup();
        
        // Store the new render ID and create new AbortController
        this.currentRenderId = newRenderId;
        this.abortController = new AbortController();
        
        console.log(`Initializing DataView: ${this.containerId} (render: ${newRenderId})`);

        this.contentTypeId = this.container.dataset.contentTypeId || null;
        this.viewType = this.container.dataset.viewType || 'table';

        // Create the appropriate view implementation
        this.createActiveView();

        // Initialize context menu for all view types
        this.setupContextMenu();

        // Setup keyboard navigation
        this.setupGlobalKeyboardListener();
        this.setupKeyboardNavigation();
    }
    
    /**
     * Create the active view based on view type
     */
    private createActiveView(): void {
        if (!this.container || !this.contentTypeId || !this.abortController) return;
        
        const viewConfig: ViewConfig = {
            container: this.container,
            contentTypeId: this.contentTypeId,
            abortController: this.abortController,
            onContextMenuRequest: (element, openedViaKeyboard) => {
                this.openContextMenuOnElement(element, openedViaKeyboard);
            },
            onMessage: (message, type) => {
                this.showMessage(message, type);
            }
        };
        
        switch (this.viewType) {
            case 'table':
                this.activeView = new TableView(viewConfig);
                break;
            case 'kanban':
                this.activeView = new KanbanView(viewConfig);
                break;
            case 'calendar':
                const calendarView = new CalendarView(viewConfig);
                calendarView.setNavigationCallback((pageOffset) => {
                    this.navigateCalendar(pageOffset);
                });
                this.activeView = calendarView;
                break;
            default:
                console.warn(`DataView: Unknown view type "${this.viewType}"`);
                return;
        }
        
        this.activeView.initialize();
    }
    
    /**
     * Cleanup all event listeners and state
     */
    private cleanup(): void {
        // Cleanup active view
        if (this.activeView) {
            this.activeView.cleanup();
            this.activeView = null;
        }
        
        // Abort all event listeners registered with the current AbortController
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        
        // Cleanup context menu listeners
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
            this.contextMenuAbortController = null;
        }
        
        // Reset context menu state
        this.contextMenuOpen = false;
        this.contextMenuItemIndex = -1;
    }

    /**
     * Get the dataview URL from hidden input
     * Note: This might need adjustment based on where the URL is stored in the new structure
     */
    private getDataViewUrl(): string {
        // Assuming the URL input might still be named similarly or we use the current URL
        // For now, let's look for the input with the old ID pattern or a new one
        const urlInput = document.getElementById(`data-table-${this.contentTypeId}-url`) as HTMLInputElement;
        return urlInput?.value || '';
    }

    /**
     * Reload the dataview with optional query parameters
     */
    public reload(requestParams?: string): void {
        // Target the data section for reload
        const targetId = `data-table-data-section`; // Or dynamic based on content type?
        // In data_table.html, the target is often #data-table-data-section (which is inside the view)
        // But HTMX usually handles this via attributes on elements.
        // If we need manual reload:
        
        const url = this.getDataViewUrl();
        if (!url) return;

        const fullUrl = requestParams ? `${url}?${requestParams}` : url;
        // We might want to target the container or a specific part
        window.htmx.ajax('GET', fullUrl, `#${this.containerId}`); 
    }

    /**
     * Set up context menu on table cells and other triggers
     */
    private setupContextMenu(): void {
        if (!this.contentTypeId || !this.abortController) return;
        
        // Initialize context menu element
        this.contextMenu = document.getElementById(`data-table-${this.contentTypeId}-context-menu`);
        if (!this.contextMenu) return;

        // Use event delegation on the container
        if (this.container) {
            this.container.addEventListener('contextmenu', (e: MouseEvent) => {
                const target = e.target as HTMLElement;
                const trigger = target.closest('td[allow-context-menu], [data-context-menu-trigger]') as DataViewContextTrigger;
                
                if (trigger) {
                    e.preventDefault();
                    this.showContextMenu(trigger, e, false);
                }
            }, { signal: this.abortController.signal });
        }

        // Hide context menu on any click outside the menu
        document.addEventListener('click', (e: MouseEvent) => {
            if (this.contextMenu && !this.contextMenu.contains(e.target as Node)) {
                this.hideContextMenu();
            }
        }, { signal: this.abortController.signal });
    }

    /**
     * Show context menu at mouse position
     */
    private showContextMenu(trigger: DataViewContextTrigger, event: MouseEvent, openedViaKeyboard: boolean = false): void {
        if (!this.contextMenu) return;

        this.currentTrigger = trigger;
        this.contextMenuOpen = true;
        this.contextMenuItemIndex = -1;
        this.contextMenuOpenedViaKeyboard = openedViaKeyboard;

        // Update menu items based on view type
        this.updateContextMenuItems(trigger.dataset.applicationFieldId);

        // Position menu at mouse coordinates (fixed positioning)
        const position = this.calculateContextMenuPosition(event);

        // Position and display the menu
        this.contextMenu.style.left = `${position.x}px`;
        this.contextMenu.style.top = `${position.y}px`;
        this.contextMenu.classList.remove('hidden');

        // Set up context menu keyboard navigation
        this.setupContextMenuKeyboardNavigation();
    }

    /**
     * Update context menu items based on view type
     */
    private updateContextMenuItems(applicationFieldId?:string): void {
        if (!this.contentTypeId) return;
        const target = `#data-table-${this.contentTypeId}-context-menu`;
        let baseUrl = `/components/dataview_context_menu/${this.viewType}/`;
        
        // Add application field ID get parameter if provided
        if (applicationFieldId) {
            baseUrl += `?application_field_id=${applicationFieldId}`;
        }

        htmx.ajax(
            'get',
            baseUrl,
            {
                target: target,
                swap: 'innerHTML'
            }
        ).then(() => {
            // After HTMX renders the menu, set up action handlers and focus
            this.setupContextMenuActionHandlers();
            
            // If opened via keyboard, focus on first item
            if (this.contextMenuOpenedViaKeyboard) {
                this.focusFirstContextMenuItem();
            }
        });
    }

    /**
     * Set up action handlers for context menu items after HTMX render
     */
    private setupContextMenuActionHandlers(): void {
        if (!this.contextMenu) return;
        
        const buttons = this.contextMenu.querySelectorAll('button[data-action]');
        buttons.forEach((button) => {
            button.addEventListener('click', (e: Event) => {
                e.preventDefault();
                e.stopPropagation(); // Prevent the document click handler from hiding the menu before action executes
                const action = (button as HTMLElement).dataset.action;
                if (action) {
                    this.handleContextMenuAction(action);
                }
            });
        });
    }

    /**
     * Handle context menu action
     */
    private handleContextMenuAction(action: string): void {
        if (!this.currentTrigger) {
            this.hideContextMenu();
            return;
        }

        const applicationFieldId = this.currentTrigger.dataset.applicationFieldId;
        const element = this.currentTrigger;

        switch (action) {
            case 'copy':
                this.copyCurrentTriggerValue();
                break;
            case 'edit':
                this.editCurrentTrigger();
                break;
            case 'filter':
                this.filterByCurrentTrigger();
                break;
            case 'goto':
                this.gotoCurrentTrigger();
                break;
            case 'download':
                this.downloadCurrentTrigger();
                break;
            default:
                console.warn(`Unknown context menu action: ${action}`);
        }
    }

    /**
     * Focus on the first context menu item
     */
    private focusFirstContextMenuItem(): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (menuItems.length > 0) {
            this.contextMenuItemIndex = 0;
            const firstItem = menuItems[0] as HTMLElement;
            firstItem.classList.add('bg-gray-100');
            firstItem.focus();
        }
    }

    /**
     * Navigate to the current trigger's object
     */
    private gotoCurrentTrigger(): void {
        if (!this.currentTrigger) return;
        
        const objectId = this.currentTrigger.dataset.objectId;
        if (!objectId || !this.contentTypeId) return;
        
        // Try to find a link within the row to navigate
        const row = this.currentTrigger.closest('tr');
        if (row) {
            const link = row.querySelector('a[hx-get]') as HTMLAnchorElement;
            if (link) {
                link.click();
                this.hideContextMenu();
                return;
            }
        }
        
        // Fallback: construct URL based on content type and object ID
        this.showMessage('Navigation coming soon', 'info');
        this.hideContextMenu();
    }

    /**
     * Download related to the current trigger
     */
    private downloadCurrentTrigger(): void {
        if (!this.currentTrigger) return;
        
        this.showMessage('Download coming soon', 'info');
        this.hideContextMenu();
    }

    /**
     * Calculate context menu position to avoid overflow
     */
    private calculateContextMenuPosition(event: MouseEvent): ContextMenuPosition {
        if (!this.contextMenu) return { x: 0, y: 0 };

        // Use pageX/pageY for absolute positioning relative to document
        let x = event.pageX;
        let y = event.pageY;

        const menuWidth = this.contextMenu.offsetWidth || 160;
        const menuHeight = this.contextMenu.offsetHeight || 200;

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Adjust if menu would go off right edge
        if (event.clientX + menuWidth > viewportWidth) {
            x = event.pageX - menuWidth;
        }

        // Adjust if menu would go off bottom edge
        if (event.clientY + menuHeight > viewportHeight) {
            y = event.pageY - menuHeight;
        }

        return { x, y };
    }

    /**
     * Toggle filter option visibility based on trigger attributes
     */
    private toggleFilterOption(trigger: DataViewContextTrigger): void {
        if (!this.contentTypeId) return;
        const filterListItem = document.getElementById(`data-table-${this.contentTypeId}-context-menu-filter-value-list-item`);

        if (filterListItem) {
            filterListItem.style.display = trigger.dataset.contextMenuFilterValue ? 'block' : 'none';
        }
    }

    /**
     * Hide context menu
     */
    private hideContextMenu(): void {
        if (this.contextMenu) {
            this.contextMenu.classList.add('hidden');
        }
        
        // Clean up context menu navigation state
        this.contextMenuOpen = false;
        this.contextMenuItemIndex = -1;
        this.removeContextMenuHighlight();
        
        // Abort context menu keyboard listeners
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
            this.contextMenuAbortController = null;
        }
    }

    /**
     * Set up keyboard navigation for the context menu
     */
    private setupContextMenuKeyboardNavigation(): void {
        // Abort previous context menu listeners if any
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
        }
        
        // Create new AbortController for context menu listeners
        this.contextMenuAbortController = new AbortController();
        
        // Use capture phase to intercept events before other handlers
        document.addEventListener('keydown', (e: KeyboardEvent) => {
            if (!this.contextMenuOpen) return;
            
            switch (e.key) {
                case NAVIGATION_KEYS.MOVE_DOWN:
                    e.preventDefault();
                    e.stopPropagation();
                    this.navigateContextMenu(1);
                    break;
                case NAVIGATION_KEYS.MOVE_UP:
                    e.preventDefault();
                    e.stopPropagation();
                    this.navigateContextMenu(-1);
                    break;
                case NAVIGATION_KEYS.SELECT:
                    e.preventDefault();
                    e.stopPropagation();
                    this.selectContextMenuItem();
                    break;
                case NAVIGATION_KEYS.EXIT_NAVIGATION:
                    e.preventDefault();
                    e.stopPropagation();
                    this.closeContextMenuAndReturnFocus();
                    break;
            }
        }, { capture: true, signal: this.contextMenuAbortController.signal });
    }

    /**
     * Navigate through context menu items
     */
    private navigateContextMenu(direction: number): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (menuItems.length === 0) return;
        
        // Remove previous highlight
        this.removeContextMenuHighlight();
        
        // Update index
        const newIndex = this.contextMenuItemIndex + direction;
        
        // If going down past the end, close menu and return to view
        if (newIndex >= menuItems.length) {
            this.closeContextMenuAndReturnFocus();
            return;
        }
        
        // If going up past the beginning, close menu and return to view
        if (newIndex < 0) {
            this.closeContextMenuAndReturnFocus();
            return;
        }
        
        this.contextMenuItemIndex = newIndex;
        
        // Highlight new item
        const currentItem = menuItems[this.contextMenuItemIndex] as HTMLElement;
        currentItem.classList.add('bg-gray-100');
        currentItem.focus();
    }

    /**
     * Get visible context menu items (buttons that are not hidden)
     */
    private getVisibleContextMenuItems(): HTMLButtonElement[] {
        if (!this.contextMenu) return [];
        
        const allButtons = this.contextMenu.querySelectorAll('button');
        const visibleButtons: HTMLButtonElement[] = [];
        
        allButtons.forEach(button => {
            const listItem = button.closest('li');
            // Check if the button's parent li is visible
            if (!listItem || listItem.style.display !== 'none') {
                visibleButtons.push(button);
            }
        });
        
        return visibleButtons;
    }

    /**
     * Remove highlight from context menu items
     */
    private removeContextMenuHighlight(): void {
        if (!this.contextMenu) return;
        
        const buttons = this.contextMenu.querySelectorAll('button');
        buttons.forEach(button => {
            button.classList.remove('bg-gray-100');
        });
    }

    /**
     * Select the currently highlighted context menu item
     */
    private selectContextMenuItem(): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (this.contextMenuItemIndex >= 0 && this.contextMenuItemIndex < menuItems.length) {
            const currentItem = menuItems[this.contextMenuItemIndex];
            currentItem.click();
        }
    }

    /**
     * Close context menu and return focus to the data view
     */
    private closeContextMenuAndReturnFocus(): void {
        this.hideContextMenu();
        
        // Return focus to the navigable element
        const navigableElement = this.getNavigableElement();
        if (navigableElement) {
            navigableElement.focus();
        }
    }

    /**
     * Copy current trigger value to clipboard
     */
    private async copyCurrentTriggerValue(): Promise<void> {
        if (!this.currentTrigger) return;

        try {
            const text = this.currentTrigger.textContent || '';
            // strip leading/trailing whitespace
            const trimmedText = text.trim();
            await navigator.clipboard.writeText(trimmedText);
            this.hideContextMenu();
            this.showMessage('Value copied to clipboard', 'info');
        } catch (err) {
            console.error('Failed to copy text:', err);
            this.showMessage('Failed to copy value', 'error');
        }
    }

    /**
     * Filter dataview by current trigger value
     */
    private filterByCurrentTrigger(): void {
        if (!this.currentTrigger) return;
        
        const filterValue = this.currentTrigger.dataset.contextMenuFilterValue;
        if (!filterValue) return;

        // Prevent duplicate filters
        if (this.currentTrigger.classList.contains('filtered')) {
            this.hideContextMenu();
            return;
        }
        
        this.applyFilter(filterValue);
        this.currentTrigger.classList.add('filtered');
        this.hideContextMenu();
    }

    /**
     * Apply filter to dataview
     */
    private applyFilter(filterParam: string): void {
        const url = this.getDataViewUrl();
        if (!url) return;

        // Check if URL already has params
        const separator = url.includes('?') ? '&' : '?';
        const fullUrl = `${url}${separator}${filterParam}`;

        window.htmx.ajax('GET', fullUrl, `#${this.containerId}`);
        
        this.showMessage('Dataview filtered', 'info');
    }

    /**
     * Edit current trigger
     */
    private editCurrentTrigger(): void {
        if (!this.currentTrigger || !this.contentTypeId) {
            this.hideContextMenu();
            return;
        }

        const applicationFieldId = this.currentTrigger.dataset.applicationFieldId;
        const objectId = this.currentTrigger.dataset.objectId;
        
        if (!applicationFieldId) {
            this.showMessage('No field selected for editing', 'warning');
            this.hideContextMenu();
            return;
        }

        // Fetch the inline edit component
        const editUrl = `/components/dataview_edit_field/${applicationFieldId}/${objectId}/`;
        
        htmx.ajax(
            'get',
            editUrl,
            {
                target: this.currentTrigger,
                swap: 'innerHTML'
            }
        ).then(() => {
            // Focus on the input after it's rendered
            const input = this.currentTrigger?.querySelector('input, select, textarea') as HTMLElement;
            if (input) {
                input.focus();
            }
        });

        this.hideContextMenu();
    }

    /**
     * Delete current item (row or card)
     */
    private deleteCurrentItem(): void {
        if (!this.currentTrigger) return;

        const objectId = this.currentTrigger.dataset.objectId;

        if (!objectId) return;

        const itemType = this.viewType === 'kanban' ? 'card' : 'row';
        const confirmed = confirm(`Are you sure you want to delete this ${itemType}?`);
        if (!confirmed) {
            this.hideContextMenu();
            return;
        }

        console.log(`Delete ${itemType}:`, objectId);
        this.showMessage('Delete functionality coming soon', 'warning');
        this.hideContextMenu();
    }

    /**
     * Navigate the calendar to a different period
     */
    private navigateCalendar(pageOffset: number): void {
        if (!this.container || !this.contentTypeId) return;
        
        // Get the data section target
        const dataSection = document.getElementById('data-table-data-section');
        if (!dataSection) {
            console.warn('DataView: Could not find data-table-data-section for calendar navigation');
            return;
        }
        
        // Get the URL from the calendar element's data-url attribute
        let baseUrl: string;
        if (this.activeView && this.activeView.viewType === 'calendar') {
            const calendarView = this.activeView as CalendarView;
            baseUrl = calendarView.getCalendarUrl();
        }
        
        // Fallback to container's search form URL
        if (!baseUrl) {
            const searchInput = this.container.querySelector('.search-input') as HTMLInputElement;
            const hxGetUrl = searchInput?.getAttribute('hx-get');
            if (hxGetUrl) {
                baseUrl = hxGetUrl;
            } else {
                console.warn('DataView: Could not determine calendar navigation URL');
                return;
            }
        }
        
        // Build the full URL with the calendar_page parameter
        const url = new URL(baseUrl, window.location.origin);
        url.searchParams.set('calendar_page', pageOffset.toString());
        
        // Use HTMX to fetch the updated calendar
        htmx.ajax(
            'get',
            url.toString(),
            {
                target: '#data-table-data-section',
                swap: 'outerHTML'
            }
        ).then(() => {
            // Reinitialize the calendar view after HTMX swap
            this.reinitializeCalendarView();
        });
    }
    
    /**
     * Reinitialize the calendar view after HTMX swap of the data section
     * This is needed because the calendar is inside the data section and the swap
     * doesn't trigger a full dataview reinitialization.
     */
    private reinitializeCalendarView(): void {
        if (!this.container || !this.contentTypeId || !this.abortController) return;
        
        // Only do this for calendar views
        if (this.viewType !== 'calendar') return;
        
        // Cleanup the old calendar view
        if (this.activeView) {
            this.activeView.cleanup();
        }
        
        // Create a new calendar view with the same config
        const viewConfig: ViewConfig = {
            container: this.container,
            contentTypeId: this.contentTypeId,
            abortController: this.abortController,
            onContextMenuRequest: (element, openedViaKeyboard) => {
                this.openContextMenuOnElement(element, openedViaKeyboard);
            },
            onMessage: (message, type) => {
                this.showMessage(message, type);
            }
        };
        
        const calendarView = new CalendarView(viewConfig);
        calendarView.setNavigationCallback((pageOffset) => {
            this.navigateCalendar(pageOffset);
        });
        this.activeView = calendarView;
        this.activeView.initialize();
        
        // Re-setup keyboard navigation on the new calendar element
        this.setupKeyboardNavigation();
        
        // Re-enter navigation mode if it was active
        this.activeView.enterNavigationMode();
    }

    /**
     * Show a message to the user
     */
    private showMessage(message: string, type: 'success' | 'info' | 'warning' | 'error'): void {
        if (typeof (window as any).showMessage === 'function') {
            (window as any).showMessage(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    /**
     * Reinitialize the dataview after HTMX updates
     */
    public reinitialize(): void {
        // Check if the container still exists
        const container = document.getElementById(this.containerId);
        if (!container) {
            console.warn(`DataView: Container "${this.containerId}" no longer exists`);
            return;
        }
        
        // Check if the render ID has changed (i.e., content was actually re-rendered)
        const newRenderId = container.dataset.renderId || null;
        if (newRenderId && newRenderId === this.currentRenderId) {
            console.log(`DataView: Same render ID ${newRenderId}, skipping reinitialization`);
            return;
        }
        
        // Force reinitialization by clearing the current render ID
        this.currentRenderId = null;
        this.initialize();
    }

    /**
     * Set up keyboard navigation - delegates to active view
     */
    private setupKeyboardNavigation(): void {
        const navigableElement = this.activeView?.getNavigableElement();
        if (!navigableElement || !this.abortController) return;

        navigableElement.addEventListener('keydown', (e: KeyboardEvent) => {
            // Don't handle navigation if context menu is open (handled separately)
            if (this.contextMenuOpen) return;
            
            // Only handle navigation keys
            const handledKeys = [
                NAVIGATION_KEYS.MOVE_UP,
                NAVIGATION_KEYS.MOVE_DOWN,
                NAVIGATION_KEYS.MOVE_LEFT,
                NAVIGATION_KEYS.MOVE_RIGHT,
                NAVIGATION_KEYS.SELECT,
                NAVIGATION_KEYS.EXIT_NAVIGATION
            ];

            if (!handledKeys.includes(e.key as any)) return;
            
            e.preventDefault();

            // Check for modifier key
            const hasModifier = e[NAVIGATION_KEYS.CONTEXT_MENU_MODIFIER as keyof KeyboardEvent] as boolean;

            // Delegate to active view
            this.activeView?.handleNavigation(e.key, hasModifier);
        }, { signal: this.abortController.signal });
    }

    /**
     * Get the navigable element from active view
     */
    private getNavigableElement(): HTMLElement | null {
        return this.activeView?.getNavigableElement() || null;
    }

    /**
     * Open context menu on an element
     */
    private openContextMenuOnElement(element: HTMLElement, openedViaKeyboard: boolean = false): void {
        const rect = element.getBoundingClientRect();
        const syntheticEvent = {
            clientX: rect.left + rect.width / 2,
            clientY: rect.top + rect.height / 2,
            pageX: rect.left + rect.width / 2 + window.scrollX,
            pageY: rect.top + rect.height / 2 + window.scrollY
        } as MouseEvent;
        
        this.currentTrigger = element as DataViewContextTrigger;
        this.showContextMenu(element as DataViewContextTrigger, syntheticEvent, openedViaKeyboard);
    }

    /**
     * Set up global keyboard listener to enter navigation mode
     */
    private setupGlobalKeyboardListener(): void {
        if (!this.abortController) return;

        document.addEventListener('keydown', (e: KeyboardEvent) => {
            const navigableElement = this.activeView?.getNavigableElement();
            
            // Try to refresh element reference if it's stale (e.g. after HTMX swap)
            if (!navigableElement || !document.body.contains(navigableElement)) {
                this.activeView?.refreshElements();
            }

            const currentNavigable = this.activeView?.getNavigableElement();
            if (!currentNavigable || !document.body.contains(currentNavigable)) {
                return;
            }

            // Don't capture events from form inputs
            if (e.target instanceof HTMLInputElement || 
                e.target instanceof HTMLTextAreaElement || 
                e.target instanceof HTMLSelectElement) {
                return;
            }

            // Enter navigation mode on ENTER_NAVIGATION key press
            // Only if we're not already focused on the navigable element or one of its children
            // This prevents re-entering navigation mode when already navigating
            if (e.key === NAVIGATION_KEYS.ENTER_NAVIGATION) {
                const isInsideNavigable = currentNavigable.contains(document.activeElement);
                if (!isInsideNavigable && document.activeElement !== currentNavigable) {
                    e.preventDefault();
                    currentNavigable.focus();
                    this.activeView?.enterNavigationMode();
                }
            }
        }, { signal: this.abortController.signal });
    }

    /**
     * Get the active view instance
     */
    public getActiveView(): IView | null {
        return this.activeView;
    }
}

/**
 * Initialize a dataview
 */
export function initDataView(config: DataViewConfig): DataView {
    return new DataView(config);
}

/**
 * Find and initialize all dataviews on the page
 */
export function initAllDataViews(): Map<string, DataView> {
    const dataViews = new Map<string, DataView>();
    const views = document.querySelectorAll('[data-dataview]');

    views.forEach(view => {
        if (view.id) {
            const dataView = new DataView({ containerId: view.id });
            dataViews.set(view.id, dataView);
        }
    });

    return dataViews;
}
