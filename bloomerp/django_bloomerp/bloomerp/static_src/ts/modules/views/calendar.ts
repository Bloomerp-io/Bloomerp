/**
 * Calendar View Module
 * 
 * Handles all calendar-specific functionality including:
 * - Cell navigation (days for month view, hours for week/day views)
 * - Event selection and navigation
 * - Context menu on events
 * - Calendar period navigation (prev/next/today)
 */

import { BaseView, ViewConfig, NAVIGATION_KEYS } from './base';


/**
 * CalendarView handles calendar interactions
 */
export class CalendarView extends BaseView {
    readonly viewType = 'calendar';
    
    private calendarElement: HTMLElement | null = null;
    private cells: HTMLElement[] = [];
    private events: HTMLElement[] = [];
    private selectedCellIndex: number = -1;
    private selectedEventIndex: number = -1;
    private viewMode: string = 'month';
    private currentPageOffset: number = 0;
    private calendarUrl: string = '';
    private onNavigate: ((pageOffset: number) => void) | null = null;
    
    // Grid dimensions for navigation
    private gridCols: number = 7;
    private gridRows: number = 1;
    
    constructor(config: ViewConfig) {
        super(config);
    }
    
    /**
     * Set the navigation callback for calendar pagination
     */
    setNavigationCallback(callback: (pageOffset: number) => void): void {
        this.onNavigate = callback;
    }
    
    /**
     * Initialize the calendar view
     */
    initialize(): void {
        this.calendarElement = this.container.querySelector('[data-calendar]') as HTMLElement;
        
        if (!this.calendarElement) {
            console.warn('CalendarView: Calendar element not found');
            return;
        }
        
        // Get data attributes
        this.viewMode = this.calendarElement.dataset.viewMode || 'month';
        this.currentPageOffset = parseInt(this.calendarElement.dataset.pageOffset || '0', 10);
        this.calendarUrl = this.calendarElement.dataset.url || '';
        
        // Calculate grid dimensions based on view mode
        this.calculateGridDimensions();
        
        // Make calendar focusable for keyboard navigation
        this.calendarElement.setAttribute('tabindex', '0');
        
        // Refresh element references
        this.refreshElements();
        
        // Setup navigation button handlers
        this.setupNavigationButtons();
        
        // Setup context menu on events
        this.setupEventContextMenu();
    }
    
    /**
     * Calculate grid dimensions based on view mode
     */
    private calculateGridDimensions(): void {
        switch (this.viewMode) {
            case 'month':
                this.gridCols = 7;  // Days per week
                // Rows will be determined by actual cells
                break;
            case 'week':
                this.gridCols = 7;  // Days
                this.gridRows = 24; // Hours
                break;
            case 'day':
                this.gridCols = 1;
                this.gridRows = 24; // Hours
                break;
        }
    }
    
    /**
     * Setup context menu handlers on calendar events
     */
    private setupEventContextMenu(): void {
        if (!this.calendarElement) return;
        
        // Right-click on events
        this.calendarElement.addEventListener('contextmenu', (e) => {
            const target = e.target as HTMLElement;
            const eventEl = target.closest('.calendar-event') as HTMLElement;
            
            if (eventEl) {
                e.preventDefault();
                e.stopPropagation();
                this.onContextMenuRequest(eventEl, false);
            }
        }, { signal: this.abortController.signal });
    }
    
    /**
     * Setup click handlers for navigation buttons
     */
    private setupNavigationButtons(): void {
        if (!this.calendarElement) return;
        
        const prevBtn = this.calendarElement.querySelector('[data-calendar-nav="prev"]');
        const nextBtn = this.calendarElement.querySelector('[data-calendar-nav="next"]');
        const todayBtn = this.calendarElement.querySelector('[data-calendar-nav="today"]');
        
        prevBtn?.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateCalendar(this.currentPageOffset - 1);
        }, { signal: this.abortController.signal });
        
        nextBtn?.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateCalendar(this.currentPageOffset + 1);
        }, { signal: this.abortController.signal });
        
        todayBtn?.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateCalendar(0);
        }, { signal: this.abortController.signal });
    }
    
    /**
     * Navigate to a different calendar period
     */
    navigateCalendar(pageOffset: number): void {
        if (this.onNavigate) {
            this.onNavigate(pageOffset);
        }
    }
    
    /**
     * Get the calendar URL for HTMX requests
     */
    getCalendarUrl(): string {
        return this.calendarUrl;
    }
    
    /**
     * Get current page offset
     */
    getCurrentPageOffset(): number {
        return this.currentPageOffset;
    }
    
    /**
     * Cleanup the calendar view
     */
    cleanup(): void {
        this.selectedCellIndex = -1;
        this.selectedEventIndex = -1;
        this.navigationMode = false;
        this.cells = [];
        this.events = [];
    }
    
    /**
     * Get the navigable element (the calendar)
     */
    getNavigableElement(): HTMLElement | null {
        return this.calendarElement;
    }
    
    /**
     * Refresh element references
     */
    refreshElements(): void {
        this.calendarElement = this.container.querySelector('[data-calendar]') as HTMLElement;
        if (this.calendarElement) {
            this.calendarElement.setAttribute('tabindex', '0');
            this.viewMode = this.calendarElement.dataset.viewMode || 'month';
            this.currentPageOffset = parseInt(this.calendarElement.dataset.pageOffset || '0', 10);
            this.calendarUrl = this.calendarElement.dataset.url || '';
            
            // Get all calendar cells
            this.cells = Array.from(this.calendarElement.querySelectorAll('[data-calendar-cell]'));
            // Get all calendar events
            this.events = Array.from(this.calendarElement.querySelectorAll('.calendar-event'));
            
            // Update grid dimensions
            this.calculateGridDimensions();
            
            // For month view, calculate rows from actual cells
            if (this.viewMode === 'month' && this.cells.length > 0) {
                this.gridRows = Math.ceil(this.cells.length / this.gridCols);
            }
        }
    }
    
    /**
     * Handle navigation key press
     */
    handleNavigation(key: string, hasModifier: boolean): void {
        // Handle context menu with modifier key + MOVE_DOWN
        if (key === NAVIGATION_KEYS.MOVE_DOWN && hasModifier) {
            this.openContextMenuOnSelected();
            return;
        }
        
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveSelection('down');
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveSelection('up');
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.moveSelection('right');
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.moveSelection('left');
                break;
            case NAVIGATION_KEYS.SELECT:
                this.handleSelect();
                break;
            case NAVIGATION_KEYS.EXIT_NAVIGATION:
                this.exitNavigationMode();
                break;
        }
    }
    
    /**
     * Handle Enter/Select key - navigate to selected event or focus on cell
     */
    handleSelect(): void {
        // Check for events in the selected cell
        if (this.selectedCellIndex >= 0 && this.selectedCellIndex < this.cells.length) {
            const cell = this.cells[this.selectedCellIndex];
            const eventsInCell = cell.querySelectorAll('.calendar-event');
            
            if (eventsInCell.length > 0) {
                // Navigate to the first event
                const firstEvent = eventsInCell[0] as HTMLAnchorElement;
                const href = firstEvent.getAttribute('href');
                if (href) {
                    if (typeof (window as any).htmx !== 'undefined') {
                        (window as any).htmx.ajax('GET', href, { target: '#main-content', swap: 'innerHTML' });
                        window.history.pushState({}, '', href);
                    } else {
                        window.location.href = href;
                    }
                }
            }
        }
    }
    
    /**
     * Enter navigation mode - select first cell
     */
    enterNavigationMode(): void {
        this.navigationMode = true;
        this.refreshElements();
        
        if (this.cells.length > 0) {
            this.selectedCellIndex = 0;
            this.selectedEventIndex = -1;
            this.highlightSelectedCell();
            this.scrollToSelectedCell();
        }
    }
    
    /**
     * Exit navigation mode
     */
    exitNavigationMode(): void {
        this.clearHighlight();
        this.selectedCellIndex = -1;
        this.selectedEventIndex = -1;
        this.navigationMode = false;
    }
    
    /**
     * Open context menu on the currently selected cell's first event
     */
    openContextMenuOnSelected(): void {
        // Check for events in the selected cell
        if (this.selectedCellIndex >= 0 && this.selectedCellIndex < this.cells.length) {
            const cell = this.cells[this.selectedCellIndex];
            const eventsInCell = cell.querySelectorAll('.calendar-event');
            
            if (eventsInCell.length > 0) {
                const firstEvent = eventsInCell[0] as HTMLElement;
                this.onContextMenuRequest(firstEvent, true);
            }
        }
    }
    
    /**
     * Move cell selection based on view mode
     * - Month view: navigate by days (7 columns grid)
     * - Week view: up/down by hour, left/right by day
     * - Day view: up/down by hour
     */
    private moveSelection(direction: 'up' | 'down' | 'left' | 'right'): void {
        if (this.cells.length === 0) return;
        
        // Initialize selection if not set
        if (this.selectedCellIndex < 0) {
            this.selectedCellIndex = 0;
            this.highlightSelectedCell();
            this.scrollToSelectedCell();
            return;
        }
        
        this.clearHighlight();
        
        const numCells = this.cells.length;
        let newIndex = this.selectedCellIndex;
        let shouldNavigatePeriod = false;
        let periodDirection: 'prev' | 'next' = 'next';
        
        if (this.viewMode === 'month') {
            // Month view: standard grid navigation (7 columns)
            const cols = this.gridCols;
            const currentRow = Math.floor(this.selectedCellIndex / cols);
            const currentCol = this.selectedCellIndex % cols;
            const totalRows = Math.ceil(numCells / cols);
            
            switch (direction) {
                case 'up':
                    if (currentRow > 0) {
                        newIndex = this.selectedCellIndex - cols;
                    }
                    break;
                case 'down':
                    if (currentRow < totalRows - 1 && this.selectedCellIndex + cols < numCells) {
                        newIndex = this.selectedCellIndex + cols;
                    }
                    break;
                case 'left':
                    if (this.selectedCellIndex > 0) {
                        newIndex = this.selectedCellIndex - 1;
                    } else {
                        // At the start, go to previous period
                        shouldNavigatePeriod = true;
                        periodDirection = 'prev';
                    }
                    break;
                case 'right':
                    if (this.selectedCellIndex < numCells - 1) {
                        newIndex = this.selectedCellIndex + 1;
                    } else {
                        // At the end, go to next period
                        shouldNavigatePeriod = true;
                        periodDirection = 'next';
                    }
                    break;
            }
        } else if (this.viewMode === 'week') {
            // Week view: 7 columns (days) x 24 rows (hours)
            // Cells are ordered by column (day) then row (hour)
            const cols = 7;
            const rows = 24;
            const currentCol = Math.floor(this.selectedCellIndex / rows);
            const currentRow = this.selectedCellIndex % rows;
            
            switch (direction) {
                case 'up':
                    if (currentRow > 0) {
                        newIndex = currentCol * rows + (currentRow - 1);
                    }
                    break;
                case 'down':
                    if (currentRow < rows - 1) {
                        newIndex = currentCol * rows + (currentRow + 1);
                    }
                    break;
                case 'left':
                    if (currentCol > 0) {
                        newIndex = (currentCol - 1) * rows + currentRow;
                    } else {
                        // At the start of week, go to previous week
                        shouldNavigatePeriod = true;
                        periodDirection = 'prev';
                    }
                    break;
                case 'right':
                    if (currentCol < cols - 1) {
                        newIndex = (currentCol + 1) * rows + currentRow;
                    } else {
                        // At the end of week, go to next week
                        shouldNavigatePeriod = true;
                        periodDirection = 'next';
                    }
                    break;
            }
        } else if (this.viewMode === 'day') {
            // Day view: single column of hours
            switch (direction) {
                case 'up':
                    if (this.selectedCellIndex > 0) {
                        newIndex = this.selectedCellIndex - 1;
                    }
                    break;
                case 'down':
                    if (this.selectedCellIndex < numCells - 1) {
                        newIndex = this.selectedCellIndex + 1;
                    }
                    break;
                case 'left':
                    // Go to previous day
                    shouldNavigatePeriod = true;
                    periodDirection = 'prev';
                    break;
                case 'right':
                    // Go to next day
                    shouldNavigatePeriod = true;
                    periodDirection = 'next';
                    break;
            }
        }
        
        // Handle period navigation at boundaries
        if (shouldNavigatePeriod) {
            const newOffset = periodDirection === 'prev' 
                ? this.currentPageOffset - 1 
                : this.currentPageOffset + 1;
            this.navigateCalendar(newOffset);
            return;
        }
        
        // Clamp to valid range
        newIndex = Math.max(0, Math.min(numCells - 1, newIndex));
        this.selectedCellIndex = newIndex;
        
        this.highlightSelectedCell();
        this.scrollToSelectedCell();
    }
    
    /**
     * Highlight the currently selected cell
     */
    private highlightSelectedCell(): void {
        if (this.selectedCellIndex >= 0 && this.selectedCellIndex < this.cells.length) {
            const cell = this.cells[this.selectedCellIndex];
            cell.classList.add('ring-2', 'ring-primary-500', 'ring-inset', 'bg-primary-50');
            cell.setAttribute('aria-selected', 'true');
            cell.focus();
        }
    }
    
    /**
     * Clear highlight from all cells and events
     */
    private clearHighlight(): void {
        this.cells.forEach(cell => {
            cell.classList.remove('ring-2', 'ring-primary-500', 'ring-inset', 'bg-primary-50');
            cell.removeAttribute('aria-selected');
        });
        this.events.forEach(event => {
            event.classList.remove('ring-2', 'ring-primary-500', 'ring-offset-1');
            event.removeAttribute('aria-selected');
        });
    }
    
    /**
     * Scroll to keep the selected cell visible
     */
    private scrollToSelectedCell(): void {
        if (this.selectedCellIndex >= 0 && this.selectedCellIndex < this.cells.length) {
            const cell = this.cells[this.selectedCellIndex];
            cell.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }
    
    /**
     * Get the currently selected object ID (for context menu)
     */
    getSelectedObjectId(): string | null {
        if (this.selectedCellIndex >= 0 && this.selectedCellIndex < this.cells.length) {
            const cell = this.cells[this.selectedCellIndex];
            const event = cell.querySelector('.calendar-event') as HTMLElement;
            return event?.dataset.objectId || null;
        }
        return null;
    }
}
