import { $createParagraphNode } from "lexical";
import { $createTableCellNode, $createTableRowNode, $isTableCellNode, $isTableRowNode, TableCellHeaderStates, type TableNode, type TableRowNode } from "@lexical/table";

export type TableAxis = "row" | "column";
export type TableAction = "insert-before" | "insert-after" | "delete" | "move-before" | "move-after" | "move" | "delete-table";

/** Check that physical rows and columns can be edited without splitting merged cells. */
export function $supportsTableStructure(table: TableNode): boolean {
    const count = table.getColumnCount();
    for (const row of table.getChildren()) {
        if (!$isTableRowNode(row) || row.getChildrenSize() !== count) return false;
        for (const cell of row.getChildren()) {
            if (!$isTableCellNode(cell) || cell.getColSpan() !== 1 || cell.getRowSpan() !== 1) return false;
        }
    }
    return count > 0;
}

/** Remove a table while leaving an editable caret at its original document position. */
function $deleteTable(table: TableNode): void {
    const paragraph = $createParagraphNode();
    table.insertAfter(paragraph);
    table.remove();
    paragraph.selectStart();
}

/** Edit a particular row or column, preserving node content, headers, and saved width proportions. */
export function $editTableStructure(table: TableNode, axis: TableAxis, index: number, action: TableAction, destination?: number): boolean {
    if (!table.isAttached()) return false;
    if (action === "delete-table") { $deleteTable(table); return true; }
    if (!$supportsTableStructure(table)) return false;
    const rows = table.getChildren<TableRowNode>();
    const count = axis === "row" ? rows.length : table.getColumnCount();
    if (!Number.isInteger(index) || index < 0 || index >= count) return false;
    let selected = index;
    if (action === "delete") {
        if (count === 1) { $deleteTable(table); return true; }
        if (axis === "row") rows[index].remove();
        else {
            for (const row of rows) row.getChildAtIndex(index)!.remove();
            const widths = table.getColWidths();
            if (widths) table.setColWidths(widths.filter(keepWidth));
        }
        selected = Math.min(index, count - 2);
    } else if (action === "insert-before" || action === "insert-after") {
        selected = index + (action === "insert-after" ? 1 : 0);
        if (axis === "row") {
            const row = $createTableRowNode();
            for (const source of rows[index].getChildren()) {
                const header = $isTableCellNode(source) && source.hasHeaderState(TableCellHeaderStates.COLUMN) ? TableCellHeaderStates.COLUMN : TableCellHeaderStates.NO_STATUS;
                row.append($createTableCellNode(header).append($createParagraphNode()));
            }
            if (action === "insert-before") rows[index].insertBefore(row);
            else rows[index].insertAfter(row);
        } else {
            for (const row of rows) {
                const source = row.getChildAtIndex(index)!;
                const header = $isTableCellNode(source) && source.hasHeaderState(TableCellHeaderStates.ROW) ? TableCellHeaderStates.ROW : TableCellHeaderStates.NO_STATUS;
                const cell = $createTableCellNode(header).append($createParagraphNode());
                if (action === "insert-before") source.insertBefore(cell);
                else source.insertAfter(cell);
            }
            const widths = table.getColWidths();
            if (widths) {
                const next = [...widths];
                next.splice(selected, 0, widths[index]);
                table.setColWidths(next);
            }
        }
    } else {
        const target = action === "move" ? destination : index + (action === "move-before" ? -1 : 1);
        if (!Number.isInteger(target) || target! < 0 || target! >= count || target === index) return false;
        selected = target!;
        if (axis === "row") {
            if (target! < index) rows[target!].insertBefore(rows[index]);
            else rows[target!].insertAfter(rows[index]);
        } else {
            for (const row of rows) {
                const source = row.getChildAtIndex(index)!;
                const reference = row.getChildAtIndex(target!)!;
                if (target! < index) reference.insertBefore(source);
                else reference.insertAfter(source);
            }
            const widths = table.getColWidths();
            if (widths) {
                const next = [...widths];
                next.splice(target!, 0, next.splice(index, 1)[0]);
                table.setColWidths(next);
            }
        }
    }
    const row = table.getChildAtIndex<TableRowNode>(axis === "row" ? selected : 0);
    row?.getChildAtIndex(axis === "column" ? selected : 0)?.selectStart();
    return true;

    /** Remove only the deleted column's width while preserving all remaining weights. */
    function keepWidth(_width: number, position: number): boolean { return position !== index; }
}
