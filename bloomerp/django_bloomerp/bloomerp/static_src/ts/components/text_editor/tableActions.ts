import { $createParagraphNode, $isElementNode, type BaseSelection } from "lexical";
import {
    $computeTableMap, $findCellNode, $findTableNode, $isTableCellNode, $isTableSelection,
    $unmergeCell, type TableCellNode,
} from "@lexical/table";
import { t } from "@/utils/i18n";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type { Action, ActionContext } from "./actionRegistry";

type CellRectangle = { cells: TableCellNode[]; rows: number; columns: number };

/** Resolve a complete rectangular selection without splitting existing spans or crossing tables. */
function $selectedRectangle(selection: BaseSelection | null): CellRectangle | null {
    if (!$isTableSelection(selection)) return null;
    const anchor = $findCellNode(selection.anchor.getNode());
    const focus = $findCellNode(selection.focus.getNode());
    const table = anchor && $findTableNode(anchor);
    if (!anchor || !focus || !table || !table.is($findTableNode(focus))) return null;
    const selected = new Set<TableCellNode>();
    for (const node of selection.getNodes()) {
        if ($isTableCellNode(node) && node.getParent()?.getParent()?.is(table)) selected.add(node);
    }
    if (selected.size < 2) return null;
    const [map] = $computeTableMap(table, anchor, focus);
    let top = Infinity, left = Infinity, bottom = -1, right = -1;
    for (const row of map) for (const value of row) {
        if (!selected.has(value.cell)) continue;
        top = Math.min(top, value.startRow);
        left = Math.min(left, value.startColumn);
        bottom = Math.max(bottom, value.startRow + value.cell.getRowSpan() - 1);
        right = Math.max(right, value.startColumn + value.cell.getColSpan() - 1);
    }
    const cells = new Set<TableCellNode>();
    for (let row = top; row <= bottom; row++) for (let column = left; column <= right; column++) {
        const value = map[row]?.[column];
        if (!value || !selected.has(value.cell)) return null;
        cells.add(value.cell);
    }
    return { cells: [...cells], rows: bottom - top + 1, columns: right - left + 1 };
}

/** Offer merging only when at least two complete neighboring cells are selected. */
function canMerge(context: ActionContext): boolean { return $selectedRectangle(context.selection) !== null; }

/** Combine cell blocks in reading order while retaining the first cell's styling and table widths. */
function mergeCells(_host: BloomerpTextEditor, context: ActionContext): void {
    const rectangle = $selectedRectangle(context.selection);
    if (!rectangle) return;
    const [first, ...others] = rectangle.cells;
    const content = rectangle.cells.flatMap(cellChildren);
    // Remove only empty filler paragraphs; keep every formatted block, reference, and image intact.
    const meaningful = content.filter(hasContent);
    first.clear();
    first.append(...(meaningful.length ? meaningful : [$createParagraphNode()]));
    first.setColSpan(rectangle.columns);
    first.setRowSpan(rectangle.rows);
    first.setWidth(undefined);
    for (const cell of others) cell.remove();
    first.selectEnd();
}

/** Keep blocks intact and wrap any imported inline children in valid table-cell paragraphs. */
function cellChildren(cell: TableCellNode): import("lexical").LexicalNode[] {
    const blocks: import("lexical").LexicalNode[] = [];
    let paragraph: import("lexical").ParagraphNode | null = null;
    for (const child of cell.getChildren()) {
        if ($isElementNode(child) && !child.isInline()) {
            blocks.push(child);
            paragraph = null;
        } else {
            if (!paragraph) { paragraph = $createParagraphNode(); blocks.push(paragraph); }
            paragraph.append(child);
        }
    }
    return blocks;
}

/** Retain nonempty paragraphs and all other block types, including atomic content. */
function hasContent(node: import("lexical").LexicalNode): boolean {
    return node.getType() !== "paragraph" || !$isElementNode(node) || node.getChildrenSize() > 0;
}

/** Locate a single selected cell for the reverse structural operation. */
function selectedCell(context: ActionContext): TableCellNode | null {
    const selection = context.selection;
    if (context.range) {
        const cell = $findCellNode(context.range.anchor.getNode());
        return cell?.is($findCellNode(context.range.focus.getNode())) ? cell : null;
    }
    if (!$isTableSelection(selection)) return null;
    const cell = $findCellNode(selection.anchor.getNode());
    return cell?.is($findCellNode(selection.focus.getNode())) ? cell : null;
}

/** Expose splitting only for a single cell spanning multiple physical rows or columns. */
function canSplit(context: ActionContext): boolean {
    const cell = selectedCell(context);
    return Boolean(cell && (cell.getColSpan() > 1 || cell.getRowSpan() > 1));
}

/** Restore individual cells using native span-aware splitting and retain the merged content. */
function splitCell(_host: BloomerpTextEditor, context: ActionContext): void {
    const cell = selectedCell(context);
    if (!cell || !canSplit(context)) return;
    cell.selectStart();
    $unmergeCell();
    cell.selectEnd();
}

/** Share selection-sensitive table transformations across fixed and floating action toolbars. */
export function createTableActions(): Record<string, Action> {
    return {
        merge_cells: {
            /** Translate the visible action without changing its stable identifier. */
            get label(): string { return t("Merge cells"); },
            icon: "fa-solid fa-object-group", group: "table", surfaces: ["toolbar", "selection"],
            isAvailable: canMerge, handler: mergeCells,
        },
        split_cell: {
            /** Translate the reverse table transformation. */
            get label(): string { return t("Split cell"); },
            icon: "fa-solid fa-object-ungroup", group: "table", surfaces: ["toolbar", "selection", "slash"],
            isAvailable: canSplit, handler: splitCell,
        },
    };
}
