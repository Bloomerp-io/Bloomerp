import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getComponent } from "../BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { componentIdentifier } from "../BaseComponent";
import type { ContextMenuItem } from "../../utils/contextMenu";
import { getCsrfToken } from "../../utils/cookies";
import showMessage from "../../utils/messages";
import { MessageType } from "../UiMessage";


export class KanbanCard extends BaseDataViewCell {
    public initialize(): void {
        super.initialize();
    }
}

export class KanbanBoard extends BaseDataViewComponent {
    protected cellClass = KanbanCard;
    private activeDragCard: HTMLElement | null = null;
    private activeDragSource: HTMLElement | null = null;
    private activeDragSourceValue: string | null = null;

    public initialize(): void {
        if (!this.element) return;

        super.initialize();

        this.setupDragAndDrop();
    }

    public override constructContextMenu(): ContextMenuItem[] {
        let contextMenu: ContextMenuItem[] = [
            {
                label: "Move right",
                icon: 'fa-solid fa-arrow-right',
                onClick: async () => {
                    await this.moveCardByDirection(1);
                },

            },
            {
                label: "Move left",
                icon: 'fa-solid fa-arrow-left',
                onClick: async () => {
                    await this.moveCardByDirection(-1);
                },
            },
            {
                label: "Move to",
                icon: 'fa-solid fa-arrow-right-arrow-left',
                onClick: async () => {},
            },
        ]

        if (this.hasMultipleSelection()) return contextMenu

        const ctxMenu: ContextMenuItem[] = [
            {
                label: "navigate",
                icon: 'fa-solid fa-location-arrow',
                onClick: async () => {
                    this.currentCell?.click();
                },
            }
        ]

        contextMenu = ctxMenu.concat(contextMenu)

        return contextMenu
    }

    public moveCellUp(): BaseDataViewCell {
        return this.getNextCardInColumn(-1) ?? this.currentCell!;
    }

    public moveCellDown(): BaseDataViewCell {
        return this.getNextCardInColumn(1) ?? this.currentCell!;
    }

    public moveCellLeft(): BaseDataViewCell {
        return this.getCardInAdjacentColumn(-1) ?? this.currentCell!;
    }

    public moveCellRight(): BaseDataViewCell {
        return this.getCardInAdjacentColumn(1) ?? this.currentCell!;
    }

    protected override handleAltArrow(event: KeyboardEvent): boolean {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
            return false;
        }

        event.preventDefault();
        const direction = event.key === 'ArrowLeft' ? -1 : 1;
        void this.moveCardByDirection(direction);
        return true;
    }

    private setupDragAndDrop(): void {
        if (!this.element) return;

        const cards = Array.from(
            this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}="kanban-card"]`)
        );
        for (const card of cards) {
            card.addEventListener('dragstart', this.onDragStart);
            card.addEventListener('dragend', this.onDragEnd);
        }

        const dropzones = Array.from(
            this.element.querySelectorAll<HTMLElement>('[data-kanban-dropzone]')
        );
        for (const dropzone of dropzones) {
            dropzone.addEventListener('dragover', this.onDragOver);
            dropzone.addEventListener('dragenter', this.onDragEnter);
            dropzone.addEventListener('dragleave', this.onDragLeave);
            dropzone.addEventListener('drop', this.onDrop);
        }
    }

    private onDragStart = (event: DragEvent): void => {
        const target = event.currentTarget as HTMLElement | null;
        if (!target) return;

        this.activeDragCard = target;
        this.activeDragSource = target.closest('[data-kanban-dropzone]') as HTMLElement | null;
        this.activeDragSourceValue = this.activeDragSource?.dataset.columnValue ?? null;

        target.classList.add('dragging');
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', target.dataset.objectId ?? '');
        }
    };

    private onDragEnd = (): void => {
        if (this.activeDragCard) {
            this.activeDragCard.classList.remove('dragging');
        }
        this.clearDropzoneHighlights();
        this.activeDragCard = null;
        this.activeDragSource = null;
        this.activeDragSourceValue = null;
    };

    private onDragOver = (event: DragEvent): void => {
        event.preventDefault();
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = 'move';
        }
    };

    private onDragEnter = (event: DragEvent): void => {
        const dropzone = (event.currentTarget as HTMLElement | null);
        if (!dropzone) return;
        dropzone.classList.add('drag-over');
    };

    private onDragLeave = (event: DragEvent): void => {
        const dropzone = (event.currentTarget as HTMLElement | null);
        if (!dropzone) return;
        dropzone.classList.remove('drag-over');
    };

    private onDrop = async (event: DragEvent): Promise<void> => {
        event.preventDefault();
        const dropzone = event.currentTarget as HTMLElement | null;
        if (!dropzone || !this.activeDragCard) return;

        dropzone.classList.remove('drag-over');

        await this.moveCardTo(this.activeDragCard, dropzone);
    };

    private async moveCardByDirection(direction: -1 | 1): Promise<void> {
        if (!this.currentCell?.element) return;

        const destinationDropzone = this.getAdjacentDropzone(direction, this.currentCell.element);
        if (!destinationDropzone) return;

        await this.moveCardTo(this.currentCell.element, destinationDropzone);
    }

    private async moveCardTo(card: HTMLElement, destinationDropzone: HTMLElement): Promise<void> {
        const originDropzone = card.closest('[data-kanban-dropzone]') as HTMLElement | null;
        const originValue = originDropzone?.dataset.columnValue ?? null;
        const destinationValue = destinationDropzone.dataset.columnValue ?? null;

        if (originDropzone === destinationDropzone) return;
        if (destinationValue === null || originValue === null) return;

        this.removeEmptyPlaceholder(destinationDropzone);
        destinationDropzone.appendChild(card);
        this.ensureEmptyPlaceholder(originDropzone);
        this.updateCounts();

        const updateSucceeded = await this.persistMove(card, destinationValue);
        if (!updateSucceeded) {
            if (originDropzone) {
                this.removeEmptyPlaceholder(originDropzone);
                originDropzone.appendChild(card);
            }
            this.ensureEmptyPlaceholder(destinationDropzone);
            this.updateCounts();
        }
    }

    private async persistMove(card: HTMLElement, destinationValue: string): Promise<boolean> {
        if (!this.element) return false;

        const contentTypeId = this.element.dataset.contentTypeId;
        const groupByFieldId = this.element.dataset.groupByFieldId;
        const objectId = card.dataset.objectId;

        if (!contentTypeId || !groupByFieldId || !objectId) return false;

        const csrfToken = getCsrfToken();
        const body = new URLSearchParams({
            object_id: objectId,
            group_by_field_id: groupByFieldId,
            group_value: destinationValue,
        });

        try {
            const response = await fetch(`/components/kanban_move_card/${contentTypeId}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                },
                body,
            });

            if (!response.ok) {
                if (response.status === 403) {
                    showMessage('You do not have permission to move this card.', MessageType.ERROR);
                } else {
                    showMessage('Unable to move card. Please try again.', MessageType.ERROR);
                }
                console.error('Failed to move kanban card', await response.text());
                return false;
            }
            return true;
        } catch (error) {
            showMessage('Unable to move card. Please try again.', MessageType.ERROR);
            console.error('Failed to move kanban card', error);
            return false;
        }
    }

    private ensureEmptyPlaceholder(dropzone: HTMLElement | null): void {
        if (!dropzone) return;

        const cards = dropzone.querySelectorAll(`[${componentIdentifier}="kanban-card"]`);
        if (cards.length > 0) return;

        const placeholder = document.createElement('div');
        placeholder.className = 'text-center py-4 text-gray-400 text-sm';
        placeholder.textContent = 'No items';
        dropzone.appendChild(placeholder);
    }

    private removeEmptyPlaceholder(dropzone: HTMLElement | null): void {
        if (!dropzone) return;

        const placeholders = Array.from(
            dropzone.querySelectorAll<HTMLElement>('.text-center.py-4.text-gray-400.text-sm')
        );
        for (const placeholder of placeholders) {
            if (!placeholder.hasAttribute(componentIdentifier)) {
                placeholder.remove();
            }
        }
    }

    private updateCounts(): void {
        if (!this.element) return;

        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        for (const column of columns) {
            const countEl = column.querySelector<HTMLElement>('[data-kanban-count]');
            const dropzone = column.querySelector<HTMLElement>('[data-kanban-dropzone]');
            if (!countEl || !dropzone) continue;

            const cardCount = dropzone.querySelectorAll(`[${componentIdentifier}="kanban-card"]`).length;
            countEl.textContent = String(cardCount);
        }
    }

    private clearDropzoneHighlights(): void {
        if (!this.element) return;
        const dropzones = Array.from(
            this.element.querySelectorAll<HTMLElement>('[data-kanban-dropzone].drag-over')
        );
        for (const dropzone of dropzones) {
            dropzone.classList.remove('drag-over');
        }
    }

    private getAdjacentDropzone(direction: -1 | 1, card: HTMLElement): HTMLElement | null {
        if (!this.element) return null;

        const currentColumn = card.closest('.kanban-column') as HTMLElement | null;
        if (!currentColumn) return null;

        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        if (columns.length === 0) return null;

        const columnIndex = columns.indexOf(currentColumn);
        if (columnIndex === -1) return null;

        let nextColumnIndex = columnIndex + direction;
        if (nextColumnIndex < 0) nextColumnIndex = 0;
        if (nextColumnIndex >= columns.length) nextColumnIndex = columns.length - 1;

        const targetColumn = columns[nextColumnIndex];
        return targetColumn.querySelector<HTMLElement>('[data-kanban-dropzone]');
    }
    
    // Helper functions
    private getNextCardInColumn(delta: number): KanbanCard | null {
        if (!this.element || !this.currentCell?.element) return null;

        const currentEl = this.currentCell.element;
        const columnBody = currentEl.closest('[data-kanban-dropzone]') as HTMLElement | null;
        if (!columnBody) return null;

        const cards = Array.from(
            columnBody.querySelectorAll<HTMLElement>(`[${componentIdentifier}="kanban-card"]`)
        );
        if (cards.length === 0) return null;

        const index = cards.indexOf(currentEl);
        if (index === -1) return null;

        let nextIndex = index + delta;
        if (nextIndex < 0) nextIndex = 0;
        if (nextIndex >= cards.length) nextIndex = cards.length - 1;

        const nextEl = cards[nextIndex] ?? null;
        return nextEl ? (getComponent(nextEl) as KanbanCard | null) : null;
    }

    private getCardInAdjacentColumn(direction: -1 | 1): KanbanCard | null {
        if (!this.element || !this.currentCell?.element) return null;

        const currentEl = this.currentCell.element;
        const currentColumn = currentEl.closest('.kanban-column') as HTMLElement | null;
        if (!currentColumn) return null;

        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        if (columns.length === 0) return null;

        const columnIndex = columns.indexOf(currentColumn);
        if (columnIndex === -1) return null;

        let nextColumnIndex = columnIndex + direction;
        if (nextColumnIndex < 0) nextColumnIndex = 0;
        if (nextColumnIndex >= columns.length) nextColumnIndex = columns.length - 1;

        const targetColumn = columns[nextColumnIndex];
        const targetBody = targetColumn.querySelector<HTMLElement>('[data-kanban-dropzone]');
        if (!targetBody) return null;

        const currentBody = currentEl.closest('[data-kanban-dropzone]') as HTMLElement | null;
        if (!currentBody) return null;

        const currentCards = Array.from(
            currentBody.querySelectorAll<HTMLElement>('[bloomerp-component="kanban-card"]')
        );
        const currentIndex = currentCards.indexOf(currentEl);

        const targetCards = Array.from(
            targetBody.querySelectorAll<HTMLElement>('[bloomerp-component="kanban-card"]')
        );
        if (targetCards.length === 0) return null;

        let targetIndex = currentIndex;
        if (targetIndex < 0) targetIndex = 0;
        if (targetIndex >= targetCards.length) targetIndex = targetCards.length - 1;

        const nextEl = targetCards[targetIndex] ?? null;
        return nextEl ? (getComponent(nextEl) as KanbanCard | null) : null;
    }
}
