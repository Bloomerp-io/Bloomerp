import {
    $createParagraphNode,
    $getSelection,
    $isRangeSelection,
    COMMAND_PRIORITY_CRITICAL,
    COMMAND_PRIORITY_LOW,
    KEY_BACKSPACE_COMMAND,
    KEY_DELETE_COMMAND,
    KEY_DOWN_COMMAND,
    KEY_ENTER_COMMAND,
    KEY_SPACE_COMMAND,
    KEY_TAB_COMMAND,
    SELECTION_CHANGE_COMMAND,
    type CommandListenerPriority,
    type LexicalNode,
    type LexicalCommand,
    type LexicalEditor,
} from "lexical";
import { $createListItemNode, $createListNode, $isListItemNode, $isListNode, type ListItemNode, type ListType } from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { getContextMenu } from "@/utils/contextMenu";
import { launchContextMenu } from "./editorContextMenu";
import { getCurrentWord, removeTextFromCurrentNode } from "./utils/wordSelector";

export type Command = {
    command: LexicalCommand<KeyboardEvent>;
    handler: (event?: KeyboardEvent) => boolean;
    priority?: CommandListenerPriority;
}

export function registerCommands(editor: LexicalEditor): Array<() => void> {
    return Object.values(COMMANDS).map(({ command, handler, priority = COMMAND_PRIORITY_LOW }) => (
        editor.registerCommand(command, (event) => handler.call(editor, event), priority)
    ));
}

function getSelectedListItem(node: LexicalNode): ListItemNode | null {
    let currentNode: LexicalNode | null = node;

    while (currentNode) {
        if ($isListItemNode(currentNode)) {
            return currentNode;
        }

        currentNode = currentNode.getParent();
    }

    return null;
}

function indentListItem(listItem: ListItemNode): boolean {
    const list = listItem.getParent();
    const previousSibling = listItem.getPreviousSibling();

    if (!$isListNode(list) || !["bullet", "number"].includes(list.getListType()) || !$isListItemNode(previousSibling)) {
        return false;
    }

    const listType = list.getListType();
    const previousNestedList = previousSibling
        .getChildren()
        .find((child) => $isListNode(child) && child.getListType() === listType);
    const nestedList = $isListNode(previousNestedList)
        ? previousNestedList
        : $createListNode(listType);

    if (!previousNestedList) {
        previousSibling.append(nestedList);
    }

    nestedList.append(listItem);
    nestedList.getChildren().forEach((child, index) => {
        if ($isListItemNode(child)) {
            child.setValue(index + 1);
        }
    });
    listItem.selectStart();

    return true;
}

function removeEmptyNestedListItem(listItem: ListItemNode): boolean {
    const list = listItem.getParent();
    const parentListItem = list?.getParent();

    if (!$isListNode(list) || !$isListItemNode(parentListItem) || listItem.getTextContent().trim() !== '') {
        return false;
    }

    listItem.remove();

    if (list.getChildrenSize() === 0) {
        list.remove();
    }

    parentListItem.selectEnd();

    return true;
}

function isEmptyCurrentListItem(listItem: ListItemNode): boolean {
    return listItem.getTextContent().trim() === '';
}

function exitEmptyListItem(listItem: ListItemNode): boolean {
    const list = listItem.getParent();

    if (!$isListNode(list) || !["bullet", "number"].includes(list.getListType()) || !isEmptyCurrentListItem(listItem)) {
        return false;
    }

    const currentIndent = listItem.getIndent();

    if (currentIndent > 0) {
        listItem.setIndent(currentIndent - 1);
        listItem.selectStart();
        return true;
    }

    const paragraph = $createParagraphNode();
    list.insertAfter(paragraph);
    listItem.remove();

    if (list.getChildrenSize() === 0) {
        list.remove();
    }

    paragraph.select();

    return true;
}

function insertListItemAfter(listItem: ListItemNode): boolean {
    const list = listItem.getParent();

    if (!$isListNode(list) || !["bullet", "number"].includes(list.getListType())) {
        return false;
    }

    const nextListItem = $createListItemNode();
    listItem.insertAfter(nextListItem);
    nextListItem.selectStart();

    return true;
}

function handleListItemEnter(listItem: ListItemNode): boolean {
    if (isEmptyCurrentListItem(listItem)) {
        return exitEmptyListItem(listItem);
    }

    return insertListItemAfter(listItem);
}

function enterListMode(editor: LexicalEditor, trigger: string, listType: ListType): boolean {
    if (getCurrentWord(editor) !== trigger) {
        return false;
    }

    removeTextFromCurrentNode(editor, trigger);

    editor.update(() => {
        const selection = $getSelection();

        if (!$isRangeSelection(selection)) {
            return;
        }

        $setBlocksType(selection, () => $createListNode(listType));
    });

    return true;
}

export const COMMANDS: Record<string, Command> = {
    slash: {
        command: KEY_DOWN_COMMAND,
        handler: function () {
            requestAnimationFrame(() => {
                const currentWord = getCurrentWord(this);
                const contextMenu = getContextMenu();

                if (currentWord[0] !== "/") {
                    contextMenu.hide();
                    return;
                }

                launchContextMenu(
                    this,
                    contextMenu,
                    ["h1", "h2", "h3", "image", "unordered_list", "ordered_list"],
                    currentWord.slice(1),
                );
            });

            return false;
        },
    },
    range: {
        command: SELECTION_CHANGE_COMMAND,
        handler: () => true,
    },
    at: {
        command: KEY_DOWN_COMMAND,
        handler: function () {
            requestAnimationFrame(() => {
                const currentWord = getCurrentWord(this);
                const contextMenu = getContextMenu();

                if (currentWord[0] !== "@") {
                    contextMenu.hide();
                    return;
                }

                launchContextMenu(
                    this,
                    contextMenu,
                    ["h1", "h2", "h3", "ordered_list", "unordered_list"],
                    currentWord.slice(1),
                );
            });

            return false;
        },
    },
    numberEntersUnorderdList: {
        command: KEY_SPACE_COMMAND,
        handler: function (event) {
            if (!enterListMode(this, "1.", "number")) {
                return false;
            }

            event?.preventDefault();
            return true;
        },
    },
    dashEntersUnorderedList: {
        command: KEY_SPACE_COMMAND,
        handler: function (event) {
            if (!enterListMode(this, "-", "bullet")) {
                return false;
            }

            event?.preventDefault();
            return true;
        },
    },
    tab: {
        command: KEY_TAB_COMMAND,
        handler: function (event) {
            event.preventDefault();

            this.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection)) {
                    return;
                }

                const listItem = getSelectedListItem(selection.anchor.getNode());

                if (listItem) {
                    indentListItem(listItem);
                    return;
                }

                selection.insertText(".");
            });

            return true;
        },
    },
    removeEmptyNestedListItemBackward: {
        command: KEY_BACKSPACE_COMMAND,
        handler: function (event) {
            let handled = false;

            this.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
                    return;
                }

                const listItem = getSelectedListItem(selection.anchor.getNode());

                if (listItem && removeEmptyNestedListItem(listItem)) {
                    event?.preventDefault();
                    handled = true;
                }
            });

            return handled;
        },
    },
    removeEmptyNestedListItemForward: {
        command: KEY_DELETE_COMMAND,
        handler: function (event) {
            let handled = false;

            this.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
                    return;
                }

                const listItem = getSelectedListItem(selection.anchor.getNode());

                if (listItem && removeEmptyNestedListItem(listItem)) {
                    event?.preventDefault();
                    handled = true;
                }
            });

            return handled;
        },
    },
    exitEmptyListItem: {
        command: KEY_ENTER_COMMAND,
        priority: COMMAND_PRIORITY_CRITICAL,
        handler: function (event) {
            let shouldHandle = false;

            this.getEditorState().read(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
                    return;
                }

                const listItem = getSelectedListItem(selection.anchor.getNode());
                shouldHandle = Boolean(listItem);
            });

            if (!shouldHandle) {
                return false;
            }

            event?.preventDefault();
            event?.stopPropagation();

            this.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
                    return;
                }

                const listItem = getSelectedListItem(selection.anchor.getNode());
                if (listItem) {
                    handleListItemEnter(listItem);
                }
            });

            return true;
        },
    },
}
