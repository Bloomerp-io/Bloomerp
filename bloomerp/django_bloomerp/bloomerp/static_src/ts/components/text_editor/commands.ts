import {
    $createTabNode,
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
    type CommandListenerPriority,
    type LexicalNode,
    type LexicalCommand,
    type LexicalEditor,
} from "lexical";
import { $createListItemNode, $createListNode, $isListItemNode, $isListNode, type ListItemNode, type ListType } from "@lexical/list";
import { getContextMenu } from "@/utils/contextMenu";
import { launchContextMenu } from "./utils/editorContextMenu";
import { getCurrentWord, removeTextFromCurrentSelection } from "./utils/wordSelector";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import { $isCodeBlockNode } from "./nodes/CodeBlockNode";

const COMMAND_CONTEXT_MENU_ID = 'bloomerp-text-editor-command-menu';

export type Command = {
    command: LexicalCommand<KeyboardEvent>;
    handler: (this: BloomerpTextEditor, event?: KeyboardEvent) => boolean;
    priority?: CommandListenerPriority;
}

export function registerCommands(textEditor: BloomerpTextEditor): Array<() => void> {
    const editor = textEditor.editor;
    if (!editor) {
        return [];
    }

    return Object.values(COMMANDS).map(({ command, handler, priority = COMMAND_PRIORITY_LOW }) => (
        editor.registerCommand(command, (event) => handler.call(textEditor, event), priority)
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

/** Check whether the selection is inside an editable code block. */
function isCodeBlockSelection(node: LexicalNode): boolean {
    let current: LexicalNode | null = node;
    while (current) {
        if ($isCodeBlockNode(current)) return true;
        current = current.getParent();
    }
    return false;
}

/** Insert a literal tab in code or apply the editor's existing list indentation. */
function handleTab(this: BloomerpTextEditor, event?: KeyboardEvent): boolean {
    event?.preventDefault();

    /** Apply the tab to the current Lexical selection. */
    function insertTab(): void {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) return;

        if (isCodeBlockSelection(selection.anchor.getNode())) {
            selection.insertNodes([$createTabNode()]);
            return;
        }

        const listItem = getSelectedListItem(selection.anchor.getNode());
        if (listItem) {
            indentListItem(listItem);
            return;
        }

        selection.insertRawText("\t");
    }

    this.editor?.update(insertTab);
    return true;
}

/** Insert a line break while keeping the caret inside a code block. */
function handleCodeBlockEnter(this: BloomerpTextEditor, event?: KeyboardEvent): boolean {
    const editor = this.editor;
    if (!editor) return false;
    let isCodeBlock = false;

    /** Read whether the caret is currently in a code block. */
    function detectCodeBlockSelection(): void {
        const selection = $getSelection();
        isCodeBlock = $isRangeSelection(selection)
            && isCodeBlockSelection(selection.anchor.getNode());
    }

    editor.getEditorState().read(detectCodeBlockSelection);
    if (!isCodeBlock) return false;

    event?.preventDefault();

    /** Insert a Lexical line break without splitting the code block. */
    function insertCodeLineBreak(): void {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) selection.insertLineBreak();
    }

    editor.update(insertCodeLineBreak);
    return true;
}

/** Nest an item under its preceding sibling when its list supports indentation. */
function indentListItem(listItem: ListItemNode): boolean {
    const list = listItem.getParent();
    const previousSibling = listItem.getPreviousSibling();

    if (!$isListNode(list) || !["bullet", "number", "check"].includes(list.getListType()) || !$isListItemNode(previousSibling)) {
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

/** Leave an empty list item, or reduce its indent, when Enter is pressed. */
function exitEmptyListItem(listItem: ListItemNode): boolean {
    const list = listItem.getParent();

    if (!$isListNode(list) || !["bullet", "number", "check"].includes(list.getListType()) || !isEmptyCurrentListItem(listItem)) {
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

/** Add the next item in the current list, leaving checklist items unchecked. */
function insertListItemAfter(listItem: ListItemNode): boolean {
    const list = listItem.getParent();

    if (!$isListNode(list) || !["bullet", "number", "check"].includes(list.getListType())) {
        return false;
    }

    const nextListItem = $createListItemNode(list.getListType() === "check" ? false : undefined);
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

/** Reuse the registered list conversion for Markdown-style keyboard triggers. */
function enterListMode(host: BloomerpTextEditor, trigger: string, listType: ListType): boolean {
    if (!host.editor || getCurrentWord(host.editor) !== trigger) return false;
    removeTextFromCurrentSelection(trigger);
    return host.actionRegistry.execute(listType === "number" ? "ordered_list" : "unordered_list", "shortcut");
}

/** Launch the existing slash menu with searchable reference actions. */
function handleSlashTrigger(this: BloomerpTextEditor, _event?: KeyboardEvent): boolean {
    const component = this;
    /** Read command text after Lexical applies the current keyboard input. */
    function openSlashAfterInput(): void {
        const editor = component.editor;
        if (!editor?.isEditable() || component.element.dataset.disabled === "true") return;
        // A queued keystroke must not dismiss a picker after its search takes focus.
        if (!editor.getRootElement()?.contains(document.activeElement)) return;
        const currentWord = getCurrentWord(editor);
        const menu = getContextMenu(COMMAND_CONTEXT_MENU_ID);
        /** Keep slash-like source code literal instead of offering document transformations. */
        function insideCode(): boolean {
            const selection = $getSelection();
            return $isRangeSelection(selection) && isCodeBlockSelection(selection.anchor.getNode());
        }
        if (editor.getEditorState().read(insideCode)) { menu.hide(); return; }
        if (!currentWord.startsWith("/")) {
            if (!currentWord.startsWith("@")) menu.hide();
            return;
        }
        launchContextMenu(component, menu, currentWord.slice(1));
    }
    requestAnimationFrame(openSlashAfterInput);
    return false;
}

export let COMMANDS: Record<string, Command> = {
    slash: { command: KEY_DOWN_COMMAND, handler: handleSlashTrigger },
    numberEntersUnorderdList: {
        command: KEY_SPACE_COMMAND,
        /** Convert the current Markdown prefix through the shared list action. */
        handler: function (this: BloomerpTextEditor, event?: KeyboardEvent): boolean {
            const editor = this.editor;
            if (!editor || !enterListMode(this, "1.", "number")) {
                return false;
            }

            event?.preventDefault();
            return true;
        },
    },
    dashEntersUnorderedList: {
        command: KEY_SPACE_COMMAND,
        /** Convert the current Markdown prefix through the shared list action. */
        handler: function (this: BloomerpTextEditor, event?: KeyboardEvent): boolean {
            const editor = this.editor;
            if (!editor || !enterListMode(this, "-", "bullet")) {
                return false;
            }

            event?.preventDefault();
            return true;
        },
    },
    tab: {
        command: KEY_TAB_COMMAND,
        handler: handleTab,
    },
    codeBlockEnter: {
        command: KEY_ENTER_COMMAND,
        priority: COMMAND_PRIORITY_CRITICAL,
        handler: handleCodeBlockEnter,
    },
    removeEmptyNestedListItemBackward: {
        command: KEY_BACKSPACE_COMMAND,
        handler: function (event) {
            let handled = false;

            this.editor?.update(() => {
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

            this.editor?.update(() => {
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
            const editor = this.editor;
            if (!editor) {
                return false;
            }

            editor.getEditorState().read(() => {
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

            editor.update(() => {
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
