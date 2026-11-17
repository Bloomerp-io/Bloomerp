import {
    $createTabNode,
    $getSelection,
    $isRangeSelection,
    COMMAND_PRIORITY_CRITICAL,
    COMMAND_PRIORITY_LOW,
    KEY_DOWN_COMMAND,
    KEY_ENTER_COMMAND,
    KEY_SPACE_COMMAND,
    KEY_TAB_COMMAND,
    type CommandListenerPriority,
    type LexicalNode,
    type LexicalCommand,
} from "lexical";
import { $isListItemNode, type ListItemNode, type ListType } from "@lexical/list";
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

/** Register scoped keyboard actions without replacing Lexical's native list editing. */
export function registerCommands(textEditor: BloomerpTextEditor): Array<() => void> {
    const editor = textEditor.editor;
    if (!editor) return [];
    /** Bind each command to its owning editor instance. */
    function register(command: Command): () => void {
        /** Execute the configured action in the current editor transaction. */
        function handle(event: KeyboardEvent): boolean { return command.handler.call(textEditor, event); }
        return editor.registerCommand(command.command, handle, command.priority ?? COMMAND_PRIORITY_LOW);
    }
    return Object.values(COMMANDS).map(register);
}

/** Locate the list item containing the caret without assuming a flat text child. */
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
            listItem.setIndent(Math.max(0, listItem.getIndent() + (event?.shiftKey ? -1 : 1)));
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

/** Reuse the registered list conversion for Markdown-style keyboard triggers. */
function enterListMode(host: BloomerpTextEditor, trigger: string, listType: ListType): boolean {
    if (!host.editor) return false;
    const selection = $getSelection();
    if (!$isRangeSelection(selection) || !selection.isCollapsed()) return false;
    const anchor = selection.anchor.getNode();
    const block = anchor.getTopLevelElementOrThrow();
    // Only a complete paragraph prefix is a Markdown trigger, never a word
    // in the middle of a paragraph, list, heading, or source code block.
    if (block.getType() !== 'paragraph' || block.getTextContent() !== trigger
        || selection.anchor.offset !== trigger.length || getCurrentWord(host.editor) !== trigger) return false;
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
}
