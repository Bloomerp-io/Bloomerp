import {
    $createRangeSelectionFromDom, $getNearestNodeFromDOMNode, $getSelection, $isRangeSelection,
    $setSelection, CLICK_COMMAND, COMMAND_PRIORITY_NORMAL, type LexicalEditor, type RangeSelection,
} from "lexical";
import { $findCellNode, $isTableCellNode, type TableCellNode } from "@lexical/table";

/** Check that a text selection belongs entirely to the cell the user actually clicked. */
function rangeInsideCell(selection: RangeSelection, cell: TableCellNode): boolean {
    return cell.is($findCellNode(selection.anchor.getNode())) && cell.is($findCellNode(selection.focus.getNode()));
}

/** Keep simple clicks in empty cells editable without interfering with rectangular drag selections. */
export function registerTableCellSelection(editor: LexicalEditor, host: HTMLElement): () => void {
    /** Repair a misplaced caret after native table selection and browser click handling have run. */
    function onCellClick(event: MouseEvent): boolean {
        if (!editor.isEditable() || host.dataset.disabled === "true" || event.button !== 0
            || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return false;
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest('[contenteditable="false"], a, button, input, textarea, select')) return false;
        const element = target?.closest("td, th");
        if (!element || !editor.getRootElement()?.contains(element)) return false;
        const cell = $getNearestNodeFromDOMNode(element);
        if (!$isTableCellNode(cell)) return false;
        const current = $getSelection();
        if ($isRangeSelection(current) && rangeInsideCell(current, cell)) return false;
        const native = $createRangeSelectionFromDom(element.ownerDocument.getSelection(), editor);
        if (native && rangeInsideCell(native, cell)) $setSelection(native);
        else cell.selectStart();
        return false;
    }
    return editor.registerCommand(CLICK_COMMAND, onCellClick, COMMAND_PRIORITY_NORMAL);
}
