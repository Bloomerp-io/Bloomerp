import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getComponent } from "../BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { componentIdentifier } from "../BaseComponent";
import type { ContextMenuItem } from "../../utils/contextMenu";


export class KanbanCard extends BaseDataViewCell {
    public initialize(): void {
        super.initialize();
    }
}

export class KanbanBoard extends BaseDataViewComponent {
    protected cellClass = KanbanCard;

    public initialize(): void {
        if (!this.element) return;

        super.initialize();

    }

    public override constructContextMenu(): ContextMenuItem[] {
        let contextMenu: ContextMenuItem[] = [
            {
                label: "Move right",
                icon: 'fa-solid fa-arrow-right',
                onClick: async () => {},

            },
            {
                label: "Move left",
                icon: 'fa-solid fa-arrow-left',
                onClick: async () => {},
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