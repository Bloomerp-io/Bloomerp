import {
    $createParagraphNode,
    $createTextNode,
    $getNodeByKey,
    $getSelection,
    $isRangeSelection,
    COMMAND_PRIORITY_CRITICAL,
    KEY_TAB_COMMAND,
    LexicalEditor,
    type NodeKey,
} from "lexical";
import {
    $createTableCellNode,
    $createTableRowNode,
    $deleteTableColumn,
    $findCellNode,
    $findTableNode,
    $isTableNode,
    $removeTableRowAtIndex,
    applyTableHandlers,
    getTableObserverFromTableElement,
    TableCellHeaderStates,
    TableNode,
    TableObserver,
    TableRowNode,
} from "@lexical/table";
import { mergeRegister } from "@lexical/utils";

type TableBehaviorState = {
    activeTableKey: NodeKey | null;
    controls: HTMLElement | null;
    observers: Map<NodeKey, TableObserver>;
};

export function registerTableBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    const state: TableBehaviorState = {
        activeTableKey: null,
        controls: null,
        observers: new Map(),
    };

    createTableControls(editor, host, state);

    return mergeRegister(
        editor.registerMutationListener(TableNode, (mutations) => {
            mutations.forEach((mutation, key) => {
                if (mutation === 'destroyed') {
                    state.observers.get(key)?.removeListeners();
                    state.observers.delete(key);
                    if (state.activeTableKey === key) {
                        state.activeTableKey = null;
                        hideTableControls(state);
                    }
                    return;
                }

                editor.getEditorState().read(() => {
                    const node = $getNodeByKey(key);
                    const element = editor.getElementByKey(key);

                    if (!$isTableNode(node) || !(element instanceof HTMLTableElement)) {
                        return;
                    }

                    if (!getTableObserverFromTableElement(element)) {
                        const observer = applyTableHandlers(node, element, editor, false);
                        state.observers.set(key, observer);
                    }
                });
            });
        }),
        editor.registerCommand(
            KEY_TAB_COMMAND,
            (event) => handleTableTab(event, state),
            COMMAND_PRIORITY_CRITICAL,
        ),
        editor.registerUpdateListener(({ editorState }) => {
            editorState.read(() => {
                const selection = $getSelection();
                const table = $isRangeSelection(selection)
                    ? $findTableNode(selection.anchor.getNode())
                    : null;

                state.activeTableKey = table?.getKey() ?? null;
            });

            positionTableControls(editor, host, state);
        }),
        () => {
            state.observers.forEach((observer) => observer.removeListeners());
            state.observers.clear();
            state.controls?.remove();
            state.controls = null;
            state.activeTableKey = null;
        },
    );
}

function handleTableTab(event: KeyboardEvent, state: TableBehaviorState): boolean {
    const selection = $getSelection();

    if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
        return false;
    }

    const tableCell = $findCellNode(selection.anchor.getNode());
    const table = tableCell ? $findTableNode(tableCell) : null;

    if (!tableCell || !table) {
        return false;
    }

    const observer = state.observers.get(table.getKey());
    if (!observer) {
        return false;
    }

    event.preventDefault();
    event.stopImmediatePropagation();
    event.stopPropagation();

    const coordinates = table.getCordsFromCellNode(tableCell, observer.table);
    const isForward = !event.shiftKey;
    const isLastColumn = coordinates.x === observer.table.columns - 1;
    const isLastRow = coordinates.y === observer.table.rows - 1;

    if (isForward && isLastColumn && isLastRow) {
        const row = createEmptyTableRow(Math.max(table.getColumnCount(), 1));
        table.append(row);
        row.getFirstChild()?.selectStart();
        return true;
    }

    if (!isForward && coordinates.x === 0 && coordinates.y === 0) {
        table.selectPrevious();
        return true;
    }

    const nextX = isLastColumn
        ? 0
        : coordinates.x + (isForward ? 1 : -1);
    const nextY = isForward
        ? coordinates.y + (isLastColumn ? 1 : 0)
        : coordinates.y - (coordinates.x === 0 ? 1 : 0);
    const targetX = isForward
        ? nextX
        : coordinates.x === 0
            ? observer.table.columns - 1
            : nextX;

    const nextCell = table.getCellNodeFromCordsOrThrow(targetX, nextY, observer.table);
    if (isForward) {
        nextCell.selectStart();
    } else {
        nextCell.selectEnd();
    }

    return true;
}

function createTableControls(
    editor: LexicalEditor,
    host: HTMLElement,
    state: TableBehaviorState,
): void {
    if (state.controls) {
        return;
    }

    const controls = document.createElement('div');
    controls.className = 'hidden absolute z-20 pointer-events-none';
    controls.innerHTML = `
        <button type="button" data-table-control="delete" class="absolute -left-9 top-0 flex h-7 w-7 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700 pointer-events-auto" title="Delete table">
            <i class="fa-solid fa-trash text-xs"></i>
        </button>
        <div class="absolute -right-10 top-1/2 flex -translate-y-1/2 flex-col gap-1 pointer-events-auto">
            <button type="button" data-table-control="column" class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-800" title="Add column">
                <i class="fa-solid fa-plus text-sm"></i>
            </button>
            <button type="button" data-table-control="remove-column" class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-800" title="Remove column">
                <i class="fa-solid fa-minus text-sm"></i>
            </button>
        </div>
        <div class="absolute left-1/2 -bottom-10 flex -translate-x-1/2 gap-1 pointer-events-auto">
            <button type="button" data-table-control="row" class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-800" title="Add row">
                <i class="fa-solid fa-plus text-sm"></i>
            </button>
            <button type="button" data-table-control="remove-row" class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-800" title="Remove row">
                <i class="fa-solid fa-minus text-sm"></i>
            </button>
        </div>
    `;

    controls.addEventListener('mousedown', (event) => {
        event.preventDefault();
    });
    controls.addEventListener('click', (event) => {
        const button = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-table-control]');
        const action = button?.dataset.tableControl;

        if (action === 'column') {
            addColumnToActiveTable(editor, state);
        } else if (action === 'row') {
            addRowToActiveTable(editor, state);
        } else if (action === 'remove-column') {
            removeColumnFromActiveTable(editor, state);
        } else if (action === 'remove-row') {
            removeRowFromActiveTable(editor, state);
        } else if (action === 'delete') {
            deleteActiveTable(editor, state);
        }
    });

    host.classList.add('relative');
    host.appendChild(controls);
    state.controls = controls;
}

function hideTableControls(state: TableBehaviorState): void {
    state.controls?.classList.add('hidden');
}

function positionTableControls(
    editor: LexicalEditor,
    host: HTMLElement,
    state: TableBehaviorState,
): void {
    requestAnimationFrame(() => {
        if (!state.activeTableKey || !state.controls) {
            hideTableControls(state);
            return;
        }

        const tableElement = editor.getElementByKey(state.activeTableKey);
        if (!(tableElement instanceof HTMLTableElement)) {
            hideTableControls(state);
            return;
        }

        const tableRect = tableElement.getBoundingClientRect();
        const hostRect = host.getBoundingClientRect();

        state.controls.classList.remove('hidden');
        state.controls.style.left = `${tableRect.left - hostRect.left}px`;
        state.controls.style.top = `${tableRect.top - hostRect.top}px`;
        state.controls.style.width = `${tableRect.width}px`;
        state.controls.style.height = `${tableRect.height}px`;
    });
}

function addColumnToActiveTable(editor: LexicalEditor, state: TableBehaviorState): void {
    const tableKey = state.activeTableKey;
    if (!tableKey) return;

    editor.update(() => {
        const table = $getNodeByKey(tableKey);
        if (!$isTableNode(table)) return;

        table.getChildren().forEach((row, rowIndex) => {
            if (!(row instanceof TableRowNode)) return;

            const headerState = rowIndex === 0 ? TableCellHeaderStates.ROW : TableCellHeaderStates.NO_STATUS;
            const cell = $createTableCellNode(headerState);
            cell.append($createParagraphNode().append($createTextNode()));
            row.append(cell);
        });
    });
}

function addRowToActiveTable(editor: LexicalEditor, state: TableBehaviorState): void {
    const tableKey = state.activeTableKey;
    if (!tableKey) return;

    editor.update(() => {
        const table = $getNodeByKey(tableKey);
        if (!$isTableNode(table)) return;

        const columnCount = Math.max(table.getColumnCount(), 1);
        const row = createEmptyTableRow(columnCount);

        table.append(row);
    });
}

function removeColumnFromActiveTable(editor: LexicalEditor, state: TableBehaviorState): void {
    const tableKey = state.activeTableKey;
    if (!tableKey) return;

    editor.update(() => {
        const table = $getNodeByKey(tableKey);
        if (!$isTableNode(table)) return;

        const columnCount = table.getColumnCount();
        if (columnCount <= 1) return;

        $deleteTableColumn(table, columnCount - 1);
        selectFirstTableCell(table);
    });
}

function removeRowFromActiveTable(editor: LexicalEditor, state: TableBehaviorState): void {
    const tableKey = state.activeTableKey;
    if (!tableKey) return;

    editor.update(() => {
        const table = $getNodeByKey(tableKey);
        if (!$isTableNode(table)) return;

        const rowCount = table.getChildrenSize();
        if (rowCount <= 1) return;

        $removeTableRowAtIndex(table, rowCount - 1);
        selectFirstTableCell(table);
    });
}

function createEmptyTableRow(columnCount: number): TableRowNode {
    const row = $createTableRowNode();

    for (let index = 0; index < columnCount; index += 1) {
        const cell = $createTableCellNode(TableCellHeaderStates.NO_STATUS);
        cell.append($createParagraphNode().append($createTextNode()));
        row.append(cell);
    }

    return row;
}

function selectFirstTableCell(table: TableNode): void {
    const firstRow = table.getFirstChild();
    if (!(firstRow instanceof TableRowNode)) return;

    firstRow.getFirstChild()?.selectStart();
}

function deleteActiveTable(editor: LexicalEditor, state: TableBehaviorState): void {
    const tableKey = state.activeTableKey;
    if (!tableKey) return;

    editor.update(() => {
        const table = $getNodeByKey(tableKey);
        if (!$isTableNode(table)) return;

        const paragraph = $createParagraphNode();
        table.insertAfter(paragraph);
        table.remove();
        paragraph.select();
    });

    state.activeTableKey = null;
    hideTableControls(state);
}
