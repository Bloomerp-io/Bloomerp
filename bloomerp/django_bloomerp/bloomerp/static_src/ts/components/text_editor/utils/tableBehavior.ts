import {
    $createParagraphNode, $createTextNode, $getNodeByKey, $getSelection, $isRangeSelection,
    COMMAND_PRIORITY_CRITICAL, KEY_TAB_COMMAND, type LexicalEditor, type NodeKey, type NodeMutation,
} from "lexical";
import {
    $createTableCellNode, $createTableRowNode, $findCellNode, $findTableNode, $isTableNode,
    applyTableHandlers, getTableObserverFromTableElement, TableCellHeaderStates, TableNode,
    type TableObserver, type TableRowNode,
} from "@lexical/table";
import { mergeRegister } from "@lexical/utils";
import { registerTableControls } from "./tableControls";

type TableBehaviorState = { observers: Map<NodeKey, TableObserver> };

/** Register native table selection, Tab navigation, and contextual row and column controls. */
export function registerTableBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    const state: TableBehaviorState = { observers: new Map() };

    /** Attach native selection observers to newly rendered tables and release removed tables. */
    function onMutations(mutations: Map<NodeKey, NodeMutation>): void {
        for (const [key, mutation] of mutations) {
            if (mutation === "destroyed") {
                state.observers.get(key)?.removeListeners();
                state.observers.delete(key);
                continue;
            }
            /** Initialize native table handling after the rendered element has committed. */
            function observeTable(): void {
                const node = $getNodeByKey(key);
                const element = editor.getElementByKey(key);
                if (!$isTableNode(node) || !(element instanceof HTMLTableElement)) return;
                if (!getTableObserverFromTableElement(element)) state.observers.set(key, applyTableHandlers(node, element, editor, false));
            }
            editor.getEditorState().read(observeTable);
        }
    }
    /** Extend the table at its last cell and otherwise move the caret between cells. */
    function onTab(event: KeyboardEvent): boolean { return handleTableTab(event, state); }
    /** Release all native table observer listeners when the editor is destroyed. */
    function cleanup(): void {
        for (const observer of state.observers.values()) observer.removeListeners();
        state.observers.clear();
    }
    return mergeRegister(
        editor.registerMutationListener(TableNode, onMutations, { skipInitialization: false }),
        editor.registerCommand(KEY_TAB_COMMAND, onTab, COMMAND_PRIORITY_CRITICAL),
        registerTableControls(editor, host),
        cleanup,
    );
}

/** Move the caret between cells, appending a row when Tab leaves the last table cell. */
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

/** Create an empty native row while preserving ordinary cell semantics. */
function createEmptyTableRow(columnCount: number): TableRowNode {
    const row = $createTableRowNode();

    for (let index = 0; index < columnCount; index += 1) {
        const cell = $createTableCellNode(TableCellHeaderStates.NO_STATUS);
        cell.append($createParagraphNode().append($createTextNode()));
        row.append(cell);
    }

    return row;
}
