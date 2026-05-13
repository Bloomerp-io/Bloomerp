import { ContextMenuController, getContextMenu } from "@/utils/contextMenu";
import { $getSelection, $isRangeSelection, $isTextNode, LexicalEditor } from "lexical";
import { ACTIONS } from "../actions";

function getCaretRect(root: HTMLElement): DOMRect {
    const selection = window.getSelection();
    const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

    if (range) {
        const slashProbe = range.cloneRange();
        const isTextNode = slashProbe.endContainer.nodeType === Node.TEXT_NODE;

        if (isTextNode && slashProbe.endOffset > 0) {
            slashProbe.setStart(slashProbe.endContainer, slashProbe.endOffset - 1);
            const slashRect = Array.from(slashProbe.getClientRects()).at(-1);
            if (slashRect && (slashRect.width > 0 || slashRect.height > 0)) {
                return slashRect;
            }
        }

        const marker = document.createElement('span');
        marker.textContent = '\u200b';

        const markerRange = range.cloneRange();
        markerRange.collapse(true);
        markerRange.insertNode(marker);

        const markerRect = marker.getBoundingClientRect();
        marker.remove();

        selection?.removeAllRanges();
        selection?.addRange(range);

        if (markerRect.width > 0 || markerRect.height > 0) {
            return markerRect;
        }
    }

    return root.getBoundingClientRect();
}

function getSlashRect(editor: LexicalEditor): DOMRect {
    const root = editor.getRootElement();

    let rect: DOMRect | null = null;

    editor.getEditorState().read(() => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
            return;
        }

        const node = selection.anchor.getNode();
        if (!$isTextNode(node)) {
            return;
        }

        const element = editor.getElementByKey(node.getKey());
        const textNode = element?.firstChild;
        const offset = selection.anchor.offset;

        if (!(textNode instanceof Text) || offset <= 0) {
            return;
        }

        const range = document.createRange();
        range.setStart(textNode, offset - 1);
        range.setEnd(textNode, offset);

        const measured = Array.from(range.getClientRects()).at(-1) ?? range.getBoundingClientRect();
        if (measured.width > 0 || measured.height > 0) {
            rect = measured;
        }
    });

    return rect ?? getCaretRect(root);
}


export function launchContextMenu(
    editor:LexicalEditor, 
    contextMenu:ContextMenuController,
    insertKeys?:Array<string>,
    query?:string
) {
    const root = editor.getRootElement()
    if (!root) {
        return;
    }

    const requestedKeys = insertKeys ?? Object.keys(ACTIONS);
    const normalizedQuery = query?.trim().toLowerCase() ?? '';
    const items = requestedKeys
        .map((key) => ACTIONS[key])
        .filter((insert) => Boolean(insert))
        .filter((insert) => {
            if (!normalizedQuery) {
                return true;
            }

            return insert.label.toLowerCase().includes(normalizedQuery);
        })
        .map((insert) => ({
            label: insert.label,
            icon: insert.icon,
            onClick: () => {
                insert.handler(editor);
            },
        }));

    requestAnimationFrame(() => {
            const rect = getSlashRect(editor);

            contextMenu.showAt(
                {
                    x: rect.left,
                    y: rect.bottom + 8,
                },
                root,
                items
            );
        });
}
