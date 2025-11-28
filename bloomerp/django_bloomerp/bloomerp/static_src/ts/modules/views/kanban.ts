/**
 * Kanban View Module
 * 
 * Handles all kanban-specific functionality including:
 * - Column and card navigation
 * - Drag and drop for cards
 * - Card movement between columns
 */

import { BaseView, ViewConfig, NAVIGATION_KEYS } from './base';

/**
 * KanbanView handles kanban board interactions
 */
export class KanbanView extends BaseView {
    readonly viewType = 'kanban';
    
    private kanbanBoard: HTMLElement | null = null;
    private selectedColumnIndex: number = -1;
    private selectedCardIndex: number = -1;
    private draggedCard: HTMLElement | null = null;
    private draggedCardPlaceholder: HTMLElement | null = null;
    
    constructor(config: ViewConfig) {
        super(config);
    }
    
    /**
     * Initialize the kanban view
     */
    initialize(): void {
        this.kanbanBoard = document.getElementById(`kanban-board-${this.contentTypeId}`);
        
        if (!this.kanbanBoard) {
            // Try finding kanban board inside container
            this.kanbanBoard = this.container.querySelector('[data-kanban]') as HTMLElement;
        }
        
        if (!this.kanbanBoard) {
            console.warn('KanbanView: Kanban board not found');
            return;
        }
        
        // Make kanban board focusable for keyboard navigation
        this.kanbanBoard.setAttribute('tabindex', '0');
        
        // Set up drag and drop
        this.setupDragAndDrop();
    }
    
    /**
     * Cleanup the kanban view
     */
    cleanup(): void {
        this.selectedColumnIndex = -1;
        this.selectedCardIndex = -1;
        this.draggedCard = null;
        this.draggedCardPlaceholder = null;
        this.navigationMode = false;
        
        // Remove card highlights
        if (this.kanbanBoard) {
            this.kanbanBoard.querySelectorAll('[data-kanban-card].ring-2').forEach(card => {
                card.classList.remove('ring-2', 'ring-primary');
            });
        }
    }
    
    /**
     * Get the navigable element (the kanban board)
     */
    getNavigableElement(): HTMLElement | null {
        return this.kanbanBoard;
    }
    
    /**
     * Refresh element references
     */
    refreshElements(): void {
        this.kanbanBoard = this.container.querySelector('[data-kanban]') as HTMLElement;
        if (this.kanbanBoard) {
            this.kanbanBoard.setAttribute('tabindex', '0');
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
        
        // Handle card movement with modifier key + MOVE_LEFT/RIGHT
        if (hasModifier) {
            if (key === NAVIGATION_KEYS.MOVE_LEFT) {
                this.moveCardToColumn(-1);
                return;
            } else if (key === NAVIGATION_KEYS.MOVE_RIGHT) {
                this.moveCardToColumn(1);
                return;
            }
        }
        
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveCardSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveCardSelection(-1);
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.moveColumnSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.moveColumnSelection(-1);
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
     * Handle Enter/Select key
     */
    handleSelect(): void {
        const card = this.getSelectedCard();
        if (card) {
            card.click();
        }
    }
    
    /**
     * Enter navigation mode
     */
    enterNavigationMode(): void {
        this.navigationMode = true;
        
        if (this.selectedColumnIndex === -1) {
            this.moveColumnSelection(1);
        }
    }
    
    /**
     * Exit navigation mode
     */
    exitNavigationMode(): void {
        if (!this.kanbanBoard) return;
        
        // Remove all selection highlights
        this.kanbanBoard.querySelectorAll('[data-kanban-card].ring-2').forEach(card => {
            card.classList.remove('ring-2', 'ring-primary');
        });
        
        this.selectedColumnIndex = -1;
        this.selectedCardIndex = -1;
        this.navigationMode = false;
    }
    
    /**
     * Open context menu on the currently selected card
     */
    openContextMenuOnSelected(): void {
        const card = this.getSelectedCard();
        if (card) {
            this.onContextMenuRequest(card, true);
        }
    }
    
    /**
     * Set up drag and drop for kanban cards
     */
    private setupDragAndDrop(): void {
        if (!this.kanbanBoard) return;
        
        const cards = this.kanbanBoard.querySelectorAll('[data-kanban-card]');
        const dropzones = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        
        // Set up drag events for cards
        cards.forEach(card => {
            const cardElement = card as HTMLElement;
            
            cardElement.addEventListener('dragstart', (e: DragEvent) => {
                this.handleDragStart(e, cardElement);
            }, { signal: this.abortController.signal });
            
            cardElement.addEventListener('dragend', (e: DragEvent) => {
                this.handleDragEnd(e, cardElement);
            }, { signal: this.abortController.signal });
        });
        
        // Set up drop events for columns
        dropzones.forEach(dropzone => {
            const dropzoneElement = dropzone as HTMLElement;
            
            dropzoneElement.addEventListener('dragover', (e: DragEvent) => {
                this.handleDragOver(e, dropzoneElement);
            }, { signal: this.abortController.signal });
            
            dropzoneElement.addEventListener('dragenter', (e: DragEvent) => {
                this.handleDragEnter(e, dropzoneElement);
            }, { signal: this.abortController.signal });
            
            dropzoneElement.addEventListener('dragleave', (e: DragEvent) => {
                this.handleDragLeave(e, dropzoneElement);
            }, { signal: this.abortController.signal });
            
            dropzoneElement.addEventListener('drop', (e: DragEvent) => {
                this.handleDrop(e, dropzoneElement);
            }, { signal: this.abortController.signal });
        });
    }
    
    /**
     * Handle drag start event
     */
    private handleDragStart(e: DragEvent, card: HTMLElement): void {
        this.draggedCard = card;
        
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', card.dataset.objectId || '');
        }
        
        requestAnimationFrame(() => {
            card.classList.add('dragging');
        });
        
        // Create a placeholder
        this.draggedCardPlaceholder = document.createElement('div');
        this.draggedCardPlaceholder.className = 'kanban-card-placeholder bg-blue-100 border-2 border-dashed border-blue-300 rounded-lg';
        this.draggedCardPlaceholder.style.height = `${card.offsetHeight}px`;
        this.draggedCardPlaceholder.style.minHeight = '60px';
    }
    
    /**
     * Handle drag end event
     */
    private handleDragEnd(e: DragEvent, card: HTMLElement): void {
        card.classList.remove('dragging');
        
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode) {
            this.draggedCardPlaceholder.parentNode.removeChild(this.draggedCardPlaceholder);
        }
        
        const dropzones = this.kanbanBoard?.querySelectorAll('[data-kanban-dropzone]');
        dropzones?.forEach(dz => {
            dz.classList.remove('drag-over');
        });
        
        this.draggedCard = null;
        this.draggedCardPlaceholder = null;
    }
    
    /**
     * Handle drag over event
     */
    private handleDragOver(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        
        if (e.dataTransfer) {
            e.dataTransfer.dropEffect = 'move';
        }
        
        if (this.draggedCard && this.draggedCardPlaceholder) {
            const cards = Array.from(dropzone.querySelectorAll('[data-kanban-card]:not(.dragging)'));
            const mouseY = e.clientY;
            
            let insertBefore: Element | null = null;
            for (const card of cards) {
                const rect = card.getBoundingClientRect();
                const cardMiddle = rect.top + rect.height / 2;
                
                if (mouseY < cardMiddle) {
                    insertBefore = card;
                    break;
                }
            }
            
            if (insertBefore) {
                if (this.draggedCardPlaceholder.nextSibling !== insertBefore) {
                    dropzone.insertBefore(this.draggedCardPlaceholder, insertBefore);
                }
            } else {
                if (this.draggedCardPlaceholder.parentNode !== dropzone || 
                    this.draggedCardPlaceholder.nextSibling !== null) {
                    dropzone.appendChild(this.draggedCardPlaceholder);
                }
            }
        }
    }
    
    /**
     * Handle drag enter event
     */
    private handleDragEnter(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        dropzone.classList.add('drag-over');
    }
    
    /**
     * Handle drag leave event
     */
    private handleDragLeave(e: DragEvent, dropzone: HTMLElement): void {
        const relatedTarget = e.relatedTarget as HTMLElement;
        if (!dropzone.contains(relatedTarget)) {
            dropzone.classList.remove('drag-over');
        }
    }
    
    /**
     * Handle drop event
     */
    private handleDrop(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        dropzone.classList.remove('drag-over');
        
        if (!this.draggedCard) return;
        
        const objectId = this.draggedCard.dataset.objectId || '';
        const newColumnValue = dropzone.dataset.columnValue || '';
        const oldColumnValue = this.draggedCard.closest('[data-kanban-dropzone]')?.getAttribute('data-column-value') || '';
        
        let insertBeforeCard: HTMLElement | null = null;
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode === dropzone) {
            const nextSibling = this.draggedCardPlaceholder.nextElementSibling;
            if (nextSibling && nextSibling.hasAttribute('data-kanban-card')) {
                insertBeforeCard = nextSibling as HTMLElement;
            }
        }
        
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode) {
            this.draggedCardPlaceholder.parentNode.removeChild(this.draggedCardPlaceholder);
        }
        
        this.moveCard(this.draggedCard, dropzone, insertBeforeCard, objectId, oldColumnValue, newColumnValue);
    }
    
    /**
     * Get the currently selected kanban card element
     */
    private getSelectedCard(): HTMLElement | null {
        if (!this.kanbanBoard || this.selectedColumnIndex === -1 || this.selectedCardIndex === -1) {
            return null;
        }
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (this.selectedColumnIndex >= columns.length) return null;
        
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (this.selectedCardIndex >= cards.length) return null;
        
        return cards[this.selectedCardIndex] as HTMLElement;
    }
    
    /**
     * Highlight the selected kanban card
     */
    private highlightCard(card: HTMLElement): void {
        card.classList.add('ring-2', 'ring-primary');
        card.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    
    /**
     * Remove highlight from a kanban card
     */
    private unhighlightCard(card: HTMLElement): void {
        card.classList.remove('ring-2', 'ring-primary');
    }
    
    /**
     * Move kanban card selection within a column (up/down)
     */
    private moveCardSelection(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (columns.length === 0) return;
        
        // If no column selected, select the first one
        if (this.selectedColumnIndex === -1) {
            this.selectedColumnIndex = 0;
            this.selectedCardIndex = -1;
        }
        
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (cards.length === 0) return;
        
        // Remove previous selection
        const previousCard = this.getSelectedCard();
        if (previousCard) {
            this.unhighlightCard(previousCard);
        }
        
        // Update selection index
        if (this.selectedCardIndex === -1) {
            this.selectedCardIndex = direction > 0 ? 0 : cards.length - 1;
        } else {
            this.selectedCardIndex += direction;
        }
        
        // Clamp to valid range
        if (this.selectedCardIndex < 0) {
            this.selectedCardIndex = 0;
        } else if (this.selectedCardIndex >= cards.length) {
            this.selectedCardIndex = cards.length - 1;
        }
        
        // Highlight new selection
        const selectedCard = cards[this.selectedCardIndex] as HTMLElement;
        this.highlightCard(selectedCard);
    }
    
    /**
     * Move kanban column selection (left/right navigation)
     */
    private moveColumnSelection(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (columns.length === 0) return;
        
        // Remove previous card selection
        const previousCard = this.getSelectedCard();
        if (previousCard) {
            this.unhighlightCard(previousCard);
        }
        
        // Update column index
        if (this.selectedColumnIndex === -1) {
            this.selectedColumnIndex = direction > 0 ? 0 : columns.length - 1;
        } else {
            this.selectedColumnIndex += direction;
        }
        
        // Clamp to valid range
        if (this.selectedColumnIndex < 0) {
            this.selectedColumnIndex = 0;
        } else if (this.selectedColumnIndex >= columns.length) {
            this.selectedColumnIndex = columns.length - 1;
        }
        
        // Try to maintain card position, or select first card
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (cards.length > 0) {
            if (this.selectedCardIndex === -1 || this.selectedCardIndex >= cards.length) {
                this.selectedCardIndex = Math.min(this.selectedCardIndex, cards.length - 1);
                if (this.selectedCardIndex < 0) this.selectedCardIndex = 0;
            }
            
            const selectedCard = cards[this.selectedCardIndex] as HTMLElement;
            this.highlightCard(selectedCard);
        } else {
            this.selectedCardIndex = -1;
        }
    }
    
    /**
     * Move the currently selected kanban card to an adjacent column
     */
    private moveCardToColumn(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const card = this.getSelectedCard();
        if (!card) {
            this.showMessage('No card selected', 'warning');
            return;
        }
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        const targetColumnIndex = this.selectedColumnIndex + direction;
        
        if (targetColumnIndex < 0 || targetColumnIndex >= columns.length) {
            this.showMessage('Cannot move card further in this direction', 'info');
            return;
        }
        
        const sourceColumn = columns[this.selectedColumnIndex];
        const targetColumn = columns[targetColumnIndex] as HTMLElement;
        
        const oldColumnValue = sourceColumn.getAttribute('data-column-value') || '';
        const newColumnValue = targetColumn.getAttribute('data-column-value') || '';
        const objectId = card.dataset.objectId || '';
        
        this.unhighlightCard(card);
        
        const targetCards = targetColumn.querySelectorAll('[data-kanban-card]');
        let insertBeforeCard: HTMLElement | null = null;
        if (this.selectedCardIndex < targetCards.length) {
            insertBeforeCard = targetCards[this.selectedCardIndex] as HTMLElement;
        }
        
        this.moveCard(card, targetColumn, insertBeforeCard, objectId, oldColumnValue, newColumnValue);
        
        this.selectedColumnIndex = targetColumnIndex;
        
        const newCards = targetColumn.querySelectorAll('[data-kanban-card]');
        const cardIndex = Array.from(newCards).indexOf(card);
        if (cardIndex !== -1) {
            this.selectedCardIndex = cardIndex;
        }
        
        this.highlightCard(card);
    }
    
    /**
     * Move a kanban card to a target column
     */
    private moveCard(
        card: HTMLElement,
        targetColumn: HTMLElement,
        insertBeforeCard: HTMLElement | null,
        objectId: string,
        oldColumnValue: string,
        newColumnValue: string
    ): void {
        if (insertBeforeCard) {
            targetColumn.insertBefore(card, insertBeforeCard);
        } else {
            targetColumn.appendChild(card);
        }
        
        this.updateColumnCounts();
        
        console.log('Card moved:', {
            objectId,
            from: oldColumnValue,
            to: newColumnValue
        });
        
        if (oldColumnValue !== newColumnValue) {
            this.showMessage(`Card moved to ${newColumnValue || 'new column'}`, 'info');
        }
    }
    
    /**
     * Update the item counts in column headers
     */
    private updateColumnCounts(): void {
        if (!this.kanbanBoard) return;
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-column]');
        columns.forEach(column => {
            const dropzone = column.querySelector('[data-kanban-dropzone]');
            const countBadge = column.querySelector('.kanban-column-header span');
            
            if (dropzone && countBadge) {
                const cardCount = dropzone.querySelectorAll('[data-kanban-card]').length;
                countBadge.textContent = cardCount.toString();
            }
        });
    }
}
