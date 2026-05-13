import { $getSelection, $isRangeSelection, $isTextNode, type LexicalEditor } from "lexical";


export function getCurrentWord(editor:LexicalEditor) : string {
    let currentWord = '';

    editor.getEditorState().read(() => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
            return;
        }

        let node = selection.anchor.getNode();
        let offset = selection.anchor.offset;

        if (!$isTextNode(node)) {
            const previousChild = offset > 0 ? node.getChildAtIndex(offset - 1) : null;
            if (!$isTextNode(previousChild)) {
                return;
            }
            node = previousChild;
            offset = previousChild.getTextContentSize();
        }

        const text = node.getTextContent();
        if (offset > 0 && /\s/.test(text.charAt(offset - 1))) {
            currentWord = '';
            return;
        }

        let beforeCursor = text.slice(0, offset);
        let currentNode = node.getPreviousSibling();

        while ($isTextNode(currentNode)) {
            const previousText = currentNode.getTextContent();
            if (previousText.length === 0) {
                currentNode = currentNode.getPreviousSibling();
                continue;
            }
            if (/\s/.test(previousText.charAt(previousText.length - 1))) {
                beforeCursor = `${previousText}${beforeCursor}`;
                break;
            }
            beforeCursor = `${previousText}${beforeCursor}`;
            currentNode = currentNode.getPreviousSibling();
        }

        const match = beforeCursor.match(/[^\s]+$/);

        currentWord = match?.[0] ?? '';
    });

    return currentWord;
}


/**
 * Removes selected text from currently selected node
 * @param editor the editor object
 * @param text the string you want to remove
 */
export function removeTextFromCurrentNode(editor:LexicalEditor, text:string) : boolean {
    let removed = false;

    if (!text) {
        return removed;
    }

    editor.update(() => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) {
            return;
        }

        let node = selection.anchor.getNode();
        let offset = selection.anchor.offset;

        if (!$isTextNode(node)) {
            const previousChild = offset > 0 ? node.getChildAtIndex(offset - 1) : null;
            if (!$isTextNode(previousChild)) {
                return;
            }

            node = previousChild;
            offset = previousChild.getTextContentSize();
        }

        const nodeText = node.getTextContent();
        const startIndex = nodeText.slice(0, offset).lastIndexOf(text);

        if (startIndex === -1) {
            return;
        }

        node.spliceText(startIndex, text.length, '', true);
        removed = true;
    });

    return removed;
}
