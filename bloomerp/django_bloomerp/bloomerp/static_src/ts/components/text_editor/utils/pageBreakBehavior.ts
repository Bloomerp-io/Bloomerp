import { $createParagraphNode, $getRoot, $getSelection, $insertNodes, $isElementNode, $isRangeSelection, $isTextNode, type LexicalEditor, type TextNode } from "lexical";
import { $createPageBreakNode, PageBreakNode } from "../nodes/PageBreakNode.ts";
import { getCurrentWordFromSelection } from "./wordSelector.ts";

/** Remove a validated slash command even when formatting splits its text nodes. */
function removeSlashTrigger(word: string): void {
    const selection = $getSelection();
    if (!$isRangeSelection(selection) || !selection.isCollapsed()) return;
    let endNode = selection.anchor.getNode();
    let endOffset = selection.anchor.offset;
    if ($isElementNode(endNode)) {
        const previousChild = endNode.getChildAtIndex(endOffset - 1);
        if (!$isTextNode(previousChild)) return;
        endNode = previousChild;
        endOffset = previousChild.getTextContentSize();
    }
    if (!$isTextNode(endNode)) return;
    let startNode: TextNode = endNode;
    let startOffset = endOffset;
    let remaining = word.length;
    while (remaining > startOffset) {
        remaining -= startOffset;
        const previous = startNode.getPreviousSibling();
        if (!$isTextNode(previous)) return;
        startNode = previous;
        startOffset = previous.getTextContentSize();
    }
    selection.setTextNodeRange(startNode, startOffset - remaining, endNode, endOffset);
    selection.removeText();
}

/** Insert a page boundary at the caret and leave an editable paragraph after it. */
export function insertPageBreak(editor: LexicalEditor, fromSlashMenu: boolean = false): void {
    if (!editor.hasNodes([PageBreakNode]) || !editor.isEditable()) return;
    /** Replace a slash trigger without dropping surrounding document content. */
    function insertAtSelection(): void {
        const currentWord = getCurrentWordFromSelection();
        if (fromSlashMenu && currentWord.startsWith("/")) removeSlashTrigger(currentWord);
        const pageBreak = $createPageBreakNode();
        const paragraph = $createParagraphNode();
        if ($isRangeSelection($getSelection())) {
            $insertNodes([pageBreak, paragraph]);
        } else {
            $getRoot().append(pageBreak, paragraph);
        }
        paragraph.selectStart();
    }
    editor.update(insertAtSelection);
    editor.focus();
}
