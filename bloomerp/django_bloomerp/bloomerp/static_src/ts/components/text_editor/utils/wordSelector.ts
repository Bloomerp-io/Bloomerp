import {
    $getSelection,
    $isElementNode,
    $isRangeSelection,
    $isTextNode,
    type LexicalEditor,
    type TextNode,
} from "lexical";

function getTextNodeBeforeSelection(): { node: TextNode, offset: number } | null {
    const selection = $getSelection();
    if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
        return null;
    }

    let node = selection.anchor.getNode();
    let offset = selection.anchor.offset;

    if (!$isTextNode(node)) {
        if (!$isElementNode(node)) {
            return null;
        }

        const previousChild = offset > 0 ? node.getChildAtIndex(offset - 1) : null;
        if (!$isTextNode(previousChild)) {
            return null;
        }

        node = previousChild;
        offset = previousChild.getTextContentSize();
    }

    return { node, offset };
}

export function getCurrentWordFromSelection(): string {
    const selectedTextNode = getTextNodeBeforeSelection();
    if (!selectedTextNode) {
        return '';
    }

    const { node, offset } = selectedTextNode;
    const text = node.getTextContent();
    if (offset > 0 && /\s/.test(text.charAt(offset - 1))) {
        return '';
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

    return match?.[0] ?? '';
}

export function removeTextFromCurrentSelection(text: string): boolean {
    if (!text) {
        return false;
    }

    const selectedTextNode = getTextNodeBeforeSelection();
    if (!selectedTextNode) {
        return false;
    }

    const { node, offset } = selectedTextNode;
    const nodeText = node.getTextContent();
    const startIndex = nodeText.slice(0, offset).lastIndexOf(text);

    if (startIndex === -1) {
        return false;
    }

    node.spliceText(startIndex, text.length, '', true);

    return true;
}


export function getCurrentWord(editor:LexicalEditor) : string {
    let currentWord = '';

    editor.getEditorState().read(() => {
        currentWord = getCurrentWordFromSelection();
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
        removed = removeTextFromCurrentSelection(text);
    });

    return removed;
}
