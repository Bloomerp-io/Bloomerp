import { t as _ } from "@/utils/i18n";
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

    private keyboardMoveCard: HTMLElement | null = null;
    private keyboardMoveTarget: HTMLElement | null = null;
    private readonly onMoveKeyDown = this.handleMoveKeyDown.bind(this);

    /** Initialize card navigation, drag targets and keyboard category selection. */
    public initialize(): void {
        if (!this.element) return;

        super.initialize();

        this.setupDragAndDrop();
    }

    /** Clear active movement state and release inherited event listeners on teardown. */
    public override destroy(): void {
        this.cancelKeyboardMove();
        this.onDragEnd();
        super.destroy();
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

    /** Register abortable movement listeners for lane bodies and category sections. */
    private setupDragAndDrop(): void {
        if (!this.element) return;
        const abortController = this.ensureAbortController();

        this.element.addEventListener('keydown', this.onMoveKeyDown, { capture: true, signal: abortController.signal });
        this.element.addEventListener('dragstart', this.onDragStart, { signal: abortController.signal });
        this.element.addEventListener('dragend', this.onDragEnd, { signal: abortController.signal });

        const dropzones = Array.from(
            this.element.querySelectorAll<HTMLElement>('[data-kanban-dropzone]')
        );
        for (const dropzone of dropzones) {
            dropzone.addEventListener('dragover', this.onDragOver, { signal: abortController.signal });
            dropzone.addEventListener('dragenter', this.onDragEnter, { signal: abortController.signal });
            dropzone.addEventListener('dragleave', this.onDragLeave, { signal: abortController.signal });
            dropzone.addEventListener('drop', this.onDrop, { signal: abortController.signal });
        }
    }

    /** Keep the source card available while revealing category sections after drag starts. */
    private onDragStart = (event: DragEvent): void => {
        const eventTarget = event.target as HTMLElement | null;
        const target = eventTarget?.closest<HTMLElement>(`[${componentIdentifier}="kanban-card"]`) ?? null;
        if (!target) return;

        this.activeDragCard = target;
        this.activeDragSource = target.closest('[data-kanban-dropzone]') as HTMLElement | null;
        this.activeDragSourceValue = this.activeDragSource?.dataset.columnValue ?? null;

        this.cancelKeyboardMove();
        target.classList.add('dragging');
        requestAnimationFrame((): void => {
            if (this.activeDragCard === target) this.element?.classList.add('kanban-moving');
        });
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', target.dataset.objectId ?? '');
        }
    };

    /** Restore ordinary card lanes when dragging ends. */
    private onDragEnd = (): void => {
        if (this.activeDragCard) {
            this.activeDragCard.classList.remove('dragging');
        }
        this.element?.classList.remove('kanban-moving');
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

    /** Highlight only the concrete category under the pointer, without shared drag styles. */
    private onDragEnter = (event: DragEvent): void => {
        const dropzone = (event.currentTarget as HTMLElement | null);
        if (!dropzone?.hasAttribute('data-kanban-target')) return;
        dropzone.classList.add('kanban-drag-over');
    };

    /** Clear a category highlight only when the pointer leaves its full section. */
    private onDragLeave = (event: DragEvent): void => {
        const dropzone = (event.currentTarget as HTMLElement | null);
        if (!dropzone) return;
        if (event.relatedTarget instanceof Node && dropzone.contains(event.relatedTarget)) return;
        dropzone.classList.remove('kanban-drag-over');
    };

    /** Persist the concrete category under the pointer without bubbling to its lane body. */
    private onDrop = async (event: DragEvent): Promise<void> => {
        event.preventDefault();
        event.stopPropagation();
        const dropzone = event.currentTarget as HTMLElement | null;
        if (!dropzone || !this.activeDragCard) return;

        dropzone.classList.remove('kanban-drag-over');

        await this.moveCardTo(this.activeDragCard, dropzone);
    };

    /** Begin a keyboard move in the adjacent lane and let the user choose its category. */
    private async moveCardByDirection(direction: -1 | 1): Promise<void> {
        if (!this.currentCell?.element) return;
        if (this.currentCell.element.dataset.kanbanMoving === 'true') return;
        const destination = this.getAdjacentDropzone(direction, this.currentCell.element);
        const target = destination?.querySelector<HTMLElement>('[data-kanban-target]');
        if (!target) return;
        this.keyboardMoveCard = this.currentCell.element;
        this.element?.classList.add('kanban-moving', 'kanban-keyboard-moving');
        this.selectKeyboardTarget(target);
    }

    /** Handle category navigation, confirmation and cancellation during a keyboard move. */
    private handleMoveKeyDown(event: KeyboardEvent): void {
        if (!this.keyboardMoveCard || !this.keyboardMoveTarget) return;
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Enter', 'Escape', 'Tab'].includes(event.key)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (event.key === 'Escape' || event.key === 'Tab') {
            this.cancelKeyboardMove();
            return;
        }
        if (event.key === 'Enter') {
            const card = this.keyboardMoveCard;
            const target = this.keyboardMoveTarget;
            this.cancelKeyboardMove();
            void this.moveCardTo(card, target);
            return;
        }
        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        const column = this.keyboardMoveTarget.closest<HTMLElement>('.kanban-column');
        const targets = Array.from(column?.querySelectorAll<HTMLElement>('[data-kanban-target]') ?? []);
        const categoryIndex = targets.indexOf(this.keyboardMoveTarget);
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            const index = Math.max(0, Math.min(targets.length - 1, categoryIndex + (event.key === 'ArrowUp' ? -1 : 1)));
            this.selectKeyboardTarget(targets[index]);
        } else {
            const index = Math.max(0, Math.min(columns.length - 1, columns.indexOf(column!) + (event.key === 'ArrowLeft' ? -1 : 1)));
            const nextTargets = Array.from(columns[index].querySelectorAll<HTMLElement>('[data-kanban-target]'));
            this.selectKeyboardTarget(nextTargets[Math.min(categoryIndex, nextTargets.length - 1)]);
        }
    }

    /** Highlight and announce the selected category while keeping keyboard focus on the board. */
    private selectKeyboardTarget(target: HTMLElement | undefined): void {
        if (!target) return;
        this.keyboardMoveTarget?.classList.remove('keyboard-target');
        this.keyboardMoveTarget = target;
        target.classList.add('keyboard-target');
        target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        const help = this.element.nextElementSibling;
        if (help?.classList.contains('kanban-move-help')) {
            help.textContent = `Move to ${target.textContent?.trim()}. Use arrow keys to choose a category, Enter to move, or Escape to cancel.`;
        }
        this.element.focus();
    }

    /** Close category selection without changing the card's stored value. */
    private cancelKeyboardMove(): void {
        this.keyboardMoveTarget?.classList.remove('keyboard-target');
        this.keyboardMoveCard = null;
        this.keyboardMoveTarget = null;
        this.element?.classList.remove('kanban-moving', 'kanban-keyboard-moving');
    }

    /** Move to a concrete status, including another status inside the same custom lane. */
    private async moveCardTo(card: HTMLElement, targetDropzone: HTMLElement): Promise<void> {
        const originDropzone = card.closest<HTMLElement>('.kanban-column-body');
        const destinationColumn = targetDropzone.closest<HTMLElement>('.kanban-column');
        const destinationDropzone = destinationColumn?.querySelector<HTMLElement>('.kanban-column-body');
        if (!originDropzone || !destinationDropzone || card.dataset.kanbanMoving === 'true') return;
        const destinationValue = targetDropzone.dataset.columnValue;
        if (destinationValue === undefined) return;
        const sameLane = originDropzone === destinationDropzone;
        const nextSibling = card.nextSibling;
        card.dataset.kanbanMoving = 'true';
        if (!sameLane) {
            this.removeEmptyPlaceholder(destinationDropzone);
            destinationDropzone.appendChild(card);
            this.ensureEmptyPlaceholder(originDropzone);
            this.adjustColumnTotals(originDropzone, destinationDropzone);
            this.updateCounts();
        }
        const updateSucceeded = await this.persistMove(card, destinationValue);
        if (!updateSucceeded && !sameLane) {
            this.removeEmptyPlaceholder(originDropzone);
            originDropzone.insertBefore(card, nextSibling?.parentNode === originDropzone ? nextSibling : null);
            this.ensureEmptyPlaceholder(destinationDropzone);
            this.adjustColumnTotals(destinationDropzone, originDropzone);
            this.updateCounts();
        }
        delete card.dataset.kanbanMoving;
        if (updateSucceeded) this.dataViewContainer?.refresh();
    }

    private async persistMove(card: HTMLElement, destinationValue: string): Promise<boolean> {
        if (!this.element) return false;

        const moveUrl = this.element.dataset.kanbanMoveUrl;
        const objectId = card.dataset.objectId;

        if (!moveUrl || !objectId) return false;

        const csrfToken = getCsrfToken();
        const body = new URLSearchParams({
            object_id: objectId,
            group_value: destinationValue,
        });

        try {
            const response = await fetch(moveUrl, {
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

    /** Show localized feedback when the last card leaves a column. */
    private ensureEmptyPlaceholder(dropzone: HTMLElement | null): void {
        if (!dropzone) return;

        const cards = dropzone.querySelectorAll(`[${componentIdentifier}="kanban-card"]`);
        if (cards.length > 0) return;

        const placeholder = document.createElement('div');
        placeholder.className = 'text-center py-4 text-gray-400 text-sm';
        placeholder.textContent = _('No items');
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

    /** Refresh counts from lane totals rather than destination target elements. */
    private updateCounts(): void {
        if (!this.element) return;

        const columns = Array.from(this.element.querySelectorAll<HTMLElement>('.kanban-column'));
        for (const column of columns) {
            const countEl = column.querySelector<HTMLElement>('[data-kanban-count]');
            const dropzone = column.querySelector<HTMLElement>('.kanban-column-body');
            if (!countEl || !dropzone) continue;

            const totalCount = column.dataset.kanbanTotalCount;
            const visibleCount = dropzone.querySelectorAll(`[${componentIdentifier}="kanban-card"]`).length;
            countEl.textContent = totalCount ?? String(visibleCount);
        }
    }

    private adjustColumnTotals(originDropzone: HTMLElement | null, destinationDropzone: HTMLElement | null): void {
        const originColumn = originDropzone?.closest<HTMLElement>('.kanban-column');
        const destinationColumn = destinationDropzone?.closest<HTMLElement>('.kanban-column');

        this.incrementColumnTotal(originColumn, -1);
        this.incrementColumnTotal(destinationColumn, 1);
    }

    private incrementColumnTotal(column: HTMLElement | null | undefined, delta: number): void {
        if (!column) return;

        const current = Number.parseInt(column.dataset.kanbanTotalCount ?? '', 10);
        if (!Number.isFinite(current)) return;

        column.dataset.kanbanTotalCount = String(Math.max(0, current + delta));
    }

    /** Remove Kanban-specific hover states from all registered drop zones. */
    private clearDropzoneHighlights(): void {
        if (!this.element) return;
        const dropzones = Array.from(
            this.element.querySelectorAll<HTMLElement>('[data-kanban-dropzone].kanban-drag-over')
        );
        for (const dropzone of dropzones) {
            dropzone.classList.remove('kanban-drag-over');
        }
    }

    /** Find the adjacent lane body for a keyboard move. */
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
        return targetColumn.querySelector<HTMLElement>('.kanban-column-body');
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

    /** Find a card in the adjacent lane body for keyboard navigation. */
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
        const targetBody = targetColumn.querySelector<HTMLElement>('.kanban-column-body');
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
