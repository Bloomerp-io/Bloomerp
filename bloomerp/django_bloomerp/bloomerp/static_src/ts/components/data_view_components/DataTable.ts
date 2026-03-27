import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getComponent } from "../BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import type { ContextMenuItem } from "../../utils/contextMenu";
import htmx from "htmx.org";
import showMessage from "@/utils/messages";
import { MessageType } from "../UiMessage";
import getGeneralModal from "@/utils/modals";
import { attachObjectPreviewTooltip } from "@/utils/objectPreviewTooltip";

export class DataTableCell extends BaseDataViewCell {
    public columnIndex: number = -1;
    public rowIndex: number = -1;
    public applicationFieldName: string;
    public filterable: boolean = true;
    public value: string;
    public applicationFieldId : string | null = null;
    private previewCleanup: (() => void) | null = null;

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        // Column/row indices are provided by the template via data attributes
        const colAttr = this.element.getAttribute('data-column-index');
        const col = colAttr ? Number.parseInt(colAttr, 10) : NaN;
        this.columnIndex = Number.isFinite(col) ? col : -1;

        const rowAttr = this.element.getAttribute('data-row-index');
        const rowIndex = rowAttr ? Number.parseInt(rowAttr, 10) : NaN;
        this.rowIndex = Number.isFinite(rowIndex) ? rowIndex : -1;

        // Initialize other stuff
        this.applicationFieldName = this.element.getAttribute('data-application-field-name') ?? '';
        this.value = this.element.getAttribute('data-value') ?? '';

        this.applicationFieldId = this.element.dataset.applicationFieldId;

        const previewTarget = this.element.querySelector<HTMLElement>('[data-preview-object-id][data-preview-content-type-id]');
        const previewObjectId = previewTarget?.dataset.previewObjectId;
        const previewContentTypeId = previewTarget?.dataset.previewContentTypeId;
        if (previewTarget && previewObjectId && previewContentTypeId) {
            this.previewCleanup = attachObjectPreviewTooltip({
                element: previewTarget,
                objectId: previewObjectId,
                contentTypeId: previewContentTypeId,
            });
        }
    }

    public destroy(): void {
        this.previewCleanup?.();
        this.previewCleanup = null;
        super.destroy();
    }

}

export class DataTable extends BaseDataViewComponent {
    protected cellClass = DataTableCell;
    public currentCell: DataTableCell | null = null;

    public initialize(): void {
        super.initialize()
    }

    public constructContextMenu(): ContextMenuItem[] {
        const copyLabel = this.hasMultipleSelection() ? 'Copy Values' : 'Copy';

        let contextMenu: ContextMenuItem[] = [
            {
                label: copyLabel,
                icon: 'fa-solid fa-copy',
                onClick: async () => {
                    await this.copyToClipboard();
                    showMessage('Items copied to clipboard', MessageType.INFO, 5)
                },
            },
        ]

        // If there is a multiple selection, return
        if (this.hasMultipleSelection()) {return contextMenu}

        contextMenu = contextMenu.concat([
            {
                label: 'Navigate',
                icon: 'fa-solid fa-arrow-right',
                onClick: async () => {
                    this.currentCell.click()
                },
            },
            {
                label: 'Filter on value',
                icon: 'fa-solid fa-filter',
                onClick: async () => {
                    if (!this.currentCell?.applicationFieldName) return;
                    this.dataViewContainer?.filter({
                        [this.currentCell.applicationFieldName]: this.currentCell.value,
                    });
                    showMessage(`Filtered on ${this.currentCell.applicationFieldId} equals ${this.currentCell.value}`)
                },
            },
            {
                label: 'Update Object',
                icon: 'fa-solid fa-arrow-up-right-from-square',
                onClick: async () => {
                    const objectId = this.currentCell?.objectId;
                    let modal = getGeneralModal();
                    modal.setTitle('Update Object');
                    htmx.ajax(
                        'get',
                        `/components/update-object/${this.contentTypeId}/${objectId}/`,
                        {
                            target: modal.getBodyElement(),
                            swap: 'innerHTML',
                            push: 'false',
                        }
                    ).then(() => {
                        modal.open();
                    }).catch((error) => {
                        console.error('Error loading update object form:', error);
                    });
                }
            },
            {
                label: 'Edit Cell',
                icon: 'fa-solid fa-edit',
                onClick: async () => {
                    if (!this.currentCell) return;
                    
                    htmx.ajax(
                        'get', 
                        `/components/dataview_edit_field/${this.currentCell.applicationFieldId}/${this.currentCell.objectId}/`, 
                        {
                            target: this.currentCell.element,
                            swap: 'innerHTML',
                            push: 'false',
                        }
                    ).then(() => {
                        // After the HTML is swapped into the cell, focus the first
                        // input/textarea/select we can find and select its contents.
                        const el = this.currentCell?.element as HTMLElement | undefined | null;
                        const focusInput = () => {
                            if (!el) return;
                            const input = el.querySelector('input, textarea, select') as (HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null);
                            if (!input) return;
                            try {
                                input.focus();
                                // Select text for inputs/textareas where supported
                                if ((input as HTMLInputElement).select) {
                                    try { (input as HTMLInputElement).select(); } catch {}
                                }
                            } catch (err) {
                                // ignore focus errors
                            }
                        };

                        // HTMX promise generally resolves after swap, but use a
                        // microtask fallback to ensure DOM is updated in all cases.
                        requestAnimationFrame(() => {
                            focusInput();
                        });
                    }).catch((error) => {
                        console.error('Error loading edit form:', error);
                    });

                },
            }
        ]);

        return contextMenu;
    }

    moveCellDown(): BaseDataViewCell {
        return this.moveCurrentCell(1, 0)
    }

    moveCellUp(): BaseDataViewCell {
        return this.moveCurrentCell(-1, 0)
    }

    moveCellLeft(): BaseDataViewCell {
        return this.moveCurrentCell(0, -1)
    }

    moveCellRight(): BaseDataViewCell {
        return this.moveCurrentCell(0, 1)
    }


    private moveCurrentCell(rowDelta: number, colDelta: number): DataTableCell {
        // Always return a valid cell so keyboard navigation can't "lose" focus.
        const current = this.currentCell as DataTableCell | null;
        if (!this.element || !current) return current as DataTableCell;

        const currentElRaw = current.element;
        if (!currentElRaw) return current;

        // Defensive: if something causes the component element to be a descendant,
        // normalize to the owning <td>.
        const currentEl =
            (currentElRaw.closest('td[bloomerp-component="datatable-cell"]') as HTMLElement | null) ??
            currentElRaw;

        const currentRow = currentEl.closest('tr') as HTMLElement | null;
        const tbody = currentRow?.parentElement as HTMLElement | null;
        if (!currentRow || !tbody) return current;

        const rows = Array.from(tbody.querySelectorAll('tr')) as HTMLElement[];
        const rowIndex = rows.indexOf(currentRow);
        if (rowIndex === -1) return current;

        const currentRowCells = Array.from(
            currentRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        const colIndex = currentRowCells.indexOf(currentEl);
        if (colIndex === -1) return current;

        let nextRowIndex = rowIndex + rowDelta;
        if (nextRowIndex < 0) nextRowIndex = 0;
        if (nextRowIndex >= rows.length) nextRowIndex = rows.length - 1;

        const targetRow = rows[nextRowIndex];
        const targetRowCells = Array.from(
            targetRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        if (targetRowCells.length === 0) return current;

        let nextColIndex = colIndex + colDelta;
        if (nextColIndex < 0) nextColIndex = 0;
        if (nextColIndex >= targetRowCells.length) nextColIndex = targetRowCells.length - 1;

        const nextCellEl = targetRowCells[nextColIndex] ?? null;
        const nextCell = nextCellEl ? (getComponent(nextCellEl) as DataTableCell | null) : null;
        if (!nextCell) return current;

        return nextCell
    }

    /**
     * Copies multiple values to the clipboard that can
     * be easily pasted into excel for example
     */
    private async copyToClipboard(): Promise<void> {
        const copyText = async (text: string): Promise<void> => {
            if (!text) return;

            try {
                if (navigator.clipboard?.writeText) {
                    await navigator.clipboard.writeText(text);
                    return;
                }
            } catch {
                // fall back
            }

            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', 'true');
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            textarea.style.top = '0';
            document.body.appendChild(textarea);
            textarea.select();
            textarea.setSelectionRange(0, textarea.value.length);
            document.execCommand('copy');
            document.body.removeChild(textarea);
        };

        const getValue = (el: HTMLElement): string => {
            return (el.getAttribute('data-value') ?? el.textContent ?? '').trim();
        };

        // Multi-selection: copy as TSV ordered by row/col.
        if (this.hasMultipleSelection()) {
            if (!this.element) return;

            const selectedEls = Array.from(
                this.element.querySelectorAll<HTMLElement>(
                    'td[bloomerp-component="datatable-cell"].cell-selected'
                )
            );

            const entries: Array<{ row: number; col: number; value: string }> = [];
            for (const el of selectedEls) {
                const rowRaw = el.getAttribute('data-row-index');
                const colRaw = el.getAttribute('data-column-index');
                const row = rowRaw != null ? Number(rowRaw) : NaN;
                const col = colRaw != null ? Number(colRaw) : NaN;
                if (!Number.isFinite(row) || !Number.isFinite(col)) continue;
                entries.push({ row, col, value: getValue(el) });
            }

            // Fallback if we can't read selection coords.
            if (entries.length === 0) {
                const el = this.currentCell?.element;
                if (el) await copyText(getValue(el));
                return;
            }

            entries.sort((a, b) => (a.row - b.row) || (a.col - b.col));

            const byRow = new Map<number, Array<{ col: number; value: string }>>();
            for (const e of entries) {
                const row = byRow.get(e.row) ?? [];
                row.push({ col: e.col, value: e.value });
                byRow.set(e.row, row);
            }

            const rowKeys = Array.from(byRow.keys()).sort((a, b) => a - b);
            const lines: string[] = [];

            for (const r of rowKeys) {
                const cells = byRow.get(r) ?? [];
                cells.sort((a, b) => a.col - b.col);

                // Insert blanks for gaps (keeps column alignment for Excel).
                const cols = cells.map((c) => c.col);
                const minCol = Math.min(...cols);
                const maxCol = Math.max(...cols);
                const values: string[] = [];
                const lookup = new Map<number, string>(cells.map((c) => [c.col, c.value]));
                for (let c = minCol; c <= maxCol; c++) {
                    values.push(lookup.get(c) ?? '');
                }

                lines.push(values.join('\t'));
            }

            await copyText(lines.join('\n'));
            return;
        }

        // Single cell: copy current cell value.
        const el = this.currentCell?.element;
        if (!el) return;
        await copyText(getValue(el));
    }

}
