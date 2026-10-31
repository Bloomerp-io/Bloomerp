import {
    $applyNodeReplacement, type DOMConversionMap, type DOMConversionOutput, type DOMExportOutput,
    type EditorConfig, type LexicalEditor, type NodeKey,
} from "lexical";
import { TableNode, type SerializedTableNode } from "@lexical/table";

/** Apply proportional columns to the same fixed table layout used by saved HTML and PDFs. */
export function applyTableColumnWidths(table: HTMLTableElement, widths: readonly number[] | undefined): void {
    if (!widths?.length || widths.some(invalidWidth)) {
        table.style.removeProperty("table-layout");
        table.style.removeProperty("width");
        return;
    }
    const total = widths.reduce(sumWidths, 0);
    table.style.tableLayout = "fixed";
    table.style.width = "100%";
    const columns = table.querySelectorAll<HTMLTableColElement>(":scope > colgroup > col");
    columns.forEach(setWidth);
    /** Give each physical column its share of the available printable table width. */
    function setWidth(column: HTMLTableColElement, index: number): void {
        column.style.width = widths![index] ? `${widths![index] / total * 100}%` : "";
    }
}

/** Reject malformed or nonpositive dimensions imported from external HTML. */
function invalidWidth(width: number): boolean { return !Number.isFinite(width) || width <= 0; }
/** Sum column weights without changing the persisted array. */
function sumWidths(total: number, width: number): number { return total + width; }

/** Retain column proportions through editing, HTML reloads, and document generation. */
export class ResizableTableNode extends TableNode {
    /** Identify the editor's table extension while retaining native table behavior. */
    public static getType(): string { return "resizable-table"; }

    /** Preserve identity while Lexical copies native table fields through afterCloneFrom. */
    public static clone(node: ResizableTableNode): ResizableTableNode { return new ResizableTableNode(node.__key); }

    /** Construct a native-compatible table with optional existing node identity. */
    public constructor(key?: NodeKey) { super(key); }

    /** Restore persisted native table options and proportional column weights. */
    public static importJSON(serialized: SerializedTableNode): ResizableTableNode {
        const table = $createResizableTableNode();
        table.setRowStriping(serialized.rowStriping ?? false);
        table.setFormat(serialized.format);
        if (serialized.colWidths?.length && !serialized.colWidths.some(invalidWidth)) table.setColWidths(serialized.colWidths);
        return table;
    }

    /** Import column groups that the native HTML table importer otherwise discards. */
    public static importDOM(): DOMConversionMap {
        /** Prefer the proportional importer over the native table conversion. */
        function importer(_element: HTMLElement): NonNullable<ReturnType<DOMConversionMap[string]>> {
            return { conversion: convertTable, priority: 2 };
        }
        return { table: importer };
    }

    /** Keep the extension identity in Lexical history and JSON snapshots. */
    public exportJSON(): SerializedTableNode { return { ...super.exportJSON(), type: ResizableTableNode.getType() }; }

    /** Render the editor using the same proportional column group that is exported. */
    public createDOM(config: EditorConfig, editor?: LexicalEditor): HTMLElement {
        const table = super.createDOM(config, editor) as HTMLTableElement;
        applyTableColumnWidths(table, this.getColWidths());
        return table;
    }

    /** Reapply proportional sizing after native reconciliation replaces the column group. */
    public updateDOM(previous: ResizableTableNode, element: HTMLElement, config: EditorConfig): boolean {
        super.updateDOM(previous, element, config);
        applyTableColumnWidths(element as HTMLTableElement, this.getColWidths());
        return false;
    }

    /** Export percentage columns without conflicting native fallback cell widths. */
    public exportDOM(editor: LexicalEditor): DOMExportOutput {
        const output = super.exportDOM(editor);
        const widths = this.getColWidths();
        const nativeAfter = output.after;
        /** Finish native row export before normalizing the printable table geometry. */
        function after(element: Parameters<NonNullable<DOMExportOutput["after"]>>[0]): ReturnType<NonNullable<DOMExportOutput["after"]>> {
            const result = nativeAfter ? nativeAfter(element) : element;
            if (result instanceof HTMLTableElement && widths?.length) {
                applyTableColumnWidths(result, widths);
                result.querySelectorAll<HTMLElement>("th, td").forEach(clearCellWidth);
            }
            return result instanceof DocumentFragment ? undefined : result;
        }
        return { ...output, after };
    }
}

/** Remove cell pixel fallbacks so the exported column group alone controls table proportions. */
function clearCellWidth(cell: HTMLElement): void { cell.style.removeProperty("width"); }

/** Import native table semantics and either percentage or pixel column proportions. */
function convertTable(element: HTMLElement): DOMConversionOutput | null {
    const output = TableNode.importDOM()?.table(element)?.conversion(element) ?? null;
    if (output?.node instanceof ResizableTableNode) {
        const columns = element.querySelectorAll<HTMLTableColElement>(":scope > colgroup > col");
        const widths: number[] = [];
        for (const column of columns) {
            const value = column.style.width;
            const width = /^(?:\d+(?:\.\d+)?|\.\d+)(?:px|%)$/.test(value) ? Number.parseFloat(value) : NaN;
            for (let index = 0; index < column.span; index++) widths.push(width);
        }
        if (widths.length && !widths.some(invalidWidth)) output.node.setColWidths(widths);
    }
    return output;
}

/** Create the replacement used by both native insertion helpers and HTML conversion. */
export function $createResizableTableNode(): ResizableTableNode { return $applyNodeReplacement(new ResizableTableNode()); }

/** Replace a native table without losing its existing layout and row-striping settings. */
export function $replaceTableNode(node: TableNode): ResizableTableNode {
    const table = new ResizableTableNode();
    table.setRowStriping(node.getRowStriping());
    const widths = node.getColWidths();
    if (widths) table.setColWidths(widths);
    return table;
}
