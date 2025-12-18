import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getComponent } from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { componentIdentifier } from "./BaseComponent";

export class KanbanCard extends BaseDataViewCell {
    public initialize(): void {
    super.initialize();
    }

    moveRight() {

    }

    moveLeft() {
    }

    /**
     * Happens on rightclick of the cell
     */
    public override rightClick(event: MouseEvent | PointerEvent): void {
        void event;
        console.log('Rightclick')
    }
}

export class KanbanBoard extends BaseDataViewComponent {
    protected cellClass = KanbanCard;

    public initialize(): void {
        if (!this.element) return;
        const abortController = this.ensureAbortController();

        // Make board focusable for keyboard navigation
        this.element.setAttribute('tabindex', '0');

        this.element.addEventListener(
            'keydown',
            (event: KeyboardEvent) => this.handleKeyDown(event),
            { signal: abortController.signal }
        );
    }

    public destroy(): void {
        super.destroy();
    }
    
    keyup(): void {
        this.moveInColumn(-1);
        console.log(this.currentCell)
    }
    
    keydown(): void {
        this.moveInColumn(1);
    }

    keyleft(): void {
        this.moveToAdjacentColumn(-1);
    }

    keyright(): void {
        this.moveToAdjacentColumn(1);
    }

    private moveInColumn(delta: number): void {
        if (!this.element || !this.currentCell?.element) return;

        const currentEl = this.currentCell.element;
        const columnBody = currentEl.closest('[data-kanban-dropzone]') as HTMLElement | null;
        if (!columnBody) return;

        const cards = Array.from(
            columnBody.querySelectorAll<HTMLElement>(`[${componentIdentifier}="kanban-card"]`)
        );
        if (cards.length === 0) return;

        const index = cards.indexOf(currentEl);
        if (index === -1) return;

        let nextIndex = index + delta;
        if (nextIndex < 0) nextIndex = 0;
        if (nextIndex >= cards.length) nextIndex = cards.length - 1;

        const nextEl = cards[nextIndex] ?? null;
        const next = nextEl ? (getComponent(nextEl) as KanbanCard | null) : null;
        if (!next) return;

        this.focus(next);
        nextEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    private moveToAdjacentColumn(direction: -1 | 1): void {
        if (!this.element || !this.currentCell?.element) return;

        const currentEl = this.currentCell.element;
        const currentColumn = currentEl.closest('.kanban-column') as HTMLElement | null;
        if (!currentColumn) return;

        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        if (columns.length === 0) return;

        const columnIndex = columns.indexOf(currentColumn);
        if (columnIndex === -1) return;

        let nextColumnIndex = columnIndex + direction;
        if (nextColumnIndex < 0) nextColumnIndex = 0;
        if (nextColumnIndex >= columns.length) nextColumnIndex = columns.length - 1;

        const targetColumn = columns[nextColumnIndex];
        const targetBody = targetColumn.querySelector<HTMLElement>('[data-kanban-dropzone]');
        if (!targetBody) return;

        const currentBody = currentEl.closest('[data-kanban-dropzone]') as HTMLElement | null;
        if (!currentBody) return;

        const currentCards = Array.from(
            currentBody.querySelectorAll<HTMLElement>('[bloomerp-component="kanban-card"]')
        );
        const currentIndex = currentCards.indexOf(currentEl);

        const targetCards = Array.from(
            targetBody.querySelectorAll<HTMLElement>('[bloomerp-component="kanban-card"]')
        );
        if (targetCards.length === 0) return;

        let targetIndex = currentIndex;
        if (targetIndex < 0) targetIndex = 0;
        if (targetIndex >= targetCards.length) targetIndex = targetCards.length - 1;

        const nextEl = targetCards[targetIndex] ?? null;
        const next = nextEl ? (getComponent(nextEl) as KanbanCard | null) : null;
        if (!next) return;

        this.focus(next);
        nextEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
}